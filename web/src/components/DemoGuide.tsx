// Owner: Person D — see docs/team/person-d-ui-deploy.md
// "Try the demo": the 3-step judge flow. A step is ticked from real memory, not from clicks:
//   1. Planner's branch has a chat commit of its own (not the seed)
//   2. team memory's history contains Scheduler's work
//   3. team memory's history contains Planner's chat commit
// Logs come from the same cached queries as the history view (['log', tenant, branch]).

import { useBranchLogs, type Commit } from '../lib/branches'

export type ChatPrompt = { agent: 'planner'; text: string }

const MONDAY = 'The launch moved to Monday.'
const plannerTurn = (log: Commit[] | undefined) => log?.find((c) => c.agent_id === 'planner' && c.kind === 'commit')

export function DemoGuide({ tenant, onPrompt }: { tenant: string; onPrompt: (p: ChatPrompt) => void }) {
  const { logs } = useBranchLogs(tenant)
  const turn = plannerTurn(logs.planner)
  const steps = [
    {
      done: !!turn,
      text: (
        <>
          Tell Planner{' '}
          <button
            type="button"
            onClick={() => onPrompt({ agent: 'planner', text: MONDAY })}
            className="underline decoration-dotted hover:text-white"
          >
            “{MONDAY}”
          </button>
        </>
      ),
    },
    {
      done: !!logs.main?.some((c) => c.agent_id === 'scheduler'),
      text: <>Click Merge Scheduler: its Friday bookings join team memory</>,
    },
    {
      done: !!turn && !!logs.main?.some((c) => c.id === turn.id),
      text: <>Click Merge Planner: see Planner and Scheduler disagree, pick a side</>,
    },
  ]

  return (
    <ol aria-label="Try the demo" className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-300">
      <li className="font-semibold text-neutral-100">Try the demo</li>
      {steps.map((s, i) => (
        <li key={i} className="flex items-center gap-1.5" data-done={s.done}>
          <span
            aria-label={s.done ? 'done' : `step ${i + 1}`}
            className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-xs ${
              s.done ? 'bg-emerald-600 text-white' : 'bg-neutral-700 text-neutral-200'
            }`}
          >
            {s.done ? '✓' : i + 1}
          </span>
          <span className={s.done ? 'text-neutral-500 line-through' : ''}>{s.text}</span>
        </li>
      ))}
    </ol>
  )
}
