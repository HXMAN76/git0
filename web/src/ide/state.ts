// Pure state for the IDE. Every SSE event goes through applyEvent, so a reload (which replays the
// backend's event buffer) rebuilds the same screen.

import { type AgentId, type AgentInfo, type AgentStatus, type ConflictInfo, type IdeEvent, type Preset } from './types'

export type Phase = 'starting' | 'live' | 'busy' | 'ended' | 'error'
export type Tone = 'ok' | 'info' | 'warn' | 'deny' | 'error' | 'muted'

export type ChatItem =
  | { id: number; kind: 'message'; role: 'user' | 'assistant'; text: string }
  | { id: number; kind: 'tool'; callId: string; tool: string; path: string; status: 'running' | 'ok' | 'fail'; summary: string }
  | {
      id: number
      kind: 'hook'
      phase: string
      tool: string
      mcpTool: string
      decision: string
      detail: string
      ms: number
    }
  | { id: number; kind: 'peer'; from: AgentId; message: string }
  | { id: number; kind: 'conflict'; conflicts: ConflictInfo[] }
  | {
      id: number
      kind: 'ask'
      questionId: string
      question: string
      options: { id: string; label: string; description?: string }[]
      resolved: string | null
    }
  | { id: number; kind: 'error'; message: string }

export interface AgentState {
  status: AgentStatus
  /** Why the status is what it is, e.g. the rate-limit wait. Empty for most statuses. */
  detail: string
  items: ChatItem[]
  usage: { input: number; output: number; requests: number }
}

export interface LogEntry {
  id: number
  ts: number
  agent: AgentId | null
  text: string
  tone: Tone
}

export interface ConflictRecord {
  id: number
  ts: number
  agent: AgentId
  conflict: ConflictInfo
}

export interface EditorGroupState {
  tabs: string[]
  active: string | null
  /** Bumped on every file_changed so the editor scrolls to the first changed line. */
  revealSeq: number
}

export type FileMap = Record<string, string>

export interface IdeState {
  phase: Phase
  sessionId: string | null
  startedAt: number
  endedReason: string | null
  busyMessage: string | null
  error: string | null
  /** Non-fatal notice, e.g. a failed scenario send. Dismissed by the user. */
  banner: string | null
  sseOpen: boolean
  agentInfo: Record<AgentId, AgentInfo> | null
  files: string[]
  presets: Preset[]
  agents: Record<AgentId, AgentState>
  /** Template contents per agent, fetched before any event (the baseline for changed-line marks). */
  baseline: Record<AgentId, FileMap>
  /** Latest content per agent: starts equal to the baseline, then follows file_changed events. */
  content: Record<AgentId, FileMap>
  editors: Record<AgentId, EditorGroupState>
  log: LogEntry[]
  conflicts: ConflictRecord[]
  /** Symbol ids on the most recent conflict's path, lit up in the GRAPH tab. */
  highlight: string[]
  graphVersion: number
  nextId: number
}

const MAX_LOG = 800
const MAX_ITEMS = 300

const emptyAgent = (): AgentState => ({ status: 'idle', detail: '', items: [], usage: { input: 0, output: 0, requests: 0 } })
const emptyEditors = (): EditorGroupState => ({ tabs: [], active: null, revealSeq: 0 })

export function initialState(): IdeState {
  return {
    phase: 'starting',
    sessionId: null,
    startedAt: Date.now(),
    endedReason: null,
    busyMessage: null,
    error: null,
    banner: null,
    sseOpen: false,
    agentInfo: null,
    files: [],
    presets: [],
    agents: { A: emptyAgent(), B: emptyAgent() },
    baseline: { A: {}, B: {} },
    content: { A: {}, B: {} },
    editors: { A: emptyEditors(), B: emptyEditors() },
    log: [],
    conflicts: [],
    highlight: [],
    graphVersion: 0,
    nextId: 1,
  }
}

export type Action =
  | { type: 'created'; sessionId: string; agents: Record<AgentId, AgentInfo>; files: string[]; presets: Preset[]; at: number }
  | { type: 'baseline'; baseline: Record<AgentId, FileMap> }
  | { type: 'busy'; message: string }
  | { type: 'failed'; message: string }
  | { type: 'sse_open'; open: boolean }
  /** A reconnect replays the backend buffer, so clear the live state first to avoid duplicates. */
  | { type: 'live_reset' }
  | { type: 'event'; event: IdeEvent }
  | { type: 'ended'; reason: string }
  | { type: 'banner'; text: string | null }
  | { type: 'open_file'; agent: AgentId; path: string }
  | { type: 'close_tab'; agent: AgentId; path: string }
  | { type: 'select_tab'; agent: AgentId; path: string }
  | { type: 'reset' }

