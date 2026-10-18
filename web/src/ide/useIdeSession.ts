// Session lifecycle for the IDE: create -> fetch template baseline -> open SSE -> reduce events.
// Everything the UI can do to the backend goes through this controller, so 404 ("session expired")
// is handled in one place.

import { useCallback, useEffect, useReducer, useRef, type Dispatch } from 'react'
import { ApiError, loadTransport } from './api'
import { initialState, reducer, type Action, type IdeState } from './state'
import { type AgentId, type GraphView, type IdeEvent, type IdeTransport, type MergeResult, type Preset } from './types'

/** Used when the backend's presets are missing, so the scenario buttons still work. */
export const FALLBACK_PRESETS: Preset[] = [
  {
    id: 'A-regional-tax',
    agent: 'A',
    title: 'Regional tax',
    text:
      'Add region-based tax. Change `apply_tax` in shop/pricing.py to `apply_tax(amount, region)` using a `TAX_RATES` dict (US 0.08, EU 0.20, IN 0.18), and make `calculate_total` in shop/cart.py take a `region="US"` argument and pass it through.',
  },
  {
    id: 'B-free-shipping',
    agent: 'B',
    title: 'Free shipping',
    text:
      'Add shipping: in shop/cart.py change `calculate_total` to add a $5 shipping fee when the subtotal is under $50, and show the shipping line in shop/receipts.py `format_receipt`.',
  },
  {
    id: 'B-gift-cards',
    agent: 'B',
    title: 'Gift cards',
    text:
      'Add gift cards: in shop/checkout.py let `checkout` accept `gift_card=0` and subtract it from the total after tax by calling `apply_tax` on the discounted amount.',
  },
]

export interface IdeController {
  state: IdeState
  /** Local UI actions (open/close/select tabs, banner) that never touch the backend. */
  dispatch: Dispatch<Action>
  start(): void
  end(): Promise<void>
  send(agent: AgentId, text: string): Promise<void>
  answer(questionId: string, choice: string): Promise<void>
  runScenario(): Promise<void>
  mergeCheck(): Promise<MergeResult>
  graph(): Promise<GraphView>
}

