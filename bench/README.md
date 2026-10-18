# Benchmark (Person C)

Git0 vs last-write-wins vs text-git across scripted multi-agent scenarios.
Plan, scenario format and metrics: [docs/team/person-c-bench-concurrency.md](../docs/team/person-c-bench-concurrency.md).

**Status (2026-10-18): skeleton only.** There is no runner (`bench/run.py`) and no scenarios or results yet, so `make bench` fails. The concurrency proof that does exist is `tests/core/test_repo.py::test_concurrent_writers_lose_nothing` (20 writers, 0 lost), which runs in CI.

```bash
make bench     # planned: -> bench/results/<backend>/<scenario>.json
```
