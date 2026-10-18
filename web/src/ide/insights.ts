// Plain-English layer over the relay graph. Pure functions only: no React, no network, no LLM. Everything
// is derived from GraphView (GET /graph) and tolerates missing props, because an older backend sends fewer.

import { AGENT_META, type GraphLink, type GraphNode, type GraphView } from './types'

/** How many hops the blast radius and the story's dependents follow (CALLS*1..3 in the backend). */
export const MAX_HOPS = 3

/** Static text for the "Why a graph?" card. */
export const WHY_GRAPH =
  'Git compares lines of text. git0 stores the code as a graph in FalkorDB — who calls whom and who changed what — so one query can follow the dependency chain (CALLS*1..3) and spot a collision even when the two people edited different lines or different files.'

export const LEGEND_ITEMS: { label: string; text: string; color: string }[] = [
  { label: 'File', text: 'a file in the repo', color: '#858585' },
  { label: 'Symbol', text: 'a function — the building blocks of the code', color: '#dcdcaa' },
  { label: 'Arrow', text: 'uses / depends on', color: '#6a6a6a' },
  { label: 'Change', text: 'an edit an agent made', color: '#4fc1ff' },
  { label: 'Conflict', text: 'a collision git0 stopped before it happened', color: '#f14c4c' },
  { label: 'Agent', text: "Alice's or Bob's AI agent", color: '#4fc1ff' },
  { label: 'Intent', text: 'what an agent said it is about to work on', color: '#c586c0' },
]

export interface StoryItem {
  /** Graph node id this item is about (Change, Conflict or Intent). */
  nodeId: string
  kind: 'change' | 'conflict' | 'intent'
  ts: number | null
  text: string
  /** Symbol to select when the item is clicked, if it has one. */
  symbolId: string | null
  tone: 'info' | 'deny'
}

export interface Hotspot {
  symbolId: string
  name: string
  agents: string[]
  text: string
}

export interface Reach {
  id: string
  name: string
  hops: number
}

export interface NodeCard {
  title: string
  kind: string
  lines: string[]
}

export interface GraphFilter {
  /** Only changed symbols, their direct callers and callees, plus Change, Conflict, Agent and Intent nodes. */
  onlyChanged: boolean
  showFiles: boolean
}

// ---------- indexing and small helpers ----------

interface Index {
  byId: Map<string, GraphNode>
  out: Map<string, GraphLink[]>
  inc: Map<string, GraphLink[]>
}

function index(view: GraphView): Index {
  const byId = new Map(view.nodes.map((n) => [n.id, n]))
  const out = new Map<string, GraphLink[]>()
  const inc = new Map<string, GraphLink[]>()
  for (const l of view.links) {
    if (!byId.has(l.source) || !byId.has(l.target)) continue
    const o = out.get(l.source)
    if (o) o.push(l)
    else out.set(l.source, [l])
    const i = inc.get(l.target)
    if (i) i.push(l)
    else inc.set(l.target, [l])
  }
  return { byId, out, inc }
}

function targets(ix: Index, id: string, type: string): string[] {
  return (ix.out.get(id) ?? []).filter((l) => l.type === type).map((l) => l.target)
}

function sources(ix: Index, id: string, type: string): string[] {
  return (ix.inc.get(id) ?? []).filter((l) => l.type === type).map((l) => l.source)
}

function str(node: GraphNode | undefined, key: string): string {
  const v = node?.props?.[key]
  return typeof v === 'string' ? v : ''
}

