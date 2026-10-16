# 03 - Frontend stack research (hackathon, 3 days)

Date of research: 2026-10-16. Versions are the `latest` dist-tag on the npm registry (or PyPI) on that date, checked with `curl registry.npmjs.org/<pkg>/latest`.

App shape: left = chat with 3 AI agents, center = git-like commit DAG + memory graph, right = live scorecard. Backend = FastAPI.

---

## 1. `@falkordb/canvas` (memory graph)

**Latest:** `@falkordb/canvas@0.3.3` (published 2026-10-12). MIT. Source lives in the monorepo `FalkorDB/falkordb-ui`, path `web-components/canvas`. The repo has ~2 GitHub stars, so it is very young: 0.3.0 to 0.3.3 shipped between 2026-10-11 and 2026-10-12. Treat it as a risk.

**What it is:** a standalone **Web Component** (`<falkordb-canvas>`) that draws a force-directed graph on HTML canvas (D3 force, optional 2D/3D). It is *not* a React wrapper. React uses it through a ref plus imperative methods. TypeScript types are included (`dist/index.d.ts`).

**Runtime deps:** `d3`, `force-graph` (^1.44.4), `3d-force-graph`, `three` (three.js is lazy-loaded only when 3D is used, per the README). Peer: `@types/react` ^18.3 or ^19. Package itself is ~0.6 MB unpacked.

**Exports:** default + named `FalkorDBCanvas`; types `Data`, `GraphNode`, `GraphLink`, `GraphData`, `ForceGraphConfig`, `ViewportState`, `LayoutMode`, `CanvasDimension`, etc.; utils `dataToGraphData`, `graphDataToData`, `getNodeDisplayText`, `getContrastTextColor`; layout helpers `getDagMode`, `pinAllNodes`, `unpinAllNodes`.

**Feeding data** (`setData`, simplified format):

```ts
type Node = {
  id: number | string;          // required, unique
  labels: string[];             // required
  color: string;                // required, hex or CSS color
  visible: boolean;             // required
  size?: number;                // default 9 (radius, world units)
  shape?: "circle" | "square";  // default circle
  caption?: string;             // property key for display text, default 'id'
  data: Record<string, unknown>;// required, properties
};
type Link = {
  id: number | string;          // required
  relationship: string;         // required, label on the edge
  color: string;                // required
  source: number | string;      // node id
  target: number | string;      // node id
  visible: boolean;             // required
  width?: number; fontSize?: number; arrowSize?: number;
  data: Record<string, unknown>;
};
```

Methods (selection): `setData`, `getData`, `setGraphData` (internal format, faster), `setConfig`, `setWidth`, `setHeight`, `setBackgroundColor`, `setForegroundColor`, `setLayout('force' | 'tree' | 'radial')`, `setLayoutOptions`, `setDimension('2d' | '3d')`, `refresh()` (repaint after in-place mutation of visibility/color/size), `getViewport`/`setViewport`, `zoom`, `zoomToFit(paddingMultiplier, filter)`, `getGraph()`.

**Events** (inside `setConfig({ eventHandlers })`):
`onNodeClick(node, event)`, `onNodeRightClick`, `onLinkClick(link, event)`, `onLinkRightClick`, `onNodeHover(node | null)`, `onLinkHover`, `onNodeDragEnd`, `onBackgroundClick`, `onBackgroundRightClick`, `onZoom...`, `onPinChange`.

**Highlighting a path (for "WhyPath"):** `nodeStyle`/`linkStyle` options plus `isNodeSelected(node)` and `isLinkSelected(link)` config callbacks; then `zoomToFit(padding, filter)`. Selected links draw thicker; selected nodes get an outline.

**Styling:** `backgroundColor`, `foregroundColor`, per-node `color`, `nodeStyle` (font, glow color, stroke widths), `linkStyle`, `captionsKeys`, `interaction` (tooltip styling), light/dark via colors. Custom node/link canvas renderers via `node` / `link` config (`node-mode` / `link-mode` attributes).

**Size:** `width`/`height` config defaults to the window size, and the CSS size of the element alone is not documented as enough. Put the element in a sized container and call `setWidth`/`setHeight` from a `ResizeObserver` (verify on first try).

**Minimal React example** (adapted from the package README, React 19 + TS):

