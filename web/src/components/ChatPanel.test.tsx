import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatPanel } from './ChatPanel'
// Build an SSE-encoded response body from token + commit events.
function sseResponse(reply: {
  agent_id: string
  text: string
  commit_id?: string
  cited_fact_ids?: string[]
  branch?: string
}) {
  const lines = [
    `event: token\ndata: ${JSON.stringify({ text: reply.text, agent_id: reply.agent_id })}\n\n`,
    `event: commit\ndata: ${JSON.stringify({
      commit_id: reply.commit_id ?? 'c1',
      cited_fact_ids: reply.cited_fact_ids ?? [],
      branch: reply.branch ?? reply.agent_id,
      agent_id: reply.agent_id,
    })}\n\n`,
  ].join('')
  return new Response(lines, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function respondSSE(route: (url: string, body: unknown) => Parameters<typeof sseResponse>[0]) {
  const fetch = vi.fn(async (input: string | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.url
    const bodyStr = init?.body ? String(init.body) : ''
    return sseResponse(route(url, bodyStr ? JSON.parse(bodyStr) : undefined))
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function respondError(status: number, detail: string) {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ detail }), { status }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderChat(props?: Partial<Parameters<typeof ChatPanel>[0]>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ChatPanel tenant="demo" {...props} />
    </QueryClientProvider>,
  )
}

describe('ChatPanel', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("sends the message to the selected agent and shows the agent's reply with why? buttons", async () => {
    const fetch = respondSSE((_url, body) => ({
      agent_id: 'scheduler',
      text: `Noted: ${(body as { text: string }).text}`,
      commit_id: 'c9',
      cited_fact_ids: ['f1', 'f2'],
      branch: 'scheduler',
    }))
    renderChat()
    fireEvent.click(screen.getByRole('tab', { name: 'Scheduler' }))

    const input = screen.getByLabelText(/Message scheduler/i)
    fireEvent.change(input, { target: { value: 'book the venue' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Noted: book the venue')).toBeDefined()
    // cited facts → "why?" buttons
    expect(screen.getAllByRole('button', { name: /why\?/ })).toHaveLength(2)
    const [calledUrl, calledInit] = fetch.mock.calls[0] as [string, RequestInit]
    expect(calledUrl).toBe('/api/demo/agents/scheduler/messages')
    const body = JSON.parse(calledInit.body as string) as { text: string; session_id: string }
    expect(body.text).toBe('book the venue')
    expect(body.session_id).toMatch(/^[0-9a-f-]{8,}/)
  })

  it('shows an LLM failure as a red banner', async () => {
    respondError(502, 'all LLM providers failed: rate limited')
    renderChat()

    const input = screen.getByLabelText(/Message planner/i)
    fireEvent.change(input, { target: { value: 'The launch moved to Monday' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect((await screen.findByRole('alert')).textContent).toContain('all LLM providers failed: rate limited')
    expect(screen.getByText('The launch moved to Monday')).toBeDefined()
  })

  it('keeps a separate thread per agent', async () => {
    respondSSE((_url, _body) => ({ agent_id: 'planner', text: 'Launch is now Monday.' }))
    renderChat()

    const input = screen.getByLabelText(/Message planner/i)
    fireEvent.change(input, { target: { value: 'move launch' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Launch is now Monday.')).toBeDefined()

    fireEvent.click(screen.getByRole('tab', { name: 'Notes' }))
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).queryByText('Launch is now Monday.')).toBeNull()
    expect(within(panel).getByText('Send a message to start.')).toBeDefined()
  })
})

describe('ChatPanel prompt', () => {
  afterEach(cleanup)

  it("puts the demo guide's message in the active agent's box without sending it", async () => {
    vi.stubGlobal('fetch', vi.fn())
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <ChatPanel tenant="demo" prompt={{ agent: 'planner', text: 'The launch moved to Monday.' }} />
      </QueryClientProvider>,
    )
    const input = (await screen.findByLabelText(/Message planner/i)) as HTMLInputElement
    expect(input.value).toBe('The launch moved to Monday.')
    expect(screen.getByRole('tab', { name: 'Planner' }).getAttribute('aria-selected')).toBe('true')
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(input)
  })
})
