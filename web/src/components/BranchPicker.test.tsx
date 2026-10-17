import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BranchPicker } from './BranchPicker'
import { respond } from '../test/fetch'

const commit = { id: 'k', seq: 1, agent_id: 'planner', kind: 'seed', msg: 'Kickoff', added: 1, removed: 0 }

function renderPicker(logs: Record<string, unknown[]>) {
  respond((req) => logs[new URL(req.url).pathname.split('/')[4]] ?? [])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <BranchPicker tenant="demo" value="main" onChange={vi.fn()} />
    </QueryClientProvider>,
  )
}

const options = () => screen.getAllByRole('option').map((o) => o.textContent)

describe('BranchPicker', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("offers only branches that exist, so Notes appears after its first turn", async () => {
    renderPicker({ main: [commit], planner: [commit], scheduler: [commit], notes: [] })
    await waitFor(() => expect(options()).toEqual(['Team memory', "Planner's own memory", "Scheduler's own memory"]))
  })

  it('adds Notes once it has history', async () => {
    renderPicker({ main: [commit], planner: [commit], scheduler: [commit], notes: [commit] })
    await waitFor(() => expect(options()).toContain("Notes' own memory"))
  })
})
