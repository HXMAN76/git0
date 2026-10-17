// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Left column: one chat per agent. Each send is one agent turn on the server
// (POST /api/{tenant}/agents/{agent}/messages -> agents.step): the agent reads its own memory branch,
// makes one LLM call and commits what it learned. Plain JSON for now; token streaming is issue #10.
// The thread lives in this component only: memory is what the agent committed, not this list.

import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { ApiError } from '../lib/apiError'
import { AGENT_BRANCHES, useMemoryChanged } from '../lib/branches'
import type { ChatPrompt } from './DemoGuide'
import { ErrorBanner } from './ErrorBanner'

type AgentId = (typeof AGENT_BRANCHES)[number]['id']
type Reply = components['schemas']['AgentReply']
type Turn = { from: 'you'; text: string } | { from: 'agent'; reply: Reply }

const HINTS: Record<AgentId, string> = {
  planner: 'Owns dates, owners and budgets. Try: "The launch moved to Monday."',
  scheduler: 'Turns the plan into tasks. Try: "What is booked for the launch?"',
  notes: 'Keeps decisions and contacts. Try: "Who is the caterer contact?"',
}

const newSession = () => `chat_${crypto.randomUUID().slice(0, 8)}`

async function send(tenant: string, agent: AgentId, message: string, session_id: string): Promise<Reply> {
  const { data, error } = await api.POST('/api/{tenant}/agents/{agent_id}/messages', {
    params: { path: { tenant, agent_id: agent } },
    body: { message, session_id },
  })
  if (error) throw new ApiError(error)
  return data
}

type Props = {
  tenant: string
  /** A message to put in the box (the demo guide's step 1); a new object each click. The visitor still sends it. */
  prompt?: ChatPrompt | null
}

export function ChatPanel({ tenant, prompt = null }: Props) {
  const [agent, setAgent] = useState<AgentId>('planner')
  const [threads, setThreads] = useState<Record<AgentId, Turn[]>>({ planner: [], scheduler: [], notes: [] })
  // One session per agent tab, so the server groups this visitor's turns with that agent.
  const [sessions] = useState(() => ({ planner: newSession(), scheduler: newSession(), notes: newSession() }))
  const [draft, setDraft] = useState('')
  // Adjust state while rendering when a new prompt arrives (React's recommended alternative to an effect).
  const [seenPrompt, setSeenPrompt] = useState<ChatPrompt | null>(null)
  if (prompt !== seenPrompt) {
    setSeenPrompt(prompt)
    if (prompt) {
      setAgent(prompt.agent)
      setDraft(prompt.text)
    }
  }
  // After the guide fills the box, Enter should send it, not re-press the guide button.
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (prompt) input.current?.focus()
  }, [prompt])
  const memoryChanged = useMemoryChanged(tenant)
  const append = (a: AgentId, t: Turn) => setThreads((all) => ({ ...all, [a]: [...all[a], t] }))

  const turn = useMutation({
    mutationFn: (v: { agent: AgentId; text: string }) => send(tenant, v.agent, v.text, sessions[v.agent]),
    onSuccess: (reply, v) => {
      append(v.agent, { from: 'agent', reply })
      return memoryChanged()
    },
  })

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || turn.isPending) return
    append(agent, { from: 'you', text })
    setDraft('')
    turn.mutate({ agent, text })
  }

  const thread = threads[agent]
  const failed = turn.isError && turn.variables?.agent === agent

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="Agents" className="flex gap-1 border-b border-neutral-800 p-2">
        {AGENT_BRANCHES.map((b) => (
          <button
            key={b.id}
            type="button"
            role="tab"
            aria-selected={agent === b.id}
            onClick={() => setAgent(b.id)}
            className={`flex items-center gap-1.5 rounded px-3 py-1 text-sm ${
              agent === b.id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: b.color }} />
            {b.label}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3" aria-live="polite">
        {thread.length === 0 && <p className="text-sm text-neutral-500">{HINTS[agent]}</p>}
        {thread.map((t, i) =>
          t.from === 'you' ? (
            <p key={i} className="ml-6 self-end rounded bg-neutral-800 px-3 py-2 text-sm text-white">
              {t.text}
            </p>
          ) : (
            <div key={i} className="mr-6 rounded border border-neutral-800 px-3 py-2 text-sm text-neutral-200">
              <p className="whitespace-pre-wrap">{t.reply.text}</p>
              <p className="mt-1 text-xs text-neutral-500">
                Saved to {t.reply.agent_id}'s memory
                {t.reply.cited_fact_ids?.length ? ` · used ${t.reply.cited_fact_ids.length} facts` : ''}
              </p>
            </div>
          ),
        )}
        {turn.isPending && turn.variables?.agent === agent && (
          <p className="text-sm text-neutral-500">Thinking…</p>
        )}
        {failed && <ErrorBanner>The agent could not answer: {turn.error.message}</ErrorBanner>}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-neutral-800 p-2">
        <label htmlFor="chat-input" className="sr-only">
          Message {agent}
        </label>
        <input
          id="chat-input"
          ref={input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Message ${AGENT_BRANCHES.find((b) => b.id === agent)!.label}…`}
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-white placeholder:text-neutral-500"
        />
        <button
          type="submit"
          disabled={turn.isPending || !draft.trim()}
          className="rounded bg-sky-700 px-3 py-1 text-sm text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}
