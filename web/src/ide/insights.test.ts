import { describe, expect, it } from 'vitest'
import { blastRadius, buildStory, describeNode, filterGraph, focusFor, highlightFor, hotspots, LEGEND_ITEMS, relativeTime } from './insights'
import type { GraphView } from './types'

/** Alice changed apply_tax's signature; calculate_total calls it; checkout calls calculate_total. Bob's conflict. */
function sampleGraph(): GraphView {
  return {
    nodes: [
      { id: 'A', label: 'Agent', name: 'Alice', kind: 'agent', props: { label: 'Alice' } },
      { id: 'B', label: 'Agent', name: 'Bob', kind: 'agent', props: { label: 'Bob' } },
      { id: 'shop/pricing.py', label: 'File', name: 'shop/pricing.py', kind: 'file', props: {} },
      {
        id: 'shop/pricing.py::apply_tax',
        label: 'Symbol',
        name: 'apply_tax',
        kind: 'function',
        props: { path: 'shop/pricing.py', signature: 'apply_tax(amount, region)' },
      },
      {
        id: 'shop/cart.py::calculate_total',
        label: 'Symbol',
        name: 'calculate_total',
        kind: 'function',
        props: { path: 'shop/cart.py', signature: 'calculate_total(items)' },
      },
      { id: 'shop/checkout.py::checkout', label: 'Symbol', name: 'checkout', kind: 'function', props: { path: 'shop/checkout.py' } },
      {
        id: 'chg-a1',
        label: 'Change',
        name: 'apply_tax',
        kind: 'signature',
        props: { agent: 'A', kind: 'signature', summary: 'apply_tax takes region', path: 'shop/pricing.py', ts: 1_000_000 },
      },
      {
        id: 'chg-a2',
        label: 'Change',
        name: 'calculate_total',
        kind: 'modified',
        props: { agent: 'A', kind: 'modified', summary: 'passes region', path: 'shop/cart.py', ts: 1_005_000 },
      },
      {
        id: 'chg-b1',
        label: 'Change',
        name: 'calculate_total',
        kind: 'modified',
        props: { agent: 'B', kind: 'modified', summary: 'shipping', path: 'shop/cart.py', ts: 1_009_000 },
      },
      {
        id: 'conflict-1',
        label: 'Conflict',
        name: 'same_symbol',
        kind: 'same_symbol',
        props: {
          agent: 'B',
          peer: 'A',
          message: 'Alice already changed calculate_total in shop/cart.py.',
          ts: 1_010_000,
          resolution: 'pending',
        },
      },
      {
        id: 'intent-b',
        label: 'Intent',
        name: 'shipping',
        kind: 'intent',
        props: { agent: 'B', task: 'Add shipping', active: true, ts: 1_008_000 },
      },
    ],
    links: [
      { source: 'shop/pricing.py', target: 'shop/pricing.py::apply_tax', type: 'DEFINES' },
      { source: 'shop/cart.py::calculate_total', target: 'shop/pricing.py::apply_tax', type: 'CALLS' },
      { source: 'shop/checkout.py::checkout', target: 'shop/cart.py::calculate_total', type: 'CALLS' },
      { source: 'A', target: 'chg-a1', type: 'MADE' },
      { source: 'A', target: 'chg-a2', type: 'MADE' },
      { source: 'B', target: 'chg-b1', type: 'MADE' },
      { source: 'chg-a1', target: 'shop/pricing.py::apply_tax', type: 'TOUCHED' },
      { source: 'chg-a2', target: 'shop/cart.py::calculate_total', type: 'TOUCHED' },
      { source: 'chg-b1', target: 'shop/cart.py::calculate_total', type: 'TOUCHED' },
      { source: 'B', target: 'conflict-1', type: 'RAISED' },
      { source: 'conflict-1', target: 'shop/cart.py::calculate_total', type: 'ON' },
      { source: 'conflict-1', target: 'chg-a2', type: 'AGAINST' },
      { source: 'B', target: 'intent-b', type: 'INTENDS' },
      { source: 'intent-b', target: 'shop/cart.py::calculate_total', type: 'TARGETS' },
    ],
  }
}

