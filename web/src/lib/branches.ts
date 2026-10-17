// The team's memory branches as the visitor sees them: one per agent plus the shared team memory (main).
// Colours are shared by the history view, chat tabs and merge buttons so "amber = Scheduler" everywhere.

import { useQueries, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { ApiError } from './apiError'

export type Commit = components['schemas']['Commit']

export const BRANCHES = [
  { id: 'main', label: 'Team memory', color: '#34d399' },
  { id: 'planner', label: 'Planner', color: '#38bdf8' },
  { id: 'scheduler', label: 'Scheduler', color: '#fbbf24' },
  { id: 'notes', label: 'Notes', color: '#c084fc' },
] as const

export type BranchId = (typeof BRANCHES)[number]['id']
export const AGENT_BRANCHES = BRANCHES.filter((b) => b.id !== 'main')
export const branchInfo = (id: string) => BRANCHES.find((b) => b.id === id) ?? BRANCHES[0]

async function fetchLog(tenant: string, name: string): Promise<Commit[]> {
  const { data, error } = await api.GET('/api/{tenant}/branches/{name}/log', {
    params: { path: { tenant, name }, query: { limit: 200 } },
  })
  if (error) throw new ApiError(error)
  return data
}

/** Every branch's history, polled like the graph. A branch nobody has written to yet comes back empty
 *  (Notes, until its first chat turn). Keyed ['log', tenant, branch] so a chat turn or merge can refresh it. */
export function useBranchLogs(tenant: string) {
  return useQueries({
    queries: BRANCHES.map((b) => ({
      queryKey: ['log', tenant, b.id],
      queryFn: () => fetchLog(tenant, b.id),
      refetchInterval: 5000,
    })),
    combine: (results) => ({
      logs: Object.fromEntries(BRANCHES.map((b, i) => [b.id, results[i].data])) as Record<
        BranchId,
        Commit[] | undefined
      >,
      error: results.find((r) => r.error)?.error ?? null,
      isPending: results.some((r) => r.isPending),
    }),
  })
}

/** Refresh every view that reads memory after a write (chat turn, merge, re-derive). */
export function useMemoryChanged(tenant: string) {
  const client = useQueryClient()
  return () =>
    Promise.all(
      ['log', 'graph', 'scorecard'].map((k) => client.invalidateQueries({ queryKey: [k, tenant] })),
    )
}
