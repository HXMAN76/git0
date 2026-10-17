// Fetches provenance for a fact and pushes all related node IDs to the MemoryCanvas highlight.
// /why returns rows with fact_id, commit_id, agent_id, episode_id — all are graph node IDs.

import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface Props {
  tenant: string
  factId: string | null
  onHighlight: (ids: string[]) => void
}

export function WhyPath({ tenant, factId, onHighlight }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!factId) return
    setLoading(true)
    setError(null)
    api
      .GET('/api/{tenant}/facts/{fact_id}/why', { params: { path: { tenant, fact_id: factId } } })
      .then(({ data, error }) => {
        if (error) throw new Error(JSON.stringify(error))
        const rows = (data ?? []) as Record<string, unknown>[]
        // Collect every node ID present in the provenance rows
        const ids = new Set<string>()
        for (const row of rows) {
          if (row.fact_id) ids.add(String(row.fact_id))
          if (row.commit_id) ids.add(String(row.commit_id))
          if (row.agent_id) ids.add(String(row.agent_id))
          if (row.episode_id) ids.add(String(row.episode_id))
        }
        onHighlight([...ids])
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [tenant, factId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!factId) return null
  if (loading) return <p className="text-xs text-neutral-400 px-3 py-1 animate-pulse">Loading why-path…</p>
  if (error) return <p className="text-xs text-red-400 px-3 py-1">{error}</p>
  return null
}
