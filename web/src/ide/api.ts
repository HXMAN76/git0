// HTTP + SSE transport for /api/ide. The mock backend is loaded only when the URL has ?mock=1,
// so the production path is one switch plus a dynamic import that never runs in production.

import { normalizeMergeResult } from './lib'
import {
  IDE_EVENT_TYPES,
  type AgentId,
  type GraphView,
  type IdeEvent,
  type IdeTransport,
  type SessionCreated,
  type StreamHandlers,
} from './types'

const BASE = '/api/ide'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const IS_MOCK = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mock') === '1'

async function request<T>(method: 'GET' | 'POST', url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body !== undefined) {
    init.headers = { 'content-type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`
    try {
      const json = (await res.json()) as { detail?: unknown }
      if (typeof json.detail === 'string') detail = json.detail
      else if (json.detail !== undefined) detail = JSON.stringify(json.detail)
    } catch {
      // Non-JSON error body: keep the status text.
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

const sessionUrl = (sid: string) => `${BASE}/sessions/${encodeURIComponent(sid)}`

export const realTransport: IdeTransport = {
  createSession: () => request<SessionCreated>('POST', `${BASE}/sessions`),
  getFiles: (sid: string, agent: AgentId) => request<Record<string, string>>('GET', `${sessionUrl(sid)}/files?agent=${agent}`),
  getGraph: (sid: string) => request<GraphView>('GET', `${sessionUrl(sid)}/graph`),
  sendMessage: async (sid: string, agent: AgentId, text: string) => {
    await request<{ ok: boolean }>('POST', `${sessionUrl(sid)}/agents/${agent}/messages`, { text })
  },
  answer: async (sid: string, questionId: string, choice: string) => {
    await request<{ ok: boolean }>('POST', `${sessionUrl(sid)}/questions/${encodeURIComponent(questionId)}/answer`, { choice })
  },
  // Old and new response shapes both normalise to MergeResult (see normalizeMergeResult).
  mergeCheck: async (sid: string) => normalizeMergeResult(await request<unknown>('POST', `${sessionUrl(sid)}/merge-check`)),
  end: async (sid: string) => {
    await request<{ ok: boolean }>('POST', `${sessionUrl(sid)}/end`, {})
  },
  beacon: (sid: string) => {
    // sendBeacon cannot set a JSON content type; the backend accepts this text/plain body.
    navigator.sendBeacon(`${sessionUrl(sid)}/end`, new Blob(['{}'], { type: 'text/plain' }))
  },
  connect: (sid: string, handlers: StreamHandlers) => {
    const source = new EventSource(`${sessionUrl(sid)}/events`)
    source.onopen = () => handlers.onOpen()
    for (const type of IDE_EVENT_TYPES) {
      source.addEventListener(type, (raw) => {
        let event: IdeEvent
        try {
          event = JSON.parse((raw as MessageEvent<string>).data) as IdeEvent
        } catch (cause) {
          // A malformed payload is a backend bug: report it instead of dropping it silently.
          console.error(`[ide] malformed JSON on "${type}"`, cause)
          return
        }
        handlers.onEvent(event)
      })
    }
    source.onerror = () => {
      // The browser gives up (CLOSED) when the response is an error status, e.g. 404 "session expired".
      if (source.readyState === EventSource.CLOSED) handlers.onFatal()
      else handlers.onRetry()
    }
    return () => source.close()
  },
}

/** Picks the transport. The mock module is imported lazily so production never loads it. */
export async function loadTransport(): Promise<IdeTransport> {
  if (!IS_MOCK) return realTransport
  const { createMockTransport } = await import('./mock')
  return createMockTransport()
}
