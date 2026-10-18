# Git0 web

React + TypeScript + Vite frontend for the Git0 hackathon app.

## Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Vite dev server on http://localhost:5173 (proxies `/api` to the backend) |
| `pnpm build` | Typecheck (`tsc -b`) then production build to `dist/` |
| `pnpm preview` | Serve the built `dist/` locally |
| `pnpm typecheck` | `tsc -b` only |
| `pnpm lint` | oxlint (the template's linter) |
| `pnpm test` | Vitest, one run, jsdom environment |
| `pnpm gen:api` | Regenerate `src/api/schema.d.ts` from the running backend's `/openapi.json` (backend must be on :8000) |

## Folder map

Two pages from one build (`vite.config.ts` has two Rollup inputs): the team room at `/` and the relay IDE at `/ide/`.

```
index.html, src/main.tsx   team room entry
src/App.tsx                shell: chat + merge bar | commit DAG / memory graph tabs | scorecard
src/components/            ChatPanel (SSE over fetch), MergeBar + ConflictCard (preview -> explain -> resolve -> rederive),
                           CommitDag (xyflow + dagre), MemoryCanvas (@falkordb/canvas), WhyPath, Scorecard,
                           DemoGuide ("Try the demo" bar), BranchPicker, TenantGate (per-visitor room), ErrorBanner
src/api/                   openapi-fetch client + generated schema.d.ts
src/lib/                   shared hooks (branch logs, tenant)
ide/index.html, src/ide/   relay IDE: App, useIdeSession (SSE events), tour + coach marks,
                           components/ (AgentPanel, Workspace (Monaco), GraphCanvas/GraphOverlay, BottomPanel)
```

`@/` is an alias for `src/` (Vite and tsconfig).

## How the API proxy works

In dev, `vite.config.ts` forwards any request whose path starts with `/api` or `/mcp` to
`http://localhost:8000`. The browser only talks to the Vite origin, so there is no CORS
setup and `EventSource` streams (SSE) pass straight through.

The client uses `baseUrl: ""`, so calls like `api.GET("/api/...")` are same-origin.
In production, FastAPI serves `web/dist` on the same origin, so the same relative paths work.
