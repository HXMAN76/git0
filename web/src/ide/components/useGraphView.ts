// Fetches the relay graph and refetches on every graph_changed (the caller passes the version).
// Both the GRAPH tab and the full-screen overlay use this, so each one stays live on its own.

import { useEffect, useState } from 'react'
import type { GraphView } from '../types'

export function useGraphView(version: number, live: boolean, fetchGraph: () => Promise<GraphView>) {
  const [view, setView] = useState<GraphView | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!live) return
    let cancelled = false
    fetchGraph().then(
      (v) => {
        if (!cancelled) {
          setView(v)
          setError(null)
        }
      },
      (err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      },
    )
    return () => {
      cancelled = true
    }
    // Only a new graph_changed (version bump) refetches. fetchGraph is bound to the session.
  }, [version, live, fetchGraph])

  return { view, error }
}
