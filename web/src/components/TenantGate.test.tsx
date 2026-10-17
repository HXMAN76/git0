import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TenantGate } from './TenantGate'

function renderGate(fetchImpl: (r: Request) => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TenantGate tenant="vroom1234">{(t) => <p>views for {t}</p>}</TenantGate>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TenantGate', () => {
  it('seeds the room before rendering any view', async () => {
    const calls: string[] = []
    renderGate(async (r) => {
      calls.push(`${r.method} ${new URL(r.url).pathname}`)
      return new Response(
        JSON.stringify({ created: true, branches: ['main'], facts_on_main: 37, facts_on_scheduler: 40 }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    })
    expect(screen.getByText(/setting up your team room/i)).toBeTruthy()
    expect(await screen.findByText('views for vroom1234')).toBeTruthy()
    expect(calls).toEqual(['POST /api/vroom1234/seed'])
  })

  it('shows the seed error instead of the views (fail loudly)', async () => {
    renderGate(async () =>
      new Response(JSON.stringify({ detail: 'FalkorDB down' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      }),
    )
    expect(await screen.findByText(/could not set up your team room: FalkorDB down/i)).toBeTruthy()
    expect(screen.queryByText(/views for/)).toBeNull()
  })
})
