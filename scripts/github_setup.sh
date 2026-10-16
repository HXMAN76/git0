#!/usr/bin/env bash
# One-time GitHub setup: labels, phase milestones, Phase 0-2 issues, branch protection on main.
# Usage: scripts/github_setup.sh OWNER/REPO [--no-protect]
#   Branch protection needs a public repo (or GitHub Pro/Team). Pass --no-protect for a private repo on free.
set -euo pipefail
REPO="${1:?usage: $0 OWNER/REPO [--no-protect]}"
PROTECT=1
[[ "${2:-}" == "--no-protect" ]] && PROTECT=0

echo "== labels"
while IFS='|' read -r name color desc; do
  gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force >/dev/null
done <<'LABELS'
task|C5DEF5|Phase task
bug|D73A4A|Something broken
owner:A|5319E7|Graph core / Cypher
owner:B|FBCA04|Agents + LLM
owner:C|0E8A16|Bench + concurrency
owner:D|1D76DB|UI + API + deploy
must-have|B60205|M1-M16, never cut
should-have|D4C5F9|Cut if late
contract|E99695|Changes a shared contract, tag all consumers
LABELS

echo "== milestones"
ms() { gh api "repos/$REPO/milestones" -f title="$1" -f due_on="$2" -f description="$3" --jq .number 2>/dev/null \
       || gh api "repos/$REPO/milestones" --jq ".[] | select(.title==\"$1\") | .number"; }
M0=$(ms "P0 Setup"        "2026-10-16T12:30:00Z" "Gate G0: live /api/health, CI green, everyone runs tests")
M1=$(ms "P1 Foundations"  "2026-10-17T04:30:00Z" "Gate G1: commit/checkout/merge-base on deployed FalkorDB")
M2=$(ms "P2 Hero flow"    "2026-10-17T16:30:00Z" "Gate G2: full 60s judge flow on live URL")
M3=$(ms "P3 Harden+prove" "2026-10-18T06:30:00Z" "Gate G3: all must-haves ticked, benchmark final")
M4=$(ms "P4 Ship"         "2026-10-18T14:30:00Z" "Submitted by 20:00 IST")
echo "milestones: $M0 $M1 $M2 $M3 $M4"

echo "== issues"
issue() { # milestone owner extra_labels title body
  gh issue create --repo "$REPO" --milestone "$1" --label "task,owner:$2${3:+,$3}" --title "$4" --body "$5" >/dev/null
  echo "  [$2] $4"
}
issue "P0 Setup" A "" "Team walkthrough of commit_cas + checkout" "15-min call. Everyone can explain CAS + ancestors. See docs/team/person-a-graph-core.md"
issue "P0 Setup" B "" "Groq + Gemini keys, record real rate limits" "Fill docs/research/02-llm.md with numbers from console.groq.com/settings/limits; confirm Gemini model id."
issue "P0 Setup" C "" "bench/ skeleton + scenario schema agreed with A and B" "See docs/team/person-c-bench-concurrency.md (scenario format)."
issue "P0 Setup" D "must-have" "Railway: FalkorDB template + api service, /api/health live" "ADR 0004. Auto-deploy from main, TIMEOUT 5000, no sleep."
issue "P1 Foundations" A "must-have" "Seed (:Rule) + merge_commit query (one query, dedup ancestors)" "M4, M15. Test: merge commit visible from both sides, seq rule holds."
issue "P1 Foundations" A "must-have,contract" "plan_merge part 1: classify keys auto/conflict" "M1. Table test with 6 base/ours/theirs combos."
issue "P1 Foundations" B "must-have,contract" "llm/client.complete_json: Groq strict, Gemini fallback, cache, LLMError" "M12, M16. ADR 0002."
issue "P1 Foundations" B "must-have" "Extractor + Planner agent step (checkout -> extract -> commit)" "M2, M16. Cached fixtures."
issue "P1 Foundations" C "must-have" "Baselines LWW + text-git, runner writes JSON" "M8. 3 scenarios on both baselines."
issue "P1 Foundations" D "must-have,contract" "SSE agent message endpoint + 3-column shell + CommitDag from /log" "M11. pnpm gen:api after API change."
issue "P2 Hero flow" A "must-have" "plan_merge complete (dependents, precedent) + apply_merge + revert cascade" "M1, M4, M9."
issue "P2 Hero flow" A "must-have" "Scorecard counts query (all Track 02 items live)" "M3."
issue "P2 Hero flow" B "must-have" "Scheduler + Notes agents, derived tasks, Arbiter, handoff" "M1, M2, M3."
issue "P2 Hero flow" C "must-have" "30 scenarios + 20-writer load test + metrics JSON" "M6, M8."
issue "P2 Hero flow" D "must-have" "ChatPanel, ConflictCard, WhyPath, Scorecard wired" "M3, M5, M11."

gh repo edit "$REPO" --default-branch main >/dev/null
if [[ $PROTECT == 0 ]]; then echo "== skipping branch protection (--no-protect)"; echo "done: https://github.com/$REPO"; exit 0; fi
echo "== branch protection on main (required checks: backend, web)"
gh api -X PUT "repos/$REPO/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["backend", "web"] },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 1, "dismiss_stale_reviews": true },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "done: https://github.com/$REPO"
