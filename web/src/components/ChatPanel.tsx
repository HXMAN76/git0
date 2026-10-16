// Owner: Person D — see docs/team/person-d-ui.md
// PLACEHOLDER: left column. TODO: three agent threads, streamed tokens via SSE (api/sse.ts).

export function ChatPanel() {
  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">Chat</h2>
      <p className="text-sm text-neutral-500">Placeholder: chat with 3 agents.</p>
    </div>
  )
}