describe('buildStory', () => {
  it('lists the newest item first and words a change with its dependents and hop counts', () => {
    const story = buildStory(sampleGraph())
    expect(story.map((s) => s.nodeId)).toEqual(['conflict-1', 'chg-b1', 'intent-b', 'chg-a2', 'chg-a1'])

    const apply = story.find((s) => s.nodeId === 'chg-a1')!
    expect(apply.text).toBe(
      'Alice changed apply_tax (new signature: apply_tax(amount, region)). 2 functions depend on it: calculate_total (1 hop), checkout (2 hops).',
    )
    expect(apply.symbolId).toBe('shop/pricing.py::apply_tax')
  })

  it('explains a conflict in plain words and names the decision', () => {
    const conflict = buildStory(sampleGraph()).find((s) => s.nodeId === 'conflict-1')!
    expect(conflict.text).toBe(
      "Bob's edit to calculate_total was stopped before it reached the code: Alice already changed calculate_total in shop/cart.py. Decision: waiting for you.",
    )
    expect(conflict.tone).toBe('deny')
  })

  it('turns a resolved decision into the matching phrase', () => {
    const graph = sampleGraph()
    graph.nodes.find((n) => n.id === 'conflict-1')!.props.resolution = 'adopt'
    const conflict = buildStory(graph).find((s) => s.nodeId === 'conflict-1')!
    expect(conflict.text).toContain("Decision: pulled Alice's change.")
  })

  it('announces intents and tolerates missing props from an older backend', () => {
    const graph: GraphView = {
      nodes: [
        { id: 'A', label: 'Agent', name: 'Alice', kind: 'agent', props: {} },
        { id: 'chg-x', label: 'Change', name: 'checkout', kind: 'modified', props: { agent: 'A' } },
        { id: 'intent-x', label: 'Intent', name: 'x', kind: 'intent', props: { agent: 'A', task: 'Refactor checkout' } },
      ],
      links: [],
    }
    const story = buildStory(graph)
    const intent = story.find((s) => s.nodeId === 'intent-x')!
    expect(intent.text).toBe('Alice announced: Refactor checkout')
    expect(intent.ts).toBeNull()
    const change = story.find((s) => s.nodeId === 'chg-x')!
    expect(change.text).toBe('Alice changed checkout. Nothing else calls it yet.')
    // Items without a timestamp still come back (no crash in the sort), and none claims a time.
    expect(story.every((s) => s.ts === null)).toBe(true)
  })
})

describe('hotspots', () => {
  it('finds symbols both agents touched and says whether git0 caught it', () => {
    const spots = hotspots(sampleGraph())
    expect(spots.map((s) => s.name)).toEqual(['calculate_total'])
    expect(spots[0].agents).toEqual(['A', 'B'])
    expect(spots[0].text).toContain('⚠ calculate_total — Alice and Bob touched this.')
    expect(spots[0].text).toContain('git0 caught it the moment it happened.')
  })

  it('does not flag a symbol only one agent touched', () => {
    const graph = sampleGraph()
    graph.nodes = graph.nodes.filter((n) => n.id !== 'chg-b1' && n.id !== 'conflict-1')
    graph.links = graph.links.filter((l) => l.source !== 'chg-b1' && l.target !== 'chg-b1' && l.source !== 'conflict-1' && l.target !== 'conflict-1')
    expect(hotspots(graph)).toEqual([])
  })
})

describe('blastRadius', () => {
  it('follows reverse CALLS up to three hops and names each hop', () => {
    const reach = blastRadius(sampleGraph(), 'shop/pricing.py::apply_tax')
    expect(reach).toEqual([
      { id: 'shop/cart.py::calculate_total', name: 'calculate_total', hops: 1 },
      { id: 'shop/checkout.py::checkout', name: 'checkout', hops: 2 },
    ])
  })

  it('stops after three hops', () => {
    const graph: GraphView = {
      nodes: ['a', 'b', 'c', 'd', 'e'].map((n) => ({ id: n, label: 'Symbol', name: n, kind: 'function', props: {} })),
      // e calls d calls c calls b calls a: from a, the chain is b (1), c (2), d (3), e (4 = out of reach).
      links: [
        { source: 'b', target: 'a', type: 'CALLS' },
        { source: 'c', target: 'b', type: 'CALLS' },
        { source: 'd', target: 'c', type: 'CALLS' },
        { source: 'e', target: 'd', type: 'CALLS' },
      ],
    }
    const names = blastRadius(graph, 'a').map((r) => `${r.name}:${r.hops}`)
    expect(names).toEqual(['b:1', 'c:2', 'd:3'])
  })
})

