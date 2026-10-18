// Window chrome: title bar, activity bar, status bar, banner, and the full-screen overlays.

import { useEffect, useState, type ReactNode } from 'react'
import type { AgentId, AgentInfo } from '../types'
import type { IdeState, Phase } from '../state'

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

interface TitleBarProps {
  startedAt: number
  phase: Phase
  canAct: boolean
  onRunScenario: () => void
  onTakeTour: () => void
  onEnd: () => void
}

export function TitleBar({ startedAt, phase, canAct, onRunScenario, onTakeTour, onEnd }: TitleBarProps) {
  const now = useNow(1000)
  return (
    <header className="flex h-[30px] shrink-0 items-center gap-3 bg-[#3c3c3c] px-3 text-[13px] text-[#cccccc] select-none">
      <span className="font-semibold">git0 relay</span>
      <span className="text-[#9d9d9d]">- shop (2 clones)</span>
      <div className="ml-auto flex items-center gap-2">
        <span className="font-mono text-[12px] text-[#9d9d9d]" aria-label="session time">
          {phase === 'ended' ? 'ended' : formatElapsed(now - startedAt)}
        </span>
        <button
          type="button"
          onClick={onTakeTour}
          className="rounded-sm px-2 py-[3px] text-[12px] text-[#cccccc] hover:bg-[#4a4a4a]"
          title="Replay the guided tour of this demo"
        >
          Take the tour
        </button>
        <button
          type="button"
          onClick={onRunScenario}
          disabled={!canAct}
          data-tour="run-scenario"
          className="rounded-sm bg-[#1f8a4c] px-3 py-[3px] text-[12px] font-semibold text-white hover:bg-[#25a35b] disabled:cursor-not-allowed disabled:opacity-40"
          title="Send Regional tax to Agent A and Free shipping to Agent B at the same time"
        >
          ▶ Run scenario
        </button>
        <button
          type="button"
          onClick={onEnd}
          disabled={!canAct}
          className="rounded-sm border border-[#6b6b6b] px-3 py-[3px] text-[12px] hover:bg-[#4a4a4a] disabled:cursor-not-allowed disabled:opacity-40"
        >
          End session
        </button>
      </div>
    </header>
  )
}

export function ActivityBar({ onOpenGraph }: { onOpenGraph: () => void }) {
  // Explorer and Run are decorative: the explorer is the only view that has a sidebar. Graph opens the overlay.
  const icons: ReactNode[] = [
    <svg key="files" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M7 3h7l5 5v13H7z" />
      <path d="M14 3v5h5" />
    </svg>,
    <svg key="git" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6" cy="5" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="18" cy="8" r="2" />
      <path d="M6 7v10M18 10c0 4-6 3-12 7" />
    </svg>,
    <svg key="run" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 5v14l11-7z" />
    </svg>,
  ]
  const graphIcon = (
    <svg key="graph" viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <path d="M8 7.5l3 8.5M16 7.5l-3 8.5M8.5 6h7" />
    </svg>
  )
  return (
    <nav className="hidden w-12 shrink-0 flex-col items-center gap-1 bg-[#333333] py-1 text-[#858585] lg:flex" aria-label="activity bar">
      {icons.map((icon, i) => (
        <span
          key={i}
          className={`flex h-12 w-12 items-center justify-center border-l-2 ${i === 0 ? 'border-[#ffffff] text-[#ffffff]' : 'border-transparent'}`}
        >
          {icon}
        </span>
      ))}
      <button
        type="button"
        onClick={onOpenGraph}
        data-tour="open-graph-activity"
        className="mt-auto flex h-12 w-12 items-center justify-center border-l-2 border-transparent hover:text-white"
        aria-label="Open graph"
        title="Open graph (full screen)"
      >
        {graphIcon}
      </button>
    </nav>
  )
}

interface StatusBarProps {
  state: IdeState
  narrator: boolean
  onToggleNarrator: () => void
}

