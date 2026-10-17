import { useState } from 'react'
import { BranchPicker } from './components/BranchPicker'
import { ChatPanel } from './components/ChatPanel'
import { CommitDag } from './components/CommitDag'
import { DemoGuide, type ChatPrompt } from './components/DemoGuide'
import { MemoryCanvas } from './components/MemoryCanvas'
import { MergeBar } from './components/MergeBar'
import { Scorecard } from './components/Scorecard'
import { TenantGate } from './components/TenantGate'
import { resolveTenant } from './lib/tenant'

type CenterTab = 'memory' | 'history'

const CENTER_TABS: { id: CenterTab; label: string }[] = [
  { id: 'memory', label: 'Memory graph' },
  { id: 'history', label: 'Team history' },
]

// 3-column shell: chat | (memory graph + history tabs, under the demo guide and merge bar) | scorecard.
// Everything sits inside TenantGate: no panel reads the room before it is seeded. Stacks on a phone.
export default function App() {
  const [tab, setTab] = useState<CenterTab>('memory')
  const [branch, setBranch] = useState('main')
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null)
  // One room per visitor (or ?team=<id> for a shared link), resolved once per page load.
  const [tenant] = useState(() => resolveTenant(window.location.search, window.localStorage))

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100 lg:h-dvh">
      <header className="flex items-center gap-3 border-b border-neutral-800 px-3 py-2">
        <h1 className="font-semibold">Git0</h1>
        <p className="hidden text-sm text-neutral-400 sm:block">Each agent remembers on its own branch; team memory is what they agree on.</p>
        <span className="ml-auto text-xs text-neutral-500" title="Share this room: add ?team=<id> to the link">
          room: {tenant}
        </span>
      </header>
      <TenantGate tenant={tenant}>
        {(t) => (
          <>
            <DemoGuide tenant={t} onPrompt={setPrompt} />
            <div className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[340px_1fr_300px]">
              <aside className="h-[45vh] min-h-0 border-neutral-800 lg:h-auto lg:border-r">
                <ChatPanel tenant={t} prompt={prompt} />
              </aside>

              <main className="flex h-[85vh] min-h-0 flex-col border-y border-neutral-800 lg:h-auto lg:border-y-0">
                <MergeBar tenant={t} />
                <div role="tablist" className="flex items-center gap-1 border-b border-neutral-800 p-2">
                  {CENTER_TABS.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      role="tab"
                      aria-selected={tab === c.id}
                      onClick={() => setTab(c.id)}
                      className={`whitespace-nowrap rounded px-3 py-1 text-sm ${
                        tab === c.id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                  {tab === 'memory' && <BranchPicker tenant={t} value={branch} onChange={setBranch} />}
                </div>
                <div role="tabpanel" className="min-h-0 flex-1">
                  {tab === 'memory' ? <MemoryCanvas tenant={t} branch={branch} /> : <CommitDag tenant={t} />}
                </div>
              </main>

              <aside className="min-h-0 border-neutral-800 lg:border-l">
                <Scorecard tenant={t} />
              </aside>
            </div>
          </>
        )}
      </TenantGate>
    </div>
  )
}
