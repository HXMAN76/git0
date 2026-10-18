// In-browser fake backend for ?mock=1. It emits the same SSE event shapes through the same reducer, so the
// UI can be developed and demoed without the FastAPI server. It plays one scripted story:
//   A "Regional tax": reads pricing.py, writes it (allowed), then writes cart.py (allowed).
//   B "Free shipping": reads cart.py (gets A's heads-up), then its write is DENIED with two conflicts,
//   the human gets an ask_user card, and the chosen option plays out.
// Nothing here is shown in the real (non-mock) path.

import { ApiError } from './api'
import {
  AGENTS,
  type AgentId,
  type ConflictInfo,
  type GraphView,
  type IdeEvent,
  type IdeTransport,
  type MergeResult,
  type Preset,
  type SessionCreated,
  type StreamHandlers,
} from './types'

type FileMap = Record<string, string>
type Payload = IdeEvent extends infer E ? (E extends IdeEvent ? Omit<E, 'ts'> : never) : never

const PRESETS: Preset[] = [
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

const TEMPLATE: FileMap = {
  'README.md': '# shop\n\nA tiny Python shop used for the git0 relay demo.\n',
  'shop/__init__.py': '',
  'shop/pricing.py': 'TAX_RATE = 0.08\n\n\ndef apply_tax(amount):\n    return round(amount * (1 + TAX_RATE), 2)\n\n\ndef apply_discount(amount, pct):\n    return round(amount * (1 - pct / 100), 2)\n',
  'shop/cart.py':
    'from shop.pricing import apply_discount, apply_tax\n\n\ndef subtotal(items):\n    return round(sum(item["price"] * item["qty"] for item in items), 2)\n\n\ndef calculate_total(items, discount_pct=0):\n    total = subtotal(items)\n    total = apply_discount(total, discount_pct)\n    return apply_tax(total)\n',
  'shop/inventory.py': 'STOCK = {"tea": 10, "mug": 4}\n\n\ndef reserve(items):\n    for item in items:\n        STOCK[item["sku"]] -= item["qty"]\n',
  'shop/receipts.py': 'def format_receipt(items, total):\n    lines = [f"{item[\'sku\']} x{item[\'qty\']}" for item in items]\n    lines.append(f"TOTAL {total:.2f}")\n    return "\\n".join(lines)\n',
  'shop/checkout.py':
    'from shop.cart import calculate_total\nfrom shop.inventory import reserve\nfrom shop.receipts import format_receipt\n\n\ndef checkout(items, user):\n    reserve(items)\n    total = calculate_total(items)\n    return format_receipt(items, total)\n',
  'tests/test_cart.py':
    'from shop.cart import subtotal\n\n\ndef test_subtotal():\n    assert subtotal([{"price": 2.0, "qty": 3}]) == 6.0\n',
}

const A_PRICING =
  'TAX_RATES = {"US": 0.08, "EU": 0.20, "IN": 0.18}\n\n\ndef apply_tax(amount, region):\n    return round(amount * (1 + TAX_RATES[region]), 2)\n\n\ndef apply_discount(amount, pct):\n    return round(amount * (1 - pct / 100), 2)\n'
const A_CART =
  'from shop.pricing import apply_discount, apply_tax\n\n\ndef subtotal(items):\n    return round(sum(item["price"] * item["qty"] for item in items), 2)\n\n\ndef calculate_total(items, discount_pct=0, region="US"):\n    total = subtotal(items)\n    total = apply_discount(total, discount_pct)\n    return apply_tax(total, region)\n'
const B_CART =
  'from shop.pricing import apply_discount, apply_tax\n\n\ndef subtotal(items):\n    return round(sum(item["price"] * item["qty"] for item in items), 2)\n\n\ndef calculate_total(items, discount_pct=0, region="US"):\n    total = subtotal(items)\n    total = apply_discount(total, discount_pct)\n    total = apply_tax(total, region)\n    if total < 50:\n        total += 5  # flat shipping under $50\n    return round(total, 2)\n'

const CONFLICTS: ConflictInfo[] = [
  {
    kind: 'same_symbol',
    severity: 'block',
    symbol: 'shop/cart.py::calculate_total',
    peer: 'A',
    peer_change_id: 'c4f1a9e20b7d',
    peer_summary: 'A changed calculate_total: added region argument',
    path: ['shop/cart.py::calculate_total'],
    message: 'Alice already changed calculate_total in shop/cart.py. Both of you would rewrite the same function.',
  },
  {
    kind: 'dependency',
    severity: 'block',
    symbol: 'shop/pricing.py::apply_tax',
    peer: 'A',
    peer_change_id: 'b83e0d17a4c2',
    peer_summary: 'A changed apply_tax signature: apply_tax(amount) -> apply_tax(amount, region)',
    path: ['shop/cart.py::calculate_total', 'shop/pricing.py::apply_tax'],
    message: "calculate_total calls apply_tax, and Alice just changed apply_tax's signature.",
  },
]

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))
const newId = () => Math.random().toString(16).slice(2, 14)

