import { useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { CommitDag } from './components/CommitDag'
import { ConflictCard } from './components/ConflictCard'
import { MemoryCanvas } from './components/MemoryCanvas'
import { Scorecard } from './components/Scorecard'
import { TenantGate } from './components/TenantGate'
import { WhyPath } from './components/WhyPath'
import { resolveTenant } from './lib/tenant'

type CenterTab = 'commits' | 'memory'

const CENTER_TABS: { id: CenterTab; label: string }[] = [
  { id: 'commits', label: 'Commit DAG' },
  { id: 'memory', label: 'Memory graph' },
]

export default function App() {
  const [tab, setTab] = useState<CenterTab>('commits')
  const [tenant] = useState(() => resolveTenant(window.location.search, window.localStorage))
  const [highlight, setHighlight] = useState<string[]>([])
  // fact ID whose why-path is being fetched; WhyPath resolves it to node IDs
  const [whyFactId, setWhyFactId] = useState<string | null>(null)
  // active agent tab so ConflictCard knows which branch to merge
  const [activeBranch, setActiveBranch] = useState<string>('planner')

  function handleFactClick(factId: string) {
    setWhyFactId(factId)
    setTab('memory')
  }

  return (
    <div className="grid h-dvh grid-cols-[320px_1fr_300px] bg-neutral-950 text-neutral-100">
      {/* LEFT — chat */}
      <aside className="flex min-h-0 flex-col border-r border-neutral-800">
        <TenantGate tenant={tenant}>
          {(t) => (
            <>
              <ChatPanel tenant={t} onFactClick={handleFactClick} onAgentChange={setActiveBranch} />
              {/* WhyPath fetches node IDs for the clicked fact and pushes them into highlight */}
              <WhyPath tenant={t} factId={whyFactId} onHighlight={(ids) => { setHighlight(ids); setWhyFactId(null) }} />
              <div className="border-t border-neutral-800 p-2">
                <ConflictCard tenant={t} sourceBranch={activeBranch} />
              </div>
            </>
          )}
        </TenantGate>
      </aside>

      {/* CENTER — DAG / memory graph */}
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
            {(t) =>
              tab === 'commits' ? (
                <CommitDag tenant={t} />
              ) : (
                <MemoryCanvas tenant={t} highlight={highlight} onNodeClick={() => setHighlight([])} />
              )
            }
          </TenantGate>
        </div>
      </main>

      {/* RIGHT — scorecard */}
      <aside className="min-h-0 border-l border-neutral-800">
        <TenantGate tenant={tenant}>
          {(t) => <Scorecard tenant={t} />}
        </TenantGate>
      </aside>
    </div>
  )
}
