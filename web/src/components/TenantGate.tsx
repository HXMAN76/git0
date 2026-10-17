// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Seeds the visitor's team room (POST /api/{tenant}/seed) before any view reads it. The seed is idempotent
// on the server (per-tenant lock, skip-if-done), so repeat visits only cost a few reads.

import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

async function seedRoom(tenant: string) {
  const { data, error } = await api.POST('/api/{tenant}/seed', { params: { path: { tenant } } })
  // Fail loudly: a room that could not be seeded must not look like an empty one.
  if (error) throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error))
  return data
}

export function TenantGate({ tenant, children }: { tenant: string; children: (tenant: string) => ReactNode }) {
  const seed = useQuery({ queryKey: ['seed', tenant], queryFn: () => seedRoom(tenant), staleTime: Infinity })

  if (seed.isError)
    return (
      <p role="alert" className="m-4 rounded border border-red-800 bg-red-950 p-3 text-sm text-red-200">
        Could not set up your team room: {seed.error.message}
      </p>
    )
  if (seed.isPending) return <p className="m-4 text-sm text-neutral-400">Setting up your team room…</p>
  return <>{children(tenant)}</>
}
