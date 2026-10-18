// Pure helpers for the IDE: changed-line marks, explorer tree, and graph data for <falkordb-canvas>.

import type { Data } from '@falkordb/canvas'
import { AGENT_META, type GraphView, type GraphNode, type MergeFile, type MergeResult, type MergeVerdict, type SemanticFinding } from './types'

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

/** Node colours for the relay graph, keyed by label. Change and Intent take their agent's colour (see nodeStyle). */
export const GRAPH_COLORS: Record<string, string> = {
  File: '#858585',
  Symbol: '#dcdcaa',
  Change: '#f48771',
  Agent: '#4ec9b0',
  Intent: '#c586c0',
  Conflict: '#f14c4c',
}
export const GRAPH_LEGEND = ['File', 'Symbol', 'Change', 'Conflict', 'Agent', 'Intent'] as const

/** Plain-word edge labels: the canvas draws these, so they say what the arrow means. */
const LINK_LABEL: Record<string, string> = {
  CALLS: 'uses',
  DEFINES: 'defines',
  MADE: 'made',
  TOUCHED: 'edited',
  INTENDS: 'plans',
  TARGETS: 'targets',
  ACKED: 'acknowledged',
  RAISED: 'raised',
  ON: 'on',
  AGAINST: 'against',
}
const CONFLICT_LINK = '#f14c4c'

function agentColor(agent: unknown): string | undefined {
  return agent === 'A' || agent === 'B' ? AGENT_META[agent].color : undefined
}

/** "Alice" / "Bob" for A / B, the raw string for anything else, "Agent" when unknown. */
function agentName(agent: unknown): string {
  if (agent === 'A' || agent === 'B') return AGENT_META[agent].owner
  return typeof agent === 'string' && agent !== '' ? agent : 'Agent'
}

/** Colour, size and border per node. Conflicts are red and bigger, tinted with the agent that raised them. */
export function nodeStyle(n: GraphNode): { color: string; size: number; borderColor?: string } {
  switch (n.label) {
    case 'Agent':
      return { color: agentColor(n.id) ?? GRAPH_COLORS.Agent, size: 12 }
    case 'Change':
      return { color: agentColor(n.props.agent) ?? GRAPH_COLORS.Change, size: 5 }
    case 'Intent':
      return { color: agentColor(n.props.agent) ?? GRAPH_COLORS.Intent, size: 5 }
    case 'Conflict':
      return { color: GRAPH_COLORS.Conflict, size: 13, borderColor: agentColor(n.props.agent) ?? '#ffffff' }
    case 'Symbol':
      return { color: GRAPH_COLORS.Symbol, size: 7 }
    case 'File':
      return { color: GRAPH_COLORS.File, size: 5 }
    default:
      return { color: '#9cdcfe', size: 5 }
  }
}

const CONFLICT_RESOLUTION: Record<string, string> = {
  override: ' · kept own',
  adopt: ' · pulled theirs',
  pause: ' · paused',
}

/**
 * The short, human caption drawn on a node. Symbol = function name, File = basename, Agent = owner,
 * Change = "Alice: signature" / "Bob: edit", Conflict = "⛔ blocked · kept own", Intent = "Bob plans…".
 */
export function captionFor(n: GraphNode): string {
  const lastPart = (s: string) => s.split('::').pop() ?? s
  switch (n.label) {
    case 'Symbol':
      return lastPart(n.name || n.id)
    case 'File':
      return (n.name || n.id).split('/').pop() ?? n.id
    case 'Agent':
      return n.id === 'A' || n.id === 'B' ? AGENT_META[n.id].owner : n.name || n.id
    case 'Change': {
      const kind = n.props.kind
      const what = kind === 'signature' ? 'signature' : kind === 'added' ? 'add' : kind === 'removed' ? 'remove' : 'edit'
      return `${agentName(n.props.agent)}: ${what}`
    }
    case 'Conflict': {
      const resolution = typeof n.props.resolution === 'string' ? n.props.resolution : ''
      return `⛔ blocked${CONFLICT_RESOLUTION[resolution] ?? ''}`
    }
    case 'Intent':
      return `${agentName(n.props.agent)} plans…`
    default:
      return n.name || n.id
  }
}

export interface CanvasDataOptions {
  /** Nodes that just appeared: drawn with the glow. */
  newIds?: ReadonlySet<string>
  /** Multiplies every node radius (the full-screen overlay uses 2). Default 1. */
  sizeScale?: number
  /**
   * Which edges carry their plain-word label. `undefined` = all of them (the small panel). `null` = none.
   * A domain id = only the edges touching that node (the overlay labels just the selected node's edges).
   */
  labelNode?: string | null
}

/**
 * Converts the API graph into <falkordb-canvas> data. The canvas wants numeric ids, so the domain id
 * (symbol id, path, change id, ...) travels in data.gid, which is what highlighting and clicks use.
 * `newIds` nodes get expand=true, which the canvas draws as a glow: that is how new nodes "flash".
 * Each node carries its caption in data.caption (see captionFor); GraphCanvas reads that key.
 */
