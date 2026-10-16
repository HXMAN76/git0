# Graph core walkthrough (15 minutes)

Script for the team session before the video. Goal: everyone can explain the graph model and the core
queries (rule M14), and can point at the file that runs each one. Section budgets add up to 15 minutes.

## Setup (once, before the session)

```bash
make db-up                                      # FalkorDB on localhost:6379
make api                                        # FastAPI on :8000
curl -s -X POST localhost:8000/api/demo/seed    # launch-plan room -> graph team_demo
```

Every `redis-cli` line below runs against `team_demo`. Use `valkey-cli` if `redis-cli` is not installed.
Everything here is read-only: the room does not change while you present.

## 1. The graph model (1 min)

One graph per team (`team_<id>`). Commits are nodes, facts are nodes, and history is edges.

```
(:Branch {name})-[:HEAD]->(:Commit {id, seq, msg, kind, agent_id, ancestors})
(:Commit)-[:PARENT]->(:Commit)                  two parents on a merge
(:Agent)-[:AUTHORED]->(:Commit)
(:Fact {id, s, p, o, key})-[:ADDED_IN]->(:Commit)
(:Fact)-[:REMOVED_IN]->(:Commit)                facts are never edited or deleted
(:Fact)-[:DERIVED_FROM]->(:Fact)
(:Commit)-[:FROM_EPISODE]->(:Episode)<-[:HAS_TURN]-(:Session)
(:Commit)<-[:RESOLVED_IN]-(:Conflict)-[:RESOLVED_BY]->(:Precedent)
(:Rule {p, strategy})
```

Try it: where each branch points.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (b:Branch)-[:HEAD]->(h:Commit) RETURN b.name AS branch, h.seq AS seq, h.msg AS msg, size(h.ancestors) AS ancestors ORDER BY seq"
```

Expect: `main` and `planner` at seq 1 (the kickoff), `scheduler` at seq 2.

## 2. The visibility rule (2 min) · `cypher/checkout.cypher`

A fact is visible on a branch when both are true:

1. It was added in a commit that is in `head.ancestors + [head]`.
2. No commit in that same list removed it.

That is the whole rule. A removal on another branch hides nothing here. A change to a fact is a `REMOVED_IN`
on the old fact plus a new `ADDED_IN` on a new fact, so history stays complete.

Try it: the scheduler branch sees the 37 facts on main plus its own 3.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (:Branch {name: 'scheduler'})-[:HEAD]->(h:Commit) WITH h.ancestors + [h.id] AS anc MATCH (f:Fact)-[:ADDED_IN]->(c:Commit) WHERE c.id IN anc OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit) WITH f, anc, collect(r.id) AS rs WHERE none(x IN rs WHERE x IN anc) RETURN count(DISTINCT f) AS visible_on_scheduler"
```

Expect: `40`.

## 3. Ancestors list vs PARENT walk (1 min) · ADR 0001

Each commit stores its full list of ancestor ids, set once when it is created. A merge uses the deduped union of
both histories. Commits never change, so the list never goes stale. Checkout reads the list instead of walking
edges. The alternative, `(h)-[:PARENT*0..200]->(a)`, blows up on merge-heavy history: many paths reach the same
commit (`docs/ARCHITECTURE.md` §3 measured 16.7M paths over 22 diamonds). The price of the list is memory that
grows with the square of the history (about 21 MB at 1000 commits). `PARENT` edges stay for the DAG view and the
why-paths.

Try it: the list and the walk give the same set. The walk includes the head itself, so the list gets `+ 1`.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (:Branch {name: 'scheduler'})-[:HEAD]->(h:Commit) MATCH (h)-[:PARENT*0..200]->(a:Commit) RETURN size(h.ancestors) + 1 AS from_list, count(DISTINCT a) AS from_walk"
```

Expect: `3` and `3`.

## 4. The CAS commit: one query (2 min) · `cypher/commit_cas.cypher`

A commit is one Cypher query:

1. `MATCH` the branch HEAD only if it still equals `$expected`. If HEAD moved, zero rows come back and nothing is written.
2. `CREATE` the commit, move HEAD, and write the author, session, episodes, facts, procedures, removals and
   `DERIVED_FROM` edges in the same query.

Why one query: FalkorDB has no multi-query transactions. One query runs atomically. Two queries could leave a
commit without its facts.

Why `CALL { ... }` blocks and not a bare `UNWIND`: `UNWIND []` drops the row. A commit with no facts would then
return zero rows even though it landed. The caller reads that as "HEAD moved", retries, and writes the commit a
second time. A unit subquery keeps the row. `MemoryRepo.commit` retries a missed CAS up to 8 times with backoff.

Try it: the CAS `MATCH` against a stale expected id returns zero rows. That is what a lost race looks like.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (b:Branch {name: 'main'})-[:HEAD]->(h:Commit {id: 'stale-expected-id'}) RETURN b.name AS branch"
```

