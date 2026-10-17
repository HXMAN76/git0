// Owner: Person D — see docs/team/person-d-ui-deploy.md
// Three agent tabs (Planner / Scheduler / Notes). Each streams tokens via SSE, then emits
// cited fact IDs up to App so WhyPath and MemoryCanvas can highlight them.

import { useRef, useState } from 'react'

const AGENTS = [
  { id: 'planner', label: 'Planner', color: '#a78bfa' },
  { id: 'scheduler', label: 'Scheduler', color: '#60a5fa' },
  { id: 'notes', label: 'Notes', color: '#34d399' },
] as const

type AgentId = (typeof AGENTS)[number]['id']

interface Message {
  role: 'user' | 'agent'
  text: string
  cited_fact_ids?: string[]
  error?: boolean
  streaming?: boolean
}

interface Props {
  tenant: string
  onFactClick?: (factId: string) => void
  onAgentChange?: (agentId: string) => void
}

function useAgentChat(tenant: string, agentId: AgentId) {
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const sessionId = useRef(crypto.randomUUID())
  const stopRef = useRef<(() => void) | null>(null)

  function send(text: string) {
    if (busy || !text.trim()) return
    setBusy(true)

    setMessages((prev) => [...prev, { role: 'user', text }])
    // placeholder streaming message
    setMessages((prev) => [...prev, { role: 'agent', text: '', streaming: true }])

    const url = `/api/${tenant}/agents/${agentId}/messages`
    // SSE via POST: EventSource only supports GET, so we open the connection via fetch + ReadableStream.
    let cancelled = false
    let agentText = ''
    let citedIds: string[] = []

    const ctrl = new AbortController()
    stopRef.current = () => { cancelled = true; ctrl.abort() }

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: sessionId.current }),
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done || cancelled) break
          buf += dec.decode(value, { stream: true })

          // Parse SSE lines from buffer
          const parts = buf.split('\n\n')
          buf = parts.pop() ?? ''

          for (const block of parts) {
            let eventName = 'message'
            let dataLine = ''
            for (const line of block.split('\n')) {
              if (line.startsWith('event: ')) eventName = line.slice(7).trim()
              if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
            }
            if (!dataLine) continue
            try {
              const payload = JSON.parse(dataLine)
              if (eventName === 'token') {
                agentText = payload.text ?? agentText
                setMessages((prev) => {
                  const next = [...prev]
                  next[next.length - 1] = { role: 'agent', text: agentText, streaming: true }
                  return next
                })
              } else if (eventName === 'commit') {
                citedIds = payload.cited_fact_ids ?? []
                setMessages((prev) => {
                  const next = [...prev]
                  next[next.length - 1] = {
                    role: 'agent',
                    text: agentText,
                    cited_fact_ids: citedIds,
                    streaming: false,
                  }
                  return next
                })
              } else if (eventName === 'error') {
                setMessages((prev) => {
                  const next = [...prev]
                  next[next.length - 1] = {
                    role: 'agent',
                    text: payload.message ?? 'Unknown error',
                    error: true,
                    streaming: false,
                  }
                  return next
                })
              }
            } catch {
              // malformed SSE block — skip
            }
          }
        }
      })
      .catch((err) => {
        if (cancelled) return
        setMessages((prev) => {
          const next = [...prev]
          next[next.length - 1] = { role: 'agent', text: String(err), error: true, streaming: false }
          return next
        })
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
        stopRef.current = null
      })
  }

  return { messages, busy, send }
}

function AgentChat({
  tenant,
  agentId,
  color,
  onFactClick,
}: {
  tenant: string
  agentId: AgentId
  color: string
  onFactClick?: (id: string) => void
}) {
  const { messages, busy, send } = useAgentChat(tenant, agentId)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  function submit() {
    const t = input.trim()
    if (!t) return
    setInput('')
    send(t)
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }

  return (
    <div className="flex h-full flex-col">
      {/* message list */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3 space-y-2">
        {messages.length === 0 && (
          <p className="text-xs text-neutral-500 text-center mt-8">
            Send a message to start.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex flex-col gap-1 ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
            <div
              className={`max-w-[85%] rounded px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                m.role === 'user'
                  ? 'bg-neutral-700 text-neutral-100'
                  : m.error
                  ? 'bg-red-950 border border-red-700 text-red-200'
                  : 'bg-neutral-800 text-neutral-100'
              }`}
            >
              {m.text || (m.streaming ? <span className="animate-pulse text-neutral-400">…</span> : '')}
            </div>
            {/* cited fact links */}
            {m.cited_fact_ids && m.cited_fact_ids.length > 0 && (
              <div className="flex flex-wrap gap-1 px-1">
                {m.cited_fact_ids.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onFactClick?.(id)}
                    className="rounded bg-neutral-700 px-2 py-0.5 text-xs hover:bg-neutral-600"
                    style={{ color }}
                    title={`Why: ${id}`}
                  >
                    why?
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div className="border-t border-neutral-800 p-2 flex gap-2">
        <input
          className="flex-1 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 placeholder-neutral-500 outline-none focus:ring-1 focus:ring-neutral-600"
          placeholder={busy ? 'Thinking…' : 'Message…'}
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), submit())}
        />
        <button
          type="button"
          onClick={submit}
          disabled={busy || !input.trim()}
          className="rounded bg-neutral-700 px-3 py-1.5 text-sm text-neutral-100 disabled:opacity-40 hover:bg-neutral-600"
        >
          Send
        </button>
      </div>
    </div>
  )
}

export function ChatPanel({ tenant, onFactClick, onAgentChange }: Props) {
  const [activeAgent, setActiveAgent] = useState<AgentId>('planner')
  return (
    <div className="flex h-full flex-col">
      {/* agent tabs */}
      <div className="flex border-b border-neutral-800">
        {AGENTS.map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() => { setActiveAgent(a.id); onAgentChange?.(a.id) }}
            className={`flex-1 py-2 text-xs font-medium transition-colors ${
              activeAgent === a.id
                ? 'border-b-2 text-white'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
            style={activeAgent === a.id ? { borderColor: a.color } : {}}
          >
            {a.label}
          </button>
        ))}
      </div>

      {/* keep all agents mounted so history is preserved when switching tabs */}
      {AGENTS.map((a) => (
        <div key={a.id} className={`min-h-0 flex-1 ${a.id === activeAgent ? 'flex flex-col' : 'hidden'}`}>
          <AgentChat tenant={tenant} agentId={a.id} color={a.color} onFactClick={onFactClick} />
        </div>
      ))}
    </div>
  )
}
