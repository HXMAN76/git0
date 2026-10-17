// Merge-to-main UI. A "Merge to main" button POSTs /merge/preview; if conflicts exist,
// renders each conflict with base/A/B values and a radio to pick a side, then POSTs /merge/resolve.

import { useState } from 'react'
import { api } from '../api/client'
import type { components } from '../api/schema'

type Conflict = components['schemas']['Conflict']
type MergeResult = components['schemas']['MergeResult']
type MergeApplied = components['schemas']['MergeApplied']

interface Props {
  tenant: string
  sourceBranch: string // the active agent's branch
}

function factValue(f: Conflict['base']): string {
  if (!f) return '—'
  // Fact has s/p/o triple; display as "subject · predicate: object"
  return `${f.s} · ${f.p}: ${f.o}`
}

export function ConflictCard({ tenant, sourceBranch }: Props) {
  const [state, setState] = useState<'idle' | 'loading' | 'conflicts' | 'done' | 'error'>('idle')
  const [result, setResult] = useState<MergeResult | null>(null)
  const [autoMerged, setAutoMerged] = useState<number>(0)
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [applied, setApplied] = useState<MergeApplied | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  async function preview() {
    setState('loading')
    setErrorMsg('')
    try {
      const { data, error } = await api.POST('/api/{tenant}/merge/preview', {
        params: { path: { tenant } },
        body: { source: sourceBranch, target: 'main' },
      })
      if (error) throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error))
      setResult(data!)
      setAutoMerged(data!.auto_merged?.length ?? 0)
      if ((data!.conflicts ?? []).length === 0) {
        // No human conflicts — call resolve immediately with empty choices to finalize the merge commit
        const { data: applied, error: resolveErr } = await api.POST('/api/{tenant}/merge/resolve', {
          params: { path: { tenant } },
          body: {
            source: sourceBranch,
            target: 'main',
            source_head: data!.source_head,
            target_head: data!.target_head,
            choices: {},
            agent_id: 'arbiter',
          },
        })
        if (resolveErr) throw new Error(typeof resolveErr.detail === 'string' ? resolveErr.detail : JSON.stringify(resolveErr))
        setState('done')
        setApplied(applied!)
      } else {
        // Pre-fill choices with any precedent picks
        const pre: Record<string, string> = {}
        for (const c of data!.conflicts) {
          if (c.precedent_choice) pre[c.key] = c.precedent_choice
        }
        setChoices(pre)
        setState('conflicts')
      }
    } catch (e) {
      setErrorMsg(String(e))
      setState('error')
    }
  }

  async function resolve() {
    if (!result) return
    setState('loading')
    try {
      const { data, error } = await api.POST('/api/{tenant}/merge/resolve', {
        params: { path: { tenant } },
        body: {
          source: sourceBranch,
          target: 'main',
          source_head: result.source_head,
          target_head: result.target_head,
          choices,
          agent_id: 'arbiter',
        },
      })
      if (error) throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error))
      setApplied(data!)
      setState('done')
    } catch (e) {
      setErrorMsg(String(e))
      setState('error')
    }
  }

  if (state === 'idle' || state === 'error') {
    return (
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={preview}
          className="rounded bg-violet-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-40"
        >
          Merge {sourceBranch} → main
        </button>
        {state === 'error' && (
          <p className="text-xs text-red-400">{errorMsg}</p>
        )}
      </div>
    )
  }

  if (state === 'loading') {
    return <p className="text-xs text-neutral-400 animate-pulse">Working…</p>
  }

  if (state === 'done' && applied) {
    return (
      <div className="rounded border border-green-800 bg-green-950 p-3 text-xs text-green-300 flex flex-col gap-1">
        <p className="font-semibold">Merged to main ✓</p>
        <p>commit: {applied.merge_commit.slice(0, 12)}</p>
        {autoMerged > 0 && <p>{autoMerged} fact(s) auto-merged</p>}
        {applied.removed.length > 0 && <p>{applied.removed.length} fact(s) removed</p>}
        <button type="button" onClick={() => { setState('idle'); setResult(null); setApplied(null) }}
          className="mt-1 self-start rounded bg-green-800 px-2 py-0.5 hover:bg-green-700">
          Done
        </button>
      </div>
    )
  }

  // conflicts state
  const conflicts = result?.conflicts ?? []
  const allPicked = conflicts.every((c) => choices[c.key])

  return (
    <div className="flex flex-col gap-3 rounded border border-amber-700 bg-amber-950/30 p-3 text-xs">
      <p className="font-semibold text-amber-300">{conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''} — pick a side for each</p>

      {conflicts.map((c) => (
        <div key={c.key} className="flex flex-col gap-1 border-t border-amber-800/50 pt-2">
          <p className="font-mono text-amber-200 truncate">{c.key}</p>
          {c.base && (
            <p className="text-neutral-400">base: <span className="text-neutral-300">{factValue(c.base)}</span></p>
          )}

          {/* Ours (source branch) */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name={c.key}
              value={c.ours?.id ?? 'DELETE_OURS'}
              checked={choices[c.key] === (c.ours?.id ?? 'DELETE_OURS')}
              onChange={() => setChoices((prev) => ({ ...prev, [c.key]: c.ours?.id ?? 'DELETE_OURS' }))}
              className="mt-0.5"
            />
            <span>
              <span className="text-violet-400">{sourceBranch}</span>:{' '}
              <span className="text-neutral-200">{factValue(c.ours)}</span>
              {c.precedent_choice === c.ours?.id && (
                <span className="ml-1 rounded bg-violet-900 px-1 text-violet-300">precedent ×{c.precedent_count}</span>
              )}
              {(c.dependents_ours?.length ?? 0) > 0 && (
                <span className="ml-1 text-neutral-500">{c.dependents_ours.length} dependent(s)</span>
              )}
            </span>
          </label>

          {/* Theirs (target branch) */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name={c.key}
              value={c.theirs?.id ?? 'DELETE_THEIRS'}
              checked={choices[c.key] === (c.theirs?.id ?? 'DELETE_THEIRS')}
              onChange={() => setChoices((prev) => ({ ...prev, [c.key]: c.theirs?.id ?? 'DELETE_THEIRS' }))}
              className="mt-0.5"
            />
            <span>
              <span className="text-pink-400">main</span>:{' '}
              <span className="text-neutral-200">{factValue(c.theirs)}</span>
              {c.precedent_choice === c.theirs?.id && (
                <span className="ml-1 rounded bg-pink-900 px-1 text-pink-300">precedent ×{c.precedent_count}</span>
              )}
              {(c.dependents_theirs?.length ?? 0) > 0 && (
                <span className="ml-1 text-neutral-500">{c.dependents_theirs.length} dependent(s)</span>
              )}
            </span>
          </label>
        </div>
      ))}

      <button
        type="button"
        onClick={resolve}
        disabled={!allPicked}
        className="self-start rounded bg-violet-800 px-3 py-1 text-white hover:bg-violet-700 disabled:opacity-40"
      >
        Resolve & merge
      </button>
    </div>
  )
}
