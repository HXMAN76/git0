// Guided tours and coach marks, all on driver.js. Every target is looked up at run time: a missing or hidden
// element drops its step instead of breaking the tour. Copy is plain English on purpose (judges open this cold).

import { flushSync } from 'react-dom'
import { driver, type Driver, type DriveStep, type PopoverDOM } from 'driver.js'
import 'driver.js/dist/driver.css'
import { markTourSeen } from './storage'

/** The bottom panel tabs, mirrored here so the tour can switch them. */
export type PanelTab = 'relay' | 'graph' | 'problems' | 'merge'

/** One driver instance at a time: a new tour or coach mark replaces the one on screen. */
let current: Driver | null = null
/** Removes the listeners and timer of the coach mark on screen (if any). Run by stopTour and by a mark's own dismissal. */
let coachTeardown: (() => void) | null = null

export function stopTour() {
  const d = current
  current = null
  const teardown = coachTeardown
  coachTeardown = null
  teardown?.()
  d?.destroy()
}

function isShown(el: Element | null): el is HTMLElement {
  return el instanceof HTMLElement && el.getClientRects().length > 0
}

/** The first selector whose element is actually rendered (not display:none), or null. */
function firstShown(selectors: string[]): string | null {
  for (const sel of selectors) {
    const found = Array.from(document.querySelectorAll(sel))
    if (found.some(isShown)) return sel
  }
  return null
}

interface TourStep {
  title: string
  text: string
  /** Candidate selectors; the first shown one is highlighted. Empty = centered popover, always kept. */
  selectors: string[]
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Bottom-panel tab to show when the step starts (the tour switches tabs itself). */
  tab?: PanelTab
  /** The last step: its primary button runs the scenario. */
  run?: boolean
}

const TAB = (id: PanelTab) => `[data-tour="tab-${id}"]`

const WELCOME: TourStep[] = [
  {
    title: 'The problem',
    text: 'Two developers clone the same repo and each let an AI agent code. With git, they find out they collided days later at merge time. git0 catches it the moment it happens.',
    selectors: [],
  },
  {
    title: 'Two laptops, two clones',
    text: "Alice's agent (blue) and Bob's agent (purple) each edit their own copy, just like real life. Nothing is shared except the git0 graph.",
    selectors: ['[data-tour="explorer"]'],
    side: 'right',
  },
  {
    title: 'Live code',
    text: 'Live code from both clones. Changed lines light up as the agents write.',
    selectors: ['[data-tour="editors"]'],
    side: 'bottom',
  },
  {
    title: 'Agent A',
    text: 'Agent A is an open-source pydantic-ai agent on Gemini. Every tool call it makes goes through git0 hooks.',
    selectors: ['[data-tour="agent-A"]'],
    side: 'left',
  },
  {
    title: 'Hooks',
    text: "Before every write, a PreToolUse hook asks the git0 MCP server: 'does this collide with anything a teammate changed?' After every write, a PostToolUse hook records the change in FalkorDB.",
    selectors: ['[data-tour="agent-B"]'],
    side: 'left',
  },
  {
    title: 'GIT0 RELAY',
    text: 'Every hook call and MCP query, live, with timings.',
    selectors: [TAB('relay')],
    side: 'top',
    tab: 'relay',
  },
  {
    title: 'The graph',
    text: 'The heart of it: a FalkorDB graph of the code. Functions, who calls whom, who changed what. One graph query follows the dependency chain to spot collisions git cannot see.',
    selectors: [TAB('graph')],
    side: 'top',
    tab: 'graph',
  },
  {
    title: 'Merge check',
    text: 'At the end, compare: what plain git would say vs what git0 knows.',
    selectors: [TAB('merge')],
    side: 'top',
    tab: 'merge',
  },
  {
    title: 'Run the scenario',
    text: "Start here. Alice adds regional tax while Bob adds free shipping, to the same function. Watch Bob's write get stopped, then you decide what happens.",
    selectors: ['[data-tour="run-scenario"]'],
    side: 'bottom',
    run: true,
  },
]

export interface TourHooks {
  /** Switches the bottom panel tab so the step's content is on screen. */
  setTab: (tab: PanelTab) => void
  /** Starts the scenario. Called by the final step's button. */
  runScenario: () => void
}

/** The welcome tour. Starting it marks the tour as seen, so auto-start happens once per browser. */
export function startWelcomeTour(hooks: TourHooks) {
  stopTour()
  markTourSeen()
  const driverSteps: DriveStep[] = []
  for (const s of WELCOME) {
    // A step whose target is missing is skipped; a step with no target list is always kept.
    const sel = s.selectors.length > 0 ? firstShown(s.selectors) : null
    if (s.selectors.length > 0 && sel === null) continue
    driverSteps.push({
      ...(sel ? { element: sel } : {}),
      onHighlightStarted: () => {
        if (s.tab) flushSync(() => hooks.setTab(s.tab as PanelTab))
      },
      popover: {
        title: s.title,
        description: s.text,
        side: sel ? s.side : undefined,
        align: 'center',
        ...(s.run
          ? {
              onNextClick: () => {
                stopTour()
                hooks.setTab('relay')
                hooks.runScenario()
              },
            }
          : {}),
      },
    })
  }
  const d: Driver = driver({
    steps: driverSteps,
    popoverClass: 'git0-popover git0-tour',
    showProgress: true,
    progressText: '{{current}} of {{total}}',
    nextBtnText: 'Next',
    prevBtnText: 'Back',
    doneBtnText: 'Run it now',
    allowClose: true,
    animate: true,
    stagePadding: 6,
    overlayOpacity: 0.55,
    onPopoverRender: (popover: PopoverDOM) => {
      // The close icon becomes a text "Skip" so judges know they can leave the tour.
      popover.closeButton.textContent = 'Skip'
      popover.closeButton.setAttribute('aria-label', 'Skip the tour')
    },
    onDestroyed: () => {
      // Only a tour that ended on its own (Skip, Esc, or the last step) returns the panel to the relay tab.
      if (current === d) {
        current = null
        hooks.setTab('relay')
      }
    },
  })
  current = d
  d.drive()
}

