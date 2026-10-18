// Explorer (both laptops as roots) and the two editor groups (A left, B right).

import { useEffect, useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import { AGENT_META, type AgentId } from '../types'
import { buildTree, changedLines, type TreeNode } from '../lib'
import { isModified, modifiedFiles, type EditorGroupState, type FileMap, type IdeState } from '../state'

// ---------- Explorer ----------

interface ExplorerProps {
  state: IdeState
  onOpen: (agent: AgentId, path: string) => void
}

export function Explorer({ state, onOpen }: ExplorerProps) {
  return (
    <aside className="flex w-full shrink-0 flex-col overflow-hidden border-b border-[#2b2b2b] bg-[#252526] text-[13px] text-[#cccccc] lg:w-[190px] lg:border-b-0 lg:border-r">
      <div className="flex h-[35px] shrink-0 items-center px-5 text-[11px] uppercase tracking-wide text-[#bbbbbb]">Explorer</div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-2">
        {(['A', 'B'] as AgentId[]).map((agent) => (
          <Root key={agent} state={state} agent={agent} onOpen={onOpen} />
        ))}
      </div>
    </aside>
  )
}

function Root({ state, agent, onOpen }: ExplorerProps & { agent: AgentId }) {
  const meta = AGENT_META[agent]
  const [collapsed, setCollapsed] = useState(false)
  const tree = useMemo(() => buildTree(state.files), [state.files])
  const modified = useMemo(() => new Set(modifiedFiles(state, agent)), [state, agent])
  const active = state.editors[agent].active
  return (
    <section>
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-1 bg-[#2d2d30] px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide hover:bg-[#37373d]"
        aria-expanded={!collapsed}
      >
        <span className="w-3 text-[#c5c5c5]">{collapsed ? '▸' : '▾'}</span>
        <span className="truncate">{meta.root}</span>
        <span className="ml-auto rounded-sm px-1 font-mono text-[10px] text-[#1e1e1e]" style={{ background: meta.color }}>
          Agent {agent}
        </span>
      </button>
      {!collapsed && (
        <div className="py-0.5">
          {tree.length === 0 && <p className="px-5 py-1 text-[#858585]">{state.phase === 'starting' ? 'Loading…' : 'No files'}</p>}
          {tree.map((node) => (
            <TreeRow key={node.path} node={node} depth={1} agent={agent} modified={modified} active={active} onOpen={onOpen} color={meta.color} />
          ))}
        </div>
      )}
    </section>
  )
}

interface TreeRowProps {
  node: TreeNode
  depth: number
  agent: AgentId
  modified: Set<string>
  active: string | null
  color: string
  onOpen: (agent: AgentId, path: string) => void
}

function TreeRow({ node, depth, agent, modified, active, color, onOpen }: TreeRowProps) {
  const [open, setOpen] = useState(true)
  const indent = { paddingLeft: `${depth * 12 + 8}px` }
  if (node.kind === 'folder') {
    return (
      <>
        <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1 py-[2px] pr-2 text-left hover:bg-[#2a2d2e]" style={indent}>
          <span className="w-3 text-[#c5c5c5]">{open ? '▾' : '▸'}</span>
          <span className="truncate">{node.name}</span>
        </button>
        {open &&
          node.children.map((child) => (
            <TreeRow key={child.path} node={child} depth={depth + 1} agent={agent} modified={modified} active={active} color={color} onOpen={onOpen} />
          ))}
      </>
    )
  }
  const isActive = active === node.path
  return (
    <button
      type="button"
      onClick={() => onOpen(agent, node.path)}
      className={`flex w-full items-center gap-1.5 py-[2px] pr-2 text-left hover:bg-[#2a2d2e] ${isActive ? 'bg-[#37373d]' : ''}`}
      style={indent}
      title={node.path}
    >
      <span className="w-3 text-center font-mono text-[10px] text-[#858585]">py</span>
      <span className="truncate">{node.name}</span>
      {modified.has(node.path) && <span className="ml-auto size-2 shrink-0 rounded-full" style={{ background: color }} aria-label="modified" />}
    </button>
  )
}

// ---------- Editor groups ----------

interface EditorAreaProps {
  state: IdeState
  onSelect: (agent: AgentId, path: string) => void
  onClose: (agent: AgentId, path: string) => void
}

export function EditorArea({ state, onSelect, onClose }: EditorAreaProps) {
  return (
    <div className="flex min-h-[260px] min-w-0 flex-1 flex-col divide-y divide-[#2b2b2b] bg-[#1e1e1e] lg:min-h-0 lg:flex-row lg:divide-x lg:divide-y-0">
      {(['A', 'B'] as AgentId[]).map((agent) => (
        <EditorGroup key={agent} agent={agent} state={state} onSelect={onSelect} onClose={onClose} />
      ))}
    </div>
  )
}

type MonacoEditor = Parameters<OnMount>[0]

function EditorGroup({ agent, state, onSelect, onClose }: { agent: AgentId } & EditorAreaProps) {
  const group: EditorGroupState = state.editors[agent]
  const meta = AGENT_META[agent]
  const path = group.active
  const content: FileMap = state.content[agent]
  const text = path !== null ? (content[path] ?? '') : ''
  const base = path !== null ? (state.baseline[agent][path] ?? '') : ''
  const changed = useMemo(() => (path !== null ? changedLines(base, text) : []), [base, text, path])
  const modifiedCount = modifiedFiles(state, agent).length
  const editorRef = useRef<MonacoEditor | null>(null)

  // Changed-line marks: a background tint plus a coloured gutter bar, in the agent's colour.
  useEffect(() => {
    const editor = editorRef.current
    if (!editor || changed.length === 0) return
    const collection = editor.createDecorationsCollection(
      changed.map((line) => ({
        range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 1 },
        options: {
          isWholeLine: true,
          className: `git0-changed git0-changed-${agent}`,
          linesDecorationsClassName: `git0-gutter git0-gutter-${agent}`,
        },
      })),
    )
    return () => collection.clear()
  }, [changed, agent, path, text])

  // Auto-reveal: every file_changed bumps revealSeq, so scroll to the first changed line.
  useEffect(() => {
    const editor = editorRef.current
    if (!editor || group.revealSeq === 0 || changed.length === 0) return
    // Only the sequence number triggers the scroll, not every text update.
    editor.revealLineInCenter(changed[0])
  }, [group.revealSeq])

  const onMount: OnMount = (editor) => {
    editorRef.current = editor
  }

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label={`${meta.root} editor`}>
      <div className="flex h-[30px] shrink-0 items-center gap-2 bg-[#252526] px-2 text-[12px]">
        <span className="rounded-sm px-1 font-mono text-[10px] text-[#1e1e1e]" style={{ background: meta.color }}>
          {agent}
        </span>
        <span className="truncate text-[#9d9d9d]">{meta.owner}&apos;s workspace</span>
        <span className="ml-auto whitespace-nowrap text-[#9d9d9d]">{modifiedCount} modified</span>
      </div>
      <div role="tablist" className="flex h-[30px] shrink-0 overflow-x-auto bg-[#2d2d2d]">
        {group.tabs.length === 0 && <span className="px-3 py-1.5 text-[12px] text-[#858585]">No file open</span>}
        {group.tabs.map((tab) => {
          const isActive = tab === path
          const dirty = isModified(state, agent, tab)
          return (
            <div
              key={tab}
              role="tab"
              aria-selected={isActive}
              tabIndex={0}
              onClick={() => onSelect(agent, tab)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') onSelect(agent, tab)
              }}
              className={`group flex cursor-pointer items-center gap-2 border-r border-[#252526] px-3 text-[12px] whitespace-nowrap ${
                isActive ? 'border-t-2 border-t-[#007acc] bg-[#1e1e1e] text-white' : 'border-t-2 border-t-transparent bg-[#2d2d2d] text-[#969696]'
              }`}
              title={tab}
            >
              <span>{tab.split('/').pop()}</span>
              {dirty && <span className="size-1.5 rounded-full" style={{ background: meta.color }} aria-label="modified" />}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onClose(agent, tab)
                }}
                className="rounded-sm px-0.5 text-[#cccccc] opacity-60 hover:bg-[#444] hover:opacity-100"
                aria-label={`Close ${tab}`}
              >
                ×
              </button>
            </div>
          )
        })}
      </div>
      {path !== null && (
        <div className="flex h-[20px] shrink-0 items-center gap-2 bg-[#1e1e1e] px-3 text-[11px] text-[#9d9d9d]">
          <span className="truncate">{path}</span>
          <span className="ml-auto whitespace-nowrap">{changed.length > 0 ? `${changed.length} line${changed.length === 1 ? '' : 's'} changed vs template` : 'matches template'}</span>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        {path === null ? (
          <div className="absolute inset-0 flex items-center justify-center text-[13px] text-[#6a6a6a]">Open a file from the explorer</div>
        ) : (
          <div className="absolute inset-0">
            <Editor
              path={`${agent}:${path}`}
              language="python"
              theme="vs-dark"
              value={text}
              height="100%"
              onMount={onMount}
              loading={<div className="p-3 text-[12px] text-[#858585]">Loading editor…</div>}
              options={{
                readOnly: true,
                domReadOnly: true,
                minimap: { enabled: false },
                fontFamily: "'Cascadia Code', Consolas, monospace",
                fontSize: 13,
                scrollBeyondLastLine: false,
                renderLineHighlight: 'none',
                lineNumbersMinChars: 3,
                glyphMargin: false,
                folding: false,
                automaticLayout: true,
                scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
              }}
            />
          </div>
        )}
      </div>
    </section>
  )
}
