// One agent's chat column: status pill, timeline (messages, tool chips, hook chips, peer notices,
// conflict card, ask_user card), preset buttons and the message input.

import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api'
import type { AgentState, ChatItem } from '../state'
import { AGENT_META, type AgentId, type AgentInfo, type AgentStatus, type ConflictInfo, type Preset } from '../types'

const STATUS: Record<AgentStatus, { label: string; cls: string }> = {
  idle: { label: 'idle', cls: 'bg-[#3c3c3c] text-[#cccccc]' },
  thinking: { label: 'thinking', cls: 'bg-[#264f78] text-[#dcefff]' },
  tool: { label: 'running tool', cls: 'bg-[#4b3a63] text-[#f0ddff]' },
  waiting_user: { label: 'waiting for you', cls: 'bg-[#7a5f00] text-[#fff1c2]' },
  error: { label: 'error', cls: 'bg-[#6e1f1f] text-[#ffd7d7]' },
}

const KIND_LABEL: Record<ConflictInfo['kind'], string> = {
  same_symbol: 'same symbol',
  dependency: 'dependency',
  reverse_dependency: 'reverse dependency',
  intent: 'intent',
}

export interface AgentPanelProps {
  agent: AgentId
  info: AgentInfo | null
  agentState: AgentState
  presets: Preset[]
  live: boolean
  onSend: (agent: AgentId, text: string) => Promise<void>
  onAnswer: (questionId: string, choice: string) => Promise<void>
}

export function AgentPanel({ agent, info, agentState, presets, live, onSend, onAnswer }: AgentPanelProps) {
  const meta = AGENT_META[agent]
  const status = STATUS[agentState.status]
  const scrollRef = useRef<HTMLDivElement>(null)
  const count = agentState.items.length

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [count])

  return (
    <section className="flex min-h-0 flex-1 flex-col border-b border-[#2b2b2b] bg-[#1e1e1e] text-[13px] text-[#cccccc] last:border-b-0" aria-label={`Agent ${agent} chat`}>
      <header className="flex shrink-0 items-center gap-2 border-b border-[#2b2b2b] bg-[#252526] px-3 py-1.5">
        <span className="flex size-5 items-center justify-center rounded-full font-mono text-[11px] font-bold text-[#1e1e1e]" style={{ background: meta.color }}>
          {agent}
        </span>
        <div className="min-w-0">
          <div className="truncate font-semibold">{info?.label ?? `${meta.owner}'s laptop`}</div>
          <div className="truncate font-mono text-[10px] text-[#858585]">{info?.model ?? 'model -'}</div>
        </div>
        <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] ${status.cls}`} role="status" aria-label={`Agent ${agent} status: ${status.label}`}>
          {status.label}
        </span>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2" aria-live="polite">
        {count === 0 && <p className="text-[12px] text-[#6a6a6a]">Send a task to Agent {agent}, or run the scenario.</p>}
        {agentState.items.map((item) => (
          <TimelineItem key={item.id} item={item} agent={agent} onAnswer={onAnswer} />
        ))}
      </div>

      <Composer agent={agent} presets={presets} live={live} onSend={onSend} />
    </section>
  )
}

function TimelineItem({ item, agent, onAnswer }: { item: ChatItem; agent: AgentId; onAnswer: (qid: string, choice: string) => Promise<void> }) {
  switch (item.kind) {
    case 'message':
      return item.role === 'user' ? (
        <div className="ml-6 rounded-md bg-[#264f78] px-2.5 py-1.5 leading-snug text-white">
          <div className="mb-0.5 text-[10px] uppercase tracking-wide text-[#b8d7f0]">you</div>
          <div className="whitespace-pre-wrap break-words">{item.text}</div>
        </div>
      ) : (
        <div className="mr-4 rounded-md bg-[#252526] px-2.5 py-1.5 leading-snug">
          <div className="mb-0.5 text-[10px] uppercase tracking-wide text-[#858585]">agent {agent}</div>
          <div className="whitespace-pre-wrap break-words">{item.text}</div>
        </div>
      )

    case 'tool': {
      const icon = item.status === 'running' ? '…' : item.status === 'ok' ? '✓' : '✕'
      const tone = item.status === 'fail' ? 'text-[#f48771]' : item.status === 'ok' ? 'text-[#89d185]' : 'text-[#4fc1ff]'
      return (
        <div className="flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-[#9d9d9d]" title={item.summary || undefined}>
          <span className={`w-3 shrink-0 text-center ${tone}`}>{icon}</span>
          <span className="shrink-0 rounded-sm bg-[#2d2d30] px-1.5 py-px text-[#dcdcaa]">{item.tool}</span>
          {item.path && <span className="truncate text-[#ce9178]">{item.path}</span>}
        </div>
      )
    }

    case 'hook': {
      const tone =
        item.decision === 'deny'
          ? 'border-[#f14c4c] text-[#f48771]'
          : item.decision === 'context'
            ? 'border-[#cca700] text-[#e5c07b]'
            : item.decision === 'recorded'
              ? 'border-[#4fc1ff] text-[#9cdcfe]'
              : 'border-[#3c7d4f] text-[#89d185]'
      return (
        <div className={`ml-4 rounded-sm border-l-2 bg-[#252526] px-2 py-1 font-mono text-[11px] ${tone}`}>
          <span>
            {item.phase} · {item.tool} → MCP {item.mcpTool} → <strong>{item.decision.toUpperCase()}</strong>
          </span>
          {item.detail && <span className="text-[#9d9d9d]"> ({item.detail})</span>}
          <span className="text-[#6a6a6a]"> {item.ms}ms</span>
        </div>
      )
    }

    case 'peer':
      return (
        <div role="note" className="rounded-sm border-l-2 border-[#cca700] bg-[#3a3300]/60 px-2.5 py-1.5 text-[12px] text-[#f5e6a8]">
          <strong>Heads-up from {item.from === 'A' ? "Alice" : "Bob"}:</strong> {item.message}
        </div>
      )

    case 'conflict':
      return (
        <div role="alert" className="rounded-md border border-[#f14c4c] bg-[#3b1d1d] px-3 py-2 text-[12px] text-[#ffd7d7]">
          <div className="mb-1 font-semibold text-[#f48771]">Conflict caught before the write</div>
          <ul className="space-y-1.5">
            {item.conflicts.map((c, i) => (
              <li key={`${c.kind}-${i}`}>
                <span className="mr-1.5 rounded-sm bg-[#f14c4c] px-1 py-px text-[10px] font-semibold uppercase text-white">{KIND_LABEL[c.kind]}</span>
                {c.message}
              </li>
            ))}
          </ul>
        </div>
      )

    case 'ask':
      return <AskCard item={item} onAnswer={onAnswer} />

    case 'error':
      return <div className="rounded-sm bg-[#5a1d1d] px-2 py-1 text-[12px] text-[#ffd7d7]">{item.message}</div>
  }
}

