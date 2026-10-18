// Shared types for the git0 relay IDE. The SSE event shapes mirror the "SSE event contract" in
// docs/plans/2026-10-18-ide-demo.md; keep them in sync with the backend.

export type AgentId = 'A' | 'B'
export const AGENTS: readonly AgentId[] = ['A', 'B'] as const

export const AGENT_META: Record<AgentId, { owner: string; root: string; color: string }> = {
  A: { owner: 'Alice', root: "ALICE'S LAPTOP", color: '#4fc1ff' },
  B: { owner: 'Bob', root: "BOB'S LAPTOP", color: '#c586c0' },
}

export type AgentStatus = 'idle' | 'thinking' | 'tool' | 'waiting_user' | 'error'
export type ConflictKind = 'same_symbol' | 'dependency' | 'reverse_dependency' | 'intent'

export interface ConflictInfo {
  kind: ConflictKind
  severity: 'block' | 'warn'
  symbol: string
  peer: string
  peer_change_id: string | null
  peer_summary: string
  path: string[]
  message: string
}

export interface AgentInfo {
  label: string
  model: string
}

export interface Preset {
  id: string
  agent: AgentId
  title: string
  text: string
}

export interface AskOption {
  id: string
  label: string
  description?: string
}

export interface SessionCreated {
  session_id: string
  agents: Record<AgentId, AgentInfo>
  files: string[]
  presets?: Preset[]
}

export interface MergeFile {
  path: string
  conflicted: boolean
  merged: string
}

export interface MergeResult {
  files: MergeFile[]
}

export interface GraphNode {
  id: string
  label: string
  name: string
  kind: string
  props: Record<string, unknown>
}

export interface GraphLink {
  source: string
  target: string
  type: string
}

export interface GraphView {
  nodes: GraphNode[]
  links: GraphLink[]
}

/** Every named SSE event the backend emits. The client subscribes to all of them. */
export const IDE_EVENT_TYPES = [
  'session',
  'agent_status',
  'agent_message',
  'tool_call',
  'tool_result',
  'hook',
  'file_changed',
  'graph_changed',
  'conflict',
  'ask_user',
  'ask_resolved',
  'peer_notice',
  'usage',
  'error',
  'session_ended',
] as const

export type IdeEvent =
  | { type: 'session'; ts: number; session_id: string; agents: Record<AgentId, AgentInfo>; files: string[]; presets?: Preset[] }
  | { type: 'agent_status'; ts: number; agent: AgentId; status: AgentStatus }
  | { type: 'agent_message'; ts: number; agent: AgentId; role: 'user' | 'assistant'; text: string }
  | { type: 'tool_call'; ts: number; agent: AgentId; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; ts: number; agent: AgentId; call_id: string; tool: string; ok: boolean; summary: string }
  | {
      type: 'hook'
      ts: number
      agent: AgentId
      phase: 'PreToolUse' | 'PostToolUse'
      tool: string
      mcp_tool: string
      decision: 'allow' | 'deny' | 'context' | 'recorded'
      detail: string
      ms: number
    }
  | { type: 'file_changed'; ts: number; agent: AgentId; path: string; content: string }
  | { type: 'graph_changed'; ts: number }
  | { type: 'conflict'; ts: number; agent: AgentId; conflicts: ConflictInfo[] }
  | { type: 'ask_user'; ts: number; agent: AgentId; question_id: string; question: string; options: AskOption[] }
  | { type: 'ask_resolved'; ts: number; agent: AgentId; question_id: string; choice: string }
  | { type: 'peer_notice'; ts: number; agent: AgentId; from: AgentId; message: string }
  | { type: 'usage'; ts: number; agent: AgentId; input_tokens: number; output_tokens: number; requests: number }
  | { type: 'error'; ts: number; agent?: AgentId; message: string }
  | { type: 'session_ended'; ts: number; reason: string }

/** Handlers the transport calls. The controller decides what each one means. */
export interface StreamHandlers {
  onEvent(event: IdeEvent): void
  onOpen(): void
  /** The stream gave up for good (the server answered with an error status). */
  onFatal(): void
  /** A transient failure; the browser retries on its own. */
  onRetry(): void
}

/** Real HTTP+SSE transport or the in-browser mock (?mock=1). Same shape, so the UI never branches. */
export interface IdeTransport {
  createSession(): Promise<SessionCreated>
  getFiles(sid: string, agent: AgentId): Promise<Record<string, string>>
  getGraph(sid: string): Promise<GraphView>
  connect(sid: string, handlers: StreamHandlers): () => void
  sendMessage(sid: string, agent: AgentId, text: string): Promise<void>
  answer(sid: string, questionId: string, choice: string): Promise<void>
  mergeCheck(sid: string): Promise<MergeResult>
  end(sid: string): Promise<void>
  /** Fire-and-forget end on page close (navigator.sendBeacon in the real transport). */
  beacon(sid: string): void
}