// ---------- Graph mini tour ("What am I looking at?") ----------

interface GraphStep {
  title: string
  text: string
  /** data-tour name inside the graph surface. */
  name: 'graph-legend' | 'graph-story' | 'graph-hotspots' | 'graph-canvas'
}

const GRAPH_STEPS: GraphStep[] = [
  {
    title: 'The legend',
    text: 'Grey circles are files, yellow are functions, salmon are changes an agent made, teal are the agents.',
    name: 'graph-legend',
  },
  {
    title: 'The story feed',
    text: 'Plain-English sentences of what changed and what it affects, newest first.',
    name: 'graph-story',
  },
  {
    title: 'Hotspots',
    text: 'Functions both people touched. That is where merge conflicts would come from.',
    name: 'graph-hotspots',
  },
  {
    title: 'Click a node',
    text: 'Click any circle to see what depends on it. That is its blast radius.',
    name: 'graph-canvas',
  },
]

/**
 * The 4-step graph helper. `surface` picks the GRAPH tab ("panel") or the full-screen overlay ("overlay"),
 * which both carry the same data-tour names, so each selector is scoped to the surface that is open.
 */
export function startGraphTour(surface: 'panel' | 'overlay') {
  stopTour()
  const scope = surface === 'panel' ? '[aria-label="Panel"] ' : '[aria-label="Code graph"] '
  const steps: DriveStep[] = []
  for (const s of GRAPH_STEPS) {
    const sel = `${scope}[data-tour="${s.name}"]`
    if (!isShown(document.querySelector(sel))) continue
    steps.push({ element: sel, popover: { title: s.title, description: s.text, side: 'bottom', align: 'start' } })
  }
  if (steps.length === 0) return
  const d: Driver = driver({
    steps,
    popoverClass: 'git0-popover git0-tour',
    showProgress: true,
    progressText: '{{current}} of {{total}}',
    nextBtnText: 'Next',
    prevBtnText: 'Back',
    doneBtnText: 'Done',
    allowClose: true,
    stagePadding: 6,
    overlayOpacity: 0.55,
    onDestroyed: () => {
      if (current === d) current = null
    },
  })
  current = d
  d.drive()
}

// ---------- Coach marks (the narrator during a live run) ----------

/** A coach mark goes away on its own after this long, so it never lingers over the work. */
export const COACH_AUTO_DISMISS_MS = 12_000

export interface CoachMarkSpec {
  title: string
  text: string
  /** Candidate selectors, first shown one wins. Nothing shown = centered popover. */
  selectors: string[]
  side?: 'top' | 'right' | 'bottom' | 'left'
}

/**
 * One coach mark: a single highlighted element with a popover. The page stays clickable (see the
 * body.git0-coach-live rule in ide.css), so the ask card buttons still work. Replaces any mark on screen.
 * The mark is dismissed when its target is clicked (or anything inside it), after COACH_AUTO_DISMISS_MS,
 * or by stopTour (the next mark, the overlay opening, the narrator being switched off).
 */
export function showCoachMark(spec: CoachMarkSpec) {
  const sel = firstShown(spec.selectors)
  const element = sel ? document.querySelector(sel) : null
  stopTour()
  document.body.classList.add('git0-coach-live')

  const onClick = (event: MouseEvent) => {
    if (element && event.target instanceof Node && element.contains(event.target)) stopTour()
  }
  // Capture phase, so the click is seen even when the target handler stops propagation.
  document.addEventListener('click', onClick, true)
  const timer = window.setTimeout(() => stopTour(), COACH_AUTO_DISMISS_MS)
  coachTeardown = () => {
    document.removeEventListener('click', onClick, true)
    window.clearTimeout(timer)
    document.body.classList.remove('git0-coach-live')
  }

  const d: Driver = driver({
    popoverClass: 'git0-popover git0-coach',
    allowClose: true,
    overlayOpacity: 0,
    stagePadding: 6,
    showButtons: ['close'],
    animate: true,
    onDestroyed: () => {
      if (current === d) {
        current = null
        const teardown = coachTeardown
        coachTeardown = null
        teardown?.()
      }
    },
  })
  current = d
  d.highlight({
    ...(element ? { element } : {}),
    popover: { title: spec.title, description: spec.text, side: element ? spec.side : undefined, align: 'center' },
  })
}
