// Pure helpers for the IDE: changed-line marks, explorer tree, and graph data for <falkordb-canvas>.

import type { Data } from '@falkordb/canvas'
import type { GraphView } from './types'

/**
 * 1-based line numbers in `current` that are not part of the longest common subsequence with `base`.
 * That is the usual "what did this agent add or change" marking. Files in this demo are short, so the
 * O(n*m) table is fine; past a size cap we fall back to "lines whose text never occurs in base".
 */
export function changedLines(base: string, current: string): number[] {
  const a = base.split('\n')
  const b = current.split('\n')
  if (base === current) return []
  if (a.length * b.length > 4_000_000) {
    const seen = new Set(a)
    return b.flatMap((line, i) => (seen.has(line) ? [] : [i + 1]))
  }
  const n = a.length
  const m = b.length
  // lcs[i][j] = LCS length of a[i..] and b[j..]; computed backwards so we can walk forwards.
  const width = m + 1
  const lcs = new Uint32Array((n + 1) * width)
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i * width + j] = a[i] === b[j] ? lcs[(i + 1) * width + j + 1] + 1 : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1])
    }
  }
  const changed: number[] = []
  let i = 0
  let j = 0
  while (j < m) {
    if (i < n && a[i] === b[j]) {
      i++
      j++
    } else if (i < n && lcs[(i + 1) * width + j] >= lcs[i * width + j + 1]) {
      i++ // a line only in base: removed, nothing to mark in current
    } else {
      changed.push(j + 1) // a line only in current
      j++
    }
  }
  return changed
}

export interface TreeFolder {
  kind: 'folder'
  name: string
  path: string
  children: TreeNode[]
}

export interface TreeFile {
  kind: 'file'
  name: string
  path: string
}

export type TreeNode = TreeFolder | TreeFile

/** Builds a folder tree from repo-relative paths. Folders first, then files, both alphabetical. */
export function buildTree(paths: string[]): TreeNode[] {
  const root: TreeFolder = { kind: 'folder', name: '', path: '', children: [] }
  for (const path of [...paths].sort()) {
    const parts = path.split('/')
    let folder = root
    parts.slice(0, -1).forEach((name, idx) => {
      const folderPath = parts.slice(0, idx + 1).join('/')
      let next = folder.children.find((c): c is TreeFolder => c.kind === 'folder' && c.name === name)
      if (!next) {
        next = { kind: 'folder', name, path: folderPath, children: [] }
        folder.children.push(next)
      }
      folder = next
    })
    folder.children.push({ kind: 'file', name: parts[parts.length - 1], path })
  }
  const sortNodes = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .map((n) => (n.kind === 'folder' ? { ...n, children: sortNodes(n.children) } : n))
      .sort((x, y) => (x.kind === y.kind ? x.name.localeCompare(y.name) : x.kind === 'folder' ? -1 : 1))
  return sortNodes(root.children)
}

/** Node colours for the relay graph, keyed by label. */
export const GRAPH_COLORS: Record<string, string> = {
  File: '#569cd6',
  Symbol: '#dcdcaa',
  Change: '#f48771',
  Agent: '#4ec9b0',
  Intent: '#c586c0',
}
export const GRAPH_LEGEND = ['File', 'Symbol', 'Change', 'Agent', 'Intent'] as const

/**
 * Converts the API graph into <falkordb-canvas> data. The canvas wants numeric ids, so the domain id
 * (symbol id, path, change id, ...) travels in data.gid, which is what highlighting and clicks use.
 */
export function toCanvasData(view: GraphView): Data {
  const num = new Map(view.nodes.map((n, i) => [n.id, i + 1]))
  return {
    nodes: view.nodes.map((n) => ({
      id: num.get(n.id)!,
      labels: [n.label],
      color: GRAPH_COLORS[n.label] ?? '#9cdcfe',
      visible: true,
      data: { ...n.props, name: n.name, gid: n.id, kind: n.kind },
    })),
    links: view.links
      .filter((l) => num.has(l.source) && num.has(l.target))
      .map((l, i) => ({
        id: i + 1,
        relationship: l.type,
        color: '#6a6a6a',
        source: num.get(l.source)!,
        target: num.get(l.target)!,
        visible: true,
        data: {},
      })),
  }
}