```tsx
import { useEffect, useRef } from "react";
import "@falkordb/canvas";
import type { FalkorDBCanvas, Data, GraphNode } from "@falkordb/canvas";

export function MemoryCanvas({
  data,
  onNodeClick,
}: {
  data: Data;
  onNodeClick: (n: GraphNode) => void;
}) {
  const ref = useRef<FalkorDBCanvas>(null);

  useEffect(() => {
    ref.current?.setData(data);
  }, [data]);

  useEffect(() => {
    ref.current?.setConfig({
      backgroundColor: "#0b0d12",
      foregroundColor: "#e5e7eb",
      eventHandlers: { onNodeClick: (node) => onNodeClick(node) },
    });
  }, [onNodeClick]);

  return <falkordb-canvas ref={ref} style={{ width: "100%", height: "100%" }} />;
}
```

Fallback if `@falkordb/canvas` misbehaves: it already depends on `force-graph` (^1.44.4), which can be imported directly. Or draw the memory graph with `@xyflow/react` + a force layout.

**Sources:**
- npm: https://registry.npmjs.org/@falkordb/canvas/latest (v0.3.3, deps, exports, types)
- README and source: https://github.com/FalkorDB/falkordb-ui/tree/main/web-components/canvas (README.md, src/index.ts, package.json)
- Repo: https://github.com/FalkorDB/falkordb-ui

---

## 2. Commit DAG rendering

Candidates compared (versions as of 2026-10-16):

| Option | Latest | Last publish | React fit | Clickable nodes / highlight | Verdict |
|---|---|---|---|---|---|
| `@xyflow/react` (React Flow) + `@dagrejs/dagre` | 12.12.0 / 3.1.1 (dagre) | 2026-09-24 / 2026-08-08 | Native React components | Native `onNodeClick`, custom node components (Tailwind/shadcn), edge styling, pan/zoom, minimap | **Recommended** |
| `elkjs` | 0.12.0 | 2026-07-17 | Same as React Flow, needs async layout hook | Same as React Flow | Only if you need edge routing / ports. Bundle is ~8 MB unpacked; the xyflow docs note its bundle is much larger than dagre's and its docs are harder to navigate. |
| `gitgraph.js` | 1.15.2 | 2019-04-07 (metadata modified 2022) | Imperative canvas/SVG API, not React-native | Possible via its callbacks, but you own the React glue | **Reject.** Effectively unmaintained for years. |
| Custom SVG (lane algorithm) | n/a | n/a | Fully yours | Full control | Fallback. ~150 lines for git-log-style lanes; you write hit-testing, pan/zoom. |

**Recommendation for <200 commits with branch/merge + clickable nodes + highlighted paths: React Flow (`@xyflow/react`) with `@dagrejs/dagre` layout.**

Why:
- <200 nodes is well inside React Flow's comfortable range, and no virtualization is needed.
- Click selection, custom commit node components, highlighting an ancestor path (set `style`/`className` on the edges and nodes in the path), and pan/zoom come built in.
- dagre gives a layered top-to-bottom (`rankdir: 'TB'`) or left-to-right (`'LR'`) layout. Branch lanes are not preserved exactly, so if the "git look" matters, add a fixed lane x-offset per branch name after dagre runs.

Layout pattern (from the xyflow Layouting example; that example still imports the legacy `dagre` package, and the maintained package is `@dagrejs/dagre`, so verify the import form when installing):

```ts
import * as dagre from "@dagrejs/dagre"; // verify import shape on install
// graph = new dagre.graphlib.Graph(); graph.setDefaultEdgeLabel(() => ({}));
// graph.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 });
// nodes.forEach(n => graph.setNode(n.id, { width: 180, height: 56 }));
// edges.forEach(e => graph.setEdge(e.source, e.target));
// dagre.layout(graph);  then map graph.node(id).x/y to React Flow positions (center -> top-left)
```

Highlight-path ("WhyPath") logic: walk `parents` from the selected commit (or from the commit that caused a conflict) to collect an ancestor set; mark those nodes and edges as highlighted.

