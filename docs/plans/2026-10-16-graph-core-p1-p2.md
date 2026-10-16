# Plan: Person A graph core, Phase 1 + 2 (issues #17 #5 #6 #11 #12 #18, prep for #1)

Spec: `docs/ARCHITECTURE.md` (graph model, invariants 1-8, REST contract table), `docs/team/person-a-graph-core.md`, `CLAUDE.md`. Strategy context (read only if needed): `docs/plan/WINPLAN.md` §1-6, §8.

Branch: `a/p1-p2-graph-core` (worktree `.worktrees/a-graph-core`). One PR closes #17 #5 #6 #11 #12 #18.

## Global Constraints
- Every query lives in `cypher/<name>.cypher` with `// name: <name>` header + a comment saying why. Python loads it via `git0.core.queries.Q[...]`. No write Cypher inlined in Python. Run `uv run python scripts/gen_cypher_docs.py` after adding/changing any `.cypher` file and commit `docs/CYPHER.md`.
- Every write = ONE Cypher query (FalkorDB has no multi-statement transactions). After a CAS `MATCH`, attach optional work with unit subqueries `CALL { WITH n UNWIND $list AS x ... }` (no RETURN inside). Never a bare `UNWIND` after the CAS (empty list drops the row and fakes a CAS failure). Aggregation (`WITH ..., collect(...)`) inside a unit `CALL {}` works (verified).
- FalkorDB has no `EXISTS {}`. Use `OPTIONAL MATCH` + `collect` + `none()`/`any()`. `list.dedup()` exists. Property values must be primitives or arrays of primitives.
- Visibility rule (same everywhere): fact F is visible at commit H iff F `ADDED_IN` a commit whose id is in `H.ancestors + [H.id]` and F has no `REMOVED_IN` to a commit in that list.
- Writes use `graph.query`, reads use `graph.ro_query`. Each `MemoryRepo` method = one query (a method may run one read to plan, then one write).
- Tests: pytest against real FalkorDB at `redis://localhost:6379` using the `repo` fixture in `tests/conftest.py` (fresh throwaway graph per test). Never mock the graph. Run `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .` before each commit. Line length 110.
- Contracts in `src/git0/core/models.py`: changes must be additive unless this plan says otherwise. Pydantic v2.
- Fail loudly: raise (`ValueError`, `KeyError`, `CommitConflictError`), never return fake/default data on errors.
- Commit messages: Conventional Commits, scope `core`/`cypher`/`api`/`docs`, body says why, trailer `Assisted-by: Claude Code`. One or more commits per task.
- Fixed predicates: `deadline, owner, status, location, budget, decision, preference, depends_on, contact`.
- Comment density like the existing code: short docstrings saying *why*, no line-by-line narration.

## Task 1: One visible value per key + commit kind (#17)

Files: `cypher/commit_cas.cypher`, `src/git0/core/models.py`, `src/git0/core/repo.py`, `tests/core/test_repo.py`.

1. In `commit_cas.cypher`, add a unit `CALL {}` block (place it BEFORE the block that creates new facts) that, for each new fact `f` in `$facts`, finds facts with `key = f.s + '|' + f.p` that are visible at the parent (ADDED_IN a commit whose id is in `n.ancestors`, not REMOVED_IN any commit in `n.ancestors`) and links them with `MERGE (old)-[:REMOVED_IN]->(n)`. Verified working shape:
   ```cypher
   CALL {
     WITH n
     UNWIND $facts AS f
     MATCH (old:Fact {key: f.s + '|' + f.p})-[:ADDED_IN]->(c:Commit)
     WHERE c.id IN n.ancestors
     OPTIONAL MATCH (old)-[:REMOVED_IN]->(r:Commit)
     WITH n, old, collect(r.id) AS rs
     WHERE none(x IN rs WHERE x IN n.ancestors)
     MERGE (old)-[:REMOVED_IN]->(n)
   }
   ```
   Also change the existing `$removed` block to use `MERGE` instead of `CREATE` for `REMOVED_IN` (so an explicit removal plus the automatic one never creates a duplicate edge).
