import { describe, expect, it } from 'vitest'
import { buildDag, type LogCommit } from './commitDag'

const c = (id: string, seq: number, parents?: string[], kind = 'commit'): LogCommit => ({
  id,
  seq,
  msg: id,
  kind,
  ts: seq,
  added: 1,
  removed: 0,
  parents,
})

describe('buildDag with parents', () => {
  const root = c('root', 0, [])
  const kickoff = c('kickoff', 1, ['root'], 'seed')
  const plan = c('plan', 2, ['kickoff'])
  const sched = c('sched', 2, ['kickoff'])
  const m1 = c('m1', 3, ['kickoff', 'sched'], 'merge')
  const m2 = c('m2', 4, ['m1', 'plan'], 'merge')

  it('draws a merge with an edge from each parent', () => {
    // Judge flow: Scheduler then Planner merged into main. Logs come newest first, like the API.
    const { nodes, edges } = buildDag({
      main: [m2, m1, plan, sched, kickoff, root],
      planner: [plan, kickoff, root],
      scheduler: [sched, kickoff, root],
    })
    expect(edges.filter((e) => e.target === 'm1').map((e) => e.source)).toEqual(['kickoff', 'sched'])
    expect(edges.filter((e) => e.target === 'm2').map((e) => e.source)).toEqual(['m1', 'plan'])
    // Linear order would have drawn plan->sched; with parents the two agents are siblings.
    expect(edges.map((e) => e.id)).not.toContain('plan->sched')
    expect(nodes.every((n) => n.branch === 'main')).toBe(true) // merged work is team memory
  })

  it('forks agent branches off team history before any merge', () => {
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

  it('drops edges to parents cut off by the log limit', () => {
    expect(buildDag({ main: [kickoff] }).edges).toEqual([])
  })
})

describe('buildDag linear fallback (log without parents)', () => {
  const root = c('root', 0)
  const kickoff = c('kickoff', 1, undefined, 'seed')
  const sched = c('sched', 2)
  const merge = c('merge', 3, undefined, 'merge')

  it('links consecutive commits per branch and counts merged work as team memory', () => {
    const { nodes, edges } = buildDag({ main: [merge, sched, kickoff, root], scheduler: [sched, kickoff, root] })
    expect(nodes.find((n) => n.id === 'sched')!.branch).toBe('main')
    expect(edges.map((e) => e.id)).toEqual(['root->kickoff', 'kickoff->sched', 'sched->merge'])
  })

  it('handles branches with no history yet', () => {
    expect(buildDag({ main: [root], notes: [] }).edges).toEqual([])
  })
})
