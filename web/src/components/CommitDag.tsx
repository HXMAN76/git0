// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Live commit DAG: fetches /log for all agent branches + main, merges into one dagre layout.

import { useMemo } from 'react'
import * as dagre from '@dagrejs/dagre'
import { useQuery } from '@tanstack/react-query'
import {
  Background,
  Controls,
  Position,
  ReactFlow,
  type Edge,
  type Node as FlowNode,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { components } from '../api/schema'
import { api } from '../api/client'

const BRANCH_COLOR: Record<string, string> = {
  planner: '#a78bfa',   // purple
  scheduler: '#60a5fa', // blue
  notes: '#34d399',     // green
  main: '#f472b6',      // pink
}
const DEFAULT_COLOR = '#737373'

const NODE_WIDTH = 200
const NODE_HEIGHT = 52
const BRANCHES = ['planner', 'scheduler', 'notes', 'main'] as const

type ApiCommit = components['schemas']['Commit']

async function fetchLog(tenant: string, branch: string): Promise<ApiCommit[]> {
  const { data, error } = await api.GET('/api/{tenant}/branches/{name}/log', {
    params: { path: { tenant, name: branch }, query: { limit: 60 } },
  })
  if (error) return []
  return data ?? []
}

function layoutDag(
  commits: (ApiCommit & { branch: string })[],
): { nodes: FlowNode[]; edges: Edge[] } {
  const graph = new dagre.graphlib.Graph()
  graph.setDefaultEdgeLabel(() => ({}))
  graph.setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 50 })

  // Dedupe by id (same commit can appear in multiple branches after a merge)
  const byId = new Map<string, ApiCommit & { branch: string }>()
  for (const c of commits) if (!byId.has(c.id)) byId.set(c.id, c)

  for (const id of byId.keys()) graph.setNode(id, { width: NODE_WIDTH, height: NODE_HEIGHT })

  // Build parent edges from seq order within each branch (seq N-1 is parent of seq N)
  const edgeSeen = new Set<string>()
  for (const branch of BRANCHES) {
    const branchCommits = commits.filter((c) => c.branch === branch).sort((a, b) => a.seq - b.seq)
    for (let i = 1; i < branchCommits.length; i++) {
      const parent = branchCommits[i - 1].id
      const child = branchCommits[i].id
      const key = `${parent}->${child}`
      if (!edgeSeen.has(key)) { edgeSeen.add(key); graph.setEdge(parent, child) }
    }
  }

  dagre.layout(graph)

  const nodes: FlowNode[] = []
  for (const [id, c] of byId) {
    const placed = graph.node(id)
    if (!placed) continue
    const branch = c.branch
    nodes.push({
      id,
      position: { x: placed.x - NODE_WIDTH / 2, y: placed.y - NODE_HEIGHT / 2 },
      data: {
        label: (
          <div style={{ fontSize: 11, lineHeight: 1.3 }}>
            <div style={{ color: BRANCH_COLOR[branch] ?? DEFAULT_COLOR, fontWeight: 600 }}>
              {branch}
            </div>
            <div style={{ color: '#d4d4d4', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: NODE_WIDTH - 16 }}>
              {c.msg ?? id.slice(0, 8)}
            </div>
          </div>
        ),
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      style: {
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        background: '#1a1a1a',
        border: `1px solid ${BRANCH_COLOR[branch] ?? DEFAULT_COLOR}`,
        borderRadius: 6,
        padding: '6px 8px',
      },
    })
  }

  const edges: Edge[] = []
  for (const key of edgeSeen) {
    const [source, target] = key.split('->')
    edges.push({ id: key, source, target, style: { stroke: '#525252' } })
  }

  return { nodes, edges }
}

export function CommitDag({ tenant }: { tenant: string }) {
  const queries = BRANCHES.map((branch) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useQuery({
      queryKey: ['log', tenant, branch],
      queryFn: () => fetchLog(tenant, branch),
      refetchInterval: 4000,
    }),
  )

  const allCommits = useMemo(() => {
    const out: (ApiCommit & { branch: string })[] = []
    queries.forEach((q, i) => {
      for (const c of q.data ?? []) out.push({ ...c, branch: BRANCHES[i] })
    })
    return out
  }, [queries.map((q) => q.data)])  // eslint-disable-line react-hooks/exhaustive-deps

  const { nodes, edges } = useMemo(
    () => (allCommits.length ? layoutDag(allCommits) : { nodes: [], edges: [] }),
    [allCommits],
  )

  const loading = queries.some((q) => q.isPending)
  const empty = !loading && allCommits.length === 0

  return (
    <div className="relative h-full w-full">
      <ReactFlow nodes={nodes} edges={edges} fitView colorMode="dark">
        <Background />
        <Controls />
      </ReactFlow>
      {/* legend */}
      <div className="pointer-events-none absolute left-2 top-2 flex gap-3 rounded bg-neutral-900/80 px-2 py-1 text-xs">
        {BRANCHES.map((b) => (
          <span key={b} className="flex items-center gap-1 text-neutral-300">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: BRANCH_COLOR[b] }} />
            {b}
          </span>
        ))}
      </div>
      {loading && (
        <p className="absolute inset-0 flex items-center justify-center text-sm text-neutral-400">
          Loading commits…
        </p>
      )}
      {empty && (
        <p className="absolute inset-0 flex items-center justify-center text-sm text-neutral-500">
          No commits yet — seed the room first.
        </p>
      )}
    </div>
  )
}