2. Add a `kind` property on the commit node: `kind: $kind`. `CommitRequest` gets `kind: Literal["commit", "merge", "revert", "handoff", "seed"] = "commit"`; `MemoryRepo.try_commit` passes it. `Commit` model gets `kind: str | None = None`; `cypher/log.cypher` returns `c.kind AS kind`.
3. `CommitRequest` model validator: raise `ValueError` if two entries in `facts` share the same `(s, p)`.
4. Update the comment header of `commit_cas.cypher` to mention the one-value-per-key rule.
5. Tests: remove the `xfail` marker from `test_one_visible_value_per_key` (it must now pass). Add: (a) explicit removal + same-key add in one commit leaves exactly one `REMOVED_IN` edge on the old fact; (b) duplicate `(s, p)` in one `CommitRequest` raises `ValueError` (pydantic `ValidationError` is a `ValueError`); (c) `log()` returns `kind == "commit"` for a normal commit; (d) branch isolation: adding `launch|deadline=mon` on branch `b` does not hide `launch|deadline=fri` on `main`.
6. Update `docs/ARCHITECTURE.md` invariant 7: remove "Not enforced yet" text, say it is enforced in `commit_cas`.

## Task 2: Merge rules + merge commit + checkout at a commit (#5)

Files: new `cypher/seed_rules.cypher`, `cypher/merge_commit.cypher`, `cypher/checkout_commit.cypher`, `cypher/rules.cypher`; `src/git0/core/repo.py`; `tests/core/test_merge_commit.py`.

1. `seed_rules.cypher`: `UNWIND $rules AS r MERGE (x:Rule {p: r.p}) ON CREATE SET x.strategy = r.strategy RETURN count(x) AS rules`. Python constant `DEFAULT_RULES` in `repo.py`: deadline, owner, budget, decision, location, depends_on, contact = `needs-review`; preference, status = `latest-wins`. `MemoryRepo.init()` runs `init_repo` then `seed_rules` (both idempotent).
2. `rules.cypher` (read): `MATCH (r:Rule) RETURN r.p AS p, r.strategy AS strategy`. `MemoryRepo.rules() -> dict[str, str]`.
3. `checkout_commit.cypher` (read): identical to `checkout.cypher` but starts from `MATCH (h:Commit {id: $commit})`. `MemoryRepo.checkout_at(commit_id) -> list[Fact]`.
4. `merge_commit.cypher` (write, ONE query): CAS on the target branch (`MATCH (b:Branch {name: $target})-[r:HEAD]->(ht:Commit {id: $expected_target})`, `MATCH (hs:Commit {id: $source_head})`), create `n:Commit {id, kind: 'merge', msg, ts: timestamp(), agent_id, seq: max(ht.seq, hs.seq) + 1, ancestors: list.dedup(ht.ancestors + hs.ancestors + [ht.id, hs.id])}` with `PARENT` edges to both heads, move HEAD, `MERGE (a:Agent {id: $agent_id}) CREATE (a)-[:AUTHORED]->(n)`, then unit `CALL {}` blocks:
   - `$removed` (list of fact ids): `MATCH (x:Fact {id: rid}) MERGE (x)-[:REMOVED_IN]->(n)`.
   - `$resolutions` (list of maps `{key, p, side, base_id, ours_id, theirs_id}`; ids may be null): `CREATE (cf:Conflict {key: r.key, status: 'resolved', side: r.side, ts: timestamp()})-[:RESOLVED_IN]->(n)`, link `SIDE_A` to the ours (target) fact, `SIDE_B` to the theirs (source) fact, `BASE` to the base fact when the id is not null (use `OPTIONAL MATCH` + `FOREACH (_ IN CASE WHEN x IS NULL THEN [] ELSE [1] END | CREATE ...)`), then `MERGE (pr:Precedent {key_pattern: r.p, choice: r.side}) ON CREATE SET pr.count = 1 ON MATCH SET pr.count = pr.count + 1` and `CREATE (cf)-[:RESOLVED_BY]->(pr)`.
   - `RETURN n.id AS id, n.seq AS seq`. Zero rows = target HEAD moved.
   Verified: `list.dedup(a.ancestors + b.ancestors + [a.id, b.id])`, two `PARENT` edges, and the `MERGE ... ON CREATE SET ... ON MATCH SET` precedent pattern all work on FalkorDB 4.22.1. Max seq: `CASE WHEN ht.seq > hs.seq THEN ht.seq ELSE hs.seq END + 1`.
