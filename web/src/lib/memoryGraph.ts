// API graph view (GET /api/{tenant}/graph) -> <falkordb-canvas> data. Pure, so it is tested without a canvas.

import type { Data } from '@falkordb/canvas'
import type { components } from '../api/schema'

export type GraphView = components['schemas']['GraphView']

// Colour by label; commits that matter in the demo (merge, revert, handoff) get their own colour.
export const NODE_COLORS = {
  Fact: '#f472b6',
  Commit: '#60a5fa',
  merge: '#fbbf24',
  revert: '#f87171',
  handoff: '#a78bfa',
  Agent: '#34d399',
  Episode: '#a3a3a3',
} as const
export const LEGEND = ['Fact', 'Commit', 'merge', 'revert', 'Agent', 'Episode'] as const
const LINK_COLORS: Record<string, string> = { DERIVED_FROM: '#fb923c' } // the lineage a revert cascades along
const LINK_COLOR = '#525252'

export function nodeColor(label: string, kind: string): string {
  if (label === 'Commit' && kind in NODE_COLORS) return NODE_COLORS[kind as keyof typeof NODE_COLORS]
  return NODE_COLORS[label as keyof typeof NODE_COLORS] ?? NODE_COLORS.Episode
}

/** The canvas wants numeric ids, so each node's domain id (fact/commit/episode id, agent name) is kept in
 * `data.gid`: that is what highlighting and click handlers speak. */
export function toCanvasData(view: GraphView): Data {
  const num = new Map(view.nodes.map((n, i) => [n.id, i + 1]))
  return {
    nodes: view.nodes.map((n) => ({
      id: num.get(n.id)!,
      labels: [n.label],
      color: nodeColor(n.label, n.kind),
      visible: true,
      data: { ...n.props, name: n.name, gid: n.id, kind: n.kind },
    })),
    links: view.links.map((l, i) => ({
      id: i + 1,
      relationship: l.type,
      color: LINK_COLORS[l.type] ?? LINK_COLOR,
      source: num.get(l.source)!, // the API only returns links between returned nodes
      target: num.get(l.target)!,
      visible: true,
      data: {},
    })),
  }
}
