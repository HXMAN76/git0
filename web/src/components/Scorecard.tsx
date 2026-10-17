// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Right column: the live Track 02 numbers for this room, straight from GET /api/{tenant}/scorecard
// (one read query, scorecard.cypher). `query_ms` is FalkorDB's own time for that query.

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { ApiError } from '../lib/apiError'
import { ErrorBanner } from './ErrorBanner'

type Card = components['schemas']['Scorecard']

// What each number means, in the visitor's words. Order = the story: memory, then coordination.
const ITEMS: { key: Exclude<keyof Card, 'query_ms'>; label: string; hint: string }[] = [
  { key: 'facts_on_main', label: 'Facts in team memory', hint: 'semantic memory everyone shares' },
  { key: 'episodes', label: 'Chat turns remembered', hint: 'episodic memory behind each fact' },
  { key: 'procedures_on_main', label: 'Learned procedures', hint: 'procedural memory on the team plan' },
  { key: 'sessions', label: 'Sessions', hint: 'conversations agents can resume' },
  { key: 'agents', label: 'Agents', hint: 'each with its own private memory' },
  { key: 'commits', label: 'Memory updates', hint: 'every write is versioned' },
  { key: 'merges', label: 'Merges into team memory', hint: 'agents agreeing on one plan' },
  { key: 'conflicts_resolved', label: 'Disagreements settled', hint: 'by a human, explained by the Arbiter' },
  { key: 'precedents_reused', label: 'Past decisions reused', hint: 'settled the same way as before' },
  { key: 'reverts', label: 'Undos', hint: 'with their dependents rolled back' },
  { key: 'handoffs', label: 'Handoffs', hint: 'an agent replaced, memory inherited' },
  { key: 'tenants', label: 'Live team rooms', hint: 'isolated graphs on this server' },
]

async function fetchScorecard(tenant: string): Promise<Card> {
  const { data, error } = await api.GET('/api/{tenant}/scorecard', { params: { path: { tenant } } })
  if (error) throw new ApiError(error)
  return data
}

export function Scorecard({ tenant }: { tenant: string }) {
  const card = useQuery({
    queryKey: ['scorecard', tenant],
    queryFn: () => fetchScorecard(tenant),
    refetchInterval: 5000,
  })

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">Scorecard</h2>
      {card.isError && <ErrorBanner>Could not load the scorecard: {card.error.message}</ErrorBanner>}
      {card.isPending && <p className="text-sm text-neutral-500">Loading live numbers…</p>}
      {card.data && (
        <>
          <dl className="flex flex-col gap-2">
            {ITEMS.map((item) => (
              <div key={item.key} className="flex items-baseline justify-between gap-2" title={item.hint}>
                <dt className="text-sm text-neutral-300">
                  {item.label}
                  <span className="block text-xs text-neutral-500">{item.hint}</span>
                </dt>
                <dd className="font-mono text-lg tabular-nums text-white" data-testid={`score-${item.key}`}>
                  {card.data[item.key]}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-auto text-xs text-neutral-500" data-testid="score-query-ms">
            One FalkorDB query: {card.data.query_ms.toFixed(1)} ms
          </p>
        </>
      )}
    </div>
  )
}
