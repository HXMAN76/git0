// Drives <falkordb-canvas> imperatively (the same way MemoryCanvas does). Shared by the GRAPH tab and the
// full-screen overlay. Highlight = focus mode: everything outside the set is dimmed. Empty highlight = no dimming.

import { useEffect, useRef, type ReactNode } from 'react'
import '@falkordb/canvas'
import type { Data, FalkorDBCanvas, GraphLink, GraphNode } from '@falkordb/canvas'

/** Caption font size in world units (fixed, not auto-fit): the small panel and the full-screen overlay. */
const FONT_SIZE = { panel: 6, overlay: 9 } as const

/** Above this many nodes the File labels are hidden, they are the most numerous and the least useful. */
const FILE_LABEL_LIMIT = 40
/** Small panel only: below this zoom the labels are clutter, so they are skipped. The overlay always shows them. */
const PANEL_MIN_LABEL_ZOOM = 0.6

type ForceGraph = NonNullable<ReturnType<FalkorDBCanvas['getGraph']>>

/**
 * Draws each node's caption under its circle, once per frame, in screen-constant size.
 * The canvas draws captions inside the circle, wrapped to the radius, so on small nodes they are unreadable.
 * Font and offsets are divided by globalScale so the text keeps the same on-screen size at any zoom.
 */
function drawLabels(canvas: FalkorDBCanvas, ctx: CanvasRenderingContext2D, globalScale: number, large: boolean, lit: Set<string>) {
  if (!large && globalScale < PANEL_MIN_LABEL_ZOOM) return
  const nodes = canvas.getGraphData().nodes
  const hideFiles = nodes.length > FILE_LABEL_LIMIT
  ctx.font = `${(large ? 12 : 10) / globalScale}px "Segoe UI", sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  // Dark outline keeps the text readable over edges and neighbouring nodes.
  ctx.lineJoin = 'round'
  ctx.lineWidth = 3 / globalScale
  ctx.strokeStyle = '#1e1e1e'
  ctx.fillStyle = '#d4d4d4'
  for (const node of nodes) {
    if (node.x === undefined || node.y === undefined || !node.data.caption) continue
    if (hideFiles && node.labels[0] === 'File') continue
    // Mirrors the focus mode: dimmed nodes get a faint label, matching their circle.
    ctx.globalAlpha = lit.size > 0 && !lit.has(String(node.data.gid)) ? 0.35 : 1
    const text = String(node.data.caption)
    const y = node.y + (node.size ?? 0) + 2 / globalScale
    ctx.strokeText(text, node.x, y)
    ctx.fillText(text, node.x, y)
  }
  ctx.globalAlpha = 1
}

interface GraphCanvasProps {
  data: Data
  /** Ids to light up (domain ids, i.e. data.gid). Empty = nothing dimmed. */
  highlight: string[]
  onNodeClick?: (gid: string) => void
  /** Left click on empty canvas. */
  onBackgroundClick?: () => void
  /** Full-screen sizing: bigger captions. */
  large?: boolean
  /** Zoom-to-fit again whenever the canvas is resized (window resize), not only on the first load. */
  fitOnResize?: boolean
}

export function GraphCanvas({ data, highlight, onNodeClick, onBackgroundClick, large = false, fitOnResize = false }: GraphCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<FalkorDBCanvas>(null)
  const clickRef = useRef(onNodeClick)
  const bgClickRef = useRef(onBackgroundClick)
  const fittedRef = useRef(false)
  const fitOnResizeRef = useRef(fitOnResize)
  // Read per frame by the label hook, so they are kept current here rather than captured at attach time.
  const largeRef = useRef(large)
  const litRef = useRef<Set<string>>(new Set())
  const fgRef = useRef<ForceGraph>(undefined)
  const highlightKey = highlight.join('|')

  useEffect(() => {
    // The canvas keeps the handlers from mount; read the latest through these refs.
    clickRef.current = onNodeClick
    bgClickRef.current = onBackgroundClick
    fitOnResizeRef.current = fitOnResize
    largeRef.current = large
  })

  // Labels go on the force-graph instance. getGraph() is undefined until the graph is built, so this is retried
  // from the data effect below until it succeeds.
  const attachLabels = () => {
    const canvas = canvasRef.current
    const fg = canvas?.getGraph()
    if (!canvas || !fg || fgRef.current === fg) return
    fgRef.current = fg
    fg.onRenderFramePost((ctx, globalScale) => drawLabels(canvas, ctx, globalScale, largeRef.current, litRef.current))
  }

  useEffect(
    () => () => {
      // Unmount: replace our hook with a no-op so it stops drawing on the old instance.
      fgRef.current?.onRenderFramePost(() => {})
      fgRef.current = undefined
    },
    [],
  )

  // Config, click handlers and sizing (re-run only if `large` changes). The component defaults to the window size, so the box is pushed in.
  useEffect(() => {
    const host = hostRef.current
    const canvas = canvasRef.current
    if (!host || !canvas || typeof canvas.setConfig !== 'function') {
      throw new Error('<falkordb-canvas> did not load')
    }
    canvas.setConfig({
      backgroundColor: '#0a0a0a',
      foregroundColor: '#e5e7eb',
      // The in-circle caption is blanked (data.inner, see toCanvasData in lib.ts). The readable label is drawn
      // under the node by drawLabels, which reads data.caption.
      captionsKeys: [['inner', true]],
      // Fixed-size captions: textFillRatio 0 turns off the auto-fit, which would shrink short captions to tiny text.
      nodeStyle: { textFillRatio: 0, fontSize: large ? FONT_SIZE.overlay : FONT_SIZE.panel },
      // Padding around the graph when zooming to fit (fraction of the smallest canvas side).
      interaction: { zoomToFitPadding: 0.15 },
      eventHandlers: {
        onNodeClick: (node: GraphNode) => clickRef.current?.(String(node.data.gid)),
        onBackgroundClick: () => bgClickRef.current?.(),
      },
    })
    const syncSize = () => {
      const { width, height } = host.getBoundingClientRect()
      canvas.setWidth(Math.floor(width))
      canvas.setHeight(Math.floor(height))
      if (fitOnResizeRef.current && fittedRef.current) canvas.zoomToFit()
    }
    syncSize()
    const observer = new ResizeObserver(syncSize)
    observer.observe(host)
    return () => observer.disconnect()
  }, [large])

  // setGraphData keeps positions of nodes already on screen, so a new edit does not reshuffle the layout.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.setGraphData(data)
    attachLabels()
    // Fit the first non-empty graph once; after that the user owns the zoom (until a resize, if fitOnResize).
    if (!fittedRef.current && data.nodes.length > 0) {
      fittedRef.current = true
      canvas.zoomToFit()
    }
  }, [data])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const lit = new Set(highlightKey ? highlightKey.split('|') : [])
    const isLit = (n: GraphNode) => lit.has(String(n.data.gid))
    const linkLit = (l: GraphLink) => isLit(l.source) && isLit(l.target)
    litRef.current = lit
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

/** Centered message on top of the canvas (loading, empty, error). */
export function CanvasNotice({ alert, children }: { alert?: boolean; children: ReactNode }) {
  return (
    <div role={alert ? 'alert' : 'status'} className="absolute inset-0 flex items-center justify-center p-6 text-center text-[12px] text-[#9d9d9d]">
      {children}
    </div>
  )
}
