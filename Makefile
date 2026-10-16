# Thin wrappers so every teammate runs the same commands as CI.
.PHONY: setup db-up db-down db-ui api web test lint fmt check bench cypher-docs

setup:          ## install python + web deps
	uv sync
	cd web && pnpm install

COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; \
	elif podman compose version >/dev/null 2>&1; then echo "podman compose"; else echo "uvx podman-compose"; fi)

db-up:          ## start FalkorDB (docker compose, podman compose, or uvx podman-compose)
	$(COMPOSE) up -d falkordb

db-down:
	$(COMPOSE) down

api:            ## FastAPI on :8000 with reload
	uv run uvicorn membranch.api.app:app --reload --port 8000

web:            ## Vite dev server on :5173 (proxies /api -> :8000)
	cd web && pnpm dev

test:           ## needs FalkorDB on localhost:6379 (make db-up)
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd web && pnpm lint && pnpm typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

check: lint test  ## run before every push
	cd web && pnpm test && pnpm build

bench:          ## Person C: run the scenario suite, writes bench/results/*.json
	uv run python -m bench.run

cypher-docs:    ## regenerate docs/CYPHER.md from cypher/*.cypher
	uv run python scripts/gen_cypher_docs.py
