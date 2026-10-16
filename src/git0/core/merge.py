"""3-way semantic merge (M1, Person A, Phase 2). The hero feature: keep it in Cypher + pure Python.

Contract (agents, API and bench already code against this):

    async def plan_merge(repo, source: str, target: str) -> MergeResult
        1. base = repo.merge_base(source, target)
        2. checkout base, source and target; index each by Fact.key
        3. for each key changed since base on exactly one side -> auto_merged
           changed on both sides to the same value              -> auto_merged (dedupe)
           changed on both sides to different values            -> Conflict, strategy from (:Rule {p})
        4. attach dependents (cypher/dependents.cypher) for both sides and any (:Precedent)
        5. NO LLM call here. The decision is deterministic (M4); the Arbiter LLM only explains.

    async def apply_merge(repo, plan: MergeResult, choices: dict[str, str]) -> str
        One merge commit (two PARENT edges, ancestors = dedup of both sides) in ONE Cypher query.
        `choices` maps conflict key -> chosen fact id. Saves a (:Precedent) per resolved key.
"""

from git0.core.models import MergeResult
from git0.core.repo import MemoryRepo


async def plan_merge(repo: MemoryRepo, source: str, target: str) -> MergeResult:
    raise NotImplementedError("Phase 2 / Person A: see docs/team/person-a-graph-core.md")


async def apply_merge(repo: MemoryRepo, plan: MergeResult, choices: dict[str, str]) -> str:
    raise NotImplementedError("Phase 2 / Person A: see docs/team/person-a-graph-core.md")