**Sources:**
- https://reactflow.dev/learn/layouting/layouting (dagre vs elkjs guidance; dagre favors speed, elk is more configurable and much larger)
- https://github.com/xyflow/xyflow/blob/main/examples/react/src/examples/Layouting/index.tsx (dagre layout code)
- https://github.com/dagrejs/dagre (README: `@dagrejs/dagre` is the maintained package)
- npm registry metadata for `@xyflow/react`, `@dagrejs/dagre`, `elkjs`, `gitgraph.js`
- https://github.com/nicoespeon/gitgraph.js (npm publish history: last publish 2019)

---

## 3. Scaffold: Vite + React + TypeScript + Tailwind v4 + shadcn/ui

Latest versions (2026-10-16):
- `create-vite` **9.2.1** (2026-09-10), engines `node ^20.19.0 || >=22.12.0`
- `vite` **8.3.4**, same Node engine range
- `@vitejs/plugin-react` **6.1.2** (2026-10-05), peer `vite ^8`
- `react` / `react-dom` **19.3.1**; `@types/react` **19.3.0**
- `typescript`: npm `latest` is **7.0.2**, but `openapi-typescript`'s peer range is `typescript ^5.x`. For a hackathon, **pin `typescript@~5.9.3`** (5.9.3 confirmed on npm). Use 7.x only if you want to check the ecosystem yourself.
- `tailwindcss` **4.3.3** and `@tailwindcss/vite` **4.3.3** (Tailwind docs show v4.3)
- `shadcn` CLI **4.21.5** (2026-10-14), engines `node >=20.18.1`
- `pnpm` **12.11.2**, engines `node >=18`

Commands (pnpm):

```bash
# 1. scaffold
pnpm create vite@latest web -- --template react-ts
cd web

# 2. Tailwind v4 via the Vite plugin
pnpm add tailwindcss @tailwindcss/vite
pnpm add -D @types/node
```

`vite.config.ts`:

```ts
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { proxy: { "/api": "http://localhost:8000" } }, // dev-only, avoids CORS
});
```

`src/index.css` (replace everything):

```css
@import "tailwindcss";
```

`tsconfig.json` and `tsconfig.app.json`, add under `compilerOptions`:

```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```

shadcn/ui (works with Tailwind v4 + the `@tailwindcss/vite` plugin):

```bash
pnpm dlx shadcn@latest init        # or: pnpm dlx shadcn@latest init -t vite
pnpm dlx shadcn@latest add button card badge scroll-area tabs
```

Compatibility notes:
- shadcn/ui's Vite guide uses exactly the v4 steps above (`@tailwindcss/vite` + `@import "tailwindcss";`) and the `@/*` alias. No Tailwind v3 config file is needed.
- Use `pnpm dlx shadcn@latest` (CLI 4.x), not `shadcn-ui`.

**Sources:**
- https://tailwindcss.com/docs/installation/using-vite (install command, plugin snippet, `@import "tailwindcss"`)
- https://ui.shadcn.com/docs/installation/vite (init command, alias config, `@tailwindcss/vite`)
- npm registry: `create-vite`, `vite`, `@vitejs/plugin-react`, `typescript`, `shadcn`, `pnpm`

---

## 4. Realtime: SSE vs WebSocket, plus TanStack Query

**Recommendation: Server-Sent Events (SSE) for server-to-client streams (agent token streaming + scorecard counters). Plain HTTP POST for user actions. Add WebSocket only if you need client-to-server messages during a stream (for example: interrupt or steer an agent mid-run).**

Why SSE for this app:
- Traffic is one-way (server pushes tokens and counter updates). SSE is exactly that.
- Browser `EventSource` reconnects automatically and supports `Last-Event-ID` resume. You write no reconnect logic.
- Plain HTTP: no WS upgrade, works through most proxies. FastAPI sends keep-alive pings and sets `X-Accel-Buffering: no`.
- FastAPI has native SSE support now, so there is no need for `sse-starlette` (though it still works; PyPI latest is 3.5.0).

FastAPI side (minimum FastAPI **0.135.0**; PyPI latest is **0.143.2**, requires Python >=3.10):

```python
from collections.abc import AsyncIterable
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

app = FastAPI()


class ScoreUpdate(BaseModel):
    agent: str
    score: int


@app.get("/api/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events(run_id: str) -> AsyncIterable[ServerSentEvent]:
    async for update in stream_for(run_id):  # your async generator
        yield ServerSentEvent(data=update, event="score", id=update.agent)
```