5. `MemoryRepo.try_merge_commit(target, expected_target, source_head, removed, resolutions, msg, agent_id) -> Commit | None` (None = target HEAD moved).
6. Tests (`tests/core/test_merge_commit.py`): merge commit makes source-only facts visible on target (union semantics through ancestors); a fact removed on source is hidden on target after merge; `$removed` hides a chosen fact; seq = max+1 and both parents present; stale `expected_target` returns None and writes nothing; resolutions create a `Conflict` + `Precedent` and a second identical resolution increments `count` to 2; `init()` seeds 9 rules and is idempotent; `checkout_at(base)` returns the base view.

## Task 3: plan_merge, deterministic 3-way classification (#6, part of #11)

Files: `src/git0/core/merge.py`, `src/git0/core/models.py`, new `cypher/dependents_visible.cypher`, `cypher/precedent_lookup.cypher`, `src/git0/core/repo.py`, `tests/core/test_plan_merge.py`.

Semantics (git-like): a merge commit's `ancestors` include both sides, so all changes made on either side since the merge base apply automatically. `plan_merge` only decides what the merge commit must additionally REMOVE, and which keys need a human.

1. Models (additive): `MergeResult` gains `target_head: str`, `source_head: str`, `removals: list[str] = []` (fact ids the merge commit will remove for auto-resolved keys), `unchanged: int = 0` (keys identical on base, target and source). `Conflict` gains `precedent_choice: str | None = None`, `precedent_count: int = 0`. Keep existing fields; `Conflict.ours` = target-side fact, `Conflict.theirs` = source-side fact.
2. `dependents_visible.cypher` (read): facts reached by `DERIVED_FROM*1..6` from `$fid` that are visible at commit `$head` (visibility rule). `MemoryRepo.dependents_visible(fact_id, head) -> list[Fact]`.
3. `precedent_lookup.cypher` (read): `MATCH (pr:Precedent {key_pattern: $p}) RETURN pr.choice AS choice, pr.count AS count ORDER BY pr.count DESC LIMIT 1`. `MemoryRepo.precedent(p) -> tuple[str, int] | None`.
4. `plan_merge(repo, source, target) -> MergeResult`: read target and source heads, `merge_base`, `checkout_at(base)`, `checkout(target)`, `checkout(source)`; index each by `key` (if a view has two facts for one key raise `ValueError` naming the key; invariant 7). Compare by VALUE (`o`, `None` when absent) per key in the union of keys:
   - base == target == source: unchanged (count it).
   - only one side differs from base: auto. Nothing to remove (ancestor union already applies it). Add the changed side's fact (if not None) to `auto_merged`.
   - both differ, target == source: auto dedupe. If both facts exist and are different nodes, add the source fact id to `removals`; add target fact to `auto_merged`.
   - both differ, values differ: look up strategy via `repo.rules()` (missing predicate = `needs-review`).
     - `latest-wins`: winner = the side whose fact has the larger `created_at`; a missing (deleted) side loses. Loser fact id (if any) plus the ids of its dependents visible on its own head go to `removals`; winner goes to `auto_merged`.
     - `needs-review`: append a `Conflict(key, base, ours, theirs, strategy=NEEDS_REVIEW, dependents_ours=dependents_visible(ours.id, target_head), dependents_theirs=dependents_visible(theirs.id, source_head), precedent_choice/precedent_count from repo.precedent(p), precedent=f"{choice} chosen {count}x" or None)`.
   - `Fact` needs `created_at` for latest-wins: add `created_at: int | None = None` to `Fact` (additive) and return `f.created_at AS created_at` from `checkout.cypher`, `checkout_commit.cypher`, `dependents_visible.cypher`.
   - No LLM call anywhere (M4).
5. Tests (`tests/core/test_plan_merge.py`), table-driven where possible, each building base on main, branching `source`, then committing on both: unchanged key counted; source-only change auto (no removals); target-only change auto; same change both sides dedupe (source id in removals); different change on `status` (latest-wins) resolved automatically with loser + its dependents in removals; different change on `deadline` gives one Conflict with base/ours/theirs values and dependents on each side; deletion on one side vs change on the other on `deadline` is a Conflict with one side None; precedent fields filled after a Precedent node exists.

## Task 4: apply_merge with cascade + precedent (#11)

Files: `src/git0/core/merge.py`, `src/git0/core/models.py`, `tests/core/test_apply_merge.py`.

