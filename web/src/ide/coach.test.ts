import { describe, expect, it } from 'vitest'
import { coachSignals, coachSpec, nextCoachMark } from './coach'
import { COACH_AUTO_DISMISS_MS } from './tour'
import { initialState, reducer, type IdeState } from './state'
import type { ConflictInfo, IdeEvent } from './types'

const conflict: ConflictInfo = {
  kind: 'same_symbol',
  severity: 'block',
  symbol: 'shop/cart.py::calculate_total',
  peer: 'A',
  peer_change_id: null,
  peer_summary: 'A changed calculate_total',
  path: ['shop/cart.py::calculate_total'],
  message: 'Bob and Alice both changed calculate_total.',
}

function apply(s: IdeState, events: IdeEvent[]): IdeState {
  return events.reduce((acc, event) => reducer(acc, { type: 'event', event }), s)
}

const hookEvent = (agent: 'A' | 'B'): IdeEvent => ({
  type: 'hook',
  ts: 1,
  agent,
  phase: 'PreToolUse',
  tool: 'read_file',
  mcp_tool: 'code_peer_activity',
  decision: 'allow',
  detail: '',
  ms: 3,
})

describe('coachSignals', () => {
  it('shows nothing before the scenario is started', () => {
    const s = apply(initialState(), [hookEvent('A')])
    expect(coachSignals(s, false, null)).toEqual([])
  })

  it('returns the hook mark for the first PreToolUse hook, on the agent that made it', () => {
    const s = apply(initialState(), [hookEvent('B')])
    expect(coachSignals(s, true, null)).toEqual([{ id: 'hook', agent: 'B' }])
  })

  it('adds the conflict mark for a collision, pointing at the blocked agent', () => {
    const s = apply(initialState(), [{ type: 'conflict', ts: 1, agent: 'B', conflicts: [conflict] }])
    expect(coachSignals(s, true, null).map((d) => d.id)).toEqual(['conflict'])
    expect(coachSignals(s, true, null)[0].agent).toBe('B')
  })

  it('earns the graph mark only when the graph changes after the first conflict', () => {
    const conflicted = apply(initialState(), [{ type: 'conflict', ts: 1, agent: 'B', conflicts: [conflict] }])
    const pinned = conflicted.graphVersion
    expect(coachSignals(conflicted, true, pinned).map((d) => d.id)).not.toContain('graph')
    const after = apply(conflicted, [{ type: 'graph_changed', ts: 2 }])
    expect(coachSignals(after, true, pinned).map((d) => d.id)).toContain('graph')
  })

  it('shows the ask mark only while the question is unanswered', () => {
    const asked = apply(initialState(), [
      { type: 'ask_user', ts: 1, agent: 'B', question_id: 'q1', question: 'Pick one', options: [{ id: 'adopt', label: 'Pull' }] },
    ])
    expect(coachSignals(asked, true, null).map((d) => d.id)).toContain('ask')
    const answered = apply(asked, [{ type: 'ask_resolved', ts: 2, agent: 'B', question_id: 'q1', choice: 'adopt' }])
    expect(coachSignals(answered, true, null).map((d) => d.id)).not.toContain('ask')
  })

  it('shows the merge mark only when both agents are idle after replying', () => {
    const replied = apply(initialState(), [
      { type: 'agent_message', ts: 1, agent: 'A', role: 'assistant', text: 'done' },
      { type: 'agent_message', ts: 1, agent: 'B', role: 'assistant', text: 'done' },
    ])
    expect(coachSignals(replied, true, null).map((d) => d.id)).toContain('merge')
    const thinking = apply(replied, [{ type: 'agent_status', ts: 2, agent: 'A', status: 'thinking' }])
    expect(coachSignals(thinking, true, null).map((d) => d.id)).not.toContain('merge')
    // Idle before any reply is not "after the run".
    expect(coachSignals(initialState(), true, null).map((d) => d.id)).not.toContain('merge')
  })

  it('gives every mark a title and copy', () => {
    for (const id of ['hook', 'conflict', 'ask', 'graph', 'merge'] as const) {
      const spec = coachSpec({ id, agent: 'A' })
      expect(spec.title.length).toBeGreaterThan(0)
      expect(spec.text.length).toBeGreaterThan(0)
    }
  })
})

describe('nextCoachMark', () => {
  const due = [
    { id: 'conflict' as const, agent: 'B' as const },
    { id: 'merge' as const, agent: null },
  ]

  it('picks the first due mark that has not been shown yet', () => {
    expect(nextCoachMark(due, new Set(), false)).toEqual({ id: 'conflict', agent: 'B' })
    expect(nextCoachMark(due, new Set(['conflict']), false)).toEqual({ id: 'merge', agent: null })
    expect(nextCoachMark(due, new Set(['conflict', 'merge']), false)).toBeNull()
  })

  it('shows nothing while the graph overlay is open', () => {
    expect(nextCoachMark(due, new Set(), true)).toBeNull()
  })

  it('leaves the auto-dismiss at 12 seconds', () => {
    expect(COACH_AUTO_DISMISS_MS).toBe(12_000)
  })
})