Pattern for agent runs (because `EventSource` is GET-only and cannot send a body or custom headers):
1. `POST /api/runs` with the user's message, returns `{run_id}`.
2. Client opens `new EventSource("/api/runs/{run_id}/events")` and listens for `message`, `score`, `token`, `done` events.
3. Close the source on `done` and in the effect cleanup (React 19 StrictMode double-mounts effects).

Client helper:

```ts
export function openRunStream(runId: string, onEvent: (type: string, data: unknown) => void) {
  const es = new EventSource(`/api/runs/${runId}/events`);
  for (const type of ["token", "score", "done"]) {
    es.addEventListener(type, (e) => onEvent(type, JSON.parse((e as MessageEvent).data)));
  }
  return () => es.close();
}
```

Authentication note: `EventSource` cannot send an `Authorization` header. If you need auth, use a same-origin session cookie, or a short-lived token in the query string.

**TanStack Query** (`@tanstack/react-query` **5.104.3**, published 2026-10-15; peer React ^18 or ^19): use it for REST snapshots (commit list, memory graph snapshot, scorecard initial state). Keep SSE events out of Query except to patch the cache: on `score` events, call `queryClient.setQueryData(["scorecard"], ...)` or `invalidateQueries`. For high-frequency token streams, keep the text in a small store (`zustand` **5.0.15**) rather than in Query.

**Sources:**
- https://fastapi.tiangolo.com/tutorial/server-sent-events/ (`fastapi.sse` imports, FastAPI 0.135.0 minimum, keep-alive ping, `Last-Event-ID`, POST example)
- PyPI: `fastapi` 0.143.2, `sse-starlette` 3.5.0
- npm registry: `@tanstack/react-query` 5.104.3, `zustand` 5.0.15
- EventSource limits (GET only, no custom headers, auto-reconnect) are standard browser behaviour, from general knowledge, not from a fetched source.

---

## 5. Typed API client from FastAPI OpenAPI

Latest: `openapi-typescript` **7.13.0**, `openapi-fetch` **0.17.0** (both 2026-02-11). Peer dep of `openapi-typescript`: `typescript ^5.x`.

```bash
pnpm add openapi-fetch
pnpm add -D openapi-typescript typescript@~5.9.3
mkdir -p src/api
pnpm openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

Add to `package.json` scripts so it regenerates after backend changes:

```json
"gen:api": "openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts"
```

`src/api/client.ts`:

```ts
import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL ?? window.location.origin,
});

// usage (route names are examples):
// const { data, error } = await api.GET("/api/commits");
```

Notes: the generator's docs example uses a local file path, and the URL input form comes from the same docs' example command. Verify with the running server on the first run. Use `pnpm gen:api` at the start of each backend change, and fail the build when `schema.d.ts` is stale if you have time.

**Sources:**
- https://openapi-ts.dev/openapi-fetch/ (install, `createClient<paths>`, typed `client.GET`)
- npm registry: `openapi-typescript` 7.13.0 (peer `typescript ^5.x`), `openapi-fetch` 0.17.0

---

## 6. Hosting: Vercel / Netlify / Cloudflare Pages vs FastAPI serving the build

**Recommendation for a 3-day hackathon: one deploy. FastAPI serves the built `web/dist` as static files on the same origin.** The UI and the API then share an origin, so SSE needs no CORS config, there's one URL for judges, and `pnpm build` is the only extra step.

FastAPI setup (mount **after** all API routes, or the mount shadows them):

```python
from fastapi.staticfiles import StaticFiles

