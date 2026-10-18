import { describe, expect, it } from 'vitest'
import { captionFor, clampPanelHeight, defaultPanelHeight, normalizeMergeResult, toCanvasData } from './lib'
import type { GraphView } from './types'

describe('normalizeMergeResult', () => {
  it('reads the current shape and keeps its verdict', () => {
    const raw = {
      files: [
        {
          path: 'shop/cart.py',
          git: 'clean',
          git_hunks: 0,
          merged: 'x',
          base: 'pulled',
          semantic: [{ kind: 'call_mismatch', symbol: 'shop/pricing.py::apply_tax', message: 'boom' }],
        },
      ],
      verdict: { status: 'semantic_conflict', headline: 'h', detail: 'd' },
    }
    const result = normalizeMergeResult(raw)
    expect(result.files[0]).toEqual({
      path: 'shop/cart.py',
      git: 'clean',
      git_hunks: 0,
      merged: 'x',
      base: 'pulled',
      semantic: [{ kind: 'call_mismatch', symbol: 'shop/pricing.py::apply_tax', message: 'boom' }],
    })
    expect(result.verdict.status).toBe('semantic_conflict')
  })

  it('maps the old conflicted shape to a git conflict and derives the verdict', () => {
    const result = normalizeMergeResult({
      files: [
        { path: 'a.py', conflicted: true, merged: '<<<' },
        { path: 'b.py', conflicted: false, merged: 'ok' },
      ],
    })
    expect(result.files.map((f) => f.git)).toEqual(['conflict', 'clean'])
    expect(result.files[0].git_hunks).toBe(1)
    expect(result.files[0].base).toBe('template')
    expect(result.verdict.status).toBe('git_conflict')
  })

  it('derives a safe verdict when nothing conflicts', () => {
    const result = normalizeMergeResult({ files: [{ path: 'a.py', conflicted: false, merged: '' }] })
    expect(result.verdict.status).toBe('safe')
  })

  it('rejects a response without files', () => {
    expect(() => normalizeMergeResult({ nope: true })).toThrow(/unexpected response/)
  })

  it('ignores a verdict with an unknown status and derives one instead', () => {
    const result = normalizeMergeResult({ files: [], verdict: { status: 'maybe', headline: 'h', detail: 'd' } })
    expect(result.verdict.status).toBe('safe')
  })
})

describe('clampPanelHeight and defaultPanelHeight', () => {
  it('keeps the panel between 120px and 75% of the viewport', () => {
    expect(clampPanelHeight(50, 900)).toBe(120)
    expect(clampPanelHeight(2000, 900)).toBe(675)
    expect(clampPanelHeight(300.4, 900)).toBe(300)
  })

  it('defaults to about 38% of the viewport', () => {
    expect(defaultPanelHeight(1000)).toBe(380)
  })
})

describe('toCanvasData', () => {
  const view: GraphView = {
    nodes: [
      { id: 'A', label: 'Agent', name: 'Alice', kind: 'agent', props: {} },
      { id: 'c1', label: 'Conflict', name: 'same_symbol', kind: 'same_symbol', props: { agent: 'B' } },
      { id: 's1', label: 'Symbol', name: 'f', kind: 'function', props: {} },
    ],
    links: [
      { source: 'A', target: 'c1', type: 'RAISED' },
      { source: 'c1', target: 's1', type: 'ON' },
      { source: 'c1', target: 'missing', type: 'AGAINST' },
    ],
  }

  it('styles conflicts red and bigger, and marks new nodes for the glow', () => {
    const data = toCanvasData(view, { newIds: new Set(['c1']) })
    const conflict = data.nodes.find((n) => n.data.gid === 'c1')!
    expect(conflict.color).toBe('#f14c4c')
    expect(conflict.size).toBeGreaterThan(7)
    expect(conflict.borderColor).toBe('#c586c0')
    expect(conflict.expand).toBe(true)
    expect(data.nodes.find((n) => n.data.gid === 's1')!.expand).toBe(false)
  })

  it('drops links to nodes that are not in the view and uses plain edge words', () => {
    const data = toCanvasData(view)
    expect(data.links).toHaveLength(2)
    expect(data.links.map((l) => l.relationship)).toEqual(['raised', 'on'])
  })
})

