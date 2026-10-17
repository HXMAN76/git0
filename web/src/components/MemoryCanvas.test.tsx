import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Data, ForceGraphConfig, GraphNode } from '@falkordb/canvas'
import { MemoryCanvas } from './MemoryCanvas'
import { NODE_COLORS, toCanvasData, type GraphView } from '../lib/memoryGraph'

// The real web component draws on a <canvas> that jsdom cannot render, so a stand-in element records the
// calls MemoryCanvas makes. The graph data itself comes through a mocked fetch, like the real API.
vi.mock('@falkordb/canvas', () => ({}))
const canvas = {
  setConfig: vi.fn<(c: Partial<ForceGraphConfig>) => void>(),
  setGraphData: vi.fn<(d: Data) => void>(),
  setWidth: vi.fn(),
  setHeight: vi.fn(),
  refresh: vi.fn(),
}
beforeAll(() => {
  class FakeCanvas extends HTMLElement {}
  Object.assign(FakeCanvas.prototype, canvas)
  customElements.define('falkordb-canvas', FakeCanvas)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
})

const VIEW: GraphView = {
  branch: 'main',
  truncated: false,
  nodes: [
    { id: 'f1', label: 'Fact', name: 'launch deadline: friday', kind: 'deadline', props: {} },
    { id: 'f2', label: 'Fact', name: 'venue status: booked', kind: 'status', props: {} },
    { id: 'c1', label: 'Commit', name: 'kickoff', kind: 'merge', props: { seq: 1 } },
    { id: 'planner', label: 'Agent', name: 'planner', kind: 'agent', props: {} },
  ],
  links: [
    { source: 'f1', target: 'c1', type: 'ADDED_IN' },
    { source: 'f2', target: 'c1', type: 'ADDED_IN' },
    { source: 'f2', target: 'f1', type: 'DERIVED_FROM' },
    { source: 'planner', target: 'c1', type: 'AUTHORED' },
  ],
}

function respond(body: unknown, status = 200) {
  const fetch = vi.fn(
    async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderCanvas(props: Partial<Parameters<typeof MemoryCanvas>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryCanvas tenant="demo" {...props} />
    </QueryClientProvider>,
  )
}

const node = (gid: string) => ({ data: { gid } }) as unknown as GraphNode

describe('MemoryCanvas', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(cleanup)

  it('loads the branch graph from the API and hands it to the canvas', async () => {
    const fetch = respond(VIEW)
    renderCanvas({ branch: 'scheduler' })

    expect(await screen.findByText('scheduler: 2 facts')).toBeDefined()
    const url = new URL((fetch.mock.calls[0] as unknown as [Request])[0].url)
    expect(url.pathname).toBe('/api/demo/graph')
    expect(url.searchParams.get('branch')).toBe('scheduler')

    const data = canvas.setGraphData.mock.lastCall![0]
    expect(data.nodes).toHaveLength(4)
    expect(data.links).toHaveLength(4)
    expect(canvas.setConfig.mock.calls[0][0]).toMatchObject({ captionsKeys: ['name'] })
  })

  it('dims everything outside the highlighted ids', async () => {
    respond(VIEW)
    renderCanvas({ highlight: ['f1', 'c1'] })
    await waitFor(() => expect(canvas.setGraphData).toHaveBeenCalled())

    const focus = canvas.setConfig.mock.calls.map((c) => c[0]).findLast((c) => 'dimmed' in c)!
    expect(focus.dimmed).toBe(true)
    expect(focus.isNodeDimmed!(node('f1'))).toBe(false)
    expect(focus.isNodeDimmed!(node('planner'))).toBe(true)
    expect(focus.isNodeSelected!(node('c1'))).toBe(true)
  })

  it('reports the click with the domain id', async () => {
    respond(VIEW)
    const onNodeClick = vi.fn()
    renderCanvas({ onNodeClick })
    await waitFor(() => expect(canvas.setConfig).toHaveBeenCalled())

    const handlers = canvas.setConfig.mock.calls.find((c) => c[0].eventHandlers)![0].eventHandlers!
    handlers.onNodeClick!(node('f2'), new MouseEvent('click'))
    expect(onNodeClick).toHaveBeenCalledWith('f2')
  })

  it("shows the API's error instead of a graph", async () => {
    respond({ detail: 'tenant not initialised: POST /api/{tenant}/init or /seed first' }, 404)
    renderCanvas()

    expect((await screen.findByRole('alert')).textContent).toContain('tenant not initialised')
    expect(canvas.setGraphData).not.toHaveBeenCalled()
  })

  it('shows an error state when the canvas component throws', async () => {
    respond(VIEW)
    canvas.setGraphData.mockImplementationOnce(() => {
      throw new Error('no 2d context')
    })
    vi.spyOn(console, 'error').mockImplementation(() => {}) // React logs the caught error
    renderCanvas()

    expect((await screen.findByRole('alert')).textContent).toBe('Graph view failed: no 2d context')
  })
})

describe('toCanvasData', () => {
  it('maps domain ids to numeric canvas ids and colours by kind', () => {
    const data = toCanvasData(VIEW)
    const byGid = new Map(data.nodes.map((n) => [n.data.gid, n]))
    expect(byGid.get('c1')!.color).toBe(NODE_COLORS.merge)
    expect(byGid.get('f1')!.color).toBe(NODE_COLORS.Fact)
    const derived = data.links.find((l) => l.relationship === 'DERIVED_FROM')!
    expect(derived.source).toBe(byGid.get('f2')!.id)
    expect(derived.target).toBe(byGid.get('f1')!.id)
  })
})
