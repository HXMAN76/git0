// Owner: Person D — see docs/team/person-d-ui-deploy.md
// One disagreement found while bringing an agent's work into team memory (a Conflict from
// /merge/preview): the value before, the team's value, the agent's value, what was built on each, a past
// decision if there is one, and the Arbiter's plain-words explanation. The human picks; the LLM only explains.

import type { components } from '../api/schema'
import { ErrorBanner } from './ErrorBanner'

export type Conflict = components['schemas']['Conflict']
type Fact = components['schemas']['Fact']

const DELETE = '__delete__' // core/merge.py: drop both sides

const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const topic = (key: string) => key.replace('|', ' ').replaceAll('_', ' ')
const choiceOf = (f: Fact | null | undefined) => f?.id ?? DELETE

/** "Planner and Scheduler disagree": the agent being merged vs whoever wrote or built on the team value. */
function headline(c: Conflict, source: string): string {
  const others = [c.ours?.agent_id, ...(c.dependents_ours ?? []).map((d) => d.agent_id)]
    .filter((a): a is string => !!a && a !== source)
    .filter((a, i, all) => all.indexOf(a) === i)
  return `${title(source)} and ${others.length ? others.map(title).join(' and ') : 'the team'} disagree`
}

type Props = {
  conflict: Conflict
  source: string
  explanation: { text?: string; error?: string; pending: boolean }
  choice: string | undefined
  onChoose: (factId: string) => void
}

export function ConflictCard({ conflict: c, source, explanation, choice, onChoose }: Props) {
  const sides = [
    { label: 'Team memory', fact: c.ours, deps: c.dependents_ours ?? [], side: 'target' },
    { label: title(source), fact: c.theirs, deps: c.dependents_theirs ?? [], side: 'source' },
  ]
  const precedentSide = sides.find((s) => s.side === c.precedent_choice)

  return (
    <section className="rounded border border-amber-700 bg-neutral-900 p-3 text-sm" aria-label={`Disagreement on ${topic(c.key)}`}>
      <h3 className="font-semibold text-amber-300">{headline(c, source)}</h3>
      <p className="text-neutral-300">
        About the <b>{topic(c.key)}</b>
        {c.base && <> (was "{c.base.o}")</>}.
        {c.reason === 'dependency' && (
          <> Work was built on the old value, so changing it leaves that work stale.</>
        )}
      </p>

      <div className="mt-2 grid grid-cols-2 gap-2">
        {sides.map((s) => {
          const id = choiceOf(s.fact)
          return (
            <button
              key={s.side}
              type="button"
              aria-pressed={choice === id}
              onClick={() => onChoose(id)}
              className={`rounded border p-2 text-left ${
                choice === id ? 'border-emerald-500 bg-emerald-950' : 'border-neutral-700 hover:border-neutral-500'
              }`}
            >
              <span className="block text-xs text-neutral-400">{s.label} says</span>
              <span className="block font-medium text-white">{s.fact ? `"${s.fact.o}"` : 'remove it'}</span>
              {s.fact?.agent_id && <span className="block text-xs text-neutral-500">by {s.fact.agent_id}</span>}
              {s.deps.length > 0 && (
                <span className="mt-1 block text-xs text-neutral-400">
                  {s.deps.length} built on it: {s.deps.map((d) => `${topic(d.key)} "${d.o}"`).join(', ')}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {c.precedent_count > 0 && (
        <p className="mt-2 inline-block rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
          Settled {c.precedent_count}× before{precedentSide ? ` by siding with ${precedentSide.label}` : ''}
        </p>
      )}

      <div className="mt-2 text-neutral-300">
        <span className="text-xs uppercase tracking-wide text-neutral-500">Arbiter</span>
        {explanation.pending && <p className="text-neutral-500">Explaining…</p>}
        {explanation.error && <ErrorBanner>The Arbiter could not explain: {explanation.error}</ErrorBanner>}
        {explanation.text && <p>{explanation.text}</p>}
      </div>
    </section>
  )
}