export function createMockTransport(): IdeTransport {
  let sid = ''
  let ended = false
  const files: Record<AgentId, FileMap> = { A: { ...TEMPLATE }, B: { ...TEMPLATE } }
  const busy: Record<AgentId, boolean> = { A: false, B: false }
  const buffer: IdeEvent[] = []
  const listeners = new Set<StreamHandlers>()
  const pendingAnswers = new Map<string, (choice: string) => void>()
  const graph: GraphView = buildGraph()

  function emit(payload: Payload) {
    if (ended) return
    const event = { ...payload, ts: Date.now() } as IdeEvent
    buffer.push(event)
    for (const handlers of listeners) handlers.onEvent(event)
  }

  function status(agent: AgentId, value: 'idle' | 'thinking' | 'tool' | 'waiting_user') {
    emit({ type: 'agent_status', agent, status: value })
  }

  function usage(agent: AgentId, input: number, output: number) {
    emit({ type: 'usage', agent, input_tokens: input, output_tokens: output, requests: 1 })
  }

  function finishTool(agent: AgentId, callId: string, tool: string, ok: boolean, summary: string) {
    emit({ type: 'tool_result', agent, call_id: callId, tool, ok, summary })
  }

  function writeFile(agent: AgentId, path: string, content: string, summary: string, check: { decision: 'allow' | 'deny'; detail: string; ms: number }) {
    const callId = newId()
    emit({ type: 'tool_call', agent, call_id: callId, tool: 'write_file', args: { path, summary } })
    status(agent, 'tool')
    emit({ type: 'hook', agent, phase: 'PreToolUse', tool: 'write_file', mcp_tool: 'code_check_edit', decision: check.decision, detail: check.detail, ms: check.ms })
    if (check.decision === 'deny') return { callId, written: false }
    files[agent][path] = content
    emit({ type: 'file_changed', agent, path, content })
    emit({ type: 'hook', agent, phase: 'PostToolUse', tool: 'write_file', mcp_tool: 'code_record_edit', decision: 'recorded', detail: summary, ms: 9 })
    recordChange(agent, path, summary)
    emit({ type: 'graph_changed' })
    finishTool(agent, callId, 'write_file', true, summary)
    return { callId, written: true }
  }

  function readFile(agent: AgentId, path: string, peer: { decision: 'allow' | 'context'; detail: string }) {
    const callId = newId()
    emit({ type: 'tool_call', agent, call_id: callId, tool: 'read_file', args: { path } })
    status(agent, 'tool')
    emit({ type: 'hook', agent, phase: 'PreToolUse', tool: 'read_file', mcp_tool: 'code_peer_activity', decision: peer.decision, detail: peer.detail, ms: 6 })
    finishTool(agent, callId, 'read_file', true, `read ${files[agent][path].split('\n').length} lines`)
  }

  function recordChange(agent: AgentId, path: string, summary: string) {
    const id = `chg-${newId()}`
    graph.nodes.push({ id, label: 'Change', name: summary.slice(0, 40), kind: 'modified', props: { agent, path } })
    graph.links.push({ source: `agent-${agent}`, target: id, type: 'MADE' })
    const symbol = path === 'shop/cart.py' ? 'shop/cart.py::calculate_total' : 'shop/pricing.py::apply_tax'
    if (graph.nodes.some((n) => n.id === symbol)) graph.links.push({ source: id, target: symbol, type: 'TOUCHED' })
  }

  async function runA() {
    await sleep(700)
    status('A', 'thinking')
    readFile('A', 'shop/pricing.py', { decision: 'allow', detail: 'no peer changes' })
    await sleep(500)
    emit({ type: 'agent_message', agent: 'A', role: 'assistant', text: 'pricing.py has one flat rate. I will make the rate depend on the region.' })
    await sleep(400)
    writeFile('A', 'shop/pricing.py', A_PRICING, 'apply_tax(amount, region) with TAX_RATES', { decision: 'allow', detail: 'no conflicts', ms: 14 })
    await sleep(700)
    readFile('A', 'shop/cart.py', { decision: 'allow', detail: 'no peer changes' })
    await sleep(500)
    writeFile('A', 'shop/cart.py', A_CART, 'calculate_total takes region and passes it on', { decision: 'allow', detail: 'no conflicts', ms: 12 })
    await sleep(400)
    emit({ type: 'agent_message', agent: 'A', role: 'assistant', text: 'Done. apply_tax takes a region, and calculate_total passes it through.' })
    usage('A', 1450, 320)
    status('A', 'idle')
    busy.A = false
  }

  async function runB() {
    await sleep(1800)
    status('B', 'thinking')
    readFile('B', 'shop/cart.py', {
      decision: 'context',
      detail: 'heads-up: A changed shop/pricing.py::apply_tax',
    })
    emit({ type: 'peer_notice', agent: 'B', from: 'A', message: 'Alice changed apply_tax(amount) -> apply_tax(amount, region) 6 s ago.' })
    await sleep(1200)
    emit({ type: 'agent_message', agent: 'B', role: 'assistant', text: 'Adding a $5 fee under $50 in calculate_total, then showing it on the receipt.' })
    await sleep(2200)
    status('B', 'thinking')

    const attempt = writeFile('B', 'shop/cart.py', B_CART, 'add $5 shipping under $50 in calculate_total', {
      decision: 'deny',
      detail: '2 conflicts',
      ms: 18,
    })
    if (attempt.written) return
    emit({ type: 'conflict', agent: 'B', conflicts: CONFLICTS })
    const qid = newId()
    emit({
      type: 'ask_user',
      agent: 'B',
      question_id: qid,
      question: "Alice changed the same function and apply_tax's signature. What should happen to Bob's write to shop/cart.py?",
      options: [
        { id: 'adopt', label: "Pull Alice's change and rework mine on top", description: "Copies Alice's files into Bob's workspace, then Bob redoes the edit" },
        { id: 'override', label: 'Keep my version anyway', description: "I'll talk to Alice; the write goes through" },
        { id: 'pause', label: 'Stop, let Alice finish first', description: "Bob's agent stops and waits" },
      ],
    })
    status('B', 'waiting_user')
    const choice = await new Promise<string>((resolve) => pendingAnswers.set(qid, resolve))
    emit({ type: 'ask_resolved', agent: 'B', question_id: qid, choice })

    if (choice === 'pause') {
      emit({ type: 'agent_message', agent: 'B', role: 'assistant', text: 'Stopped as you asked. Alice finishes first.' })
    } else {
      if (choice === 'adopt') {
        files.B['shop/cart.py'] = files.A['shop/cart.py']
        emit({ type: 'file_changed', agent: 'B', path: 'shop/cart.py', content: files.A['shop/cart.py'] })
        emit({ type: 'agent_message', agent: 'B', role: 'assistant', text: "Pulled Alice's cart.py. Redoing my edit on top of it." })
        await sleep(900)
        writeFile('B', 'shop/cart.py', B_CART, 'add $5 shipping on top of Alice region change', { decision: 'allow', detail: 'no conflicts left', ms: 11 })
      } else {
        writeFile('B', 'shop/cart.py', B_CART, 'add $5 shipping (user override)', { decision: 'allow', detail: 'user override', ms: 11 })
      }
      emit({ type: 'agent_message', agent: 'B', role: 'assistant', text: 'Shipping fee added in calculate_total.' })
    }
    usage('B', 2210, 540)
    status('B', 'idle')
    busy.B = false
  }

  async function runGeneric(agent: AgentId) {
    status(agent, 'thinking')
    await sleep(700)
    emit({
      type: 'agent_message',
      agent,
      role: 'assistant',
      text: 'Mock backend: only the scripted presets run in ?mock=1. Use Run scenario.',
    })
    status(agent, 'idle')
    busy[agent] = false
  }

  return {
    async createSession(): Promise<SessionCreated> {
      sid = newId()
      ended = false
      buffer.length = 0
      emit({
        type: 'session',
        session_id: sid,
        agents: {
          A: { label: "Alice's laptop", model: 'gemini-3.1-flash-lite (mock)' },
          B: { label: "Bob's laptop", model: 'gemini-3.1-flash-lite (mock)' },
        },
        files: Object.keys(TEMPLATE),
        presets: PRESETS,
      })
      return {
        session_id: sid,
        agents: {
          A: { label: "Alice's laptop", model: 'gemini-3.1-flash-lite (mock)' },
          B: { label: "Bob's laptop", model: 'gemini-3.1-flash-lite (mock)' },
        },
        files: Object.keys(TEMPLATE),
        presets: PRESETS,
      }
    },

    async getFiles() {
      // The baseline is the untouched template for both laptops.
      return { ...TEMPLATE }
    },

    async getGraph() {
      return JSON.parse(JSON.stringify(graph)) as GraphView
    },

    connect(_sid, handlers) {
      listeners.add(handlers)
      queueMicrotask(() => {
        if (!listeners.has(handlers)) return
        handlers.onOpen()
        for (const event of buffer) handlers.onEvent(event)
      })
      return () => listeners.delete(handlers)
    },

    async sendMessage(_sid, agent, text) {
      if (ended) throw new ApiError(404, 'session expired')
      if (busy[agent]) throw new ApiError(409, `Agent ${agent} is still working on the last message`)
      busy[agent] = true
      emit({ type: 'agent_message', agent, role: 'user', text })
      const preset = PRESETS.find((p) => p.agent === agent && p.text === text)
      const scripted = (agent === 'A' && (preset?.id === 'A-regional-tax' || text.includes('region-based tax'))) ||
        (agent === 'B' && (preset?.id === 'B-free-shipping' || text.includes('shipping')))
      if (agent === 'A' && scripted) void runA()
      else if (agent === 'B' && scripted) void runB()
      else void runGeneric(agent)
    },

    async answer(_sid, questionId, choice) {
      const resolve = pendingAnswers.get(questionId)
      if (!resolve) throw new ApiError(404, 'question not pending')
      pendingAnswers.delete(questionId)
      resolve(choice)
    },

    async mergeCheck(): Promise<MergeResult> {
      const paths = Object.keys(TEMPLATE)
      return {
        files: paths.map((path) => {
          const aChanged = files.A[path] !== TEMPLATE[path]
          const bChanged = files.B[path] !== TEMPLATE[path]
          if (aChanged && bChanged && files.A[path] !== files.B[path]) {
            return {
              path,
              conflicted: true,
              merged: `<<<<<<< alice\n${files.A[path]}=======\n${files.B[path]}>>>>>>> bob\n`,
            }
          }
          return { path, conflicted: false, merged: aChanged ? files.A[path] : files.B[path] }
        }),
      }
    },

    async end() {
      if (ended) return
      ended = true
      emit({ type: 'session_ended', reason: 'ended by you' })
    },

    beacon() {
      // The mock has no server to notify.
    },
  }
}

