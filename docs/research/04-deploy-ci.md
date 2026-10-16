# 04 - Deployment, CI and Team Workflow (hackathon)

Research date: 2026-10-16. Stack: FastAPI (Python 3.12, uv) + React static build + FalkorDB.
Goal: live public URL within 3 days, free or cheap, reliable during judging (no cold starts ideally).

Confidence legend: **[V]** verified on an official page during this research, **[S]** only from search snippets or third-party sites, **[I]** inference / my own recommendation. Items marked [S] or [I] must be checked before relying on them.

---

## 1. FalkorDB Cloud

| Item | Finding | Confidence |
|---|---|---|
| Free tier memory | 100 MB RAM; max graph dataset 100 MB | [V] https://docs.falkordb.com/cloud/tiers/free |
| Free tier idle policy | Instance not used for 1 day is **stopped**; deleted after 7 days of inactivity. Deleted data is unrecoverable | [V] same page |
| Free tier persistence | No snapshots, no backups, no persistence | [V] same page |
| Free tier TLS | **Not included** (TLS is a paid-tier feature) | [V] same page and https://www.falkordb.com/pricing |
| Free tier connections limit | Not stated anywhere found | [S] unknown |
| Free tier extras excluded | VPC, HA, multi-zone, cluster, advanced monitoring | [V] same page |
| Free tier support | Community only (support@falkordb.com, Discord); no credit card | [V] same page |
| Paid tiers (pricing page) | STARTUP "from $73/1GB/Month" (no backups every 12 h, TLS included); PRO "from $350/8GB/Month" (continuous persistence). The FAQ text on the same page gives different numbers, so treat prices as unverified | [V page] but [S] on exact figures |
| Regions | AWS or GCP; Azure is also listed. No regions named | [V] |
| Export/import | RDB export/import from the instance page: download link, S3, GCS. Scheduled exports are **Pro/Enterprise only** | [V] https://docs.falkordb.com/cloud/operations/export-import |
| TLS / connection string for Python | Docs say `falkor://`, `falkors://`, `redis://`, `rediss://` URLs are accepted (default port 6379). Exact cloud connection string and CA handling not found (the cloud connect page returned 404) | [S] https://docs.falkordb.com/browser/ui/login |
| Python client | Package `FalkorDB` on PyPI (`pip install FalkorDB`, optional `[hiredis]`). README shows `FalkorDB(host="localhost", port=6379)` and an async `connection_pool=` form. Its TLS options were not documented in the README. The Railway docs use `FalkorDB.from_url(os.environ[...])`, so `from_url` exists | [V] https://github.com/FalkorDB/falkordb-py (README), [V] https://docs.falkordb.com/operations/railway |
| GRAPH.COPY | Documented: `GRAPH.COPY <src> <dest>`. Source stays usable during copy. Copies nodes, edges, properties, indexes, constraints. Fails if destination exists (`GRAPH.DELETE` first). Python method is `copy`. **Cloud availability not confirmed**; the cloud docs never mention it | [V] https://docs.falkordb.com/commands/graph.copy, cloud: [S]/unknown |
| algo.* procedures | Documented: `algo.pageRank(label, relationship)` -> `node, score`; `algo.BFS` / `algo.bfs(start, max_depth, relationship)` -> `nodes, edges`. Docs disagree on casing and argument names (`max-level` vs `max_depth`), so test on your pinned version. Cloud availability not explicitly confirmed | [V] https://docs.falkordb.com/algorithms , https://docs.falkordb.com/cypher/procedures.html ; cloud: [S] |

**Verdict for judging:** FalkorDB Cloud free is **not suitable** as the production DB. It stops after 1 idle day (judges would hit a dead or waking instance), has no TLS (so the DB would be on the public internet unencrypted), and has no backups. Use a self-hosted FalkorDB container on Railway instead (section 4). Keep FalkorDB Cloud only as a dev sandbox if you want.

---

## 2. Railway

