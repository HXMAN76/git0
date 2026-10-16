# ADR 0003: Plain async agent loop (no LangGraph)

**Status:** accepted 2026-10-16 · **Owner:** Person B

## Context
Rule: the product must break without FalkorDB, and M2 says the graph is the only channel between agents. LangGraph + FalkorDBSaver adds a second state store (checkpoints) and makes the repo look like a framework wrapper.

## Decision
Each agent turn = `checkout(branch)` → one structured LLM call → one CAS commit. Orchestration is `asyncio.gather` over agents. Handoff = new agent checks out the dead agent's branch and reads `log`.

## Consequences
Fewer moving parts, and the "kill FalkorDB, agents know nothing" demo is true by construction. We write our own ~100-line loop.
