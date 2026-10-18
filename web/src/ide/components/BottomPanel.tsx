// Bottom panel: GIT0 RELAY log, GRAPH (FalkorDB code graph), PROBLEMS (conflicts), MERGE CHECK.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import '@falkordb/canvas'
import type { Data, FalkorDBCanvas, GraphLink, GraphNode } from '@falkordb/canvas'
import { ApiError } from '../api'
import { GRAPH_COLORS, GRAPH_LEGEND, toCanvasData } from '../lib'
import type { IdeState, LogEntry, Tone } from '../state'
import { AGENT_META, type GraphView, type MergeResult } from '../types'

type TabId = 'relay' | 'graph' | 'problems' | 'merge'

interface BottomPanelProps {
  state: IdeState
  fetchGraph: () => Promise<GraphView>
  mergeCheck: () => Promise<MergeResult>
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'relay', label: 'GIT0 RELAY' },
  { id: 'graph', label: 'GRAPH' },
  { id: 'problems', label: 'PROBLEMS' },
  { id: 'merge', label: 'MERGE CHECK' },
]

export function BottomPanel({ state, fetchGraph, mergeCheck }: BottomPanelProps) {
  const [tab, setTab] = useState<TabId>('relay')
  const problemCount = state.conflicts.length
  return (
    <section className="flex h-[240px] shrink-0 flex-col border-t border-[#2b2b2b] bg-[#1e1e1e] lg:h-[205px]" aria-label="Panel">
      <div role="tablist" className="flex h-[30px] shrink-0 items-center gap-1 border-b border-[#2b2b2b] bg-[#252526] px-2 text-[11px]">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 border-b-2 px-2 py-1 ${tab === t.id ? 'border-[#e7e7e7] text-[#e7e7e7]' : 'border-transparent text-[#9d9d9d] hover:text-[#cccccc]'}`}
          >
            {t.label}
            {t.id === 'problems' && problemCount > 0 && (
              <span className="rounded-full bg-[#f14c4c] px-1.5 text-[10px] font-semibold text-white">{problemCount}</span>
            )}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'relay' && <RelayLog log={state.log} />}
        {tab === 'graph' && <GraphPanel version={state.graphVersion} highlight={state.highlight} fetchGraph={fetchGraph} live={state.sessionId !== null} />}
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
    <div className="flex h-full flex-col gap-2 p-2 text-[12px]">
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => void run()} disabled={!live || running} className="rounded-sm bg-[#0e639c] px-3 py-1 text-white hover:bg-[#1177bb] disabled:opacity-40">
          {running ? 'Running…' : 'Run merge check'}
        </button>
        <span className="text-[#9d9d9d]">What plain git would do: 3-way merge of A and B against the template, per file.</span>
      </div>
      {error && <p className="text-[#f48771]">{error}</p>}
      {result && (
        <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto">
          {result.files.map((f) => (
            <details key={f.path} className="rounded-sm bg-[#252526] px-2 py-1">
              <summary className="flex cursor-pointer items-center gap-2 font-mono">
                <span className={`rounded-sm px-1.5 text-[10px] font-semibold ${f.conflicted ? 'bg-[#f14c4c] text-white' : 'bg-[#3c7d4f] text-white'}`}>
                  {f.conflicted ? 'CONFLICT' : 'CLEAN'}
                </span>
                {f.path}
              </summary>
              <pre className="mt-1 max-h-[140px] overflow-auto rounded-sm bg-[#1e1e1e] p-2 font-mono text-[11px] text-[#d4d4d4]">{f.merged}</pre>
            </details>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------- GRAPH ----------

type CanvasHandle = FalkorDBCanvas

interface GraphPanelProps {
  version: number
  highlight: string[]
  fetchGraph: () => Promise<GraphView>
  live: boolean
}

/** Refetches on every graph_changed (version bump). Mounted only while the tab is open, so it is sized correctly. */
function GraphPanel({ version, highlight, fetchGraph, live }: GraphPanelProps) {
  const [view, setView] = useState<GraphView | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!live) return
    let cancelled = false
    fetchGraph().then(
      (v) => {
        if (!cancelled) {
          setView(v)
          setError(null)
        }
      },
      (err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      },
    )
    return () => {
      cancelled = true
    }
    // Only a new graph_changed (version bump) refetches. fetchGraph is bound to the session.
  }, [version, live, fetchGraph])

  const data = useMemo(() => (view ? toCanvasData(view) : null), [view])
  const highlightKey = highlight.join('|')

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#0a0a0a]">
      {data && <GraphCanvas data={data} highlightKey={highlightKey} />}
      {error && <Overlay alert>Graph could not load: {error}</Overlay>}
      {!error && !view && <Overlay>Loading graph…</Overlay>}
      {view && view.nodes.length === 0 && <Overlay>The graph is empty until an agent records an edit.</Overlay>}
      {view && (
        <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-3 rounded bg-[#1e1e1e]/85 px-2 py-1 text-[11px] text-[#cccccc]">
          {GRAPH_LEGEND.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span className="inline-block size-2 rounded-full" style={{ background: GRAPH_COLORS[k] }} />
              {k}
            </span>
          ))}
          <span>
            {view.nodes.length} nodes, {view.links.length} edges{highlight.length > 0 ? `, ${highlight.length} on conflict path` : ''}
          </span>
        </div>
      )}
    </div>
  )
}

function Overlay({ alert, children }: { alert?: boolean; children: ReactNode }) {
  return (
    <div role={alert ? 'alert' : 'status'} className="absolute inset-0 flex items-center justify-center p-6 text-center text-[12px] text-[#9d9d9d]">
      {children}
    </div>
  )
}

/** Drives <falkordb-canvas> imperatively, the same way the memory graph does. Highlight = focus mode. */
function GraphCanvas({ data, highlightKey }: { data: Data; highlightKey: string }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<CanvasHandle>(null)

  // Mount once: config and sizing. The component defaults to the window size, so the box is pushed in.
  useEffect(() => {
    const host = hostRef.current
    const canvas = canvasRef.current
    if (!host || !canvas || typeof canvas.setConfig !== 'function') return
    canvas.setConfig({
      backgroundColor: '#0a0a0a',
      foregroundColor: '#e5e7eb',
      captionsKeys: ['name'],
    })
    const syncSize = () => {
      const { width, height } = host.getBoundingClientRect()
      canvas.setWidth(Math.floor(width))
      canvas.setHeight(Math.floor(height))
    }
    syncSize()
    const observer = new ResizeObserver(syncSize)
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  // setGraphData keeps positions of nodes already on screen, so a new edit does not reshuffle the layout.
  useEffect(() => {
    canvasRef.current?.setGraphData(data)
  }, [data])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const lit = new Set(highlightKey ? highlightKey.split('|') : [])
    const isLit = (n: GraphNode) => lit.has(String(n.data.gid))
    const linkLit = (l: GraphLink) => isLit(l.source) && isLit(l.target)
    canvas.setConfig({
      dimmed: lit.size > 0,
      isNodeDimmed: (n: GraphNode) => !isLit(n),
      isLinkDimmed: (l: GraphLink) => !linkLit(l),
      isNodeSelected: isLit,
      isLinkSelected: linkLit,
    })
    canvas.refresh()
  }, [highlightKey, data])

  return (
    <div ref={hostRef} className="absolute inset-0">
      <falkordb-canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, display: 'block' }} />
    </div>
  )
}
