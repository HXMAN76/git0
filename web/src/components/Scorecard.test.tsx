import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Scorecard } from './Scorecard'
import { respond, urlOf } from '../test/fetch'

const CARD = {
  episodes: 4,
  sessions: 2,
  facts_on_main: 37,
  procedures_on_main: 1,
  commits: 6,
  merges: 1,
  reverts: 0,
  handoffs: 0,
  conflicts_resolved: 1,
  precedents_reused: 0,
  agents: 3,
  tenants: 5,
  query_ms: 0.42,
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Scorecard tenant="demo" />
    </QueryClientProvider>,
  )
}

describe('Scorecard', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("shows each live number and FalkorDB's query time", async () => {
    const fetch = respond(() => CARD)
    renderCard()

    expect((await screen.findByTestId('score-facts_on_main')).textContent).toBe('37')
    expect(screen.getByTestId('score-tenants').textContent).toBe('5')
    expect(screen.getByTestId('score-query-ms').textContent).toContain('0.4 ms')
    expect(urlOf(fetch, 0).pathname).toBe('/api/demo/scorecard')
  })

  it("shows the API's error, never zeros", async () => {
    respond(() => [{ detail: 'tenant not initialised' }, 404])
    renderCard()

    expect((await screen.findByRole('alert')).textContent).toContain('tenant not initialised')
    expect(screen.queryByTestId('score-facts_on_main')).toBeNull()
  })
})