export function useIdeSession(): IdeController {
  const [state, dispatch] = useReducer(reducer, undefined, initialState)
  const transportRef = useRef<IdeTransport | null>(null)
  const sidRef = useRef<string | null>(null)
  const closeStreamRef = useRef<(() => void) | null>(null)
  /** Each start() bumps this; late callbacks from an older start are ignored. */
  const runRef = useRef(0)
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const closeStream = useCallback(() => {
    closeStreamRef.current?.()
    closeStreamRef.current = null
  }, [])

  const expire = useCallback(
    (reason: string) => {
      closeStream()
      dispatch({ type: 'ended', reason })
    },
    [closeStream],
  )

  /** A 404 means the backend forgot the session (idle sweep, restart). Anything else is the caller's error. */
  const guard = useCallback(
    async <T,>(promise: Promise<T>): Promise<T> => {
      try {
        return await promise
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) expire('session expired')
        throw err
      }
    },
    [expire],
  )

  const start = useCallback(() => {
    const run = ++runRef.current
    const stale = () => run !== runRef.current
    closeStream()
    sidRef.current = null
    dispatch({ type: 'reset' })

    void (async () => {
      let transport: IdeTransport
      try {
        transport = transportRef.current ?? (await loadTransport())
        transportRef.current = transport
        const created = await transport.createSession()
        if (stale()) return
        sidRef.current = created.session_id
        dispatch({
          type: 'created',
          sessionId: created.session_id,
          agents: created.agents,
          files: created.files,
          presets: created.presets?.length ? created.presets : FALLBACK_PRESETS,
          at: Date.now(),
        })
        const sid = created.session_id
        const [aFiles, bFiles] = await Promise.all([transport.getFiles(sid, 'A'), transport.getFiles(sid, 'B')])
        if (stale()) return
        dispatch({ type: 'baseline', baseline: { A: aFiles, B: bFiles } })

        let opens = 0
        closeStreamRef.current = transport.connect(sid, {
          onOpen: () => {
            if (stale()) return
            opens += 1
            // Reconnects replay the whole buffer; drop what we have so nothing shows twice.
            if (opens > 1) dispatch({ type: 'live_reset' })
            dispatch({ type: 'sse_open', open: true })
          },
          onRetry: () => {
            if (!stale()) dispatch({ type: 'sse_open', open: false })
          },
          onFatal: () => {
            if (stale()) return
            dispatch({ type: 'sse_open', open: false })
            // The browser closed the stream on an error status. Ask the backend which one.
            transport.getGraph(sid).then(
              () => dispatch({ type: 'banner', text: 'Live event stream stopped. Reload the page to resume.' }),
              (err: unknown) => {
                if (err instanceof ApiError && err.status === 404) expire('session expired')
                else dispatch({ type: 'banner', text: 'Live event stream stopped. Reload the page to resume.' })
              },
            )
          },
          onEvent: (event: IdeEvent) => {
            if (stale()) return
            dispatch({ type: 'event', event })
            if (event.type === 'session_ended') closeStream()
          },
        })
      } catch (err) {
        if (stale()) return
        if (err instanceof ApiError && err.status === 503) {
          dispatch({ type: 'busy', message: err.message })
        } else {
          dispatch({ type: 'failed', message: err instanceof Error ? err.message : String(err) })
        }
      }
    })()
  }, [closeStream, expire])

  // Start once. No StrictMode in the IDE entry, so this effect runs exactly once per page load.
  useEffect(() => {
    const runs = runRef
    start()
    return () => {
      runs.current++
      closeStream()
    }
  }, [start, closeStream])

  // Closing the tab ends the session on the backend so its graph and workspaces are deleted.
  useEffect(() => {
    const onHide = () => {
      const sid = sidRef.current
      if (sid && stateRef.current.phase !== 'ended' && transportRef.current) transportRef.current.beacon(sid)
    }
    window.addEventListener('pagehide', onHide)
    return () => window.removeEventListener('pagehide', onHide)
  }, [])

  const requireSession = useCallback((): { transport: IdeTransport; sid: string } => {
    const transport = transportRef.current
    const sid = sidRef.current
    if (!transport || !sid) throw new Error('No active session yet')
    return { transport, sid }
  }, [])

  const end = useCallback(async () => {
    const { transport, sid } = requireSession()
    try {
      await guard(transport.end(sid))
    } finally {
      closeStream()
      dispatch({ type: 'ended', reason: 'ended by you' })
    }
  }, [closeStream, guard, requireSession])

  const send = useCallback(
    async (agent: AgentId, text: string) => {
      const { transport, sid } = requireSession()
      await guard(transport.sendMessage(sid, agent, text))
    },
    [guard, requireSession],
  )

  const answer = useCallback(
    async (questionId: string, choice: string) => {
      const { transport, sid } = requireSession()
      await guard(transport.answer(sid, questionId, choice))
    },
    [guard, requireSession],
  )

  /** Sends the Regional tax preset to A and Free shipping to B at the same time. */
  const runScenario = useCallback(async () => {
    const { presets } = stateRef.current
    const pick = (agent: AgentId, title: string): Preset | undefined =>
      presets.find((p) => p.agent === agent && (p.title ?? '').toLowerCase().includes(title.toLowerCase())) ??
      FALLBACK_PRESETS.find((p) => p.agent === agent && p.title === title)
    const a = pick('A', 'Regional tax')
    const b = pick('B', 'Free shipping')
    const results = await Promise.allSettled(
      [a && send('A', a.text), b && send('B', b.text)].filter((p): p is Promise<void> => p !== undefined),
    )
    const failed = results.filter((r) => r.status === 'rejected')
    if (failed.length > 0) {
      const messages = failed.map((r) => (r.status === 'rejected' ? (r.reason instanceof Error ? r.reason.message : String(r.reason)) : ''))
      dispatch({ type: 'banner', text: `Scenario not fully sent: ${messages.join('; ')}` })
    }
  }, [send])

  const mergeCheck = useCallback(async () => {
    const { transport, sid } = requireSession()
    return guard(transport.mergeCheck(sid))
  }, [guard, requireSession])

  const graph = useCallback(async () => {
    const { transport, sid } = requireSession()
    return guard(transport.getGraph(sid))
  }, [guard, requireSession])

  return { state, dispatch, start, end, send, answer, runScenario, mergeCheck, graph }
}