Expect: an empty result set.

## 5. One visible value per key (1 min) · `cypher/commit_cas.cypher`

The key is `subject|predicate`, for example `launch|deadline`. A branch shows one value per key. When a commit
sets a new value, `commit_cas` finds the visible old fact with the same key and writes `REMOVED_IN` from the new
commit to it. The old fact stays in the graph. `CommitRequest` rejects two new facts with the same key in one
commit.

Try it: the launch deadline has one value, added by the kickoff commit and never removed.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (f:Fact {key: 'launch|deadline'})-[:ADDED_IN]->(c:Commit) OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit) RETURN f.o AS value, c.msg AS added_in, collect(r.msg) AS removed_in"
```

Expect: `friday | Kickoff: launch plan | []`. After a commit changes the deadline, the same query shows the old value
with `removed_in` filled in, and the new value on its own.

## 6. Merge and plan_merge (3 min) · `cypher/merge_commit.cypher`, `src/git0/core/merge.py`

A merge commit has two `PARENT` edges (target head and source head). Its ancestors are the deduped union of both
histories, so checkout already sees both branches' facts. The merge query only adds `REMOVED_IN` on the facts the
merge hides, fresh copies of facts it must restore, and `Conflict` nodes with `Precedent` counters. It is one
query with a CAS on the target head. If the target moved, zero rows come back and `apply_merge` raises
`CommitConflictError` (HTTP 409). There is no silent retry: re-plan.

`plan_merge` is read-only and deterministic, no LLM. It finds the merge base (highest `seq` common ancestor,
`cypher/merge_base.cypher`), reads the state at the base, target head and source head, and puts every key in
one bucket:

| Bucket | When | Result |
|-|-|-|
| unchanged | same value on base, target and source | nothing to do |
| dedupe | same new value on both sides, but two fact nodes | keep the target's copy, remove the source's |
| one-sided | only one side changed | auto-merged |
| same change | both sides made the same change | auto-merged |
| latest-wins | both changed, predicate is `latest-wins` | newer `created_at` wins; loser and its visible dependents removed |
| needs-review | both changed, predicate needs a human | `Conflict` with each side's dependents and any precedent |
| dependency | one side changed, the other kept the base value but gained facts derived from it | `Conflict` with `reason="dependency"` (unless latest-wins) |

Rules live in the graph (`cypher/rules.cypher`), so the decision is a query over data, not Python constants.

Try it (read-only API call): preview merging `scheduler` into `main`. The three scheduler facts are new keys
that only one side touched, so nothing conflicts.

```bash
curl -s -X POST localhost:8000/api/demo/merge/preview -H 'Content-Type: application/json' -d '{"source": "scheduler", "target": "main"}'
```

Expect: `auto_merged` holds 3 facts and `conflicts` is empty.

Rules the classifier reads:

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (r:Rule) RETURN r.p AS predicate, r.strategy AS strategy ORDER BY predicate"
```

Expect: 9 rows. `preference` and `status` are `latest-wins`; the other seven are `needs-review`.

## 7. Dependency conflicts and apply_merge (3 min) · `cypher/dependents.cypher`, `cypher/merge_commit.cypher`

Dependency example: `main` changes the launch deadline from friday to monday. The scheduler still has friday, and
it holds 3 facts derived from the friday fact. The values do not collide, so a plain 3-way merge would take main's
value and leave three stale facts behind. `plan_merge` returns a `needs-review` conflict with `reason="dependency"`
and lists the stale facts.

Try it: the facts derived from the launch deadline, which is what would go stale. This is the unfiltered
`cypher/dependents.cypher`, so it lists every derivation on every branch. `plan_merge` uses
`cypher/dependents_visible.cypher`, the same walk filtered to facts visible at each side's head.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(:Fact {id: 'seed-launch-deadline'}) RETURN d.key AS key, d.o AS value ORDER BY key"
```

Expect: 3 rows: `catering|deadline thursday`, `invites|status sent for friday`, `venue|status booked friday`.

`apply_merge` takes one choice per conflict in the API input: the id of one side's fact, or `__delete__`. Then it:

- removes the losing fact and its dependents on that side (the cascade). The winner survives,
- if the base-valued side wins a dependency conflict, makes a fresh copy of that fact. The other side already
  removed the base fact, so the union would hide it otherwise,
- reports `invalidated`: the dependents it removed. The Arbiter only re-derives those,
- writes a `Conflict` and a `Precedent` in the same merge query. A `Precedent` is keyed by predicate, and its
  `choice` is the side, not a fact id: `target` (ours), `source` (theirs) or `delete`. Its `count` goes up on
  every resolution. `plan_merge` shows the most-chosen side as a suggestion. It never decides.

Try it: saved precedents. A fresh room has none. Each human resolution adds one. For example, keeping the base
(friday) value on the dependency above saves `deadline | source | 1`.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (pr:Precedent) RETURN pr.key_pattern AS predicate, pr.choice AS choice, pr.count AS count ORDER BY count DESC"
```

