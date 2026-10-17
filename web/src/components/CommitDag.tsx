// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Team history: every memory update on team memory, Planner, Scheduler and Notes, from each branch's
// GET /log, laid out left-to-right with dagre and drawn with React Flow. See lib/commitDag.ts for why
// edges are linear per branch.

import { useMemo } from 'react'
import * as dagre from '@dagrejs/dagre'
import { Background, Controls, Position, ReactFlow, type Edge, type Node as FlowNode } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { BRANCHES, branchInfo, useBranchLogs } from '../lib/branches'
import { buildDag, type DagEdge, type DagNode } from '../lib/commitDag'
import { ErrorBanner } from './ErrorBanner'

const NODE_WIDTH = 200
const NODE_HEIGHT = 60

function layout(nodes: DagNode[], edges: DagEdge[]): { nodes: FlowNode[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph()
  graph.setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 50 })
  for (const n of nodes) graph.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const e of edges) graph.setEdge(e.source, e.target)
  dagre.layout(graph)

  return {
    nodes: nodes.map((c) => {
      const placed = graph.node(c.id) // dagre gives the center; React Flow wants the top-left
      const color = branchInfo(c.branch).color
      const merge = c.kind === 'merge'
      const msg = (c.msg ?? '').replace(/ into main\b/, ' into team memory') // server text; no git words in the UI
      return {
        id: c.id,
        position: { x: placed.x - NODE_WIDTH / 2, y: placed.y - NODE_HEIGHT / 2 },
        data: {
          label: (
            <div className="text-left" title={msg}>
              <div className="truncate text-xs font-medium">{merge ? `⇄ ${msg}` : msg}</div>
              <div className="text-[10px] opacity-70">
                {c.agent_id ?? 'unknown'} · +{c.added} −{c.removed}
              </div>
            </div>
          ),
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        style: {
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          background: '#171717',
          color: '#e5e5e5',
          border: `${merge ? 3 : 1}px solid ${color}`,
        },
      }
    }),
    edges: edges.map((e) => ({ ...e, style: { stroke: branchInfo(e.branch).color } })),
  }
}

export function CommitDag({ tenant }: { tenant: string }) {
  const { logs, error, isPending } = useBranchLogs(tenant)
  const flow = useMemo(() => {
    const { nodes, edges } = buildDag(logs)
    return layout(nodes, edges)
  }, [logs])

  if (error) return <div className="m-4"><ErrorBanner>Could not load the team history: {error.message}</ErrorBanner></div>
  if (isPending) return <p className="m-4 text-sm text-neutral-400">Loading team history…</p>

  return (
    <div className="relative h-full w-full">
      <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView colorMode="dark" nodesConnectable={false}>
        <Background />
        <Controls />
      </ReactFlow>
      <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-3 rounded bg-neutral-900/80 px-2 py-1 text-xs text-neutral-300">
        {BRANCHES.map((b) => (
          <span key={b.id} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: b.color }} />
            {b.label}
          </span>
        ))}
        <span>⇄ = merged into team memory</span>
      </div>
    </div>
  )
}
