import { useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { CommitDag } from './components/CommitDag'
import { MemoryCanvas } from './components/MemoryCanvas'
import { Scorecard } from './components/Scorecard'
import { TenantGate } from './components/TenantGate'
import { resolveTenant } from './lib/tenant'

type CenterTab = 'commits' | 'memory'

const CENTER_TABS: { id: CenterTab; label: string }[] = [
  { id: 'commits', label: 'Commit DAG' },
  { id: 'memory', label: 'Memory graph' },
]

// 3-column shell: chat | (commit DAG + memory graph tabs) | scorecard.
export default function App() {
  const [tab, setTab] = useState<CenterTab>('commits')
  // One room per visitor (or ?team=<id> for a shared link), resolved once per page load.
  const [tenant] = useState(() => resolveTenant(window.location.search, window.localStorage))

  return (
    <div className="grid h-dvh grid-cols-[320px_1fr_300px] bg-neutral-950 text-neutral-100">
      <aside className="min-h-0 border-r border-neutral-800">
        <ChatPanel />
      </aside>

      <main className="flex min-h-0 flex-col">
        <div role="tablist" className="flex items-center gap-1 border-b border-neutral-800 p-2">
          {CENTER_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`rounded px-3 py-1 text-sm ${
                tab === t.id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {t.label}
            </button>
          ))}
          <span className="ml-auto text-xs text-neutral-500" title="Share this room: add ?team=<id> to the link">
            room: {tenant}
          </span>
        </div>
        <div role="tabpanel" className="min-h-0 flex-1">
          <TenantGate tenant={tenant}>
            {(t) => (tab === 'commits' ? <CommitDag /> : <MemoryCanvas tenant={t} />)}
          </TenantGate>
        </div>
      </main>

      <aside className="min-h-0 border-l border-neutral-800">
        <Scorecard />
      </aside>
    </div>
  )
}
