// Owner: Person D — see docs/team/person-d-ui.md
// Proof of integration: a hard-coded 3-commit DAG laid out with dagre and rendered by React Flow.
// TODO: replace COMMITS with REST data (TanStack Query) and add WhyPath highlighting.

import { useMemo } from 'react'
import * as dagre from '@dagrejs/dagre'
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node as FlowNode,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

type Commit = { id: string; message: string; parents: string[] }

const COMMITS: Commit[] = [
  { id: 'c1', message: 'init repo', parents: [] },
  { id: 'c2', message: 'add chat panel', parents: ['c1'] },
  { id: 'c3', message: 'wire SSE stream', parents: ['c2'] },
]

const NODE_WIDTH = 180
const NODE_HEIGHT = 56

function layoutCommits(commits: Commit[]): { nodes: FlowNode[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph()
  graph.setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'TB', nodesep: 40, ranksep: 60 })

  for (const c of commits) graph.setNode(c.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const c of commits) for (const p of c.parents) graph.setEdge(p, c.id)

  dagre.layout(graph)

  const nodes: FlowNode[] = commits.map((c) => {
    const placed = graph.node(c.id) // dagre gives the center; React Flow wants the top-left
    return {
      id: c.id,
      position: { x: placed.x - NODE_WIDTH / 2, y: placed.y - NODE_HEIGHT / 2 },
      data: { label: `${c.id} ${c.message}` },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      style: { width: NODE_WIDTH, height: NODE_HEIGHT },
    }
  })

  const edges: Edge[] = commits.flatMap((c) =>
    c.parents.map((p) => ({ id: `${p}->${c.id}`, source: p, target: c.id })),
  )

  return { nodes, edges }
}

export function CommitDag() {
  const { nodes, edges } = useMemo(() => layoutCommits(COMMITS), [])

  return (
    <div className="h-full w-full">
      <ReactFlow nodes={nodes} edges={edges} fitView colorMode="dark">
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  )
}
