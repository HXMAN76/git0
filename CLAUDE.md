# Membranch: notes for AI coding assistants

Read `docs/ARCHITECTURE.md` first. Hard rules:

1. **All Cypher lives in `cypher/<name>.cypher`** with a `// name:` header and a comment saying why it exists. Load it via `membranch.core.queries.Q`. Never inline write queries in Python. Run `make cypher-docs` after any change.
2. **Every write is ONE query** (FalkorDB has no multi-query transactions). After a CAS `MATCH`, use `CALL { WITH n UNWIND ... }` unit subqueries, never a bare `UNWIND` (an empty list drops the row and fakes a CAS failure).
3. FalkorDB has **no `EXISTS {}`**. Use `OPTIONAL MATCH` + `collect` + `none()/any()`.
4. Agents read memory **only** via `MemoryRepo.checkout/log`. No caches, no direct agent-to-agent messages.
5. Merge decisions are deterministic (Cypher rules + human). The LLM only explains.
6. **Fail loudly.** Never return canned/fake output when an LLM or DB call fails. Raise (`LLMError`) and surface it.
7. Tests run against a real FalkorDB (`make db-up`). Do not mock the graph. Each test uses a throwaway graph (`tests/conftest.py`).
8. Shared contracts: `src/membranch/core/models.py`, stub signatures in `core/merge.py`, `llm/client.py`, `agents/base.py`. Don't change them without telling the user it affects other owners.
9. Before finishing: `make check`. Commit trailer `Assisted-by: Claude Code` when you wrote meaningful code.
10. The human owner must be able to explain what you wrote (hackathon rule). Keep code small and comment the *why*.
