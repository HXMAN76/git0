# Git + GitHub workflow

Trunk-based with short-lived branches. **`main` is always deployable**: Railway auto-deploys every push to it, so a broken `main` breaks the live demo.

## Branches
- `main`: protected. PR + green CI required. Squash merge only.
- Work branches: `<person>/<phase>-<topic>`, e.g. `a/p1-merge-commit`, `b/p1-llm-client`, `c/p1-baselines`, `d/p0-railway`. Keep each one under ~4 hours of work. Open the PR early as a draft.
- Never commit straight to `main` (admins can bypass in an emergency. Post in the channel if you do).

## The loop for every task
```bash
git switch main && git pull --rebase
git switch -c a/p1-merge-commit
# test first (red) → code → green
make check                 # ruff + pytest (real FalkorDB) + web lint/test/build
git commit -m "feat(core): merge commit query with dedup ancestors"
git push -u origin HEAD
gh pr create --fill --draft      # mark ready when make check is green
gh pr ready && gh pr edit --add-reviewer <buddy>
# after approval + green CI:
gh pr merge --squash --delete-branch
```
If `main` moved under you: `git fetch && git rebase origin/main`, re-run `make check`, then `git push --force-with-lease`.

## Commit messages (Conventional Commits)
`feat(core): …` `fix(agents): …` `test(bench): …` `docs: …` `chore(ci): …` `perf(core): …`. Scopes: `core`, `cypher`, `llm`, `agents`, `mcp`, `api`, `web`, `bench`, `deploy`, `docs`.
Add an AI trailer when an assistant wrote a meaningful part: `Assisted-by: Claude Code`. Feeds the AI-disclosure section.

## Pull requests
- One task (one issue) per PR. Link it: `Closes #12`.
- Template checklist (`.github/pull_request_template.md`): `make check` green, Cypher in `cypher/` + `make cypher-docs`, contracts unchanged or team pinged, no fake fallback output, **you can explain every line**.
- Review buddy pairs: **A↔B, C↔D**. Target ≤ 30 min turnaround. The reviewer pulls the branch and runs the thing, not just reads it.
- Contract files (`core/models.py`, stub signatures, API routes, scenario schema) need **every consumer** tagged.

## CI (`.github/workflows/ci.yml`)
| Job | Steps |
|-|-|
| backend | `uv sync --frozen` → ruff check + format check → `docs/CYPHER.md` drift check → pytest against a `falkordb/falkordb` service container |
| web | pnpm install → lint → typecheck → vitest → build |

Tests marked `@pytest.mark.llm` are skipped in CI (no API keys in CI. The bench runs from the committed LLM cache).

## Integration cadence
- Pull `main` and run `make check` at least at every stand-up (09:00, 14:00, 21:00).
- Integration points I1/I2/I3 (see PHASES): merge whatever is green before them. Then the whole team clicks through the deployed flow.
- If an integration breaks `main`: **revert first** (`gh pr revert` or `git revert`), fix on a branch. Don't debug on `main`.

## GitHub setup (lead, once)
Run `scripts/github_setup.sh` after the repo exists. It creates labels, milestones (one per phase) and the Phase 0-1 issues, and turns on branch protection for `main` (needs a **public** repo on the free plan).

## Tags
`git tag g1 && git push --tags` at each passed gate (g0…g3) and `v1.0-submission` at submit. That gives the video and the judges a stable point.
