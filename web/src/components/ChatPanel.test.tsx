import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatPanel } from './ChatPanel'
import { bodyOf, respond, urlOf } from '../test/fetch'

function renderChat() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ChatPanel tenant="demo" />
    </QueryClientProvider>,
  )
}

function say(text: string) {
  fireEvent.change(screen.getByLabelText(/Message/), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

describe('ChatPanel', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("sends the message to the selected agent and shows the agent's real reply", async () => {
    const fetch = respond((_req, body) => ({
      agent_id: 'scheduler',
      text: `Noted: ${(body as { message: string }).message}`,
      commit_id: 'c9',
      cited_fact_ids: ['f1', 'f2'],
      branch: 'scheduler',
    }))
    renderChat()
    fireEvent.click(screen.getByRole('tab', { name: 'Scheduler' }))
    say('book the venue')

    expect(await screen.findByText('Noted: book the venue')).toBeDefined()
    expect(screen.getByText(/used 2 facts/)).toBeDefined()
    expect(urlOf(fetch, 0).pathname).toBe('/api/demo/agents/scheduler/messages')
    const body = (await bodyOf(fetch, 0)) as { message: string; session_id: string }
    expect(body.message).toBe('book the venue')
    expect(body.session_id).toMatch(/^chat_/)
  })

  it('shows an LLM failure (502) as a red banner with the real reason', async () => {
    respond(() => [{ detail: 'all LLM providers failed: rate limited' }, 502])
    renderChat()
    say('The launch moved to Monday')

    expect((await screen.findByRole('alert')).textContent).toContain('all LLM providers failed: rate limited')
    expect(screen.getByText('The launch moved to Monday')).toBeDefined() // your message stays visible
  })

  it('keeps a separate thread per agent', async () => {
    respond(() => ({ agent_id: 'planner', text: 'Launch is now Monday.', branch: 'planner' }))
    renderChat()
    say('move launch')
    expect(await screen.findByText('Launch is now Monday.')).toBeDefined()

    fireEvent.click(screen.getByRole('tab', { name: 'Notes' }))
    expect(screen.queryByText('Launch is now Monday.')).toBeNull()
    expect(screen.getByText(/Keeps decisions and contacts/)).toBeDefined()
  })
})

describe('ChatPanel prompt', () => {
  afterEach(cleanup)

  it("puts the demo guide's message in the agent's box without sending it", () => {
    const fetch = respond(() => ({}))
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <ChatPanel tenant="demo" prompt={{ agent: 'planner', text: 'The launch moved to Monday.' }} />
      </QueryClientProvider>,
    )
    expect((screen.getByLabelText(/Message/) as HTMLInputElement).value).toBe('The launch moved to Monday.')
    expect(screen.getByRole('tab', { name: 'Planner' }).getAttribute('aria-selected')).toBe('true')
    expect(fetch).not.toHaveBeenCalled()
  })
})
