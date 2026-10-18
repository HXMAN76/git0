// git0 relay IDE: VS Code-like shell around one session. Layout is a flex column on phones and tablets,
// and a fixed-height desktop grid from 1024px up (no page scroll at 1366x768).

import { useState, type ReactNode } from 'react'
import { AgentPanel } from './components/AgentPanel'
import { ActivityBar, Banner, BusyOverlay, HowItWorks, SessionEndedOverlay, StartErrorOverlay, StatusBar, TitleBar } from './components/Chrome'
import { readHowToSeen } from './storage'
import { BottomPanel } from './components/BottomPanel'
import { EditorArea, Explorer } from './components/Workspace'
import { useIdeSession } from './useIdeSession'

export default function App() {
  const ide = useIdeSession()
  const { state, dispatch } = ide
  const [howOpen, setHowOpen] = useState(() => !readHowToSeen())
  const live = state.phase === 'live'

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
  } else if (howOpen) {
    overlay = <HowItWorks onClose={() => setHowOpen(false)} />
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#1e1e1e] text-[13px] text-[#cccccc] lg:h-screen lg:overflow-hidden">
      <TitleBar startedAt={state.startedAt} phase={state.phase} canAct={live} onRunScenario={() => void ide.runScenario()} onEnd={endSession} />
      {state.banner && <Banner text={state.banner} onDismiss={() => dispatch({ type: 'banner', text: null })} />}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <ActivityBar />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <Explorer state={state} onOpen={(agent, path) => dispatch({ type: 'open_file', agent, path })} />
            <EditorArea
              state={state}
              onSelect={(agent, path) => dispatch({ type: 'select_tab', agent, path })}
              onClose={(agent, path) => dispatch({ type: 'close_tab', agent, path })}
            />
          </div>
          <BottomPanel state={state} fetchGraph={ide.graph} mergeCheck={ide.mergeCheck} />
        </div>

        <aside className="flex h-[620px] w-full shrink-0 flex-col border-l border-[#2b2b2b] lg:h-auto lg:w-[340px]">
          <AgentPanel agent="A" info={state.agentInfo?.A ?? null} agentState={state.agents.A} presets={state.presets} live={live} onSend={ide.send} onAnswer={ide.answer} />
          <AgentPanel agent="B" info={state.agentInfo?.B ?? null} agentState={state.agents.B} presets={state.presets} live={live} onSend={ide.send} onAnswer={ide.answer} />
        </aside>
      </div>

      <StatusBar state={state} />
      {overlay}
    </div>
  )
}