1. Contract change (ruling): `apply_merge` returns a new model `MergeApplied(merge_commit: str, removed: list[str], invalidated: list[Fact])` instead of `str`. `invalidated` = dependents removed by the cascade (the Arbiter re-derives only these).
2. `apply_merge(repo, plan, choices: dict[str, str], agent_id: str = "human", msg: str | None = None) -> MergeApplied`:
   - `choices` maps conflict key to the chosen fact id (`ours.id` or `theirs.id`) or the sentinel `DELETE = "__delete__"` (export it). Raise `ValueError` if any needs-review conflict lacks a choice, or a choice is not one of the allowed values for that conflict.
   - For each conflict: losers = the non-chosen side facts (both if `__delete__`). Removed = losers + their dependents visible on their own head (`dependents_ours` / `dependents_theirs` already in the plan). side = `"target"`, `"source"`, or `"delete"`.
   - removed = `plan.removals` + conflict removals (dedup, keep order). invalidated = the dependent facts among them.
   - Call `repo.try_merge_commit(target=plan.target, expected_target=plan.target_head, source_head=plan.source_head, removed, resolutions=[{key, p, side, base_id, ours_id, theirs_id}], msg=msg or f"merge {plan.source} into {plan.target}", agent_id)`. If it returns None raise `CommitConflictError("target moved since plan; re-plan")`. Do not retry silently: the plan is stale.
3. Tests: full judge story: main base `launch|deadline=fri`; branch `planner` changes it to `mon`; branch `scheduler` (from same base) adds `venue|status=booked_fri` DERIVED_FROM the fri fact; merge `scheduler` into main first (auto, no conflict), then plan merge `planner` into main: one conflict on `launch|deadline` with the venue fact in `dependents_ours`; apply choosing planner's `mon` fact: main shows `mon`, venue fact is removed, `invalidated` == [venue fact], a `Precedent {key_pattern:'deadline', choice:'source', count:1}` exists, and a second plan on a similar conflict reports `precedent_count == 1`. Also: missing choice raises; stale plan (target committed after planning) raises `CommitConflictError`; `__delete__` removes both sides.

## Task 5: Revert with dependency cascade (#11)

Files: new `cypher/commit_changes.cypher`, `src/git0/core/repo.py` (or new `src/git0/core/revert.py`), `src/git0/core/models.py`, `tests/core/test_revert.py`.

1. `commit_changes.cypher` (read): facts `ADDED_IN` and `REMOVED_IN` commit `$commit` with id, s, p, o, key.
2. Model `RevertResult(revert_commit: str, reverted: list[str], cascaded: list[str], restored: list[str], unchanged: int)`.
3. `revert(repo, branch, commit_id, agent_id="human") -> RevertResult`, loop up to 8 attempts: read branch head H; raise `ValueError` if `commit_id` is not an ancestor of H (check via `checkout`/head ancestors, one read); visible = `checkout(branch)`; reverted = facts added in `commit_id` that are visible; cascaded = union of `dependents_visible(f, H)` for reverted facts, minus reverted; restored = for each fact removed in `commit_id` whose key is not visible after removing reverted+cascaded: a `NewFact` copy (new id, same s/p/o); write with `repo.try_commit(CommitRequest(branch, agent_id, kind="revert", msg=f"revert {commit_id}", removed=reverted+cascaded, facts=restored), expected=H)`; None = HEAD moved, recompute. `unchanged` = visible count minus reverted minus cascaded.
4. Tests: revert of the commit that set `launch|deadline=mon` (over an earlier `fri`) restores a `fri` copy and removes `mon`; a fact derived from `mon` (added later) is cascaded; unrelated facts unchanged and counted; reverting a commit not on the branch raises `ValueError`.

## Task 6: Seed the launch-plan room (#18)

Files: new `src/git0/seed.py`, `src/git0/api/app.py`, `tests/core/test_seed.py`, `tests/api/test_seed_api.py`.

