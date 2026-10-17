import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { CommitDag } from './CommitDag'
import { respond } from '../test/fetch'

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})

const commit = (id: string, seq: number, msg: string, agent_id: string, kind = 'commit') => ({
  id,
  seq,
  msg,
  agent_id,
  kind,
  ts: seq,
  added: 1,
  removed: 0,
})
const kickoff = commit('k', 1, 'Kickoff: launch plan', 'planner', 'seed')
const LOGS: Record<string, unknown[]> = {
  main: [kickoff],
  planner: [commit('p', 2, 'planner: move launch to monday', 'planner'), kickoff],
  scheduler: [commit('s', 2, 'Book the venue for Friday', 'scheduler'), kickoff],
  notes: [],
}

function renderDag() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommitDag tenant="demo" />
    </QueryClientProvider>,
  )
}

describe('CommitDag', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("draws every branch's real history, nothing hard-coded", async () => {
    const fetch = respond((req) => LOGS[new URL(req.url).pathname.split('/')[4]])
    renderDag()

    expect(await screen.findByText('planner: move launch to monday')).toBeDefined()
    expect(screen.getByText('Book the venue for Friday')).toBeDefined()
    expect(screen.getAllByText('Kickoff: launch plan')).toHaveLength(1) // shared commit drawn once
    const paths = fetch.mock.calls.map((c) => new URL((c as unknown as [Request])[0].url).pathname)
    expect(paths).toEqual(
      expect.arrayContaining(['main', 'planner', 'scheduler', 'notes'].map((b) => `/api/demo/branches/${b}/log`)),
    )
  })

  it("shows the API's error instead of a history", async () => {
    respond(() => [{ detail: 'tenant not initialised' }, 404])
    renderDag()
    expect((await screen.findByRole('alert')).textContent).toContain('tenant not initialised')
  })
})
