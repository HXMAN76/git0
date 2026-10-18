// Bottom panel: GIT0 RELAY log, GRAPH (FalkorDB code graph), PROBLEMS (conflicts), MERGE CHECK.
// Its height is owned by App (drag sash + persisted); this component only renders it.

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { ApiError } from '../api'
import { GRAPH_COLORS, GRAPH_LEGEND, toCanvasData } from '../lib'
import { hotspots } from '../insights'
import type { IdeState, LogEntry, Tone } from '../state'
import { AGENT_META, type GraphView, type MergeFile, type MergeResult, type MergeVerdict, type VerdictStatus } from '../types'
import { CanvasNotice, GraphCanvas } from './GraphCanvas'
import { GraphCaption } from './GraphOverlay'
import { startGraphTour, type PanelTab } from '../tour'
import { useGraphView } from './useGraphView'

type TabId = PanelTab

interface BottomPanelProps {
  state: IdeState
  fetchGraph: () => Promise<GraphView>
  mergeCheck: () => Promise<MergeResult>
  /** Height in px. Ignored while maximized, when the panel takes the whole editor area. */
  height: number
  maximized: boolean
  onToggleMaximize: () => void
  onOpenGraph: () => void
  /** The active tab is owned by App so the welcome tour can switch it. */
  tab: TabId
  onTabChange: (tab: TabId) => void
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'relay', label: 'GIT0 RELAY' },
  { id: 'graph', label: 'GRAPH' },
  { id: 'problems', label: 'PROBLEMS' },
  { id: 'merge', label: 'MERGE CHECK' },
]

export function BottomPanel({ state, fetchGraph, mergeCheck, height, maximized, onToggleMaximize, onOpenGraph, tab, onTabChange }: BottomPanelProps) {
  const problemCount = state.conflicts.length
  const style: CSSProperties = maximized ? { flex: '1 1 auto', minHeight: 0 } : { height, flexShrink: 0 }
  return (
    <section className="flex flex-col border-t border-[#2b2b2b] bg-[#1e1e1e]" style={style} aria-label="Panel">
      <div role="tablist" className="flex h-[30px] shrink-0 items-center gap-1 border-b border-[#2b2b2b] bg-[#252526] px-2 text-[11px]">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => onTabChange(t.id)}
            data-tour={`tab-${t.id}`}
            className={`flex items-center gap-1.5 border-b-2 px-2 py-1 ${tab === t.id ? 'border-[#e7e7e7] text-[#e7e7e7]' : 'border-transparent text-[#9d9d9d] hover:text-[#cccccc]'}`}
          >
            {t.label}
            {t.id === 'problems' && problemCount > 0 && (
              <span className="rounded-full bg-[#f14c4c] px-1.5 text-[10px] font-semibold text-white">{problemCount}</span>
            )}
          </button>
        ))}
        <button
          type="button"
          onClick={onToggleMaximize}
          className="ml-auto flex size-6 items-center justify-center rounded-sm text-[#cccccc] hover:bg-[#3c3c3c]"
          aria-label={maximized ? 'Restore panel size' : 'Maximize panel'}
          title={maximized ? 'Restore panel size' : 'Maximize panel'}
        >
          <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            {maximized ? <path d="M4 10l4-4 4 4" /> : <path d="M4 6l4 4 4-4" />}
          </svg>
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'relay' && <RelayLog log={state.log} />}
        {tab === 'graph' && (
          <GraphPanel version={state.graphVersion} highlight={state.highlight} fetchGraph={fetchGraph} live={state.sessionId !== null} onOpen={onOpenGraph} />
        )}
        {tab === 'problems' && <Problems state={state} />}
        {tab === 'merge' && <MergeCheck mergeCheck={mergeCheck} live={state.sessionId !== null && state.phase !== 'ended'} />}
      </div>
    </section>
  )
}

// ---------- GIT0 RELAY ----------

const TONE_CLASS: Record<Tone, string> = {
  ok: 'text-[#89d185]',
  info: 'text-[#cccccc]',
  warn: 'text-[#e5c07b]',
  deny: 'text-[#f48771]',
  error: 'text-[#f14c4c]',
  muted: 'text-[#808080]',
}

function clock(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour12: false })
}