describe('describeNode and highlightFor', () => {
  it('describes a function in plain English with its blast radius', () => {
    const card = describeNode(sampleGraph(), 'shop/pricing.py::apply_tax')!
    expect(card.kind).toBe('Function')
    expect(card.lines).toContain('If apply_tax changes, these could break: calculate_total (1 hop), checkout (2 hops).')
    expect(card.lines).toContain('Edited by: Alice.')
  })

  it('returns null for an unknown node', () => {
    expect(describeNode(sampleGraph(), 'nope')).toBeNull()
  })

  it('highlights a symbol with its dependents', () => {
    expect(highlightFor(sampleGraph(), 'shop/pricing.py::apply_tax')).toEqual([
      'shop/pricing.py::apply_tax',
      'shop/cart.py::calculate_total',
      'shop/checkout.py::checkout',
    ])
  })
})

describe('filterGraph', () => {
  it('hides files unless asked and drops their DEFINES edges', () => {
    const hidden = filterGraph(sampleGraph(), { onlyChanged: false, showFiles: false })
    expect(hidden.nodes.some((n) => n.label === 'File')).toBe(false)
    expect(hidden.links.some((l) => l.type === 'DEFINES')).toBe(false)
    const shown = filterGraph(sampleGraph(), { onlyChanged: false, showFiles: true })
    expect(shown.nodes.some((n) => n.label === 'File')).toBe(true)
  })

  it('keeps changed symbols, their 1-hop neighbours and the change nodes only', () => {
    const graph = sampleGraph()
    const focused = filterGraph(graph, { onlyChanged: true, showFiles: false })
    const ids = new Set(focused.nodes.map((n) => n.id))
    // checkout is 2 hops from apply_tax, but 1 hop from calculate_total, which is changed: it stays.
    expect(ids.has('shop/checkout.py::checkout')).toBe(true)
    expect(ids.has('chg-a1')).toBe(true)
    expect(ids.has('conflict-1')).toBe(true)
    expect(ids.has('A')).toBe(true)
    // The input is not mutated.
    expect(graph.nodes.length).toBe(11)
  })
})

describe('relativeTime and legend', () => {
  it('formats relative times from milliseconds', () => {
    const now = 10_000_000
    expect(relativeTime(now - 2_000, now)).toBe('just now')
    expect(relativeTime(now - 30_000, now)).toBe('30s ago')
    expect(relativeTime(now - 5 * 60_000, now)).toBe('5m ago')
    expect(relativeTime(now - 3 * 3_600_000, now)).toBe('3h ago')
    expect(relativeTime(now - 2 * 86_400_000, now)).toBe('2d ago')
    expect(relativeTime(null, now)).toBe('earlier')
  })

  it('explains every legend entry in plain words', () => {
    const labels = LEGEND_ITEMS.map((l) => l.label)
    expect(labels).toEqual(['File', 'Symbol', 'Arrow', 'Change', 'Conflict', 'Agent', 'Intent'])
    expect(LEGEND_ITEMS.find((l) => l.label === 'Arrow')?.text).toBe('uses / depends on')
  })
})

describe('focusFor', () => {
  it('lights the node, its 1-hop neighbours and its blast radius', () => {
    const ids = focusFor(sampleGraph(), 'shop/pricing.py::apply_tax')
    // File (DEFINES) and Change (TOUCHED) are 1-hop neighbours; calculate_total and checkout are the blast radius.
    expect(ids[0]).toBe('shop/pricing.py::apply_tax')
    expect(ids).toEqual(expect.arrayContaining(['shop/pricing.py', 'chg-a1', 'shop/cart.py::calculate_total', 'shop/checkout.py::checkout']))
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('returns nothing for an unknown id', () => {
    expect(focusFor(sampleGraph(), 'nope')).toEqual([])
  })
})
