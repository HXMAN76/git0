import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Scorecard } from './Scorecard'

vi.mock('../api/client', () => ({
  api: { GET: vi.fn(() => Promise.resolve({ data: null, error: null })) },
}))

describe('Scorecard', () => {
  afterEach(cleanup)

  it('renders its heading', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <Scorecard tenant="test" />
      </QueryClientProvider>,
    )
    expect(screen.getByText('Track 02 Scorecard')).toBeDefined()
  })
})