function buildGraph(): GraphView {
  const nodes: GraphView['nodes'] = [
    ...['shop/pricing.py', 'shop/cart.py', 'shop/receipts.py', 'shop/checkout.py'].map((p) => ({
      id: p,
      label: 'File',
      name: p,
      kind: 'file',
      props: {},
    })),
    ...[
      'shop/pricing.py::apply_tax',
      'shop/pricing.py::apply_discount',
      'shop/cart.py::subtotal',
      'shop/cart.py::calculate_total',
      'shop/receipts.py::format_receipt',
      'shop/checkout.py::checkout',
    ].map((id) => ({ id, label: 'Symbol', name: id.split('::')[1], kind: 'function', props: { path: id.split('::')[0] } })),
    ...AGENTS.map((a) => ({ id: `agent-${a}`, label: 'Agent', name: a === 'A' ? 'Alice' : 'Bob', kind: 'agent', props: {} })),
  ]
  const links: GraphView['links'] = [
    { source: 'shop/pricing.py', target: 'shop/pricing.py::apply_tax', type: 'DEFINES' },
    { source: 'shop/pricing.py', target: 'shop/pricing.py::apply_discount', type: 'DEFINES' },
    { source: 'shop/cart.py', target: 'shop/cart.py::subtotal', type: 'DEFINES' },
    { source: 'shop/cart.py', target: 'shop/cart.py::calculate_total', type: 'DEFINES' },
    { source: 'shop/receipts.py', target: 'shop/receipts.py::format_receipt', type: 'DEFINES' },
    { source: 'shop/checkout.py', target: 'shop/checkout.py::checkout', type: 'DEFINES' },
    { source: 'shop/cart.py::calculate_total', target: 'shop/cart.py::subtotal', type: 'CALLS' },
    { source: 'shop/cart.py::calculate_total', target: 'shop/pricing.py::apply_tax', type: 'CALLS' },
    { source: 'shop/checkout.py::checkout', target: 'shop/cart.py::calculate_total', type: 'CALLS' },
  ]
  return { nodes, links }
}