export function toCanvasData(view: GraphView, opts: CanvasDataOptions = {}): Data {
  const num = new Map(view.nodes.map((n, i) => [n.id, i + 1]))
  const scale = opts.sizeScale ?? 1
  return {
    nodes: view.nodes.map((n) => {
      const style = nodeStyle(n)
      return {
        id: num.get(n.id)!,
        labels: [n.label],
        color: style.color,
        borderColor: style.borderColor,
        size: style.size * scale,
        expand: opts.newIds?.has(n.id) ?? false,
        visible: true,
        // `inner` is what the canvas draws inside the circle. It is a zero-width space, not '': an empty
        // caption falls back to the numeric node id. GraphCanvas draws the real label under the node instead.
        data: { ...n.props, name: n.name, gid: n.id, kind: n.kind, caption: captionFor(n), inner: '​' },
      }
    }),
    links: view.links
      .filter((l) => num.has(l.source) && num.has(l.target))
      .map((l, i) => {
        // The canvas has no per-link switch for labels, so an unlabelled edge gets an empty relationship.
        const labelled = opts.labelNode === undefined || (opts.labelNode !== null && (l.source === opts.labelNode || l.target === opts.labelNode))
        return {
          id: i + 1,
          relationship: labelled ? (LINK_LABEL[l.type] ?? l.type) : '',
          color: l.type === 'RAISED' || l.type === 'ON' || l.type === 'AGAINST' ? CONFLICT_LINK : '#6a6a6a',
          source: num.get(l.source)!,
          target: num.get(l.target)!,
          visible: true,
          data: {},
        }
      }),
  }
}

// ---------- merge check ----------

const VERDICT_STATUSES = ['safe', 'git_conflict', 'semantic_conflict'] as const

function isFinding(x: unknown): x is SemanticFinding {
  if (!x || typeof x !== 'object') return false
  const f = x as Record<string, unknown>
  return typeof f.kind === 'string' && typeof f.symbol === 'string' && typeof f.message === 'string'
}

/** Verdict from the per-file results, used when an older backend does not send one. */
export function deriveVerdict(files: MergeFile[]): MergeVerdict {
  const semantic = files.flatMap((f) => f.semantic)
  if (semantic.length > 0) {
    return {
      status: 'semantic_conflict',
      headline: 'Plain git would merge this, but git0 found a semantic conflict',
      detail: semantic.map((s) => s.message).join(' '),
    }
  }
  const gitConflicts = files.filter((f) => f.git === 'conflict')
  if (gitConflicts.length > 0) {
    return {
      status: 'git_conflict',
      headline: `Plain git conflicts in ${gitConflicts.length} file${gitConflicts.length === 1 ? '' : 's'}`,
      detail: gitConflicts.map((f) => f.path).join(', '),
    }
  }
  return { status: 'safe', headline: 'Safe to merge', detail: 'No git conflicts and no semantic conflicts.' }
}

/**
 * Accepts both the current shape ({git, git_hunks, semantic, base, verdict}) and the old one
 * ({conflicted, merged}, no verdict). Old `conflicted` maps to git "conflict", and the verdict is derived.
 */
export function normalizeMergeResult(raw: unknown): MergeResult {
  if (!raw || typeof raw !== 'object' || !Array.isArray((raw as { files?: unknown }).files)) {
    throw new Error('Merge check returned an unexpected response')
  }
  const rawFiles = (raw as { files: unknown[] }).files
  const files: MergeFile[] = rawFiles.map((item, i) => {
    const f = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>
    const git: MergeFile['git'] = f.git === 'clean' || f.git === 'conflict' ? f.git : f.conflicted === true ? 'conflict' : 'clean'
    return {
      path: typeof f.path === 'string' ? f.path : `(file ${i + 1})`,
      git,
      git_hunks: typeof f.git_hunks === 'number' ? f.git_hunks : git === 'conflict' ? 1 : 0,
      merged: typeof f.merged === 'string' ? f.merged : '',
      base: f.base === 'pulled' ? 'pulled' : 'template',
      semantic: Array.isArray(f.semantic) ? f.semantic.filter(isFinding) : [],
    }
  })
  const v = (raw as { verdict?: unknown }).verdict as Record<string, unknown> | undefined
  const hasVerdict =
    !!v &&
    typeof v === 'object' &&
    VERDICT_STATUSES.includes(v.status as (typeof VERDICT_STATUSES)[number]) &&
    typeof v.headline === 'string' &&
    typeof v.detail === 'string'
  const verdict: MergeVerdict = hasVerdict
    ? { status: v!.status as MergeVerdict['status'], headline: v!.headline as string, detail: v!.detail as string }
    : deriveVerdict(files)
  return { files, verdict }
}

// ---------- panel height ----------

export const PANEL_MIN = 120

/** The bottom panel is at least 120px and at most 75% of the viewport. */
export function clampPanelHeight(height: number, viewportHeight: number): number {
  const max = Math.floor(viewportHeight * 0.75)
  return Math.max(PANEL_MIN, Math.min(max, Math.round(height)))
}

/** Default: about 38% of the viewport, clamped like any other height. */
export function defaultPanelHeight(viewportHeight: number): number {
  return clampPanelHeight(viewportHeight * 0.38, viewportHeight)
}
