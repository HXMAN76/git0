import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Scorecard } from './Scorecard'

describe('Scorecard', () => {
  afterEach(cleanup)

  it('renders its heading', () => {
    render(<Scorecard />)
    expect(screen.getByRole('heading', { name: 'Scorecard' })).toBeDefined()
  })
})
