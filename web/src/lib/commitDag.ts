// Builds the history graph from each branch's log. Each commit lists its parents (two for a merge), so a
// merge is drawn joining both branches. A log without parents (an API from before they were added) falls
// back to linear edges per branch: consecutive commits in that branch's history. Shared commits are
// deduped by id, so agent branches fork off the team history where they started. A commit is coloured by
// the first branch (team memory first) whose history has it: once merged, an agent's work counts as team
// memory.

import type { BranchId, Commit } from './branches'
import { BRANCHES } from './branches'

// parents is optional here only for the linear fallback; the current API always sends it.
export type LogCommit = Omit<Commit, 'parents'> & { parents?: string[] }
export type DagNode = LogCommit & { branch: BranchId }
export type DagEdge = { id: string; source: string; target: string; branch: BranchId }

export function buildDag(logs: Partial<Record<BranchId, LogCommit[] | undefined>>): {
  nodes: DagNode[]
  edges: DagEdge[]
} {
  const nodes = new Map<string, DagNode>()
  const edges = new Map<string, DagEdge>()
  const link = (source: string, target: string, branch: BranchId) => {
    const id = `${source}->${target}`
    if (!edges.has(id)) edges.set(id, { id, source, target, branch })
  }
  for (const { id: branch } of BRANCHES) {
    const log = [...(logs[branch] ?? [])].sort((a, b) => a.seq - b.seq || (a.ts ?? 0) - (b.ts ?? 0))
    log.forEach((c, i) => {
      if (!nodes.has(c.id)) nodes.set(c.id, { ...c, branch })
      if (c.parents) c.parents.forEach((p) => link(p, c.id, branch))
      else if (i > 0) link(log[i - 1].id, c.id, branch)
    })
  }
  // A parent older than the log's limit is not a node; dagre would invent a blank one for its edge.
  const drawn = [...edges.values()].filter((e) => nodes.has(e.source) && nodes.has(e.target))
  return { nodes: [...nodes.values()], edges: drawn }
}