1. `async def seed(repo: MemoryRepo) -> dict` builds the demo team room deterministically (fixed fact ids prefixed `seed-`), idempotent: if branch `scheduler` already exists return the summary without writing.
   - `repo.init()`; commit on `main` (agent `planner`, kind `seed`, one Episode in session `seed`, text "Kickoff: launch plan") with exactly 37 facts: `launch|deadline=friday` (id `seed-launch-deadline`), `launch|owner=asha`, `launch|location=hall b`, `launch|budget=50000 inr`, plus 33 more plausible launch-project facts using only the fixed predicates over entities such as website, press_kit, qa, beta, docs, demo_video, social, sponsors, swag, caterer_shortlist (each entity/predicate pair unique).
   - create branches `planner` and `scheduler` from main.
   - commit on `scheduler` (agent `scheduler`, kind `seed`, Episode text "Book the venue and send invites for Friday"): `venue|status=booked friday` (id `seed-venue-status`), `invites|status=sent for friday` (id `seed-invites-status`), `catering|deadline=thursday` (id `seed-catering-deadline`), each `DERIVED_FROM` `seed-launch-deadline`.
   - Return `{"created": bool, "branches": ["main", "planner", "scheduler"], "facts_on_main": 37, "facts_on_scheduler": 40}` (compute counts from checkout, don't hard-code).
2. `POST /api/{tenant}/seed` in `api/app.py` calls `seed()` on the tenant repo (ensure_schema too) and returns the dict.
3. Tests: seed twice gives `created` True then False and identical counts; scheduler dependents of `seed-launch-deadline` are the 3 derived facts; API test via `TestClient` on tenant `ci_seed` (delete the graph `team_ci_seed` at the end of the test).

## Task 7: Live scorecard (#12)

Files: new `cypher/scorecard.cypher`, `src/git0/core/models.py`, `src/git0/core/repo.py`, `src/git0/api/app.py`, `tests/core/test_scorecard.py`.

1. `scorecard.cypher` (read, ONE query) returns: `episodes`, `sessions`, `facts_on_main` (visible on main), `procedures_on_main`, `commits`, `merges` (kind merge), `reverts` (kind revert), `handoffs` (kind handoff), `conflicts_resolved`, `precedents_reused` (sum of `count - 1` over Precedent nodes with count > 1), `agents`. Use chained `OPTIONAL MATCH ... WITH count(...)` or returning `CALL {}` subqueries, whichever works on FalkorDB; empty graph must return zeros, not zero rows.
2. Model `Scorecard` with those int fields plus `tenants: int` and `query_ms: float`. `MemoryRepo.scorecard() -> Scorecard` (tenants filled by the API layer; `query_ms` from the result's internal execution time, `result.run_time_ms` in falkordb-py).
3. `GET /api/{tenant}/scorecard` returns `Scorecard` with `tenants` = number of graphs whose name starts with `settings.tenant_graph_prefix`.
4. Tests: empty repo gives zeros; after a few commits, a merge, an episode and a resolved conflict the counts match.

## Task 8: Merge, revert and procedures endpoints

Files: `src/git0/api/app.py`, `tests/api/test_merge_api.py`. Matches the REST table in `docs/ARCHITECTURE.md` §6 (update its Status column to `done` for the rows this task and Tasks 6-7 deliver).

1. `POST /api/{tenant}/merge/preview` body `{source, target}` returns `MergeResult` (ValueError gives 400).
2. `POST /api/{tenant}/merge/resolve` body `{source, target, choices: dict[str, str], agent_id: str = "human"}`: re-plan, then `apply_merge`; returns `MergeApplied`. Invalid/missing choices give 400; `CommitConflictError` gives 409.
3. `POST /api/{tenant}/revert` body `{branch, commit_id, agent_id = "human"}` returns `RevertResult` (ValueError gives 400).
4. `GET /api/{tenant}/branches/{name}/procedures` returns `list[Procedure]`.
5. Request bodies as Pydantic models in `api/app.py`. Tests via `TestClient` on tenant `ci_merge` (delete `team_ci_merge` afterwards): seed, commit Monday on planner via `POST /commits`, merge scheduler then preview planner, resolve choosing planner's fact, check `invalidated` has 3 facts and `/scorecard` shows 1 resolved conflict.

## Task 9: Graph-core walkthrough doc (prep for #1)

File: new `docs/team/walkthrough-graph-core.md`.

A 15-minute script Hari can present so every teammate can explain the model (M14): graph model diagram, the visibility rule, ancestors vs PARENT walk (ADR 0001), CAS commit and why one query, one-value-per-key, merge = ancestor union + removals, plan_merge classification table, apply_merge cascade + precedent, revert, scorecard. For each, the `cypher/` file name and one `redis-cli GRAPH.QUERY` the reader can paste against a seeded tenant (`team_demo` after `POST /api/demo/seed`). End with 8 quiz questions with short answers. Only describe what the code on this branch actually does (read the files).