Expect: an empty result on a fresh room.

## 8. Revert (1 min) · `core/revert.py`, `cypher/commit_changes.cypher`

Revert adds a new commit of kind `revert`. History is never rewritten.

- Facts the commit added and that are still visible are removed.
- Their visible dependents go too (`DERIVED_FROM` up to 6 hops).
- Values the commit replaced come back as fresh copies, unless another visible fact still holds that key.

Revert reads first, then writes one commit query with a CAS on HEAD. If HEAD moved, it recomputes and retries.

Try it: the facts the scheduler's own commit added. Reverting that commit removes exactly these.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (f:Fact)-[:ADDED_IN]->(c:Commit {msg: 'Book the venue and send invites for Friday'}) RETURN f.key AS key, f.o AS value ORDER BY key"
```

Expect: 3 rows, the same three facts as in section 7.

## 9. Scorecard (1 min) · `cypher/scorecard.cypher`

One read query feeds `GET /api/{tenant}/scorecard`: episodes, sessions, facts and procedures on main, commits
(every commit with a `kind`, so the init root is excluded), merges, reverts, handoffs, conflicts resolved,
precedents reused, agents. The API adds `tenants` from the graph list. `query_ms` is FalkorDB's own time.

Try it: commits by kind.

```bash
redis-cli GRAPH.QUERY team_demo "MATCH (c:Commit) WHERE c.kind IS NOT NULL RETURN c.kind AS kind, count(c) AS commits ORDER BY kind"
```

Expect: `seed | 2`.

## Quiz (8 questions)

1. What makes a fact visible on a branch?
   *Added in a commit in `head.ancestors + [head]`, and not removed by any commit in that same list.*
2. Why does each commit store its ancestor list instead of walking `PARENT*`?
   *The walk explodes on merge diamonds (many paths to one commit). The list is set once and never goes stale. The cost is memory, roughly N squared.*
3. Why must a commit be one query?
   *FalkorDB has no multi-query transactions. One query is atomic, so a commit can never land without its facts.*
4. Why `CALL { }` blocks instead of a bare `UNWIND` after the CAS?
   *`UNWIND []` drops the row. A landed commit then looks like a CAS miss, and the retry writes it twice.*
5. What happens to the old value when a commit sets a new value for a key?
   *`commit_cas` writes `REMOVED_IN` from the new commit to the visible old fact. The old fact stays.*
6. How does a merge commit make both branches' facts visible?
   *It has two parents, and its ancestors are the deduped union of both histories. The merge query only adds removals, restores and conflict records.*
7. What is a dependency conflict, and when does latest-wins remove the stale facts automatically?
   *One side changed a value and the other side gained facts derived from the old value. It needs review, unless the predicate is latest-wins, in which case the stale dependents are removed.*
8. What does `apply_merge` write, and what happens if the target moved after the plan?
   *One merge commit: removals for losers and their dependents, a restored copy if needed, and the Conflict and Precedent. If the target moved, it raises `CommitConflictError` (409) and the human must re-plan.*

## Where to look

| Topic | Query | Code |
|-|-|-|
| Visibility, checkout | `cypher/checkout.cypher` | `core/repo.py` `checkout` |
| Commit (CAS) | `cypher/commit_cas.cypher` | `core/repo.py` `try_commit`, `commit` |
| Merge commit | `cypher/merge_commit.cypher` | `core/repo.py` `try_merge_commit` |
| Merge plan and apply | `cypher/merge_base.cypher`, `dependents_visible.cypher`, `precedent_lookup.cypher` | `core/merge.py` |
| Revert | `cypher/commit_changes.cypher`, `dependents_visible.cypher` | `core/revert.py` |
| Scorecard | `cypher/scorecard.cypher` | `core/repo.py` `scorecard` |

Full query text: [`docs/CYPHER.md`](../CYPHER.md).