function AskCard({
  item,
  onAnswer,
}: {
  item: Extract<ChatItem, { kind: 'ask' }>
  onAnswer: (qid: string, choice: string) => Promise<void>
}) {
  const [chosen, setChosen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const locked = item.resolved !== null || chosen !== null
  const resolvedLabel = item.resolved ? (item.options.find((o) => o.id === item.resolved)?.label ?? item.resolved) : null

  const pick = async (choice: string) => {
    if (locked) return
    setChosen(choice)
    setError(null)
    try {
      await onAnswer(item.questionId, choice)
    } catch (err) {
      setChosen(null)
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <div role="group" aria-label="Question for you" className="rounded-md border border-[#4fc1ff] bg-[#1f2a3a] px-3 py-2 text-[12px]">
      <div className="mb-2 font-semibold text-[#9cdcfe]">Your decision</div>
      <p className="mb-2 leading-snug">{item.question}</p>
      <div className="space-y-1.5">
        {item.options.map((opt) => {
          const isChosen = item.resolved === opt.id || chosen === opt.id
          return (
            <button
              key={opt.id}
              type="button"
              disabled={locked}
              onClick={() => void pick(opt.id)}
              className={`block w-full rounded-sm border px-2.5 py-1.5 text-left disabled:cursor-not-allowed ${
                isChosen ? 'border-[#4fc1ff] bg-[#0e639c] text-white' : 'border-[#3c3c3c] bg-[#252526] hover:bg-[#2d2d30] disabled:opacity-50'
              }`}
            >
              <div className="font-semibold">{opt.label}</div>
              {opt.description && <div className="text-[11px] text-[#b0b0b0]">{opt.description}</div>}
            </button>
          )
        })}
      </div>
      {resolvedLabel && <p className="mt-2 text-[11px] text-[#89d185]">Answered: {resolvedLabel}</p>}
      {error && <p className="mt-2 text-[11px] text-[#f48771]">{error}</p>}
    </div>
  )
}

function Composer({
  agent,
  presets,
  live,
  onSend,
}: {
  agent: AgentId
  presets: Preset[]
  live: boolean
  onSend: (agent: AgentId, text: string) => Promise<void>
}) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mine = presets.filter((p) => p.agent === agent)

  const send = async (body: string) => {
    const trimmed = body.trim()
    if (!trimmed || sending || !live) return
    setSending(true)
    setError(null)
    try {
      await onSend(agent, trimmed)
      setText('')
    } catch (err) {
      // 409 = agent still busy, 429 = turn budget used up. The backend's detail says which.
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="shrink-0 space-y-1.5 border-t border-[#2b2b2b] bg-[#252526] px-3 py-2">
      {mine.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {mine.map((p) => (
            <button
              key={p.id}
              type="button"
              title={p.text}
              disabled={!live || sending}
              onClick={() => void send(p.text)}
              className="rounded-sm border border-[#3c3c3c] bg-[#2d2d30] px-2 py-0.5 text-[11px] hover:bg-[#37373d] disabled:opacity-40"
            >
              {p.title}
            </button>
          ))}
        </div>
      )}
      <form
        className="flex items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          void send(text)
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!live || sending}
          placeholder={`Message Agent ${agent}`}
          aria-label={`Message Agent ${agent}`}
          className="min-w-0 flex-1 rounded-sm border border-[#3c3c3c] bg-[#3c3c3c] px-2 py-1 text-[12px] text-[#cccccc] placeholder:text-[#8b8b8b] focus:border-[#007acc] focus:outline-none disabled:opacity-50"
        />
        <button type="submit" disabled={!live || sending || text.trim() === ''} className="rounded-sm bg-[#0e639c] px-3 py-1 text-[12px] text-white hover:bg-[#1177bb] disabled:opacity-40">
          Send
        </button>
      </form>
      {error && <p className="text-[11px] text-[#f48771]">{error}</p>}
    </div>
  )
}
