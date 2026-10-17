import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MergeBar } from './MergeBar'
import { respond } from '../test/fetch'

const fact = (id: string, key: string, o: string, agent_id: string) => {
  const [s, p] = key.split('|')
  return { id, s, p, o, key, agent_id }
}
const friday = fact('seed-launch-deadline', 'launch|deadline', 'friday', 'planner')
const monday = fact('p-launch', 'launch|deadline', 'monday', 'planner')
const venue = fact('seed-venue-status', 'venue|status', 'booked friday', 'scheduler')

const PLAN = {
  source: 'planner',
  target: 'main',
  base_commit: 'b0',
  target_head: 'th1',
  source_head: 'sh1',
  removals: [],
  unchanged: 37,
  invalidated_auto: [],
  auto_merged: [],
  conflicts: [
    {
      key: 'launch|deadline',
      base: friday,
      ours: friday,
      theirs: monday,
      strategy: 'needs-review',
      reason: 'dependency',
      dependents_ours: [venue],
      dependents_theirs: [],
      precedent: 'source chosen 2x',
      precedent_choice: 'source',
      precedent_count: 2,
    },
  ],
  merge_commit: null,
}

type Route = Record<string, (body: unknown) => unknown>

function serve(routes: Route) {
  return respond((req, body) => {
    const path = new URL(req.url).pathname.replace('/api/demo/', '')
    if (path.startsWith('branches/')) return [] // logs for the Notes check
    return routes[path](body)
  })
}

const posted = (fetch: ReturnType<typeof serve>, path: string) =>
  fetch.mock.calls
    .map((c) => (c as unknown as [Request])[0])
    .filter((r) => r.method === 'POST' && r.url.endsWith(path))

function renderBar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MergeBar tenant="demo" />
    </QueryClientProvider>,
  )
}

describe('MergeBar', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows the disagreement, lets the human pick, merges with the previewed heads and re-derives', async () => {
    const fetch = serve({
      'merge/preview': () => PLAN,
      'merge/explain': () => [{ key: 'launch|deadline', text: 'Planner moved the launch after Scheduler booked Friday.' }],
      'merge/resolve': () => ({ merge_commit: 'm1', removed: [venue.id], invalidated: [venue], restored: [] }),
      'arbiter/rederive': () => ({
        replies: [{ agent_id: 'scheduler', text: 'Venue re-booked for Monday.' }],
        tokens: 120,
        owners: ['scheduler'],
        skipped: [],
      }),
    })
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Merge Planner' }))

    expect(await screen.findByText('Planner and Scheduler disagree')).toBeDefined()
    expect(await screen.findByText('Planner moved the launch after Scheduler booked Friday.')).toBeDefined()
    expect(screen.getByText(/1 built on it: venue status “booked friday”/)).toBeDefined()
    expect(screen.getByText('Settled 2× before by siding with Planner')).toBeDefined()

    const merge = screen.getByRole('button', { name: 'Merge with my choices' }) as HTMLButtonElement
    expect(merge.disabled).toBe(true) // nothing chosen yet
    fireEvent.click(screen.getByRole('button', { name: /Planner says/ }))
    fireEvent.click(merge)

    expect((await screen.findByRole('status')).textContent).toContain('Venue re-booked for Monday.')
    expect(screen.getByRole('status').textContent).toContain('37 unchanged')
    expect(await posted(fetch, 'merge/resolve')[0].clone().json()).toEqual({
      source: 'planner',
      target: 'main',
      choices: { 'launch|deadline': 'p-launch' },
      agent_id: 'human',
      target_head: 'th1',
      source_head: 'sh1',
    })
    expect(await posted(fetch, 'arbiter/rederive')[0].clone().json()).toEqual({
      target: 'main',
      fact_ids: ['seed-venue-status'],
      session_id: 'arbiter',
    })
  })

  it('merges right away when nothing needs a decision', async () => {
    const fetch = serve({
      'merge/preview': () => ({ ...PLAN, source: 'scheduler', conflicts: [], auto_merged: [venue] }),
      'merge/resolve': () => ({ merge_commit: 'm1', removed: [], invalidated: [], restored: [] }),
    })
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Merge Scheduler' }))

    expect((await screen.findByRole('status')).textContent).toContain("Scheduler's work is now team memory: 1 change(s)")
    expect(posted(fetch, 'merge/explain')).toHaveLength(0)
    expect(posted(fetch, 'arbiter/rederive')).toHaveLength(0)
  })

  it("shows the Arbiter's failure but still lets the human decide", async () => {
    serve({
      'merge/preview': () => PLAN,
      'merge/explain': () => [{ detail: 'all LLM providers failed: boom' }, 502],
    })
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Merge Planner' }))

    expect((await screen.findByRole('alert')).textContent).toContain('all LLM providers failed: boom')
    fireEvent.click(screen.getByRole('button', { name: /Team memory says/ }))
    await waitFor(() =>
      expect((screen.getByRole('button', { name: 'Merge with my choices' }) as HTMLButtonElement).disabled).toBe(false),
    )
  })

  it('shows a stale-preview 409 from resolve as an error', async () => {
    serve({
      'merge/preview': () => ({ ...PLAN, conflicts: [], auto_merged: [monday] }),
      'merge/resolve': () => [{ detail: 'branch moved since preview; preview again' }, 409],
    })
    renderBar()
    fireEvent.click(screen.getByRole('button', { name: 'Merge Planner' }))
    expect((await screen.findByRole('alert')).textContent).toContain('branch moved since preview')
  })
})
