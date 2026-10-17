import { describe, expect, it } from 'vitest'
import { buildDag } from './commitDag'
import type { Commit } from './branches'

const c = (id: string, seq: number, kind = 'commit'): Commit => ({ id, seq, msg: id, kind, ts: seq, added: 1, removed: 0 })
const root = c('root', 0)
const kickoff = c('kickoff', 1, 'seed')
const plan = c('plan', 2)
const sched = c('sched', 2)
const merge = c('merge', 3, 'merge')

describe('buildDag', () => {
  it('dedupes shared commits and forks agent branches off team history', () => {
    // Logs come newest first, like the API.
    const { nodes, edges } = buildDag({
      main: [kickoff, root],
      planner: [plan, kickoff, root],
      scheduler: [sched, kickoff, root],
    })
    expect(nodes.map((n) => [n.id, n.branch])).toEqual([
      ['root', 'main'],
      ['kickoff', 'main'],
      ['plan', 'planner'],
      ['sched', 'scheduler'],
    ])
    expect(edges.map((e) => e.id)).toEqual(['root->kickoff', 'kickoff->plan', 'kickoff->sched'])
  })

  it('counts merged agent work as team memory', () => {
    const { nodes, edges } = buildDag({ main: [merge, sched, kickoff, root], scheduler: [sched, kickoff, root] })
    expect(nodes.find((n) => n.id === 'sched')!.branch).toBe('main')
    expect(edges.map((e) => e.id)).toContain('sched->merge')
  })

  it('handles branches with no history yet', () => {
    expect(buildDag({ main: [root], notes: [] }).edges).toEqual([])
  })
})
