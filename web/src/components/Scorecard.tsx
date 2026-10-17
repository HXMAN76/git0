// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Polls /scorecard every 3s and shows live Track 02 counters.

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

const ITEMS = [
  { key: 'facts_on_main', label: 'Facts on main', track: 'Semantic memory' },
  { key: 'episodes', label: 'Episodes stored', track: 'Episodic memory' },
  { key: 'procedures', label: 'Procedures', track: 'Procedural memory' },
  { key: 'sessions_resumed', label: 'Sessions resumed', track: 'Persistent history' },
  { key: 'handoffs', label: 'Handoffs done', track: 'Shared state' },
  { key: 'commits_total', label: 'Total commits', track: 'Concurrency proof' },
  { key: 'tenants', label: 'Tenants live', track: 'Tenant isolation' },
] as const

export function Scorecard({ tenant }: { tenant: string }) {
  const { data, isError, error } = useQuery({
    queryKey: ['scorecard', tenant],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/{tenant}/scorecard', {
        params: { path: { tenant } },
      })
      if (error) throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error))
      return data
    },
    refetchInterval: 3000,
  })

  return (
    <div className="flex h-full flex-col gap-0 overflow-y-auto">
      <h2 className="sticky top-0 bg-neutral-950 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-400 border-b border-neutral-800">
        Track 02 Scorecard
      </h2>

      {isError && (
        <p role="alert" className="m-3 rounded border border-red-800 bg-red-950 p-2 text-xs text-red-300">
          {(error as Error).message}
        </p>
      )}

      <div className="flex flex-col divide-y divide-neutral-800">
        {ITEMS.map(({ key, label, track }) => {
          const val = data ? (data as Record<string, number>)[key] : null
          return (
            <div key={key} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm text-neutral-200">{label}</p>
                <p className="text-xs text-neutral-500">{track}</p>
              </div>
              <span className="text-lg font-bold tabular-nums text-white">
                {val == null ? <span className="text-neutral-600 text-sm">—</span> : val}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
