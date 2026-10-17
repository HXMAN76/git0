// Builds the history graph from each branch's log. The log API lists a branch's commits (ancestors
// included) but not each commit's parents, so edges are drawn linearly per branch: consecutive commits in
// that branch's history. Shared commits are deduped by id, so agent branches fork off the team history
// where they started. A commit is coloured by the first branch (team memory first) whose history has it:
// once merged, an agent's work counts as team memory.

import type { BranchId, Commit } from './branches'
import { BRANCHES } from './branches'

export type DagNode = Commit & { branch: BranchId }
export type DagEdge = { id: string; source: string; target: string; branch: BranchId }

export function buildDag(logs: Partial<Record<BranchId, Commit[] | undefined>>): {
  nodes: DagNode[]
  edges: DagEdge[]
} {
  const nodes = new Map<string, DagNode>()
  const edges = new Map<string, DagEdge>()
  for (const { id: branch } of BRANCHES) {
    const log = [...(logs[branch] ?? [])].sort((a, b) => a.seq - b.seq || (a.ts ?? 0) - (b.ts ?? 0))
    log.forEach((c, i) => {
      if (!nodes.has(c.id)) nodes.set(c.id, { ...c, branch })
      const prev = log[i - 1]
      const id = prev && `${prev.id}->${c.id}`
      if (prev && !edges.has(id)) edges.set(id, { id, source: prev.id, target: c.id, branch })
    })
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] }
}
