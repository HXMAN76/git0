// Full-screen graph view and the plain-English caption shown in the small GRAPH tab. The overlay is the
// same page (no new browser tab, so the SSE stream and the pagehide logic are untouched).

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Data } from '@falkordb/canvas'
import {
  buildStory,
  describeNode,
  filterGraph,
  focusFor,
  hotspots,
  LEGEND_ITEMS,
  relativeTime,
  WHY_GRAPH,
  type StoryItem,
} from '../insights'
import { toCanvasData } from '../lib'
import { startGraphTour } from '../tour'
import type { GraphView } from '../types'
import { CanvasNotice, GraphCanvas } from './GraphCanvas'
import { useGraphView } from './useGraphView'

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

/** The two newest story items, one line each. Shown above the small graph so its meaning is visible at a glance. */
export function GraphCaption({ view, onOpen, onHelp }: { view: GraphView | null; onOpen: () => void; onHelp: () => void }) {
  const story = useMemo(() => (view ? buildStory(view) : []), [view])
  const spotCount = useMemo(() => (view ? hotspots(view).length : 0), [view])
  const now = useNow(5000)
  return (
    <div className="flex shrink-0 items-start gap-3 border-b border-[#2b2b2b] bg-[#252526] px-3 py-1.5 text-[12px]">
      <div className="min-w-0 flex-1 space-y-0.5" data-tour="graph-story">
        {story.length === 0 && <p className="text-[#858585]">The story of the shop appears here as agents make changes.</p>}
        {story.slice(0, 2).map((item) => (
          <p key={item.nodeId} className={`truncate ${item.tone === 'deny' ? 'text-[#f48771]' : 'text-[#cccccc]'}`} title={item.text}>
            <span className="mr-2 font-mono text-[11px] text-[#6a6a6a]">{relativeTime(item.ts, now)}</span>
            {item.text}
          </p>
        ))}
        {spotCount > 0 && (
          <p className="text-[#e5c07b]" data-tour="graph-hotspots">
            ⚠ {spotCount} hotspot{spotCount === 1 ? '' : 's'}: symbols both agents touched
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <HelpButton onClick={onHelp} />
        <button
          type="button"
          onClick={onOpen}
          data-tour="open-graph"
          className="rounded-sm border border-[#6b6b6b] px-2 py-[2px] text-[11px] hover:bg-[#4a4a4a]"
          title="Open the full-screen graph (Esc closes it)"
        >
          ⤢ Open graph
        </button>
      </div>
    </div>
  )
}

/** The "?" that starts the 4-step graph helper. */
export function HelpButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex size-[22px] items-center justify-center rounded-full border border-[#6b6b6b] text-[12px] font-semibold text-[#cccccc] hover:bg-[#4a4a4a]"
      title="What am I looking at? A 4-step tour of this graph"
      aria-label="What am I looking at? Start the graph tour"
    >
      ?
    </button>
  )
}

interface GraphOverlayProps {
  version: number
  live: boolean
  fetchGraph: () => Promise<GraphView>
  /** Symbol ids on the latest conflict path (lit up when nothing is selected). */
  conflictHighlight: string[]
  onClose: () => void
}

export function GraphOverlay({ version, live, fetchGraph, conflictHighlight, onClose }: GraphOverlayProps) {
  const { view, error } = useGraphView(version, live, fetchGraph)
  const [onlyChanged, setOnlyChanged] = useState(false)
  const [showFiles, setShowFiles] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  /** Off by default: the overlay is not dimmed unless a node is selected or this is switched on. */
  const [conflictLit, setConflictLit] = useState(false)
  const [newIds, setNewIds] = useState<ReadonlySet<string>>(() => new Set())
  const previousIds = useRef<Set<string> | null>(null)
  const now = useNow(5000)

  const close = useCallback(() => onClose(), [onClose])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  // A node counts as NEW when it was missing from the previous fetch. The first fetch marks nothing.
  useEffect(() => {
    if (!view) return
    const current = new Set(view.nodes.map((n) => n.id))
    const prev = previousIds.current
    previousIds.current = current
    if (prev === null) return
    setNewIds(new Set([...current].filter((id) => !prev.has(id))))
  }, [view])

  const shown = useMemo(() => (view ? filterGraph(view, { onlyChanged, showFiles }) : null), [view, onlyChanged, showFiles])
  // Edge labels only on the selected node's edges. Bigger nodes (2x the panel) so the captions fit.
  const data: Data | null = useMemo(
    () => (shown ? toCanvasData(shown, { newIds, sizeScale: 2, labelNode: selected }) : null),
    [shown, newIds, selected],
  )
  // Selection lights the node, its 1-hop neighbours and its blast radius. With nothing selected, nothing is
  // dimmed unless "Highlight last conflict" is on.
  const highlight = useMemo(() => {
    if (selected && view) return focusFor(view, selected)
    return conflictLit ? conflictHighlight : []
  }, [selected, view, conflictLit, conflictHighlight])
  const story = useMemo(() => (view ? buildStory(view) : []), [view])
  const spots = useMemo(() => (view ? hotspots(view) : []), [view])
  const card = useMemo(() => (view && selected ? describeNode(view, selected) : null), [view, selected])

  let notice: string | null = null
  if (!view && !error) notice = 'Loading graph…'
  else if (view && view.nodes.length === 0) notice = 'The graph is empty until an agent records an edit.'
  else if (shown && shown.nodes.length === 0) notice = 'Nothing to show with these filters. Turn off "Show only what changed".'

  return (
    <div role="dialog" aria-modal="true" aria-label="Code graph" className="fixed inset-0 z-50 flex flex-col bg-[#0a0a0a] text-[13px] text-[#cccccc]">
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-[#2b2b2b] bg-[#252526] px-4 py-2">
        <div className="mr-2">
          <div className="font-semibold text-white">Code graph</div>
          <div className="text-[11px] text-[#9d9d9d]">Who changed what in the shop, and what depends on what</div>
        </div>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]" aria-label="Legend" data-tour="graph-legend">
          {LEGEND_ITEMS.map((item) => (
            <li key={item.label} className="flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-full" style={{ background: item.color }} aria-hidden="true" />
              <span className="font-semibold text-[#e0e0e0]">{item.label}</span>
              <span className="text-[#9d9d9d]">= {item.text}</span>
            </li>
          ))}
        </ul>
        <div className="ml-auto flex items-center gap-2">
          <Toggle pressed={onlyChanged} onClick={() => setOnlyChanged((v) => !v)}>
            Show only what changed
          </Toggle>
          <Toggle pressed={showFiles} onClick={() => setShowFiles((v) => !v)}>
            Show files
          </Toggle>
          <Toggle pressed={conflictLit} onClick={() => setConflictLit((v) => !v)}>
            Highlight last conflict
          </Toggle>
          <HelpButton onClick={() => startGraphTour('overlay')} />
          <button type="button" onClick={close} className="rounded-sm border border-[#6b6b6b] px-3 py-[3px] text-[12px] hover:bg-[#4a4a4a]" aria-label="Close graph (Esc)">
            ✕ Close
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div data-tour="graph-canvas" className="relative h-[55vh] min-w-0 flex-[7] bg-[#0a0a0a] lg:h-auto">
          {data && (
            <GraphCanvas
              data={data}
              highlight={highlight}
              onNodeClick={setSelected}
              onBackgroundClick={() => setSelected(null)}
              large
              fitOnResize
            />
          )}
          {error && <CanvasNotice alert>Graph could not load: {error}</CanvasNotice>}
          {!error && notice && <CanvasNotice>{notice}</CanvasNotice>}
          {view && (
            <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-[#1e1e1e]/85 px-2 py-1 text-[11px] text-[#9d9d9d]">
              {shown?.nodes.length ?? 0} nodes, {shown?.links.length ?? 0} links. Click a node to see what it means. Click empty space to clear.
              {newIds.size > 0 && <span className="ml-2 font-semibold text-[#89d185]">{newIds.size} new</span>}
            </div>
          )}
        </div>

        <aside className="flex min-h-0 flex-[3] flex-col overflow-hidden border-t border-[#2b2b2b] bg-[#181818] lg:w-[380px] lg:flex-none lg:border-l lg:border-t-0">
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
            <h2 className="text-[14px] font-semibold text-white">What the graph is telling you</h2>

            {card && (
              <Section title={`Selected: ${card.kind}`} action={<button type="button" onClick={() => setSelected(null)} className="text-[11px] text-[#9d9d9d] hover:text-white">Clear</button>}>
                <div className="rounded-sm border border-[#333] bg-[#222] p-3">
                  <div className="font-mono text-[13px] font-semibold text-[#dcdcaa]">{card.title}</div>
                  <ul className="mt-2 list-disc space-y-1 pl-4 leading-relaxed">
                    {card.lines.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                </div>
              </Section>
            )}

            <Section title={`Hotspots (${spots.length})`} tour="graph-hotspots">
              {spots.length === 0 && <p className="text-[#858585]">No symbol has been touched by both agents yet.</p>}
              {spots.map((spot) => (
                <button
                  key={spot.symbolId}
                  type="button"
                  onClick={() => setSelected(spot.symbolId)}
                  className="block w-full rounded-sm border-l-2 border-[#e5c07b] bg-[#2a2516] p-2 text-left leading-relaxed text-[#f3e3b3] hover:bg-[#332e1c]"
                >
                  {spot.text}
                </button>
              ))}
            </Section>

            <Section title="What happened, newest first" tour="graph-story">
              {story.length === 0 && <p className="text-[#858585]">Nothing yet. Run the scenario and watch git0 catch a collision.</p>}
              <ol className="space-y-2">
                {story.map((item) => (
                  <StoryRow key={item.nodeId} item={item} now={now} isNew={newIds.has(item.nodeId)} onSelect={() => setSelected(item.nodeId)} />
                ))}
              </ol>
            </Section>

            <Section title="Why a graph?">
              <p className="rounded-sm bg-[#222] p-3 leading-relaxed text-[#cccccc]">{WHY_GRAPH}</p>
            </Section>
          </div>
        </aside>
      </div>
    </div>
  )
}

function Toggle({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`rounded-sm border px-3 py-[3px] text-[12px] ${pressed ? 'border-[#007acc] bg-[#094771] text-white' : 'border-[#6b6b6b] text-[#cccccc] hover:bg-[#4a4a4a]'}`}
    >
      {children}
    </button>
  )
}

function Section({ title, action, children, tour }: { title: string; action?: ReactNode; children: ReactNode; tour?: string }) {
  return (
    <section className="space-y-2 text-[12px]" data-tour={tour}>
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[#9d9d9d]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function StoryRow({ item, now, isNew, onSelect }: { item: StoryItem; now: number; isNew: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`w-full rounded-sm border-l-2 bg-[#222] p-2 text-left leading-relaxed hover:bg-[#2a2d2e] ${item.tone === 'deny' ? 'border-[#f14c4c] text-[#f8c4b8]' : 'border-[#4fc1ff] text-[#dddddd]'}`}
      >
        <span className="mb-0.5 flex items-center gap-2 font-mono text-[10px] text-[#858585]">
          {relativeTime(item.ts, now)}
          {isNew && <span className="rounded-sm bg-[#89d185] px-1 font-sans font-semibold text-[#0a0a0a]">NEW</span>}
        </span>
        {item.text}
      </button>
    </li>
  )
}
