import { useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { CommitDag } from './components/CommitDag'
import { MemoryCanvas } from './components/MemoryCanvas'
import { Scorecard } from './components/Scorecard'

// Until the per-visitor tenant lands (person-d-ui-deploy.md), every view reads the seeded demo room.
const TENANT = 'demo'

type CenterTab = 'commits' | 'memory'

const CENTER_TABS: { id: CenterTab; label: string }[] = [
  { id: 'commits', label: 'Commit DAG' },
  { id: 'memory', label: 'Memory graph' },
]

// 3-column shell: chat | (commit DAG + memory graph tabs) | scorecard.
export default function App() {
  const [tab, setTab] = useState<CenterTab>('commits')

  return (
    <div className="grid h-dvh grid-cols-[320px_1fr_300px] bg-neutral-950 text-neutral-100">
      <aside className="min-h-0 border-r border-neutral-800">
        <ChatPanel />
      </aside>

      <main className="flex min-h-0 flex-col">
        <div role="tablist" className="flex gap-1 border-b border-neutral-800 p-2">
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
        </div>
        <div role="tabpanel" className="min-h-0 flex-1">
          {tab === 'commits' ? <CommitDag /> : <MemoryCanvas tenant={TENANT} />}
        </div>
      </main>

      <aside className="min-h-0 border-l border-neutral-800">
        <Scorecard />
      </aside>
    </div>
  )
}