function pushItem(s: IdeState, agent: AgentId, item: (id: number) => ChatItem): IdeState {
  const id = s.nextId
  const prev = s.agents[agent].items
  const items = [...prev, item(id)]
  const trimmed = items.length > MAX_ITEMS ? items.slice(items.length - MAX_ITEMS) : items
  return { ...s, nextId: id + 1, agents: { ...s.agents, [agent]: { ...s.agents[agent], items: trimmed } } }
}

function pushLog(s: IdeState, ts: number, agent: AgentId | null, text: string, tone: Tone): IdeState {
  const id = s.nextId
  const log = [...s.log, { id, ts, agent, text, tone }]
  return { ...s, nextId: id + 1, log: log.length > MAX_LOG ? log.slice(log.length - MAX_LOG) : log }
}

function patchItem(s: IdeState, agent: AgentId, match: (item: ChatItem) => boolean, patch: (item: ChatItem) => ChatItem): IdeState {
  const items = s.agents[agent].items.map((item) => (match(item) ? patch(item) : item))
  return { ...s, agents: { ...s.agents, [agent]: { ...s.agents[agent], items } } }
}

/** Opens (or focuses) the file in that agent's editor group. */
function openTab(s: IdeState, agent: AgentId, path: string, reveal: boolean): IdeState {
  const group = s.editors[agent]
  const tabs = group.tabs.includes(path) ? group.tabs : [...group.tabs, path]
  return {
    ...s,
    editors: {
      ...s.editors,
      [agent]: { tabs, active: path, revealSeq: reveal ? group.revealSeq + 1 : group.revealSeq },
    },
  }
}

function applyEvent(s: IdeState, ev: IdeEvent): IdeState {
  switch (ev.type) {
    case 'session':
      return { ...s, sessionId: ev.session_id, agentInfo: ev.agents, files: ev.files, presets: ev.presets ?? s.presets }

    case 'agent_status':
      return { ...s, agents: { ...s.agents, [ev.agent]: { ...s.agents[ev.agent], status: ev.status, detail: ev.detail ?? '' } } }

    case 'agent_message':
      return pushItem(s, ev.agent, (id) => ({ id, kind: 'message', role: ev.role, text: ev.text }))

    case 'tool_call': {
      const path = typeof ev.args.path === 'string' ? ev.args.path : ''
      const withItem = pushItem(s, ev.agent, (id) => ({
        id,
        kind: 'tool',
        callId: ev.call_id,
        tool: ev.tool,
        path,
        status: 'running',
        summary: '',
      }))
      return pushLog(withItem, ev.ts, ev.agent, `tool ${ev.tool}${path ? ` ${path}` : ''}`, 'info')
    }

    case 'tool_result': {
      const patched = patchItem(
        s,
        ev.agent,
        (item) => item.kind === 'tool' && item.callId === ev.call_id,
        (item) =>
          item.kind === 'tool' ? { ...item, status: ev.ok ? 'ok' : 'fail', summary: ev.summary } : item,
      )
      return ev.ok ? patched : pushLog(patched, ev.ts, ev.agent, `tool ${ev.tool} failed: ${ev.summary}`, 'error')
    }

    case 'hook': {
      const withItem = pushItem(s, ev.agent, (id) => ({
        id,
        kind: 'hook',
        phase: ev.phase,
        tool: ev.tool,
        mcpTool: ev.mcp_tool,
        decision: ev.decision,
        detail: ev.detail,
        ms: ev.ms,
      }))
      const tone: Tone = ev.decision === 'deny' ? 'deny' : ev.decision === 'context' ? 'warn' : 'ok'
      const detail = ev.detail ? ` (${ev.detail})` : ''
      const text = `${ev.phase} · ${ev.tool} → MCP ${ev.mcp_tool} → ${ev.decision.toUpperCase()}${detail} ${ev.ms}ms`
      return pushLog(withItem, ev.ts, ev.agent, text, tone)
    }

    case 'file_changed': {
      const content = { ...s.content, [ev.agent]: { ...s.content[ev.agent], [ev.path]: ev.content } }
      return openTab({ ...s, content }, ev.agent, ev.path, true)
    }

    case 'graph_changed':
      return { ...s, graphVersion: s.graphVersion + 1 }

    case 'conflict': {
      let next = s
      for (const conflict of ev.conflicts) {
        const id = next.nextId
        next = {
          ...next,
          nextId: id + 1,
          conflicts: [...next.conflicts, { id, ts: ev.ts, agent: ev.agent, conflict }],
        }
        next = pushLog(next, ev.ts, ev.agent, `CONFLICT ${conflict.kind} on ${conflict.symbol}: ${conflict.message}`, 'deny')
      }
      if (ev.conflicts.length > 0) {
        const highlight = Array.from(new Set(ev.conflicts.flatMap((c) => c.path)))
        next = { ...next, highlight }
      }
      return pushItem(next, ev.agent, (id) => ({ id, kind: 'conflict', conflicts: ev.conflicts }))
    }

    case 'ask_user': {
      const withItem = pushItem(s, ev.agent, (id) => ({
        id,
        kind: 'ask',
        questionId: ev.question_id,
        question: ev.question,
        options: ev.options,
        resolved: null,
      }))
      return pushLog(withItem, ev.ts, ev.agent, `ASK ${ev.question}`, 'warn')
    }

    case 'ask_resolved': {
      const patched = patchItem(
        s,
        ev.agent,
        (item) => item.kind === 'ask' && item.questionId === ev.question_id,
        (item) => (item.kind === 'ask' ? { ...item, resolved: ev.choice } : item),
      )
      return pushLog(patched, ev.ts, ev.agent, `answer ${ev.choice}`, 'info')
    }

    case 'peer_notice': {
      const withItem = pushItem(s, ev.agent, (id) => ({ id, kind: 'peer', from: ev.from, message: ev.message }))
      return pushLog(withItem, ev.ts, ev.agent, `NOTICE from ${ev.from}: ${ev.message}`, 'warn')
    }

    case 'usage': {
      const prev = s.agents[ev.agent].usage
      // The backend reports the tokens of each run; the status bar shows running totals.
      const usage = {
        input: prev.input + ev.input_tokens,
        output: prev.output + ev.output_tokens,
        requests: prev.requests + ev.requests,
      }
      return { ...s, agents: { ...s.agents, [ev.agent]: { ...s.agents[ev.agent], usage } } }
    }

    case 'error': {
      if (ev.agent) {
        const withItem = pushItem(s, ev.agent, (id) => ({ id, kind: 'error', message: ev.message }))
        return pushLog(withItem, ev.ts, ev.agent, `ERROR ${ev.message}`, 'error')
      }
      return { ...pushLog(s, ev.ts, null, `ERROR ${ev.message}`, 'error'), banner: ev.message }
    }

    case 'session_ended':
      return { ...s, phase: 'ended', endedReason: ev.reason }
  }
}