export function StatusBar({ state, narrator, onToggleNarrator }: StatusBarProps) {
  const info = state.agentInfo
  const connected = state.sseOpen && state.phase === 'live'
  const dot = connected ? '#89d185' : state.phase === 'ended' ? '#9d9d9d' : '#f48771'
  const label = connected ? 'connected' : state.phase === 'ended' ? 'session ended' : state.phase === 'busy' ? 'busy' : 'connecting'
  return (
    <footer className="flex h-[22px] shrink-0 items-center gap-4 bg-[#007acc] px-3 text-[12px] text-white select-none">
      <span>
        FalkorDB <span style={{ color: dot }}>●</span> {label}
      </span>
      <span className="font-mono opacity-90">session {state.sessionId ? state.sessionId.slice(0, 12) : '-'}</span>
      {(['A', 'B'] as AgentId[]).map((agent) => {
        const u = state.agents[agent].usage
        return (
          <span key={agent} className="font-mono opacity-90">
            {agent} tokens {u.input.toLocaleString()} in / {u.output.toLocaleString()} out
          </span>
        )
      })}
      <span className="ml-auto font-mono opacity-90">model {modelName(info)}</span>
      <button
        type="button"
        onClick={onToggleNarrator}
        aria-pressed={narrator}
        title="Coach marks point at the key moments of a live run"
        className="rounded-sm px-1.5 hover:bg-[#1a8ad4]"
      >
        Narrator: {narrator ? 'on' : 'off'}
      </button>
    </footer>
  )
}

function modelName(info: Record<AgentId, AgentInfo> | null): string {
  if (!info) return '-'
  const models = Array.from(new Set([info.A.model, info.B.model]))
  return models.join(', ')
}

export function Banner({ text, onDismiss }: { text: string; onDismiss: () => void }) {
  return (
    <div role="alert" className="flex shrink-0 items-center gap-3 bg-[#5a1d1d] px-3 py-1.5 text-[12px] text-[#ffd7d7]">
      <span className="flex-1">{text}</span>
      <button type="button" onClick={onDismiss} className="rounded-sm px-2 hover:bg-[#7a2a2a]" aria-label="Dismiss">
        ×
      </button>
    </div>
  )
}

function Modal({ title, children, actions }: { title: string; children: ReactNode; actions: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4">
      <div role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-[460px] rounded-md border border-[#454545] bg-[#252526] p-5 text-[13px] text-[#cccccc] shadow-2xl">
        <h2 className="mb-3 text-[15px] font-semibold text-white">{title}</h2>
        <div className="space-y-2 leading-relaxed">{children}</div>
        <div className="mt-5 flex justify-end gap-2">{actions}</div>
      </div>
    </div>
  )
}

export function SessionEndedOverlay({ reason, onRestart }: { reason: string | null; onRestart: () => void }) {
  return (
    <Modal
      title="Session ended"
      actions={
        <button type="button" onClick={onRestart} className="rounded-sm bg-[#0e639c] px-4 py-1.5 text-white hover:bg-[#1177bb]">
          Start new session
        </button>
      }
    >
      <p>Session ended: your workspace and graph were deleted.</p>
      {reason && <p className="text-[#9d9d9d]">Reason: {reason}</p>}
    </Modal>
  )
}

export function BusyOverlay({ message, onRetry }: { message: string | null; onRetry: () => void }) {
  return (
    <Modal
      title="Demo is busy"
      actions={
        <button type="button" onClick={onRetry} className="rounded-sm bg-[#0e639c] px-4 py-1.5 text-white hover:bg-[#1177bb]">
          Try again
        </button>
      }
    >
      <p>{message ?? 'All demo sessions are in use right now.'}</p>
      <p className="text-[#9d9d9d]">Wait a minute, then try again.</p>
    </Modal>
  )
}

export function StartErrorOverlay({ message, onRetry }: { message: string | null; onRetry: () => void }) {
  return (
    <Modal
      title="Could not start a session"
      actions={
        <button type="button" onClick={onRetry} className="rounded-sm bg-[#0e639c] px-4 py-1.5 text-white hover:bg-[#1177bb]">
          Retry
        </button>
      }
    >
      <p className="break-words text-[#f48771]">{message ?? 'Unknown error'}</p>
    </Modal>
  )
}
