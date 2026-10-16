# Git for agent memory: deep dive + Track 02 feasibility (2026-10-16)

> **Strategy doc (human reading: pitch, judge flow, video script).** Where it disagrees with the code, `docs/ARCHITECTURE.md` or an ADR, those win: e.g. no LiteLLM (ADR 0002), ancestors-list checkout (ADR 0001), AWS + Caddy deploy (ADR 0006).

> Working name in this doc: Membranch. The project is now called Git0.

## Verdict
**Yes, but only graph-native.** File/blob "git for memory" is crowded (6+ tools). Nobody does git semantics *on a graph*: semantic merge conflicts, dependency-aware revert, blame through derivation. FalkorDB makes that load-bearing. It also absorbs the "Undo" idea (revert = undo cascade, purge = provable forget). Feasible in 2.5 days with 4 people.

Score vs earlier picks (/10): Relatable 7 (devs high, normal users medium) · Track 02 fit 9 · Novelty 7 (graph-native) / 2 (if file-based) · Build 7 · Live 60 s 8.

## Prior art (checked today)
| Tool | What | Backend | Multi-agent | Gap |
|-|-|-|-|-|
| agmem (PyPI, MIT, v0.3.0 Feb 2026) https://pypi.org/project/agmem/ | commit/branch/merge/diff/blame/reset; merge by memory type (episodic append, semantic conflict markers) | files, SHA-256 objects | trust store, signed commits; federation is a stub | text-level conflicts, line blame, no dependency cascade |
| memgit https://glama.ai/mcp/servers/code4161/memgit | add/commit/log/diff/rollback/merge/squash, MCP+HTTP, Claude Code hooks | files (.toon blobs) | store lock, 3-way merge, newest wins | conflict = newest wins; no meaning |
| gitmem (PyPI, v0.1.0 Mar 2026) https://pypi.org/project/gitmem/ | init/commit/branch/merge/log | markdown files, "no database" | single agent | tiny |
| memov (188 stars) https://gittrend.io/repo/memovai/memov | git-like traceable memory for coding agents | ? | ? | coding-agent lane |
| Memoria by MatrixOrigin (271 stars, Apache-2.0) https://www.sourcepulse.org/projects/29043951 | snapshot/branch/merge/rollback | MatrixOne copy-on-write SQL | ? | SQL rows, not graph |
| grit-core (Rust, 0.4.0 Aug 2026) https://docs.rs/crate/grit-core/0.2.4 | bi-temporal graph, append-only op-log, as_of queries | SQLite | sync-ready (HLC) | no branch/merge, no Cypher |
| Graphiti/Zep bitemporal edges https://mintlify.com/getzep/graphiti/concepts/temporal-model | valid_at/invalid_at | Neo4j/FalkorDB | - | time travel only, no branches |
| Mintive "memory should live in git" https://www.mintmcp.com/blog/agent-memory-should-live-git | vendor argument for plain git repos | git | - | admits: concurrent updates need merge workflows; poisoning needs provenance |
| TerminusDB / Dolt | git for data (graph / SQL) | own DB | - | general DB, not agent memory |

Read: "git for memory" as a phrase is taken. Every existing tool treats memory as text/rows; merges are textual or newest-wins; revert undoes one commit but leaves memories derived from it.

## The gap we take
1. **Semantic conflict on merge.** Branch A: agent learned "launch = Friday". Branch B: "launch = Monday". Text merge sees two different lines; we see same (subject, predicate), different object since merge base = real conflict. Plus: dependents on each side (tasks scheduled off each fact).
2. **Dependency-aware revert.** Revert commit C removes its facts AND marks/re-derives every memory `DERIVED_FROM*` them, on every branch. No other tool does this.
3. **Blame through derivation.** Not "which line": "which agent, which commit, which source chat produced the fact that this answer rests on" = multi-hop path.
4. **Provable purge (forget).** `purge` removes a fact from all history + derived memories, then a no-path Cypher check returns 0 = receipt.
5. **Agents coordinate by branching.** Each agent works on its own branch (sandbox, no clobbering), opens a "memory PR" into team `main`; a human or reviewer agent merges. Clean Track 02 coordination story, no locks needed for reads.

## Why FalkorDB is load-bearing (not a wrapper)
Git itself is a DAG; memory is a graph; one FalkorDB graph holds both.
- `(:Commit {id, agent, msg, ts})-[:PARENT]->(:Commit)`; `(:Branch {name})-[:HEAD]->(:Commit)`
- `(:Fact {s,p,o})-[:ADDED_IN]->(:Commit)`, `-[:REMOVED_IN]->(:Commit)`
- `(:Fact)-[:DERIVED_FROM]->(:Fact|:Source)`; `(:Agent)-[:WROTE|READ]->(:Fact)`
- **checkout** = facts added in ancestors of HEAD minus removed: `MATCH (:Branch {name:$b})-[:HEAD]->(h)-[:PARENT*0..]->(c)<-[:ADDED_IN]-(f) WHERE NOT (f)-[:REMOVED_IN]->(:Commit)<-[:PARENT*0..]-(h) RETURN f`
- **merge-base** = lowest common ancestor via two variable-length `PARENT*` paths.
- **diff / conflict** = facts since merge base on each side, joined on (s,p) with different o.
- **revert cascade / blame / purge proof** = `DERIVED_FROM*`, `READ`, no-path count.
- Optional: `GRAPH.COPY` (consistent snapshot, https://docs.falkordb.com/commands/graph.copy) for cheap "fork whole tenant" / tag release; per-team graph = tenant isolation.
- Main implementation is our own Cypher layer = new work (rule OK).

## Feasibility (4 people, ~2.5 days left)
- Day 1 (Oct 16-17): graph schema + core ops in Python (commit, branch, checkout, log, diff, merge-base) with pytest; LLM fact extractor (Groq via LiteLLM) into fixed predicate list (deadline, owner, status, location, preference, decision) so (s,p) match is reliable.
- Day 2 (Oct 17): semantic merge + conflict UI, revert cascade, blame path, purge + receipt; 2-3 agents (planner, scheduler, notes) that read checkout of their branch.
- Day 3 (Oct 18): web app (FastAPI + simple React; commit DAG + @falkordb/canvas), deploy (FalkorDB Cloud free or Docker on Render/Railway/Fly), README with Cypher list, video.
- Split: A = Cypher core, B = merge/revert/purge, C = agents + LLM extract, D = UI + deploy + video.
- Risks: (1) LLM fact normalisation → fixed predicates + entity dedupe by name; (2) variable-length paths slow on deep history → cap depth, keep demo history < 500 commits, index Commit.id; (3) judges say "memgit clone" → open demo with the conflict + cascade, never with plain commit/log; (4) free tier graph count → one graph per team, branches as nodes, not GRAPH.COPY per branch.

## Live demo (60-90 s, judge drives)
1. Judge opens link, gets a team room with 2 agents, each on its own branch.
2. Tells agent A "launch is Friday", agent B "launch moved to Monday". Each plans tasks.
3. Clicks "Merge B into main": conflict card shows both facts + 3 dependent tasks each side, and which agent/chat caused each (blame path lit on canvas).
4. Picks Monday: only the 3 Friday-dependent tasks flip; 40 other memories untouched (count shown).
5. "Forget my phone number": purge + receipt "0 paths remain".

## Recommendation
Fold "Undo" into this: pitch = **"Git for agent memory, but it understands meaning."** Keep the Promise Graph team room as the app skin so non-dev judges relate. Don't build a file-based git clone.
