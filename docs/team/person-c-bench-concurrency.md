# Person C: Benchmark + concurrency + write-up, Raghav N (@Rag-795)

**You own:** `bench/`, `scripts/`, the README results section, the blog post. **Buddy reviewer:** D.
**Your output is the headline number in the video.** Lethe won with a benchmark, so ours must be reproducible offline from the repo.

## Read first
`docs/research/05-agents-mcp-bench.md` (bench design, concurrency harness), winplan §7.

## Layout to build
```
bench/
  README.md            how to run + metric definitions
  scenarios/*.yaml     30 scripted multi-agent stories
  backends/base.py     Protocol: reset(), commit(agent, branch, facts), checkout(agent, branch), merge(src, dst) -> report
  backends/lww.py      baseline 1: one shared dict, last write wins (Mem0-style)
  backends/textgit.py  baseline 2: facts as lines in files + `git merge-file` (newest wins on conflict)
  backends/git0.py  MemoryRepo + plan_merge/apply_merge (from A)
  run.py               python -m bench.run [--scenario x] [--backend y] -> bench/results/<backend>/<scenario>.json
  load.py              20-writer concurrency test -> bench/results/concurrency.json
  report.py            results -> markdown table for README
  cache/               committed LLM extraction cache (offline, reproducible)
```

## Scenario format (agree with A + B in Phase 0)
```yaml
id: deadline-moved
description: Planner moves launch to Monday while Scheduler books venue on Friday
agents: [planner, scheduler]
steps:
  - {agent: planner,   branch: planner,   add: [[launch, deadline, fri]]}
  - {merge: planner -> main}
  - {agent: scheduler, branch: scheduler, add: [[venue, status, booked_fri]], derived_from: [launch|deadline]}
  - {agent: planner,   branch: planner,   change: [[launch, deadline, mon]]}
  - {merge: planner -> main}
  - {merge: scheduler -> main}
expect:
  conflicts: [launch|deadline]
  invalidated: [venue|status]
  final_main: {launch|deadline: mon}
```
Scenarios use structured facts directly (no LLM) so they're deterministic. A separate `--with-llm` mode feeds the raw chat text through B's extractor using the committed cache.

## Metrics (JSON per scenario)
silent overwrites · stale facts acted on · conflicts caught/missed (precision, recall) · dependents invalidated after revert (precision, recall) · lost commits under 20 writers · catch-up tokens after handoff (log + checkout vs full chat) · p50/p95 ms for checkout / merge-base / merge.

## Phase 0-1 (→ Oct 17 10:00)
- [ ] Scenario schema + 3 scenarios. `backends/base.py` + `lww.py` + `textgit.py`. `run.py` writes JSON
- [ ] `backends/git0.py` against the stub: until A's merge lands, mark merges `skipped`, not passed

## Phase 2 (→ Oct 17 22:00)
- [ ] 30 scenarios (deadline change, owner swap, budget cut, wrong fact later reverted, concurrent edits, handoff)
- [ ] `load.py`: N=20 async writers on one branch and on 20 branches. Record commits, lost, retries, p50/p95. The test in `tests/core/test_repo.py` is your seed
- [ ] Backend endpoint for the "20 agents at once" button (give D a function `run_load(tenant, n) -> dict`)

## Phase 3 (→ Oct 18 12:00)
- [ ] Final run. `report.py` → README table. Headline sentence with real numbers
- [ ] Blog post draft (AirPods side prize): problem → thesis → model → Cypher → numbers
- [ ] README: "Benchmark" + "How to reproduce" (3 commands)

## Phase 4
- [ ] Narrate the numbers in the video. Fresh-clone test of the README

## Explain-it test (M14)
What exactly counts as a "silent overwrite"? Why does LWW lose updates while CAS doesn't? Why do the results reproduce without an API key?
