# Git for agent memory: deep design + must-haves to win Track 02 (2026-10-16)

> **Strategy doc (human reading: pitch, judge flow, video script).** Where it disagrees with the code, `docs/ARCHITECTURE.md` or an ADR, those win: e.g. no LiteLLM (ADR 0002), ancestors-list checkout (ADR 0001), AWS + Caddy deploy (ADR 0006).

> Working name in this doc: Membranch. The project is now called Git0.

Builds on [prior-art.md](prior-art.md) (prior art). Working name **Membranch** (check name is free before repo).

## 1. Thesis (one line)
**"Agents get their own memory branches. FalkorDB merges what they learned by meaning, not by text, and every answer shows the commit path it came from."**

Track 02 text: "remember across sessions and share state with each other... persist, update over time, available to every agent that needs it." Branch = private working memory, merge = sharing, history = persist + update over time. Fits the brief word for word.

## 2. Honest novelty check (read before pitching)
Judges have already seen two pieces we wanted to lead with:
- **Lethe** (Cognee hackathon grand winner, WeMakeDevs): verifiable forgetting with "Certificate of Erasure". So **forget receipt cannot be our headline**. Keep it as a small feature only.
- **Drift** (FalkorDB's own Memory Meets Motion standouts): decisions in a graph, flags when a later meeting contradicts an earlier one, human approval gate. So **"contradiction detector" alone is not new**.

What is new (no tool or past winner found doing it):
1. **Three-way semantic merge of agent memories** (merge base + both sides, conflicts by meaning, with dependents).
2. **Branch-per-agent as the coordination primitive** (agents never clobber each other; merging is the handoff).
3. **Revert that cascades across branches** through `DERIVED_FROM*`.
4. **Merge precedent**: past conflict resolutions are reused on the next conflict (experience compounds).
5. **Atomic compare-and-set commits** in one Cypher query, proven under concurrent agents.

Lead with 1 and 2. Everything else supports them.

## 3. MUST-HAVES (no-cut list)
If one of these is missing, we do not win. Ordered by impact.

| # | Must-have | Why judges care | Proof on screen |
|-|-|-|-|
| M1 | **Semantic 3-way merge with dependents** | The hero; nobody else has it | Conflict card: base value, A value, B value, dependent memories each side, author agent + source chat |
| M2 | **Graph is the only channel between agents** | Rule: product must break without FalkorDB | Agents read only `checkout(branch)`; no message passing. Kill FalkorDB = agents know nothing |
| M3 | **All 5 Track 02 focus items live, with a scorecard** | Matches the page checklist exactly | Side panel, each item with a live number (see section 4) |
| M4 | **Deterministic merge authority** | FalkorDB praised "deterministic Bailiff, not LLM" | Cypher rule engine decides auto-merge / needs-review; LLM only explains. Human clicks to resolve |
| M5 | **Why-path on every agent answer** | Organisers: "show the path behind an answer" | Click answer: Fact ← Commit ← Agent ← Session turn, path lit on canvas, query ms shown |
| M6 | **Concurrency proof** | "High-concurrency reads and writes" | Button: 20 agents commit at once; counter shows N commits, 0 lost, retries, p95 ms |
| M7 | **Tenant isolation by graph** | CEO blog: graph per tenant | Each visitor/team = own graph `team_<id>`; show a cross-tenant query returning nothing |
| M8 | **Measured benchmark vs baselines** | Lethe won with a benchmark; WeMakeDevs rewards measured proof | 30 scripted scenarios, JSON results in repo, table in README + video (section 6) |
| M9 | **Precedent / experience compounds** | FalkorDB praised MuscleMemory, Hopper precedent | 2nd similar conflict auto-suggests the earlier resolution: "resolved same way 3 times" |
| M10 | **No-path = proof + "not in memory"** | Hopper praised; WeMakeDevs blog trick | "Is X in team memory?" returns "no path from main HEAD" instead of a guess |
| M11 | **Live 60-second judge flow** | Our own hard rule | Link opens a seeded team room; judge triggers the conflict in 2 messages |
| M12 | **Fail loudly** | DealBench praised | No canned fallbacks; LLM error shows red banner, not fake output |
| M13 | **Submission basics** | Required | Public repo, README (setup in 3 commands, data model diagram, full Cypher list, AI disclosure, track), 3-min video, live URL |
| M14 | **Every teammate can explain the model + queries** | Rule: AI-only work may be rejected | 15-min walkthrough before recording |

Should-have (cut only if late): MCP server (so Claude Code/Cursor agents use Membranch as memory; Lethe had one), Python SDK `pip install`, forget/purge receipt, `algo.betweenness` "key memory" badge, blog post (AirPods).

Avoid: headlining forget, "contradiction detector" wording, "blast radius" wording (official WeMakeDevs demo), file-based storage, coding-agent memory as the story, canned demo, Graphiti/Mem0 wrapper.

## 4. Track 02 focus items mapped to features (M3 scorecard)
| Focus item | Our feature | Live number |
|-|-|-|
| Episodic memory | `(:Episode)` = each chat turn / tool call, linked to the commit it produced | episodes stored |
| Semantic memory | `(:Fact {s,p,o})` triples, visible per branch | facts on main |
| Procedural memory | `(:Rule)` merge rules + `(:Precedent)` learned resolutions, reused automatically | precedents reused |
| Persistent conversation history | `(:Session)-[:HAS_TURN]->(:Episode)`; restart app, agent resumes from `log` | sessions resumed |
| Shared state + handoffs | Kill agent mid-task; new agent checks out its branch, reads `log`, says what it inherited | handoffs done |
| High-concurrency R/W | CAS commit query + retry; load button | commits/s, lost = 0 |
| Separate memory per tenant | Graph per team | tenants live |

## 5. Graph model
```
(:Agent {id, name, role})
(:Session {id, started_at})-[:HAS_TURN]->(:Episode {id, text, ts})
(:Branch {name})-[:HEAD]->(:Commit)
(:Commit {id, seq, msg, ts, agent_id})-[:PARENT]->(:Commit)      // 2 parents on merge
(:Commit)-[:FROM_EPISODE]->(:Episode)
(:Agent)-[:AUTHORED]->(:Commit)
(:Fact {id, s, p, o, key: s+'|'+p, confidence, created_at, agent_id})
(:Fact)-[:ADDED_IN]->(:Commit)
(:Fact)-[:REMOVED_IN]->(:Commit)
(:Fact)-[:DERIVED_FROM]->(:Fact)                                // task "book venue Fri" derived from "launch=Fri"
(:Agent)-[:READ {ts}]->(:Fact)
(:Conflict {key, status})-[:SIDE_A|SIDE_B|BASE]->(:Fact)
(:Conflict)-[:RESOLVED_BY]->(:Precedent {key_pattern, choice, count})
(:Rule {p, strategy})          // e.g. deadline: needs-review; preference: latest-wins; owner: needs-review
```
Fixed predicate list (keeps LLM extraction reliable): `deadline, owner, status, location, budget, decision, preference, depends_on, contact`. Entity names normalised (lowercase, alias table).
Every node carries `agent_id, created_at, confidence` (CEO schema, judges will recognise it).

## 6. Core Cypher (draft, verify on FalkorDB day 1)
Each Commit stores `ancestors: [ids]` at creation (`dedupe(parentA.ancestors + parentB.ancestors + [parentA.id, parentB.id])`). Commits are immutable, so this never goes stale. It avoids path blow-up on merge-heavy DAGs (teammate review fix). Keep `PARENT` edges for the DAG view, why-paths and one showcase traversal.

Checkout (fast, used by agents):
```cypher
MATCH (:Branch {name:$b})-[:HEAD]->(h:Commit)
WITH h, h.ancestors + [h.id] AS anc
MATCH (f:Fact)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN DISTINCT f
```
Note: uses OPTIONAL MATCH + `none()` instead of `EXISTS { }`, because FalkorDB's Cypher coverage page does not list EXISTS subqueries. The teammate's version also had a precedence bug (`A OR B AND NOT ...` binds as `A OR (B AND NOT ...)`).

Checkout (showcase traversal, same result, in README):
```cypher
MATCH (:Branch {name:$b})-[:HEAD]->(h:Commit)
MATCH (h)-[:PARENT*0..200]->(a:Commit)
WITH collect(DISTINCT a) AS anc
MATCH (f:Fact)-[:ADDED_IN]->(c:Commit) WHERE c IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, anc, collect(r) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN f
```
Merge base becomes: intersect `ha.ancestors + [ha.id]` and `hb.ancestors + [hb.id]`, pick the highest `seq`.
Atomic commit with compare-and-set (FalkorDB runs each write query atomically, so this is safe under concurrency; 0 rows = HEAD moved, client rebases and retries):
```cypher
MATCH (b:Branch {name:$b})-[r:HEAD]->(h:Commit {id:$expected})
CREATE (n:Commit {id:$id, seq:h.seq+1, msg:$msg, ts:timestamp(), agent_id:$agent})-[:PARENT]->(h)
DELETE r
CREATE (b)-[:HEAD]->(n)
RETURN n.id
```
Merge base (latest common ancestor):
```cypher
MATCH (:Branch {name:$a})-[:HEAD]->(ha), (:Branch {name:$b})-[:HEAD]->(hb)
MATCH (ha)-[:PARENT*0..200]->(c:Commit)<-[:PARENT*0..200]-(hb)
RETURN c ORDER BY c.seq DESC LIMIT 1
```
Conflicts = facts changed since base on both sides with same key, different value (checkout of base, A, B, then join on `key`; heavy lifting in Cypher, join in Python or one query with `collect`).
Dependents of a fact (for conflict card and revert cascade):
```cypher
MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(f:Fact {id:$fid}) RETURN DISTINCT d
```
Why-path for an answer:
```cypher
MATCH p=(f:Fact {id:$fid})-[:ADDED_IN]->(:Commit)<-[:AUTHORED]-(:Agent),
      (f)-[:ADDED_IN]->(:Commit)-[:FROM_EPISODE]->(e:Episode)
RETURN p, e
```
No-path proof: `MATCH ... checkout(main) ... WHERE f.key=$key RETURN count(f)` = 0 → "not in team memory".
Precedent lookup: `MATCH (pr:Precedent) WHERE pr.key_pattern = $p RETURN pr ORDER BY pr.count DESC LIMIT 1`.
Optional: `CALL algo.betweenness` on Fact-DERIVED_FROM subgraph for "load-bearing memory" badge; `GRAPH.COPY` for "fork whole team memory" (tag/release).

Perf guardrails: index `Commit.id`, `Branch.name`, `Fact.key`; cap path depth 200; demo history < 1,000 commits; FalkorDB Cloud free = 100 MB, so tiny is fine. If checkout is slow, cache per-HEAD visible set as `(:Commit)-[:SNAPSHOT]->` edges every 50 commits.

## 7. Benchmark (M8)
Scenario suite: 30 scripted multi-agent stories (deadline change, owner swap, budget cut, wrong fact later reverted, concurrent edits). Same stories through 3 memory backends:
1. **Flat shared memory, last-write-wins** (Mem0-style).
2. **Text git** (files + line merge, like memgit/agmem behaviour: newest wins).
3. **Membranch** (graph 3-way semantic merge).

Metrics (JSON per scenario in `bench/results/`):
- silent overwrites (a fact lost with no warning)
- stale facts an agent acted on after a change
- conflicts caught / missed (precision, recall)
- dependent memories correctly invalidated after revert (precision, recall)
- lost commits under 20 concurrent writers
- tokens an agent needs to catch up after a handoff (log + checkout vs re-reading chat)
- p50/p95 ms for checkout, merge-base, merge

Script runs offline with cached LLM extractions so results are reproducible. Headline number for video: "last-write-wins silently lost 41% of changes; Membranch lost 0 and flagged every conflict" (fill with real numbers).

## 8. App + 60-second judge flow (M11)
Web app: left = team chat with 2-3 agents (Planner, Scheduler, Notes), each on its own branch; center = commit graph (DAG) + @falkordb/canvas memory view; right = Track 02 scorecard + query ms.
1. Judge opens link, gets own tenant graph seeded with a small team project (launch plan).
2. Types to Planner: "launch moved to Monday". Scheduler (on its branch) still has "Friday" and booked venue + emails off it.
3. Clicks **Merge to main**: rule engine says `deadline` needs review; conflict card shows base/A/B, 3 dependents each side, who said what, from which chat turn.
4. Picks Monday: only the 3 Friday-derived tasks are reverted/re-derived; "37 other memories unchanged". Precedent saved.
5. Asks any agent "when is launch?": answer + why-path lit. Asks "who is the caterer?": "not in team memory (no path)".
Extra buttons: "Kill Scheduler" (handoff), "20 agents at once" (concurrency), "Revert commit" (cascade).

## 9. 3-minute video script
0:00 problem: agents sharing one memory overwrite each other silently; give the benchmark number. 0:20 thesis line. 0:30 live flow steps 2-5. 1:40 handoff + concurrency buttons. 2:10 benchmark table + Cypher on screen with ms. 2:40 architecture + "remove FalkorDB and agents know nothing". 2:55 link + repo.

## 10. Build plan (4 people, Oct 16 afternoon to Oct 18 night IST)
| Person | Oct 16-17 morning | Oct 17 | Oct 18 |
|-|-|-|-|
| A: Cypher core | schema, indexes, commit CAS, checkout, log, merge-base + pytest | conflict detect, revert cascade, precedent, why-path | perf numbers, Cypher list for README |
| B: Agents + LLM | LiteLLM (Groq, Gemini fallback), fact extractor to fixed predicates, 3 agents reading checkout only | derived facts (tasks from facts), handoff flow, cached extractions | fail-loud errors, prompt polish |
| C: Bench + concurrency | scenario format, baselines 1 and 2 | 30 scenarios, 20-writer load test, JSON results | README results table, blog draft |
| D: UI + deploy | FastAPI + React skeleton, deploy FalkorDB Cloud + Render/Railway on day 1 (deploy early!) | chat, DAG view, conflict card, scorecard | video (record by Oct 18 noon IST), submit early |

Gates: Oct 17 10:00 IST = commit/checkout/merge-base working on deployed FalkorDB. Oct 17 22:00 IST = full 60 s flow works end to end. Oct 18 14:00 IST = video recorded. Submit by Oct 18 20:00 IST, not last hour.

Cut order if late: MCP server → forget receipt → betweenness badge → 3rd agent → GRAPH.COPY fork. Never cut M1-M8.

## 11. Risks + fixes
| Risk | Fix |
|-|-|
| Judges say "memgit clone" | First 20 s of video and landing page show the semantic conflict + dependents, never plain commit/log |
| LLM extracts same fact in different words, misses conflicts | Fixed predicates, alias table, extraction cached; benchmark uses cached outputs |
| Groq free rate limits during judging | Small prompts, one extraction call per message, Gemini Flash fallback, show limit errors loudly |
| Variable-length paths slow | Depth cap, indexes, snapshot edges, history small |
| Feels dev-only to non-dev judges | Team-project room story (launch plan) everyone understands; no git jargon in UI ("Planner and Scheduler disagree") |
| Track 01 blur | None: no external data retrieval; pure memory + coordination |
| "Graph is decoration" | All state lives only in FalkorDB; README section "what breaks without FalkorDB" |

## Sources
- Track 02 text, rules, FAQ: https://www.wemakedevs.org/hackathons/falkordb ; resources: https://www.wemakedevs.org/hackathons/falkordb/resources
- FalkorDB algorithms (BFS, SPpath, SSpath, PageRank, betweenness, WCC, CDLP, MaxFlow): https://docs.falkordb.com/algorithms
- Cypher functions (shortestPath, allShortestPaths, vecf32, none/any): https://new.docs.falkordb.com/cypher/functions
- GRAPH.COPY consistent snapshot: https://docs.falkordb.com/commands/graph.copy
- Judge taste (Lethe, Drift, Hopper, AgentCourt, MuscleMemory, CEO schema): falkordb-research.md sections 4, 20-22, 25; https://www.falkordb.com/blog/memory-meets-motion-the-falkordb-standouts/ ; https://www.falkordb.com/blog/ai-agent-memory-retrieval-architecture/
- Prior art table: git-for-memory.md

## 12. Teammate review (2026-10-16): what we adopt, change, reject
Review covered the older git-for-memory.md; several points were already in this plan (Session/HAS_TURN, concurrency button, tenant graphs). Checked against docs today.

| # | Teammate point | Verdict | Change to plan |
|-|-|-|-|
| 1 | Procedural memory missing | **Adopt, stronger.** Rule/Precedent was only merge logic | Add `(:Procedure {trigger, steps, agent_id, confidence})-[:ADDED_IN]->(:Commit)`, versioned like facts. Agent commits a learned workflow on its branch ("when launch date moves: notify QA lead, add 24h freeze"); after merge to main, other agents load procedures from checkout and follow them. Show "procedure adopted by 2 agents" on scorecard |
| 2 | Checkout path blow-up | **Adopt** (ancestors array) | Section 6 updated. Avoid `EXISTS {}` (not in FalkorDB Cypher coverage list: https://new.docs.falkordb.com/cypher/cypher-support.md). Fixed precedence bug in the suggested query |
| 3 | Entity normalisation | **Adopt** | Inject current entity list from checkout into the extraction prompt ("reuse an id from this list"). Use Groq `json_schema` strict mode, which only works on gpt-oss-20b/120b, qwen3.8-27b, muse-spark-open; other models only get `json_object` (valid JSON, schema not enforced) and no streaming/tool use with structured outputs (https://console.groq.com/docs/structured-outputs.md). So extractor = `openai/gpt-oss-20b` strict; validate with Pydantic anyway; alias table as backup |
| 4 | Arbiter agent | **Adopt** | Arbiter agent runs the diff: auto-merges non-colliding facts, blocks the PR on collisions, after the human picks it re-invokes only the owners of the invalidated derived tasks and lands one merge commit. The **decision** stays in Cypher rules + human (deterministic authority, M4); Arbiter LLM only writes the explanation |
| 5 | GRAPH.COPY fork button | **Adopt, but measure** | "Fork team memory to sandbox" button runs `GRAPH.COPY team_x team_x_sandbox` (consistent snapshot, https://docs.falkordb.com/commands/graph.copy). Do **not** claim "1-2 ms": no published number; show our measured ms. Check FalkorDB Cloud free tier allows it and has room (100 MB); else self-host FalkorDB in Docker on the same box |
| 6 | Enter Track 03 too | **Your call; I lean yes** | Track 03 focus includes "tracing decisions back to their source", "who owns what", "keeping knowledge current", "answers with clear sources". The team-room skin fits. Page says you may enter several tracks; it does not say whether one project can win two. Costs nothing; pitch stays Track 02 |

Wording fixes in the teammate's script:
- Don't say "blast radius" (official WeMakeDevs demo name). Say "what depends on it" / "ripple".
- Don't say "cryptographic receipt" unless we hash it. Cheap fix: receipt = SHA-256 of (fact id, purge commit id, zero-count query, timestamp), stored on the purge commit. Then the word is true.
- Don't say "commit simultaneously without locking". FalkorDB runs reads in parallel and **serialises writes**, each query atomic (https://new.docs.falkordb.com/design/concurrency.md). Correct claim: "parallel reads on snapshots; writes are atomic and ordered, and our compare-and-set commit means 0 lost updates". Multi-query transactions are not supported, so every commit must be ONE Cypher query (CAS + facts + edges together).
- Forget/purge stays a 10-second side feature (Lethe did it), not part of the hook.

## 13. Extra gaps found in this pass
1. **One-query commits.** Because FalkorDB has no multi-query transactions, the commit query must create the Commit, move HEAD (CAS), and write all Facts/Procedures/edges in a single UNWIND query. Design the payload for that from day 1.
2. **Re-derive cost.** Re-planning invalidated tasks calls the LLM. Limit to the invalidated set (usually 1-5), cache, show token count saved vs re-planning everything (benchmark metric).
3. **Public demo safety.** Each visitor gets a tenant graph with TTL (delete after 2 h) to fit 100 MB; rate-limit LLM calls per visitor; seed data loads on first visit.
4. **Session resume proof.** "Restart server" button (or reload) then agent answers from graph only; this is the cleanest "persists across sessions" proof.
5. **Scorecard must count real things**, read live from the graph by Cypher (not hard-coded). Judges may click through.
6. **README "remove FalkorDB" section** listing exactly which features die (checkout, merge, cascade, why-path, CAS, tenants).

## 14. Updated must-have list (delta)
- M1 now includes the **Arbiter agent** (auto-merge clean, block on conflict, targeted re-plan).
- M3 procedural = **Procedure nodes adopted after merge** (plus Precedent).
- M6 claim wording fixed (serialised atomic writes + CAS, parallel reads).
- New M15: **every commit is one atomic Cypher query**.
- New M16: **entity reuse + strict JSON extraction** (gpt-oss-20b on Groq).
- Should-have adds: GRAPH.COPY sandbox button with measured ms, hashed purge receipt, Track 03 declared.
