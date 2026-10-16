// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Live memory graph: what FalkorDB holds behind one branch (facts, the commits that added them, the agents
// that authored those commits, the chat turns behind them), drawn with the <falkordb-canvas> web component
// (@falkordb/canvas 0.3.3). Data comes from GET /api/{tenant}/graph, because FalkorDB itself is not public.
// The component's default size is the window, not its CSS box, so the host box is measured
// and pushed in with setWidth/setHeight (ResizeObserver).

import { Component, useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import '@falkordb/canvas'
import type { Data, FalkorDBCanvas, GraphLink, GraphNode } from '@falkordb/canvas'
import { api } from '../api/client'
import { LEGEND, NODE_COLORS, toCanvasData, type GraphView } from '../lib/memoryGraph'

async function fetchGraph(tenant: string, branch: string): Promise<GraphView> {
  const { data, error } = await api.GET('/api/{tenant}/graph', {
    params: { path: { tenant }, query: { branch } },
  })
  // Fail loudly: show the API's reason (e.g. "tenant not initialised"), never a stand-in graph.
  if (error) throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail))
  return data
}

type Props = {
  tenant: string
  branch?: string
  /** Domain ids (fact, commit, agent, episode) to light up, e.g. a why-path; everything else is dimmed. */
  highlight?: string[]
  onNodeClick?: (id: string) => void
}

export function MemoryCanvas({ tenant, branch = 'main', highlight = [], onNodeClick }: Props) {
  const query = useQuery({
    queryKey: ['graph', tenant, branch],
    queryFn: () => fetchGraph(tenant, branch),
    refetchInterval: 5000, // agents commit while judges watch; a light poll until the SSE commit event lands
  })
  // Structural sharing keeps query.data the same object when a poll returns the same graph, so this
  // (and the canvas update behind it) only reruns when memory actually changed.
  const data = useMemo(() => (query.data ? toCanvasData(query.data) : null), [query.data])
  const view = query.data

  let status: string | null = null
  if (query.isError) status = `Could not load the memory graph: ${query.error.message}`
  else if (query.isPending) status = 'Loading memory graph…'
  else if (view && view.nodes.length === 0) status = `No facts on ${branch} yet.`

  return (
    <div className="relative h-full w-full overflow-hidden">
      <CanvasErrorBoundary key={`${tenant}/${branch}`}>
        <GraphCanvas data={data} highlight={highlight.join('|')} onNodeClick={onNodeClick} />
      </CanvasErrorBoundary>
      {status && <Overlay alert={query.isError}>{status}</Overlay>}
      {view && !status && (
        <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-3 rounded bg-neutral-900/80 px-2 py-1 text-xs text-neutral-300">
          {LEGEND.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: NODE_COLORS[k] }} />
              {k}
            </span>
          ))}
          <span>
            {branch}: {view.nodes.filter((n) => n.label === 'Fact').length} facts
            {view.truncated ? ' (capped)' : ''}
          </span>
        </div>
      )}
    </div>
  )
}

type CanvasProps = {
  data: Data | null
  highlight: string // ids joined with '|': a stable effect dependency, callers pass a fresh array each render
  onNodeClick?: (id: string) => void
}

/** Drives the web component imperatively. Any failure throws, so CanvasErrorBoundary shows it. */
function GraphCanvas({ data, highlight, onNodeClick }: CanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<FalkorDBCanvas>(null)
  const clickRef = useRef(onNodeClick)
  useEffect(() => {
    clickRef.current = onNodeClick // the canvas keeps the handler from mount; read the latest prop through it
  })

  // Mount once: config, click handler, and sizing.
  useEffect(() => {
    const host = hostRef.current
    const canvas = canvasRef.current
    // The custom element is registered by the import above; without it the methods below do not exist.
    if (!host || !canvas || typeof canvas.setConfig !== 'function') {
      throw new Error('<falkordb-canvas> did not load')
    }
    canvas.setConfig({
      backgroundColor: '#0a0a0a',
      foregroundColor: '#e5e7eb',
      captionsKeys: ['name'], // which data property is drawn as the node label (and the hover tooltip)
      eventHandlers: { onNodeClick: (node: GraphNode) => clickRef.current?.(String(node.data.gid)) },
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

  // setGraphData keeps the positions of nodes already on screen, so a new commit does not reshuffle the view.
  useEffect(() => {
    if (data) canvasRef.current?.setGraphData(data)
  }, [data])

  // Highlight = focus mode: dim everything outside the set, draw the set in the selected style.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const lit = new Set(highlight ? highlight.split('|') : [])
    const isLit = (n: GraphNode) => lit.has(String(n.data.gid))
    const linkLit = (l: GraphLink) => isLit(l.source) && isLit(l.target)
    canvas.setConfig({
      dimmed: lit.size > 0,
      isNodeDimmed: (n) => !isLit(n),
      isLinkDimmed: (l) => !linkLit(l),
      isNodeSelected: isLit,
      isLinkSelected: linkLit,
    })
    canvas.refresh()
  }, [highlight, data])

  return (
    <div ref={hostRef} className="absolute inset-0">
      <falkordb-canvas ref={canvasRef} style={{ position: 'absolute', inset: 0, display: 'block' }} />
    </div>
  )
}

function Overlay({ alert, children }: { alert: boolean; children: ReactNode }) {
  return (
    <div
      role={alert ? 'alert' : 'status'}
      className="absolute inset-0 flex items-center justify-center bg-neutral-950/80 p-6 text-center text-sm text-neutral-300"
    >
      {children}
    </div>
  )
}

/** If the web component breaks (no canvas support, bad data), say so instead of a blank panel. */
class CanvasErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) return <Overlay alert>Graph view failed: {this.state.error.message}</Overlay>
    return this.props.children
  }
}
