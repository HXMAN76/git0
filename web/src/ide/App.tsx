// git0 relay IDE: VS Code-like shell around one session. Layout is a flex column on phones and tablets,
// and a fixed-height desktop grid from 1024px up (no page scroll at 1366x768).

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { AgentPanel } from './components/AgentPanel'
import { ActivityBar, Banner, BusyOverlay, SessionEndedOverlay, StartErrorOverlay, StatusBar, TitleBar } from './components/Chrome'
import { readNarrator, readPanelHeight, readTourSeen, writeNarrator, writePanelHeight } from './storage'
import { BottomPanel } from './components/BottomPanel'
import { GraphOverlay } from './components/GraphOverlay'
import { EditorArea, Explorer } from './components/Workspace'
import { clampPanelHeight, defaultPanelHeight } from './lib'
import { useCoachMarks } from './coach'
import { startWelcomeTour, type PanelTab } from './tour'
import { useIdeSession } from './useIdeSession'

/** Keyboard resize step for the sash (ArrowUp / ArrowDown), in px. */
const SASH_STEP = 16
/** The welcome tour starts a moment after the screen is live, so the first paint is not covered. */
const TOUR_DELAY_MS = 700

export default function App() {
  const ide = useIdeSession()
  const { state, dispatch } = ide
  const [graphOpen, setGraphOpen] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [tab, setTab] = useState<PanelTab>('relay')
  const [narrator, setNarrator] = useState(() => readNarrator())
  /** Session id for which the scenario was started. Coach marks only run after that. */
  const [armedSid, setArmedSid] = useState<string | null>(null)
  const armed = armedSid !== null && armedSid === state.sessionId
  const live = state.phase === 'live'
  const closeGraph = useCallback(() => setGraphOpen(false), [])

  const runNow = () => {
    setArmedSid(state.sessionId)
    void ide.runScenario()
  }
  // The tour is started from timers and driver callbacks, so it reads the latest scenario runner through a ref.
  const runRef = useRef(runNow)
  useEffect(() => {
    runRef.current = runNow
  })

  const tourHooks = useCallback(
    () => ({
      setTab,
      runScenario: () => runRef.current(),
    }),
    [],
  )
  const takeTour = useCallback(() => startWelcomeTour(tourHooks()), [tourHooks])

  // First visit: the welcome tour starts once the IDE is live. Remembered in storage, so it runs once per browser.
  useEffect(() => {
    if (state.phase !== 'live' || readTourSeen()) return
    const id = window.setTimeout(() => startWelcomeTour(tourHooks()), TOUR_DELAY_MS)
    return () => window.clearTimeout(id)
  }, [state.phase, tourHooks])

  // While the full-screen graph is open, coach marks are held back (and the one on screen is dismissed).
  useCoachMarks(state, armed, narrator, graphOpen)
  const toggleNarrator = () => {
    const next = !narrator
    setNarrator(next)
    writeNarrator(next)
  }

  // Bottom panel height: restored from localStorage, default ~38% of the viewport, always clamped.
  const [panelHeight, setPanelHeight] = useState(() => {
    const vh = window.innerHeight
    const saved = readPanelHeight()
    return saved === null ? defaultPanelHeight(vh) : clampPanelHeight(saved, vh)
  })
  // Mirrors panelHeight for the pointer handlers, which must read the latest value without re-rendering.
  const heightRef = useRef(panelHeight)
  const applyHeight = useCallback((h: number) => {
    heightRef.current = h
    setPanelHeight(h)
  }, [])
  const dragRef = useRef<{ startY: number; startH: number } | null>(null)

  useEffect(() => {
    const onResize = () => applyHeight(clampPanelHeight(heightRef.current, window.innerHeight))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [applyHeight])

  const onSashDown = (e: PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { startY: e.clientY, startH: heightRef.current }
  }
  const onSashMove = (e: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    // Dragging the sash up makes the panel taller, so the delta is subtracted.
    applyHeight(clampPanelHeight(drag.startH - (e.clientY - drag.startY), window.innerHeight))
  }
  const onSashUp = () => {
    if (!dragRef.current) return
    dragRef.current = null
    writePanelHeight(heightRef.current)
  }
  const onSashKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
    e.preventDefault()
    const delta = e.key === 'ArrowUp' ? SASH_STEP : -SASH_STEP
    const next = clampPanelHeight(heightRef.current + delta, window.innerHeight)
    applyHeight(next)
    writePanelHeight(next)
  }

  const endSession = () => {
    ide.end().catch((err: unknown) => {
      dispatch({ type: 'banner', text: `Could not end the session cleanly: ${err instanceof Error ? err.message : String(err)}` })
    })
  }

  let overlay: ReactNode = null
  if (state.phase === 'ended') {
    overlay = <SessionEndedOverlay reason={state.endedReason} onRestart={ide.start} />
  } else if (state.phase === 'busy') {
    overlay = <BusyOverlay message={state.busyMessage} onRetry={ide.start} />
  } else if (state.phase === 'error') {
    overlay = <StartErrorOverlay message={state.error} onRetry={ide.start} />
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#1e1e1e] text-[13px] text-[#cccccc] lg:h-screen lg:overflow-hidden">
      <TitleBar startedAt={state.startedAt} phase={state.phase} canAct={live} onRunScenario={runNow} onTakeTour={takeTour} onEnd={endSession} />
      {state.banner && <Banner text={state.banner} onDismiss={() => dispatch({ type: 'banner', text: null })} />}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <ActivityBar onOpenGraph={() => setGraphOpen(true)} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Maximizing the panel hides the editors (kept mounted, so Monaco state survives). */}
          <div className={`min-h-0 flex-1 flex-col lg:flex-row ${maximized ? 'hidden' : 'flex'}`}>
            <Explorer state={state} onOpen={(agent, path) => dispatch({ type: 'open_file', agent, path })} />
            <EditorArea
              state={state}
              onSelect={(agent, path) => dispatch({ type: 'select_tab', agent, path })}
              onClose={(agent, path) => dispatch({ type: 'close_tab', agent, path })}
            />
          </div>
          {!maximized && (
            <div
              role="separator"
              aria-orientation="horizontal"
              aria-label="Resize bottom panel"
              aria-valuenow={panelHeight}
              tabIndex={0}
              onPointerDown={onSashDown}
              onPointerMove={onSashMove}
              onPointerUp={onSashUp}
              onPointerCancel={onSashUp}
              onKeyDown={onSashKey}
              className="hidden h-1 shrink-0 cursor-row-resize bg-transparent hover:bg-[#007acc] focus-visible:bg-[#007acc] focus-visible:outline-none lg:block"
            />
          )}
          <BottomPanel
            state={state}
            fetchGraph={ide.graph}
            mergeCheck={ide.mergeCheck}
            height={panelHeight}
            maximized={maximized}
            onToggleMaximize={() => setMaximized((m) => !m)}
            onOpenGraph={() => setGraphOpen(true)}
            tab={tab}
            onTabChange={setTab}
          />
        </div>

        <aside className="flex h-[620px] w-full shrink-0 flex-col border-l border-[#2b2b2b] lg:h-auto lg:w-[340px]">
          <AgentPanel agent="A" info={state.agentInfo?.A ?? null} agentState={state.agents.A} presets={state.presets} live={live} onSend={ide.send} onAnswer={ide.answer} />
          <AgentPanel agent="B" info={state.agentInfo?.B ?? null} agentState={state.agents.B} presets={state.presets} live={live} onSend={ide.send} onAnswer={ide.answer} />
        </aside>
      </div>

      <StatusBar state={state} narrator={narrator} onToggleNarrator={toggleNarrator} />
      {graphOpen && (
        <GraphOverlay version={state.graphVersion} live={live} fetchGraph={ide.graph} conflictHighlight={state.highlight} onClose={closeGraph} />
      )}
      {overlay}
    </div>
  )
}
