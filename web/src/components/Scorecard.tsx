// Owner: Person D — see docs/team/person-d-ui.md
// PLACEHOLDER: right column. TODO: live counters fed by SSE 'score' events.

export function Scorecard() {
  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">Scorecard</h2>
      <p className="text-sm text-neutral-500">Placeholder: live scores.</p>
    </div>
  )
}