export function reducer(s: IdeState, action: Action): IdeState {
  switch (action.type) {
    case 'reset':
      return initialState()

    case 'created':
      return {
        ...s,
        phase: 'live',
        sessionId: action.sessionId,
        agentInfo: action.agents,
        files: action.files,
        presets: action.presets,
        startedAt: action.at,
        busyMessage: null,
        error: null,
      }

    case 'baseline':
      return {
        ...s,
        baseline: action.baseline,
        content: { A: { ...action.baseline.A }, B: { ...action.baseline.B } },
        editors: openingEditors(action.baseline),
      }

    case 'busy':
      return { ...s, phase: 'busy', busyMessage: action.message }

    case 'failed':
      return { ...s, phase: 'error', error: action.message }

    case 'sse_open':
      return { ...s, sseOpen: action.open }

    case 'live_reset':
      return {
        ...s,
        log: [],
        conflicts: [],
        highlight: [],
        graphVersion: s.graphVersion + 1,
        agents: { A: emptyAgent(), B: emptyAgent() },
        content: { A: { ...s.baseline.A }, B: { ...s.baseline.B } },
        editors: openingEditors(s.baseline),
      }

    case 'event':
      return applyEvent(s, action.event)

    case 'ended':
      return { ...s, phase: 'ended', endedReason: action.reason, sseOpen: false }

    case 'banner':
      return { ...s, banner: action.text }

    case 'open_file':
      return openTab(s, action.agent, action.path, false)

    case 'select_tab':
      return { ...s, editors: { ...s.editors, [action.agent]: { ...s.editors[action.agent], active: action.path } } }

    case 'close_tab': {
      const group = s.editors[action.agent]
      const tabs = group.tabs.filter((p) => p !== action.path)
      const active = group.active === action.path ? (tabs[tabs.length - 1] ?? null) : group.active
      return { ...s, editors: { ...s.editors, [action.agent]: { ...group, tabs, active } } }
    }
  }
}

/** Derived: a file counts as modified once an agent's copy differs from the template. */
export function isModified(s: IdeState, agent: AgentId, path: string): boolean {
  const now = s.content[agent][path]
  if (now === undefined) return false
  return now !== s.baseline[agent][path]
}

export function modifiedFiles(s: IdeState, agent: AgentId): string[] {
  return Object.keys(s.content[agent]).filter((p) => isModified(s, agent, p))
}

/** Editors start on the agent's entry file so the first screen is not empty. */
function openingEditors(baseline: Record<AgentId, FileMap>): Record<AgentId, EditorGroupState> {
  const opening = (agent: AgentId): EditorGroupState => {
    const files = Object.keys(baseline[agent])
    const path = files.includes('shop/cart.py') ? 'shop/cart.py' : (files[0] ?? null)
    return path ? { tabs: [path], active: path, revealSeq: 0 } : emptyEditors()
  }
  return { A: opening('A'), B: opening('B') }
}