| Item | Finding | Confidence |
|---|---|---|
| FalkorDB template | Yes. Two official templates: **Single Instance** (https://railway.com/deploy/falkordb-graph) and **Cluster**. Single Instance includes a persistent volume and the browser UI | [V] https://docs.falkordb.com/operations/railway |
| Template variables | `FALKORDB_PRIVATE_URL` (use from other services in the project), `FALKORDB_PUBLIC_URL` (needs TCP proxy), `FALKORDB_PASSWORD`, `FALKORDB_HOST`, `FALKORDB_PORT`, `RAILWAY_PUBLIC_DOMAIN` (browser UI). Browser user is `default`. Internal host `falkordb.railway.internal`, internal port 16379 per docs | [V] same page |
| TLS on private network | Docs do not say whether the protocol endpoint uses TLS. Private traffic stays on Railway's internal network, so TLS is not needed there. Confirm the scheme in the copied URL | [V] gap noted |
| Pricing 2026 (official page fetch) | **Free** plan: $0, $1/month usage credit, 1 vCPU / 0.5 GB per service, 1 replica, 3-day logs. **Free Trial**: $0, one-time $5 credit for 30 days, no credit card, 2 vCPU / 1 GB. **Hobby**: $5/month incl. $5 usage, up to 48 vCPU / 48 GB per service, 6 replicas. **Pro**: $20/month per workspace, $20 usage | [V] https://railway.com/pricing (page had no date, so check it again before budgeting) |
| Usage beyond included credit | Billed per compute/memory/egress/volume usage on top of the plan | [S] third-party aggregators (https://livemy.app/blog/railway-pricing) |
| Dockerfile deploys | Railway builds a Dockerfile at repo root automatically; set `RAILWAY_DOCKERFILE_PATH` if it lives elsewhere. Provides `PORT` env var; bind `0.0.0.0` | [S] search snippets of https://docs.railway.app/guides/private-networking and https://blog.railway.com/p/deploy-scale-docker-containers-railway |
| Private networking | On by default. Each service gets a `*.railway.internal` DNS name resolving over IPv6. A service must listen on IPv6 (`::`) only if it *receives* private traffic. The API only makes outbound calls to FalkorDB, so it can listen on `0.0.0.0` | [S] https://docs.railway.app/guides/private-networking |
| Reference variables | Services reference each other with `${{service.VARIABLE}}` (e.g. `${{falkordb.FALKORDB_PRIVATE_URL}}`) | [I] standard Railway syntax, verify in the dashboard |
| Sleep / cold start on Hobby | Not verified. I believe serverless "sleep" is opt-in per service, so an always-on service should stay up. Verify the service setting before judging | [I] |

---

## 3. Render

| Item | Finding | Confidence |
|---|---|---|
| Free web service spin-down | Spins down after **15 minutes** without inbound traffic (WebSocket messages count as traffic). Reduced from 30 min on 2025-09-01 | [V] https://render.com/docs/free ; date [S] |
| Cold start time | "About one minute" per Render docs. Third-party sites say 30-60 s | [V] docs quote |
| Free hours | 750 instance hours per workspace per calendar month; unused hours don't roll over; when exhausted, all Free web services are suspended until next month | [V] https://render.com/docs/free |
| Free service types | Free instances only for **web services**, Render Postgres, Key Value and static sites. **Private services and background workers are not eligible** | [V] same |
| Free persistent disks | Not supported on free web services. Local files are lost on redeploy/restart/spin-down | [V] same |
| Free Postgres / Key Value | Postgres: 1 GB, expires after 30 days (+14 day grace). Key Value: in-memory, data lost on restart | [V] same |
| Persistent disks | Only on **paid** web, private, or background worker services (not cron). Price per GB/month: $0.25 | [V] https://render.com/docs/disks for scope; price [S] |
| Paid instance prices | Starter $7/month (512 MB, 0.5 CPU) is the smallest paid tier and also applies to private services | [S] third-party sites only; render.com/pricing could not be fetched |
| Workspace fee | Conflicting third-party numbers (Hobby $0 vs. Pro $25/mo). Check the live pricing page | [S] |
| Docker deploys | Supported (Render builds Dockerfiles); the free docs page did not address Docker specifically | [S] |
| Hosting FalkorDB | Possible as a **private service** from the `falkordb/falkordb` image with a disk. Not free: needs Starter ($7) + disk ($0.25/GB). No official FalkorDB Render template found | [I] based on the rules above |

**Verdict:** Render free web tier is acceptable for a dev preview but **will cold-start (about 1 min) during judging**, and its free tier cannot host the DB. Paid Render (web + private FalkorDB with disk) is workable but costs more than Railway Hobby.

---

## 4. Fly.io (brief alternative)

| Item | Finding | Confidence |
|---|---|---|
| Free tier | None for new orgs. Trial: up to 2 hours of Machine runtime or 7 days, whichever first; a credit card is needed to keep billable resources after the trial | [V] https://docs.fly.io/about/pricing |
| Machine prices | shared-cpu-1x 256 MB: $2.19/mo; shared-cpu-1x 512 MB: $3.69/mo (always-on, 30 days) | [V] same |
| Volumes | $0.15/GB/month provisioned | [V] same |
| Dedicated IPv4 | $2/mo optional. Shared IPv4 + IPv6 are free | [V] same |
| Snapshots | Volume snapshot storage $0.08/GB/mo after first 10 GB, billed since Jan 2026 | [V] same |
| Fit | No cold starts if Machines are always on. Needs `fly.toml`, Flycast private networking, and volume management for FalkorDB. More manual setup than Railway | [I] |

---

## 5. Recommended combo and cost

**Recommendation: Railway Hobby, one project, two services** (see section 9).
- Service A: `api` = FastAPI + built React, from the repo Dockerfile, public domain.
- Service B: `falkordb` = official Single Instance template, with volume, **no public domain**.

**Expected cost:** Hobby $5/month (includes $5 usage). Two small always-on services plus a few GB of volume should stay around **$5-10/month**, so roughly $10-15 for the whole hackathon. The number is an estimate, not a quote: check Railway's usage dashboard after day 1.

| Option | Always on? | Est. monthly | Verdict |
|---|---|---|---|
| FalkorDB Cloud free + Render free | No (cold start, 1 day idle stop) | $0 | Reject (no TLS, no backups, DB stops) |
| Render free web + FalkorDB Cloud free | No | $0 | Reject |
| **Railway Hobby + FalkorDB template** | Yes (verify sleep setting) | ~$5-10 | **Choose** |
| Render Starter web + private FalkorDB with disk | Yes | ~$15-20 + workspace fee [S] | Backup if Railway fails |
| Fly.io 2 x 512 MB Machines + 5 GB volume | Yes | ~$8-10 (+$2 if dedicated IPv4) | Backup, more manual |

---

## 6. Dockerfile for uv + FastAPI + static React

Verified pattern from the uv Docker guide (https://docs.astral.sh/uv/guides/integration/docker/): cache mounts, `--frozen`, `--no-install-project` for a dependency-only layer, `UV_LINK_MODE=copy`, `UV_COMPILE_BYTECODE=1`, venv copied to the runtime stage. I added a Node build stage and kept the same Python base in both Python stages so the venv path matches. Adjust paths to your package layout.

```dockerfile
# syntax=docker/dockerfile:1

# ---- 1. Build React (Vite/CRA style: outputs web/dist) ----
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---- 2. Resolve Python deps with uv ----
FROM python:3.12-slim-trixie AS builder
# Pin uv in production builds, e.g. ghcr.io/astral-sh/uv:0.x.y
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependency-only layer (cached until uv.lock / pyproject change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --no-editable
# Project layer
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- 3. Runtime ----
FROM python:3.12-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app/ ./app/
COPY --from=web --chown=app:app /web/dist ./static
USER app
EXPOSE 8000
# Railway/Render inject PORT; default 8000 locally
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`.dockerignore`:

```
.git
.venv
**/__pycache__
.pytest_cache
.ruff_cache
web/node_modules
web/dist
tests
*.md
```

**Serving the SPA from FastAPI.** Two options:

1. `app.frontend("/", directory="static", fallback="index.html")` ([V] https://fastapi.tiangolo.com/tutorial/frontend/). Path operations are checked first, so `/api/*` routes win. Fallback applies only to `GET`/`HEAD` requests that accept HTML. The page does not state the minimum FastAPI version, so check the release notes. The page also warns that with a `/` mount, unknown `/api/...` paths from a browser may return `index.html` instead of JSON 404. Mount API routes under `/api` and test it.
2. Manual catch-all (works on any FastAPI version):

```python
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI()

# ... include API routers under /api here ...

app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    candidate = (STATIC / full_path).resolve()
    if candidate.is_file() and STATIC in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(STATIC / "index.html")
```

Note: plain `StaticFiles(html=True)` does **not** give SPA fallback for client-side routes ([V] FastAPI static-files docs do not mention it; Starlette behaviour [I]). Use option 1 or 2.

---

## 7. GitHub Actions CI

Facts used:
- GitHub's service-container tutorial for Redis uses `--health-cmd "redis-cli ping"`, interval 10s, timeout 5s, retries 5, and maps `6379:6379` when the job runs directly on the runner ([V] https://docs.github.com/en/actions/tutorials/use-containerized-services/create-redis-service-containers).
- FalkorDB image `falkordb/falkordb` bundles server (6379) and browser UI (3000) ([V] https://docs.falkordb.com/operations/docker.html). Check that `redis-cli` exists inside the image, because the health check runs there. Verify with: `docker run --rm --entrypoint sh falkordb/falkordb:latest -c 'which redis-cli'`. If it's missing, use `--health-cmd "bash -c ':> /dev/tcp/127.0.0.1/6379'"` instead.
- Pin the `falkordb/falkordb` tag in production (`latest` is what the docs use). Browse Docker Hub for the version list [S].
- Action version tags below are from memory and should be checked against the Marketplace before merging.

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    name: backend
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      falkordb:
        image: falkordb/falkordb:latest        # pin a version in real use
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20
    env:
      FALKORDB_HOST: localhost
      FALKORDB_PORT: "6379"
      PYTHONUNBUFFERED: "1"
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Install Python 3.12
        run: uv python install 3.12

      - name: Sync dependencies (locked)
        run: uv sync --frozen

      - name: Ruff lint
        run: |
          uv run ruff check .
          uv run ruff format --check .

      - name: Pytest
        run: uv run pytest -q

  web:
    name: web
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4

      - name: Install pnpm
        uses: pnpm/action-setup@v4
        # version comes from "packageManager" in web/package.json if set

      - name: Install Node
        uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: web/pnpm-lock.yaml

      - name: Install
        run: pnpm install --frozen-lockfile

      - name: Lint
        run: pnpm lint

      - name: Build
        run: pnpm build

  docker:
    name: docker
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - name: Build image (no push)
        run: docker build -t hack-app:ci .
```

Ruff config goes in `pyproject.toml`, e.g.:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Required status check contexts for branch protection: `backend`, `web`, `docker` (the job `name:` values).

---

## 8. Branch protection, labels, issues, milestones via `gh`

**Plan requirements (important):**
- Branch protection and rulesets on a **private** repo need GitHub **Pro, Team, or Enterprise** ([V] https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches and managing-rulesets/about-rulesets). On GitHub Free, protection is available only on **public** repos.
- For a 4-person team on a private repo: GitHub Team (per-user price, [S] roughly $4/user/month, verify) or make the repo public.
- Actions minutes: free and unlimited on public repos; private repos get a monthly quota on Free [I, verify].

**Commands** (replace `OWNER`, `REPO`):

```bash
# 1. Create repo from local folder and push (public enables free protection)
gh repo create OWNER/REPO --public --source=. --remote=origin --push
#   private instead: gh repo create OWNER/REPO --private --source=. --remote=origin --push

# 2. Protect main: require PR, passing CI checks, allow admins to bypass
cat > /tmp/protect.json <<'EOF'   # use your scratchpad dir instead of /tmp in practice
{
  "required_status_checks": { "strict": true, "contexts": ["backend", "web", "docker"] },
  "enforced_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input /tmp/protect.json
```

Notes on step 2 [V in part]:
- `enforce_admins: false` lets repo admins bypass the rules. The GitHub API field name is `enforce_admins` (object or boolean). Use the value `false` to allow bypass. Check the response afterwards with `gh api repos/OWNER/REPO/branches/main/protection`.
- A PUT **replaces** the whole protection config. Always GET first and include every field you want to keep.
- Community reports say PATCHing `required_status_checks` fails if protection is not already on. Use the full PUT.
- Rulesets are the newer mechanism (`gh api repos/OWNER/REPO/rulesets --input ruleset.json`), and their `bypass_actors` can allow repo admins. Pick one mechanism and stick to it.
- Set the default branch to `main` before protecting it: `gh repo edit --default-branch main`.

```bash
# 3. Labels (idempotent with --force)
gh label create bug         --color D73A4A --description "Something broken"   --force
gh label create feature     --color A2EEEF --description "New capability"     --force
gh label create infra       --color 0E8A16 --description "Deploy, CI, infra"  --force
gh label create frontend    --color 1D76DB --description "React/web"          --force
gh label create backend     --color 5319E7 --description "FastAPI/graph"      --force
gh label create blocked     --color B60205 --description "Waiting on something" --force

# 4. Milestones (no gh subcommand; use the REST API)
gh api repos/OWNER/REPO/milestones -f title="Day 1: skeleton" -f due_on="2026-10-17T23:59:59Z"
gh api repos/OWNER/REPO/milestones -f title="Day 2: features" -f due_on="2026-10-18T23:59:59Z"
gh api repos/OWNER/REPO/milestones -f title="Day 3: deploy and demo" -f due_on="2026-10-19T23:59:59Z"

# 5. Issues (attach milestone by number; get it with: gh api repos/OWNER/REPO/milestones --jq '.[].number')
gh issue create --title "Deploy FalkorDB template on Railway" \
  --body "Single Instance template, volume on, no public domain" \
  --label infra --milestone "Day 3: deploy and demo" --assignee @me
```

Verify a PR flow end-to-end with a throwaway branch before the team starts: `git switch -c test/ci-check`, push, `gh pr create --fill`, then confirm the checks are required in the PR page.

---

## 9. docker-compose for local dev (works with podman-compose)

Local dev uses `falkordb` + `api` + `web`. The API container serves the built SPA from the same Dockerfile, so `web` in compose is the Vite dev server for hot reload. Vite needs a proxy to `api` (add in `web/vite.config.ts`: `server: { proxy: { "/api": "http://localhost:8000" } }` when running on host, or the service name when inside compose).

`compose.yaml`:

```yaml
name: hack

services:
  falkordb:
    image: falkordb/falkordb:latest          # pin in real use
    ports:
      - "6379:6379"                          # protocol
      - "3000:3000"                          # browser UI
    volumes:
      - falkordb-data:/data                  # confirm the data dir for this image
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20

  api:
    build: .
    environment:
      FALKORDB_HOST: falkordb
      FALKORDB_PORT: "6379"
      PORT: "8000"
    ports:
      - "8000:8000"
    depends_on:
      falkordb:
        condition: service_healthy           # podman-compose: verify this is supported in your version

  web:
    image: node:22-alpine
    working_dir: /web
    command: sh -c "corepack enable && pnpm install && pnpm dev --host 0.0.0.0"
    volumes:
      - ./web:/web
      - web-node-modules:/web/node_modules   # keep host node_modules out of the container
    ports:
      - "5173:5173"
    depends_on:
      - api

volumes:
  falkordb-data:
  web-node-modules:
```

Run: `docker compose up --build` or `podman-compose up --build`. For podman-compose, if `condition: service_healthy` is not supported in your version, start `falkordb` first, wait, then `up` the rest.

---

## 10. Recommendation

### Chosen topology

```
GitHub repo (main, protected, CI required)
   |  Railway GitHub deploy on push to main
   v
Railway project "hack"
  +-- service "api"       Dockerfile at repo root
  |     public domain: https://<name>.up.railway.app   (only public entry point)
  |     env: FALKORDB_URL = ${{falkordb.FALKORDB_PRIVATE_URL}}
  |     healthcheck path: /healthz
  |     serves /api/* and the React SPA from /static
  |
  +-- service "falkordb" Single Instance template (falkordb/falkordb image)
        volume: attached (persistence)
        NO public domain; TCP proxy disabled after setup
        reachable only at falkordb.railway.internal (private network)
```

- Public traffic: one domain, the `api` service.
- DB: private network only. Connect with the password in `FALKORDB_PRIVATE_URL`.
- Cost: Railway Hobby, about $5-10/month.

### Step-by-step deploy checklist

1. **Repo and plan.** Decide public vs private. Public = free branch protection. Private = GitHub Team.
2. **Code the deploy pieces.** Add `Dockerfile`, `.dockerignore`, `/healthz`, and SPA serving (section 6). Check that `/api/*` 404s return JSON.
3. **Local smoke test.** `docker build -t hack-app . && docker run --rm -p 8000:8000 -e FALKORDB_HOST=host.docker.internal hack-app`. Open `/`, refresh a client route, and hit `/healthz`.
4. **Verify FalkorDB image facts** (once): `redis-cli` present in image; GRAPH.COPY and algo procedures work on the pinned tag (`docker run -p 6379:6379 falkordb/falkordb:<tag>` then run the commands via `redis-cli`).
5. **CI.** Add `.github/workflows/ci.yml` (section 7), push a branch, and make sure `backend`, `web`, `docker` pass.
6. **Branch protection.** Run the `gh api -X PUT .../protection` command (section 8). Confirm with a GET. Open a test PR and check that merge is blocked until checks pass.
7. **Railway project.** Create project. Deploy the FalkorDB **Single Instance** template (https://railway.com/deploy/falkordb-graph). Copy `FALKORDB_PASSWORD` into your password manager (not into the repo). Do **not** generate a public domain for it.
8. **Railway api service.** New service from the GitHub repo. Set `FALKORDB_URL=${{falkordb.FALKORDB_PRIVATE_URL}}` (or the app's equivalent variables). Set healthcheck path `/healthz`. Generate a public domain.
9. **Trigger a deploy** and watch logs. Confirm the app connects to FalkorDB over the private URL. Run one graph write and read.
10. **Verify live.** `curl -fsS https://<domain>/healthz`, load `/`, refresh a deep SPA route, call one API route, run a `GRAPH.QUERY` smoke test.
11. **Persistence.** Confirm the volume is attached to the `falkordb` service. Restart the service once and check the data is still there. Schedule an RDB export or `BGSAVE` snapshot before judging (manual download is fine for a hackathon).
12. **Judging-day checks.** Turn off any auto-redeploy that could break the demo. Keep the last green deployment as a rollback target (Railway: redeploy previous). Check usage against the $5 credit.
13. **Fallback if Railway fails.** Render paid web + private FalkorDB with disk (about $15-20/month), or Fly.io (about $8-10/month). Keep the Dockerfile portable so either works.

### Open items to verify before day 2

- Railway serverless/sleep setting on the Hobby plan (judging needs always-on).
- Railway pricing page date and Hobby terms (fetch had no date).
- FalkorDB `GRAPH.COPY` and `algo.*` on the pinned Docker tag and on cloud (if cloud is ever used).
- Exact FalkorDB connection URL scheme and TLS for the Python client (`from_url` path).
- Render workspace fee and paid instance prices (render.com/pricing could not be fetched).
- Action version pins (`setup-uv`, `pnpm/action-setup`) and the uv image tag.

---

## Sources

Official / verified:
- https://www.falkordb.com/pricing
- https://docs.falkordb.com/cloud/tiers/free
- https://docs.falkordb.com/cloud/operations/export-import
- https://docs.falkordb.com/operations/railway
- https://docs.falkordb.com/operations/docker.html
- https://docs.falkordb.com/commands/graph.copy
- https://docs.falkordb.com/algorithms
- https://docs.falkordb.com/cypher/procedures.html
- https://github.com/FalkorDB/falkordb-py
- https://railway.com/deploy/falkordb-graph
- https://railway.com/pricing
- https://docs.railway.app/guides/private-networking (search snippet only)
- https://render.com/docs/free
- https://render.com/docs/disks
- https://docs.fly.io/about/pricing
- https://docs.astral.sh/uv/guides/integration/docker/
- https://fastapi.tiangolo.com/tutorial/static-files/
- https://fastapi.tiangolo.com/tutorial/frontend/
- https://docs.github.com/en/actions/tutorials/use-containerized-services/create-redis-service-containers (search snippet)
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches (search snippet)
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets (search snippet)

Secondary / search-only (treat as unverified):
- https://livemy.app/blog/railway-pricing
- https://livemy.app/blog/render-pricing
- https://temps.sh/blog/render-pricing-2026
- https://sota.io/blog/railway-vs-render-vs-fly-pricing-2026
- https://www.budgetforge.dev/tools/render-pricing-2026
- https://github.com/orgs/community/discussions/174419 (free private-repo branch protection request)
