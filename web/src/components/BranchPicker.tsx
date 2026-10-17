// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Which memory the graph shows. An agent's branch is only offered once it exists (has history): Notes has
// none until its first chat turn, and picking it before then only produced a "no such branch" error.

import { BRANCHES, useBranchLogs } from '../lib/branches'

type Props = { tenant: string; value: string; onChange: (branch: string) => void }

export function BranchPicker({ tenant, value, onChange }: Props) {
  const { logs } = useBranchLogs(tenant)
  const options = BRANCHES.filter((b) => b.id === 'main' || b.id === value || (logs[b.id]?.length ?? 0) > 0)

  return (
    <label className="ml-auto flex items-center gap-2 text-xs text-neutral-400">
      Showing
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-neutral-100"
      >
        {options.map((b) => (
          <option key={b.id} value={b.id}>
            {b.id === 'main' ? b.label : `${b.label}${b.label.endsWith('s') ? "'" : "'s"} own memory`}
          </option>
        ))}
      </select>
    </label>
  )
}