describe('captionFor', () => {
  const node = (label: string, id: string, name: string, props: Record<string, unknown> = {}, kind = 'function') => ({
    id,
    label,
    name,
    kind,
    props,
  })

  it('captions symbols with the bare function name and files with the basename', () => {
    expect(captionFor(node('Symbol', 'shop/cart.py::calculate_total', 'calculate_total'))).toBe('calculate_total')
    expect(captionFor(node('Symbol', 'shop/cart.py::calculate_total', 'shop/cart.py::calculate_total'))).toBe('calculate_total')
    expect(captionFor(node('File', 'shop/cart.py', 'shop/cart.py', {}, 'file'))).toBe('cart.py')
  })

  it('captions agents by owner and changes by owner and kind', () => {
    expect(captionFor(node('Agent', 'A', 'Alice', {}, 'agent'))).toBe('Alice')
    expect(captionFor(node('Agent', 'B', 'Bob', {}, 'agent'))).toBe('Bob')
    expect(captionFor(node('Change', 'c1', 'apply_tax', { agent: 'A', kind: 'signature' }, 'signature'))).toBe('Alice: signature')
    expect(captionFor(node('Change', 'c2', 'calculate_total', { agent: 'B', kind: 'modified' }, 'modified'))).toBe('Bob: edit')
  })

  it('captions conflicts as blocked, with the resolution when there is one', () => {
    expect(captionFor(node('Conflict', 'x', 'same_symbol', { resolution: 'pending' }, 'same_symbol'))).toBe('⛔ blocked')
    expect(captionFor(node('Conflict', 'x', 'same_symbol', { resolution: 'override' }, 'same_symbol'))).toBe('⛔ blocked · kept own')
    expect(captionFor(node('Conflict', 'x', 'same_symbol', { resolution: 'adopt' }, 'same_symbol'))).toBe('⛔ blocked · pulled theirs')
  })

  it('captions intents as "Owner plans…"', () => {
    expect(captionFor(node('Intent', 'i1', 'intent', { agent: 'B' }, 'intent'))).toBe('Bob plans…')
  })
})

describe('toCanvasData captions, size and edge labels', () => {
  const view: GraphView = {
    nodes: [
      { id: 'A', label: 'Agent', name: 'Alice', kind: 'agent', props: {} },
      { id: 's1', label: 'Symbol', name: 'f', kind: 'function', props: {} },
      { id: 's2', label: 'Symbol', name: 'g', kind: 'function', props: {} },
    ],
    links: [
      { source: 'A', target: 's1', type: 'MADE' },
      { source: 's1', target: 's2', type: 'CALLS' },
    ],
  }

  it('puts the caption on every node and scales the radius', () => {
    const data = toCanvasData(view, { sizeScale: 2 })
    expect(data.nodes.find((n) => n.data.gid === 's1')!.data.caption).toBe('f')
    expect(data.nodes.find((n) => n.data.gid === 's1')!.size).toBe(14)
  })

  it('blanks the in-circle caption (zero-width) so only the label under the node shows', () => {
    const data = toCanvasData(view)
    expect(data.nodes.every((n) => n.data.inner === '​')).toBe(true)
    expect(data.nodes.find((n) => n.data.gid === 's1')!.data.caption).toBe('f')
  })

  it('labels only the edges of the given node, or none with null', () => {
    expect(toCanvasData(view, { labelNode: 's2' }).links.map((l) => l.relationship)).toEqual(['', 'uses'])
    expect(toCanvasData(view, { labelNode: null }).links.map((l) => l.relationship)).toEqual(['', ''])
    expect(toCanvasData(view).links.map((l) => l.relationship)).toEqual(['made', 'uses'])
  })
})
