import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DemoGuide } from './DemoGuide'
import { respond } from '../test/fetch'

const c = (id: string, agent_id: string, kind: string) => ({ id, seq: 1, agent_id, kind, msg: id, added: 0, removed: 0 })
const seed = c('k', 'planner', 'seed')

function renderGuide(logs: Record<string, unknown[]>, onPrompt = vi.fn()) {
  respond((req) => logs[new URL(req.url).pathname.split('/')[4]] ?? [])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DemoGuide tenant="demo" onPrompt={onPrompt} />
    </QueryClientProvider>,
  )
  return onPrompt
}

const doneFlags = () => screen.getAllByRole('listitem').slice(1).map((li) => li.dataset.done)

describe('DemoGuide', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('ticks steps from the real branch histories', async () => {
    renderGuide({
      main: [c('s', 'scheduler', 'seed'), seed],
      planner: [c('p1', 'planner', 'commit'), seed],
      scheduler: [c('s', 'scheduler', 'seed'), seed],
    })
    await waitFor(() => expect(doneFlags()).toEqual(['true', 'true', 'false']))
  })

  it('nothing is ticked in a fresh room, and step 1 fills the Planner chat', async () => {
    const onPrompt = renderGuide({ main: [seed], planner: [seed], scheduler: [seed] })
    await waitFor(() => expect(doneFlags()).toEqual(['false', 'false', 'false']))
    fireEvent.click(screen.getByRole('button', { name: /launch moved to Monday/ }))
    expect(onPrompt).toHaveBeenCalledWith({ agent: 'planner', text: 'The launch moved to Monday.' })
  })
})
