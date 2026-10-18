// Coach marks: the narrator that points at the moments that matter during a live run. Which marks are due is
// derived from the reducer state (pure, unit-tested); the hook only decides what is shown and remembers it.

import { useEffect, useRef } from 'react'
import type { IdeState } from './state'
import type { AgentId } from './types'
import { showCoachMark, stopTour, type CoachMarkSpec } from './tour'

export type CoachId = 'hook' | 'conflict' | 'ask' | 'graph' | 'merge'

/** One due coach mark. `agent` picks the panel the mark points into (null = not agent-specific). */
export interface CoachSignal {
  id: CoachId
  agent: AgentId | null
}

const AGENTS: AgentId[] = ['A', 'B']

function firstAgentWith(state: IdeState, match: (item: IdeState['agents']['A']['items'][number]) => boolean): AgentId | null {
  for (const agent of AGENTS) {
    if (state.agents[agent].items.some(match)) return agent
  }
  return null
}

/**
 * Coach marks the state justifies right now, in the order they should appear. Nothing is due until the
 * scenario has been started (`armed`). `conflictGraphVersion` is the graph version when the first conflict
 * was seen, so "the first graph_changed after a conflict" is a version comparison.
 */
export function coachSignals(state: IdeState, armed: boolean, conflictGraphVersion: number | null): CoachSignal[] {
  if (!armed) return []
  const due: CoachSignal[] = []

  const hookAgent = firstAgentWith(state, (item) => item.kind === 'hook' && item.phase === 'PreToolUse')
  if (hookAgent) due.push({ id: 'hook', agent: hookAgent })

  if (state.conflicts.length > 0) due.push({ id: 'conflict', agent: state.conflicts[0].agent })

  const askAgent = firstAgentWith(state, (item) => item.kind === 'ask' && item.resolved === null)
  if (askAgent) due.push({ id: 'ask', agent: askAgent })

  if (conflictGraphVersion !== null && state.graphVersion > conflictGraphVersion) due.push({ id: 'graph', agent: null })

  // "Both agents idle after the run": each has answered at least once, so the idle state before the first
  // reply does not count.
  const bothDone = AGENTS.every(
    (agent) =>
      state.agents[agent].status === 'idle' && state.agents[agent].items.some((item) => item.kind === 'message' && item.role === 'assistant'),
  )
  if (bothDone) due.push({ id: 'merge', agent: null })

  return due
}

/** The copy and targets for one mark. Targets are data-tour / data-coach hooks in the components. */
export function coachSpec(signal: CoachSignal): CoachMarkSpec {
  const panel = (agent: AgentId | null, name: string) => (agent ? [`section[aria-label="Agent ${agent} chat"] [${name}]`] : [])
  switch (signal.id) {
    case 'hook':
      return {
        title: 'The hook',
        text: "That's the hook firing: the agent asked git0 before touching the file.",
        selectors: panel(signal.agent, 'data-coach="hook"'),
        side: 'left',
      }
    case 'conflict':
      return {
        title: 'Collision caught',
        text: "Collision caught BEFORE the code was written. Bob's change touches calculate_total, which Alice just changed. Plain git would only notice at merge time, or not at all.",
        selectors: panel(signal.agent, 'data-coach="conflict"'),
        side: 'left',
      }
    case 'ask':
      return {
        title: 'Your call',
        text: "Your call. 'Pull Alice's change' = rebase on her work (safest). 'Keep mine' = what usually happens today. 'Stop' = wait for Alice.",
        selectors: panel(signal.agent, 'data-coach="ask"'),
        side: 'left',
      }
    case 'graph':
      return {
        title: 'The graph',
        text: 'The collision is now a node in the graph. Open the graph to see who changed what and what depends on it.',
        selectors: ['[data-tour="open-graph"]', '[data-tour="open-graph-activity"]', '[data-tour="tab-graph"]'],
        side: 'top',
      }
    case 'merge':
      return {
        title: 'Merge check',
        text: 'Now run Merge check: see what git would say vs git0.',
        selectors: ['[data-tour="tab-merge"]'],
        side: 'top',
      }
  }
}

/**
 * The mark to show now, or null. The first due mark that has not been shown yet in this session wins, and
 * nothing is shown while `blocked` (the full-screen overlay is open). A mark skipped while blocked is not
 * remembered, so it is shown after the overlay closes if the state still justifies it.
 */
export function nextCoachMark(due: CoachSignal[], shown: ReadonlySet<CoachId>, blocked: boolean): CoachSignal | null {
  if (blocked) return null
  return due.find((signal) => !shown.has(signal.id)) ?? null
}

/**
 * Shows each coach mark at most once per backend session, one at a time (a new mark replaces the one on
 * screen). Turning the narrator off hides the current mark and stops new ones. Opening the overlay hides
 * the current mark and holds back new ones until it closes.
 */
export function useCoachMarks(state: IdeState, armed: boolean, narrator: boolean, blocked = false) {
  const memory = useRef<{ sid: string | null; shown: Set<CoachId>; conflictVersion: number | null }>({
    sid: null,
    shown: new Set(),
    conflictVersion: null,
  })

  useEffect(() => {
    const m = memory.current
    if (m.sid !== state.sessionId) {
      memory.current = { sid: state.sessionId, shown: new Set(), conflictVersion: null }
    }
    const mem = memory.current
    // The first conflict pins the graph version; only a later graph_changed earns the graph mark.
    if (state.conflicts.length === 0) mem.conflictVersion = null
    else if (mem.conflictVersion === null) mem.conflictVersion = state.graphVersion

    if (!narrator) return
    const next = nextCoachMark(coachSignals(state, armed, mem.conflictVersion), mem.shown, blocked)
    if (!next) return
    mem.shown.add(next.id)
    showCoachMark(coachSpec(next))
  }, [state, armed, narrator, blocked])

  // Turning the narrator off, or opening the overlay, removes the mark that is on screen.
  useEffect(() => {
    if (!narrator || blocked) stopTour()
  }, [narrator, blocked])
}