function num(node: GraphNode | undefined, key: string): number | null {
  const v = node?.props?.[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function nameOf(node: GraphNode | undefined, fallbackId: string): string {
  if (node?.name) return node.name
  return fallbackId.split('::').pop() ?? fallbackId
}

/** "Alice" / "Bob" for A / B. Falls back to the Agent node's label, then to the raw id. */
export function agentLabel(ix: Index | null, id: string): string {
  const owner = (AGENT_META as Record<string, { owner: string } | undefined>)[id]?.owner
  if (owner) return owner
  const label = str(ix?.byId.get(id), 'label')
  return label || id
}

/** The agent behind a Change / Conflict / Intent: its prop if present, else the edge from the Agent node. */
function agentOf(ix: Index, node: GraphNode, edgeType: 'MADE' | 'RAISED' | 'INTENDS'): string {
  const fromProp = str(node, 'agent')
  if (fromProp) return fromProp
  return sources(ix, node.id, edgeType)[0] ?? ''
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many
}

function hopsText(hops: number): string {
  return `${hops} ${plural(hops, 'hop', 'hops')}`
}

function trimPeriod(s: string): string {
  return s.replace(/[.\s]+$/, '')
}

function shorten(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`
}

// ---------- dependency reach ----------

/** Functions that depend on `symbolId`, following reverse CALLS up to MAX_HOPS. Nearest first. */
function dependentsIn(ix: Index, symbolId: string): Reach[] {
  const seen = new Set([symbolId])
  let frontier = [symbolId]
  const found: Reach[] = []
  for (let hop = 1; hop <= MAX_HOPS && frontier.length > 0; hop++) {
    const next: string[] = []
    for (const current of frontier) {
      for (const caller of sources(ix, current, 'CALLS')) {
        if (seen.has(caller)) continue
        seen.add(caller)
        next.push(caller)
        found.push({ id: caller, name: nameOf(ix.byId.get(caller), caller), hops: hop })
      }
    }
    frontier = next
  }
  return found
}

/** Blast radius: what could break if this symbol's contract changes. */
export function blastRadius(view: GraphView, symbolId: string): Reach[] {
  return dependentsIn(index(view), symbolId)
}

function blastText(name: string, reach: Reach[]): string {
  if (reach.length === 0) return `Nothing else calls ${name}, so changing it stays local.`
  const list = reach.map((r) => `${r.name} (${hopsText(r.hops)})`).join(', ')
  return `If ${name} changes, these could break: ${list}.`
}

// ---------- story feed ----------

const DECISION: Record<string, (peer: string) => string> = {
  adopt: (peer) => `pulled ${peer}'s change`,
  override: () => 'kept own version',
  pause: () => 'paused',
}

/** Newest first. Each Change, Conflict and Intent becomes one plain sentence. */
export function buildStory(view: GraphView): StoryItem[] {
  const ix = index(view)
  const items: StoryItem[] = []

  for (const node of view.nodes) {
    if (node.label === 'Change') {
      const agent = agentOf(ix, node, 'MADE')
      const symbolId = targets(ix, node.id, 'TOUCHED')[0] ?? null
      const symbol = symbolId ? ix.byId.get(symbolId) : undefined
      const name = symbol && symbolId ? nameOf(symbol, symbolId) : str(node, 'summary') || node.name || node.id
      const kind = str(node, 'kind')
      const verb = kind === 'added' ? 'added' : kind === 'removed' ? 'removed' : 'changed'
      const signature = kind === 'signature' ? str(symbol, 'signature') : ''
      const sig = signature ? ` (new signature: ${signature})` : ''
      const reach = symbolId ? dependentsIn(ix, symbolId) : []
      const dependsText =
        reach.length === 0
          ? 'Nothing else calls it yet.'
          : `${reach.length} ${plural(reach.length, 'function', 'functions')} ${plural(reach.length, 'depends', 'depend')} on it: ${reach
              .map((r) => `${r.name} (${hopsText(r.hops)})`)
              .join(', ')}.`
      items.push({
        nodeId: node.id,
        kind: 'change',
        ts: num(node, 'ts'),
        text: `${agentLabel(ix, agent)} ${verb} ${name}${sig}. ${dependsText}`,
        symbolId,
        tone: 'info',
      })
    } else if (node.label === 'Conflict') {
      const agent = agentOf(ix, node, 'RAISED')
      const peer = str(node, 'peer')
      const symbolId = targets(ix, node.id, 'ON')[0] ?? null
      const symbol = symbolId ? ix.byId.get(symbolId) : undefined
      const resolution = str(node, 'resolution') || 'pending'
      const decide = DECISION[resolution]
      const decision = resolution === 'pending' ? 'waiting for you' : decide ? decide(agentLabel(ix, peer)) : resolution
      const message = trimPeriod(str(node, 'message'))
      const target = symbol && symbolId ? ` to ${nameOf(symbol, symbolId)}` : ''
      const reason = message ? `: ${message}` : ''
      items.push({
        nodeId: node.id,
        kind: 'conflict',
        ts: num(node, 'ts'),
        text: `${agentLabel(ix, agent)}'s edit${target} was stopped before it reached the code${reason}. Decision: ${decision}.`,
        symbolId,
        tone: 'deny',
      })
    } else if (node.label === 'Intent') {
      const agent = agentOf(ix, node, 'INTENDS')
      const task = str(node, 'task')
      items.push({
        nodeId: node.id,
        kind: 'intent',
        ts: num(node, 'ts'),
        text: task ? `${agentLabel(ix, agent)} announced: ${shorten(task, 140)}` : `${agentLabel(ix, agent)} announced a task.`,
        symbolId: targets(ix, node.id, 'TARGETS')[0] ?? null,
        tone: 'info',
      })
    }
  }

  // Newest first; items without a timestamp sink to the bottom. Array.prototype.sort is stable, so
  // equal timestamps keep the order the graph returned.
  return items.sort((a, b) => (b.ts ?? -1) - (a.ts ?? -1))
}

/** "just now", "12s ago", "3m ago", "2h ago", "4d ago". Missing timestamps read as "earlier". */
export function relativeTime(ts: number | null, now: number): string {
  if (ts === null) return 'earlier'
  const seconds = Math.max(0, Math.floor((now - ts) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

// ---------- hotspots ----------

/** Symbols touched (by a Change or a Conflict) by both agents: where a plain-git merge would fail later. */
export function hotspots(view: GraphView): Hotspot[] {
  const ix = index(view)
  const touchedBy = new Map<string, Set<string>>()
  const conflictOn = new Set<string>()
  const add = (symbolId: string, agent: string) => {
    if (!agent) return
    const set = touchedBy.get(symbolId) ?? new Set<string>()
    set.add(agent)
    touchedBy.set(symbolId, set)
  }

  for (const node of view.nodes) {
    if (node.label === 'Change') {
      const agent = agentOf(ix, node, 'MADE')
      for (const symbolId of targets(ix, node.id, 'TOUCHED')) add(symbolId, agent)
    } else if (node.label === 'Conflict') {
      const agent = agentOf(ix, node, 'RAISED')
      for (const symbolId of targets(ix, node.id, 'ON')) {
        conflictOn.add(symbolId)
        add(symbolId, agent)
        // The peer's side of the collision is the Change it was checked against.
        for (const changeId of targets(ix, node.id, 'AGAINST')) {
          const change = ix.byId.get(changeId)
          if (change) add(symbolId, agentOf(ix, change, 'MADE'))
        }
      }
    }
  }

  const result: Hotspot[] = []
  for (const [symbolId, agentSet] of touchedBy) {
    if (agentSet.size < 2) continue
    const agents = [...agentSet].sort()
    const name = nameOf(ix.byId.get(symbolId), symbolId)
    const caught = conflictOn.has(symbolId)
      ? 'git0 caught it the moment it happened.'
      : 'git0 recorded both edits, so the collision is visible now.'
    result.push({
      symbolId,
      name,
      agents,
      text: `⚠ ${name} — ${agents.map((a) => agentLabel(ix, a)).join(' and ')} touched this. With plain git this is where the merge conflict (or a silent bug) would have shown up days later. ${caught}`,
    })
  }
  return result.sort((a, b) => a.name.localeCompare(b.name))
}

// ---------- node cards and highlighting ----------

/** Plain-English card for the sidebar when a node is clicked. Returns null for unknown ids. */
export function describeNode(view: GraphView, id: string): NodeCard | null {
  const ix = index(view)
  const node = ix.byId.get(id)
  if (!node) return null

  if (node.label === 'Symbol') {
    const name = nameOf(node, id)
    const calls = targets(ix, id, 'CALLS').map((t) => nameOf(ix.byId.get(t), t))
    const editors = sources(ix, id, 'TOUCHED')
    const editedBy = [...new Set(editors.map((c) => agentOf(ix, ix.byId.get(c)!, 'MADE')).filter(Boolean))].sort()
    const signature = str(node, 'signature')
    const lines = [
      `Lives in ${str(node, 'path') || id.split('::')[0]}.`,
      signature ? `Signature: ${signature}` : '',
      calls.length > 0 ? `Calls: ${calls.join(', ')}.` : 'Calls no other project function.',
      blastText(name, dependentsIn(ix, id)),
      editedBy.length > 0 ? `Edited by: ${editedBy.map((a) => agentLabel(ix, a)).join(' and ')}.` : 'Nobody has edited this yet.',
    ].filter((line) => line !== '')
    return { title: name, kind: 'Function', lines }
  }

  if (node.label === 'File') {
    const count = targets(ix, id, 'DEFINES').length
    return {
      title: node.name || id,
      kind: 'File',
      lines: [`A file in the repo, with ${count} ${plural(count, 'function', 'functions')}.`],
    }
  }

  if (node.label === 'Agent') {
    const made = (ix.out.get(id) ?? []).filter((l) => l.type === 'MADE').length
    const raised = (ix.out.get(id) ?? []).filter((l) => l.type === 'RAISED').length
    return {
      title: agentLabel(ix, id),
      kind: 'Agent',
      lines: [
        `${agentLabel(ix, id)}'s AI agent.`,
        `Made ${made} ${plural(made, 'change', 'changes')} and raised ${raised} ${plural(raised, 'conflict', 'conflicts')}.`,
      ],
    }
  }

  const story = buildStory(view)
  const item = story.find((s) => s.nodeId === id)
  if (node.label === 'Change') {
    return { title: 'Change', kind: 'Change', lines: [item?.text ?? 'An edit an agent made.'] }
  }
  if (node.label === 'Conflict') {
    const against = targets(ix, id, 'AGAINST')
      .map((c) => str(ix.byId.get(c), 'summary'))
      .filter((s) => s !== '')
    const lines = [item?.text ?? 'A collision git0 stopped.']
    if (against.length > 0) lines.push(`Checked against: ${against.join('; ')}.`)
    return { title: 'Conflict', kind: 'Conflict', lines }
  }
  if (node.label === 'Intent') {
    return { title: 'Intent', kind: 'Intent', lines: [item?.text ?? (str(node, 'task') || 'An announced task.')] }
  }
  return { title: node.name || id, kind: node.label, lines: [] }
}

/** Node ids to light up for a selection: the node, its blast radius, or its direct edges. */
export function highlightFor(view: GraphView, id: string): string[] {
  const ix = index(view)
  const node = ix.byId.get(id)
  if (!node) return []
  if (node.label === 'Symbol') return [id, ...dependentsIn(ix, id).map((r) => r.id)]
  if (node.label === 'Change') return [id, ...targets(ix, id, 'TOUCHED')]
  if (node.label === 'Conflict') return [id, ...targets(ix, id, 'ON'), ...targets(ix, id, 'AGAINST')]
  if (node.label === 'File') return [id, ...targets(ix, id, 'DEFINES')]
  if (node.label === 'Intent') return [id, ...targets(ix, id, 'TARGETS')]
  return [id]
}

/**
 * Selection focus for the overlay: the node, its 1-hop neighbours (any edge, either way) and its blast radius
 * (highlightFor). Deduplicated, the node first.
 */
export function focusFor(view: GraphView, id: string): string[] {
  const ix = index(view)
  if (!ix.byId.has(id)) return []
  const neighbours = [...(ix.out.get(id) ?? []).map((l) => l.target), ...(ix.inc.get(id) ?? []).map((l) => l.source)]
  return [...new Set([id, ...neighbours, ...highlightFor(view, id)])]
}

// ---------- filters ----------

/** Applies the overlay's two toggles. Pure: the input view is never mutated. */
export function filterGraph(view: GraphView, filter: GraphFilter): GraphView {
  let nodes = view.nodes
  if (filter.onlyChanged) {
    const ix = index(view)
    const changedSymbols = new Set<string>()
    for (const node of view.nodes) {
      if (node.label === 'Change') targets(ix, node.id, 'TOUCHED').forEach((t) => changedSymbols.add(t))
      if (node.label === 'Conflict') targets(ix, node.id, 'ON').forEach((t) => changedSymbols.add(t))
      if (node.label === 'Intent') targets(ix, node.id, 'TARGETS').forEach((t) => changedSymbols.add(t))
    }
    const keep = new Set(changedSymbols)
    for (const id of changedSymbols) {
      for (const callee of targets(ix, id, 'CALLS')) keep.add(callee)
      for (const caller of sources(ix, id, 'CALLS')) keep.add(caller)
    }
    nodes = view.nodes.filter(
      (n) =>
        n.label === 'Change' ||
        n.label === 'Conflict' ||
        n.label === 'Agent' ||
        n.label === 'Intent' ||
        (n.label === 'Symbol' && keep.has(n.id)),
    )
  }
  if (!filter.showFiles) nodes = nodes.filter((n) => n.label !== 'File')
  const ids = new Set(nodes.map((n) => n.id))
  const links = view.links.filter((l) => ids.has(l.source) && ids.has(l.target) && (filter.showFiles || l.type !== 'DEFINES'))
  return { nodes, links }
}