app.mount("/", StaticFiles(directory="web/dist", html=True), name="web")
```

Gotchas:
- `StaticFiles(html=True)` serves `index.html` only for directory URLs. Deep links such as `/commits/abc` return 404 on refresh. Either keep the app single-route (state in Zustand, no router), or add a catch-all route that returns `index.html`.
- Keep the API under `/api/...` so the mount never collides with it.

Alternatives, if the backend cannot run on the same host:
- **Vercel** hosts static Vite builds for free. The Hobby plan limits for Python and Node functions are 300 s with Fluid compute, and streamed responses count toward that limit (per Vercel docs). That only matters if the backend runs on Vercel, which I do not recommend for SSE. Frontend-only on Vercel is fine, but then you need CORS and `VITE_API_URL`.
- **Netlify** and **Cloudflare Pages** are also fine for static builds. Their limits were not checked in this pass.

**Sources:**
- https://vercel.com/docs/functions/limitations (300 s Hobby limit with Fluid compute; streamed responses count toward it; found via web search, not fetched directly)
- https://fastapi.tiangolo.com/tutorial/server-sent-events/ (same-origin SSE; no separate hosting needed)
- Netlify / Cloudflare Pages limits: not verified.

---

## Recommendation

### Final frontend stack (pinned, as of 2026-10-16)

Runtime:
| Package | Version | Purpose |
|---|---|---|
| `react` | 19.3.1 | UI |
| `react-dom` | 19.3.1 | UI |
| `@xyflow/react` | 12.12.0 | Commit DAG (CommitDag, WhyPath highlights) |
| `@dagrejs/dagre` | 3.1.1 | DAG layout |
| `@falkordb/canvas` | 0.3.3 | Memory graph (MemoryCanvas) |
| `@tanstack/react-query` | 5.104.3 | REST data |
| `zustand` | 5.0.15 | Run/stream UI state |
| `openapi-fetch` | 0.17.0 | Typed API client |
| `tailwindcss` | 4.3.3 | Styling |

Dev:
| Package | Version | Purpose |
|---|---|---|
| `vite` | 8.3.4 | Build/dev server |
| `@vitejs/plugin-react` | 6.1.2 | React plugin |
| `@tailwindcss/vite` | 4.3.3 | Tailwind v4 plugin |
| `typescript` | ~5.9.3 | TS (pinned to 5.x for openapi-typescript peer range) |
| `openapi-typescript` | 7.13.0 | Generate types from FastAPI OpenAPI |
| `@types/react` | 19.3.0 | Types |
| `@types/node` | latest | `path` import in vite config |
| `shadcn` (CLI) | 4.21.5 | `pnpm dlx shadcn@latest add ...` |
| `create-vite` | 9.2.1 | Scaffold (`pnpm create vite@latest`) |

Package manager: `pnpm` 12.11.2 (Node >=18). Runtime: Node 20.19+ or 22.12+ (Vite 8 requirement).

### Proposed folder layout

```
web/
  index.html
  package.json
  vite.config.ts
  components.json                  # shadcn config
  tsconfig.json  tsconfig.app.json  tsconfig.node.json
  src/
    main.tsx
    App.tsx                        # 3-column shell: chat | center | scorecard
    index.css                      # @import "tailwindcss"; + theme tokens
    api/
      client.ts                    # openapi-fetch client
      schema.d.ts                  # generated by `pnpm gen:api` (do not edit)
      queries.ts                   # TanStack Query hooks (commits, memory, scorecard)
      stream.ts                    # openRunStream (EventSource wrapper)
    store/
      runStore.ts                  # zustand: active run, streamed tokens, scores
    lib/
      utils.ts                     # shadcn cn()
      dag.ts                       # dagre layout + ancestor-path highlight
      memory.ts                    # FalkorDB rows -> @falkordb/canvas Data
    components/
      ui/                          # shadcn generated primitives
      ChatPanel.tsx                # left: 3 agent threads, streaming tokens
      CommitDag.tsx                # center top: React Flow commit graph
      CommitNode.tsx               # custom React Flow node
      MemoryCanvas.tsx             # center bottom: <falkordb-canvas> wrapper
      ConflictCard.tsx             # shown in chat/DAG when a merge conflict is detected
      Scorecard.tsx                # right: live counters (SSE 'score' events)
      WhyPath.tsx                  # highlights the ancestor path in DAG + memory graph
    types/
      domain.ts                    # shared app types (commit, memory node, agent)
```

### Risks and fallbacks
- `@falkordb/canvas` 0.3.x is days old with ~2 GitHub stars. Keep a fallback path: import `force-graph` directly (already a transitive dependency), or render the memory graph with React Flow.
- `typescript` latest is 7.0.2. Stay on 5.9.x until typescript-eslint and openapi-typescript confirm 7.x support.
- gitgraph.js is not maintained (last publish 2019). Do not use it.
- Verify the `@dagrejs/dagre` import form and the `openapi-typescript` URL input on first install. Both are noted above.