function RelayLog({ log }: { log: LogEntry[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log.length])
  return (
    <div ref={ref} className="h-full overflow-y-auto px-3 py-1.5 font-mono text-[12px] leading-[18px]" aria-live="polite">
      {log.length === 0 && <p className="text-[#6a6a6a]">Hook and MCP activity appears here once an agent makes a tool call.</p>}
      {log.map((entry) => (
        <div key={entry.id} className="flex gap-2 whitespace-pre-wrap break-all">
          <span className="shrink-0 text-[#6a6a6a]">{clock(entry.ts)}</span>
          <span className="w-8 shrink-0 font-semibold" style={{ color: entry.agent ? AGENT_META[entry.agent].color : '#9d9d9d' }}>
            {entry.agent ? `[${entry.agent}]` : '[git0]'}
          </span>
          <span className={TONE_CLASS[entry.tone]}>{entry.text}</span>
        </div>
      ))}
    </div>
  )
}

// ---------- PROBLEMS ----------

function Problems({ state }: { state: IdeState }) {
  if (state.conflicts.length === 0) {
    return <p className="p-3 text-[12px] text-[#6a6a6a]">No conflicts so far. Run the scenario to see git0 catch one.</p>
  }
  const newestFirst = [...state.conflicts].reverse()
  return (
    <ul className="h-full space-y-1 overflow-y-auto p-2 text-[12px]">
      {newestFirst.map((rec) => (
        <li key={rec.id} className="rounded-sm border-l-2 border-[#f14c4c] bg-[#252526] px-2.5 py-1.5">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-[#9d9d9d]">
            <span className="font-semibold" style={{ color: AGENT_META[rec.agent].color }}>
              [{rec.agent}]
            </span>
            <span className="text-[#f48771]">{rec.conflict.kind}</span>
            <span>{rec.conflict.severity}</span>
            <span className="truncate">{rec.conflict.symbol}</span>
            <span className="ml-auto">{clock(rec.ts)}</span>
          </div>
          <div className="mt-0.5 text-[#e0e0e0]">{rec.conflict.message}</div>
          <div className="mt-0.5 font-mono text-[11px] text-[#858585]">{rec.conflict.peer_summary}</div>
        </li>
      ))}
    </ul>
  )
}

// ---------- MERGE CHECK ----------

// own_bug = a bug already inside one clone, not caused by merging, so it gets a neutral badge.
const SEMANTIC_BADGE: Record<string, string> = {
  both_changed: 'BOTH',
  call_mismatch: 'CALL',
  own_bug: 'OWN BUG',
  syntax_error: 'SYNTAX',
}

const VERDICT_STYLE: Record<VerdictStatus, { box: string; title: string }> = {
  safe: { box: 'border-[#3c7d4f] bg-[#16301f] text-[#c9f0d4]', title: 'SAFE' },
  git_conflict: { box: 'border-[#f14c4c] bg-[#4a1717] text-[#ffd7d7]', title: 'GIT CONFLICT' },
  semantic_conflict: { box: 'border-[#e5c07b] bg-[#3d3210] text-[#fff1c2]', title: 'SEMANTIC CONFLICT' },
}

function VerdictBanner({ verdict }: { verdict: MergeVerdict }) {
  const style = VERDICT_STYLE[verdict.status]
  return (
    <div role="status" className={`shrink-0 rounded-sm border-l-4 px-3 py-2 ${style.box}`}>
      <div className="text-[10px] font-bold tracking-wider opacity-80">{style.title}</div>
      <div className="text-[14px] font-semibold">{verdict.headline}</div>
      {verdict.detail && <div className="mt-0.5 leading-relaxed opacity-90">{verdict.detail}</div>}
    </div>
  )
}

function GitCell({ file }: { file: MergeFile }) {
  if (file.git === 'clean') return <span className="rounded-sm bg-[#3c7d4f] px-1.5 text-[10px] font-semibold text-white">CLEAN</span>
  return (
    <span className="rounded-sm bg-[#f14c4c] px-1.5 text-[10px] font-semibold text-white">
      CONFLICT {file.git_hunks} {file.git_hunks === 1 ? 'hunk' : 'hunks'}
    </span>
  )
}

function Git0Cell({ file }: { file: MergeFile }) {
  if (file.semantic.length === 0) return <span className="rounded-sm bg-[#3c7d4f] px-1.5 text-[10px] font-semibold text-white">OK</span>
  return (
    <ul className="space-y-1">
      {file.semantic.map((s, i) => (
        <li key={i} className="leading-snug text-[#fff1c2]">
          <span className={`mr-1 rounded-sm px-1 text-[10px] font-semibold ${s.kind === 'own_bug' ? 'bg-[#3c3c3c]' : 'bg-[#7a5f00]'}`}>{SEMANTIC_BADGE[s.kind] ?? 'NOTE'}</span>
          {s.message}
        </li>
      ))}
    </ul>
  )
}

function MergeCheck({ mergeCheck, live }: { mergeCheck: () => Promise<MergeResult>; live: boolean }) {
  const [result, setResult] = useState<MergeResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      setResult(await mergeCheck())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-2 text-[12px]">
      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <button type="button" onClick={() => void run()} disabled={!live || running} className="rounded-sm bg-[#0e639c] px-3 py-1 text-white hover:bg-[#1177bb] disabled:opacity-40">
          {running ? 'Running…' : 'Run merge check'}
        </button>
        <span className="text-[#9d9d9d]">
          Plain git merges each file on its own. git0 also checks that the functions still agree with each other.
        </span>
      </div>
      {error && <p className="text-[#f48771]">{error}</p>}
      {result && (
        <>
          <VerdictBanner verdict={result.verdict} />
          <div className="min-h-0 overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-left">
              <thead className="text-[10px] uppercase tracking-wide text-[#9d9d9d]">
                <tr className="border-b border-[#2b2b2b]">
                  <th className="px-2 py-1 font-semibold">File</th>
                  <th className="px-2 py-1 font-semibold">Plain git says</th>
                  <th className="px-2 py-1 font-semibold">git0 says</th>
                </tr>
              </thead>
              <tbody>
                {result.files.map((f) => (
                  <MergeRow key={f.path} file={f} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!result && !error && <p className="text-[#6a6a6a]">Run the check to compare what plain git would do with what git0 sees.</p>}
    </div>
  )
}

function MergeRow({ file }: { file: MergeFile }) {
  const base = file.base === 'pulled' ? "vs Alice's version you pulled" : 'vs original'
  return (
    <tr className="border-b border-[#2b2b2b] align-top">
      <td className="px-2 py-1.5 font-mono">
        <div>{file.path}</div>
        <span className="mt-0.5 inline-block rounded-sm bg-[#333] px-1.5 text-[10px] text-[#cccccc]">{base}</span>
        <details className="mt-1">
          <summary className="cursor-pointer text-[11px] text-[#9d9d9d] hover:text-[#cccccc]">merged text</summary>
          <pre className="mt-1 max-h-[160px] max-w-[420px] overflow-auto rounded-sm bg-[#1e1e1e] p-2 font-mono text-[11px] text-[#d4d4d4]">{file.merged}</pre>
        </details>
      </td>
      <td className="px-2 py-1.5">
        <GitCell file={file} />
      </td>
      <td className="px-2 py-1.5">
        <Git0Cell file={file} />
      </td>
    </tr>
  )
}

// ---------- GRAPH ----------

interface GraphPanelProps {
  version: number
  highlight: string[]
  fetchGraph: () => Promise<GraphView>
  live: boolean
  onOpen: () => void
}

/** The small graph: a plain-English caption on top, the canvas underneath. Refetches on every graph_changed. */
function GraphPanel({ version, highlight, fetchGraph, live, onOpen }: GraphPanelProps) {
  const { view, error } = useGraphView(version, live, fetchGraph)
  const data = useMemo(() => (view ? toCanvasData(view) : null), [view])
  const highlightKey = highlight.join('|')
  const spots = useMemo(() => (view ? hotspots(view).length : 0), [view])

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[#0a0a0a]">
      <GraphCaption view={view} onOpen={onOpen} onHelp={() => startGraphTour('panel')} />
      <div data-tour="graph-canvas" className="relative min-h-0 flex-1">
        {data && <GraphCanvas data={data} highlight={highlightKey ? highlightKey.split('|') : []} />}
        {error && <CanvasNotice alert>Graph could not load: {error}</CanvasNotice>}
        {!error && !view && <CanvasNotice>Loading graph…</CanvasNotice>}
        {view && view.nodes.length === 0 && <CanvasNotice>The graph is empty until an agent records an edit.</CanvasNotice>}
        {view && (
          <div data-tour="graph-legend" className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-3 rounded bg-[#1e1e1e]/85 px-2 py-1 text-[11px] text-[#cccccc]">
            {GRAPH_LEGEND.map((k) => (
              <span key={k} className="flex items-center gap-1">
                <span className="inline-block size-2 rounded-full" style={{ background: GRAPH_COLORS[k] }} />
                {k}
              </span>
            ))}
            <span>
              {view.nodes.length} nodes, {view.links.length} edges{spots > 0 ? `, ${spots} hotspot${spots === 1 ? '' : 's'}` : ''}
              {highlight.length > 0 ? `, ${highlight.length} on conflict path` : ''}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
