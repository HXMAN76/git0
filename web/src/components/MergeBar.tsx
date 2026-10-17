// Owner: Person D — see docs/team/person-d-ui-deploy.md
// "Merge into team memory", one button per agent. The flow is the API's, step by step:
//   1. POST /merge/preview: what would change, and any disagreements (deterministic Cypher rules)
//   2. disagreements -> ConflictCards; POST /merge/explain fetches the Arbiter's words (the LLM only explains)
//   3. the human picks a side; POST /merge/resolve with the previewed heads (409 if a branch moved since)
//   4. POST /arbiter/rederive for the work the merge made stale (MergeApplied.invalidated)
// No changes and no disagreements = nothing to do; no disagreements = steps 3-4 run right away.

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { ApiError } from '../lib/apiError'
import { AGENT_BRANCHES, branchInfo, useBranchLogs, useMemoryChanged } from '../lib/branches'
import { ConflictCard } from './ConflictCard'
import { ErrorBanner } from './ErrorBanner'

type Plan = components['schemas']['MergeResult']
type Applied = components['schemas']['MergeApplied']
type Rederived = components['schemas']['RederiveResult']
type Done = { plan: Plan; applied: Applied; rederived: Rederived | null; rederiveError: string | null }

const TARGET = 'main'

async function preview(tenant: string, source: string): Promise<Plan> {
  const { data, error } = await api.POST('/api/{tenant}/merge/preview', {
    params: { path: { tenant } },
    body: { source, target: TARGET },
  })
  if (error) throw new ApiError(error)
  return data
}

async function explain(tenant: string, source: string) {
  const { data, error } = await api.POST('/api/{tenant}/merge/explain', {
    params: { path: { tenant } },
    body: { source, target: TARGET },
  })
  if (error) throw new ApiError(error)
  return Object.fromEntries(data.map((e) => [e.key, e.text]))
}

async function apply(tenant: string, plan: Plan, choices: Record<string, string>): Promise<Done> {
  const { data: applied, error } = await api.POST('/api/{tenant}/merge/resolve', {
    params: { path: { tenant } },
    body: {
      source: plan.source,
      target: TARGET,
      choices,
      agent_id: 'human', // the person clicking decided; recorded as the merge author and precedent
      target_head: plan.target_head,
      source_head: plan.source_head,
    },
  })
  if (error) throw new ApiError(error)
  if (applied.invalidated.length === 0) return { plan, applied, rederived: null, rederiveError: null }
  // The merge is already committed here, so a re-derive failure is reported next to it, not instead of it.
  const r = await api.POST('/api/{tenant}/arbiter/rederive', {
    params: { path: { tenant } },
    body: { target: TARGET, fact_ids: applied.invalidated.map((f) => f.id), session_id: 'arbiter' },
  })
  return {
    plan,
    applied,
    rederived: r.data ?? null,
    rederiveError: r.error ? new ApiError(r.error).message : null,
  }
}

export function MergeBar({ tenant }: { tenant: string }) {
  const { logs } = useBranchLogs(tenant)
  const memoryChanged = useMemoryChanged(tenant)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)

  const resolve = useMutation({
    mutationFn: (v: { plan: Plan; choices: Record<string, string> }) => apply(tenant, v.plan, v.choices),
    onSuccess: () => {
      setPlan(null)
      return memoryChanged()
    },
  })

  const start = useMutation({
    mutationFn: (source: string) => preview(tenant, source),
    onMutate: () => {
      setPlan(null)
      setNotice(null)
      setChoices({})
      resolve.reset()
    },
    onSuccess: (p) => {
      const label = branchInfo(p.source).label
      if (p.conflicts.length > 0) setPlan(p)
      else if (p.auto_merged.length === 0 && p.removals.length === 0)
        setNotice(`Nothing new from ${label}: team memory already has all of it.`)
      else resolve.mutate({ plan: p, choices: {} })
    },
  })

  const conflicts = plan?.conflicts ?? []
  const why = useQuery({
    queryKey: ['explain', tenant, plan?.source, plan?.source_head, plan?.target_head],
    queryFn: () => explain(tenant, plan!.source),
    enabled: conflicts.length > 0,
    staleTime: Infinity,
  })

  const busy = start.isPending || resolve.isPending
  // Notes appears once it has memory of its own (its first chat turn creates the branch).
  const agents = AGENT_BRANCHES.filter((b) => b.id !== 'notes' || (logs.notes?.length ?? 0) > 0)
  const done = resolve.data

  return (
    <div className="flex flex-col gap-2 border-b border-neutral-800 p-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-neutral-400">Bring an agent's work into team memory:</span>
        {agents.map((b) => (
          <button
            key={b.id}
            type="button"
            disabled={busy}
            onClick={() => start.mutate(b.id)}
            className="rounded border px-3 py-1 text-neutral-100 hover:bg-neutral-800 disabled:opacity-40"
            style={{ borderColor: b.color }}
          >
            Merge {b.label}
          </button>
        ))}
        {busy && <span className="text-neutral-500">Working…</span>}
      </div>

      {start.isError && <ErrorBanner>Could not check the merge: {start.error.message}</ErrorBanner>}
      {resolve.isError && <ErrorBanner>Could not merge: {resolve.error.message}</ErrorBanner>}
      {notice && <p className="text-sm text-neutral-400">{notice}</p>}

      {done && <Summary done={done} />}

      {plan && conflicts.length > 0 && (
        <div className="flex max-h-[55vh] flex-col gap-2 overflow-y-auto">
          <p className="text-sm text-neutral-300">
            {branchInfo(plan.source).label} brings {plan.auto_merged.length} change(s) that fit and{' '}
            {conflicts.length} that need your call:
          </p>
          {conflicts.map((c) => (
            <ConflictCard
              key={c.key}
              conflict={c}
              source={plan.source}
              explanation={{ pending: why.isPending, text: why.data?.[c.key], error: why.error?.message }}
              choice={choices[c.key]}
              onChoose={(id) => setChoices((all) => ({ ...all, [c.key]: id }))}
            />
          ))}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy || conflicts.some((c) => !choices[c.key])}
              onClick={() => resolve.mutate({ plan, choices })}
              className="rounded bg-emerald-700 px-3 py-1 text-sm text-white disabled:opacity-40"
            >
              Merge with my choices
            </button>
            <button
              type="button"
              onClick={() => setPlan(null)}
              className="rounded px-3 py-1 text-sm text-neutral-400 hover:text-neutral-200"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Summary({ done }: { done: Done }) {
  const { plan, applied, rederived, rederiveError } = done
  const label = branchInfo(plan.source).label
  return (
    <div role="status" className="rounded border border-emerald-800 bg-emerald-950 p-2 text-sm text-emerald-100">
      <p>
        {label}'s work is now team memory: {plan.auto_merged.length + plan.conflicts.length} change(s) merged,{' '}
        {plan.unchanged} unchanged.
      </p>
      {applied.invalidated.length > 0 && (
        <p>
          {applied.invalidated.length} task(s) were built on a value that changed
          {rederived &&
            `; the Arbiter re-derived them with ${rederived.owners.join(', ') || 'no owner'} (${rederived.tokens} tokens)`}
          .
        </p>
      )}
      {rederived?.replies.map((r, i) => (
        <p key={i} className="text-emerald-200/80">
          {r.agent_id}: {r.text}
        </p>
      ))}
      {rederiveError && <ErrorBanner>Merged, but re-deriving the stale tasks failed: {rederiveError}</ErrorBanner>}
    </div>
  )
}
