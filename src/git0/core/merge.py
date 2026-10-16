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

from git0.core.models import Conflict, Fact, MergeResult, MergeStrategy
from git0.core.repo import MemoryRepo


def _by_key(facts: list[Fact], view: str) -> dict[str, Fact]:
    """Index a branch view by key. Invariant 7 says one visible value per key, so a duplicate is a bug."""
    out: dict[str, Fact] = {}
    for f in facts:
        if f.key in out:
            raise ValueError(f"{view}: two visible facts for key {f.key!r} (invariant 7 violated)")
        out[f.key] = f
    return out


def _value(f: Fact | None) -> str | None:
    return f.o if f else None


async def plan_merge(repo: MemoryRepo, source: str, target: str) -> MergeResult:
    """Classify every key as unchanged / auto / conflict. Deterministic, no LLM (M4).

    The merge commit's ancestors include both sides, so every change made since the base already applies.
    This only decides what the merge commit must additionally REMOVE, and which keys need a human.
    """
    # Read both heads once and view the graph at exactly those commits, even if branches move meanwhile.
    target_head, source_head = await repo.head(target), await repo.head(source)
    base_id = await repo.merge_base(source, target)
    base = _by_key(await repo.checkout_at(base_id), "base")
    ours = _by_key(await repo.checkout_at(target_head), target)
    theirs = _by_key(await repo.checkout_at(source_head), source)
    rules = await repo.rules()

    plan = MergeResult(
        source=source, target=target, base_commit=base_id, target_head=target_head, source_head=source_head
    )
    for key in sorted(base.keys() | ours.keys() | theirs.keys()):
        b, t, s = base.get(key), ours.get(key), theirs.get(key)
        bo, to, so = _value(b), _value(t), _value(s)

        # Same value on both sides but two nodes (both re-committed it): both would stay visible after the
        # union, so drop the source one. A node that is the base fact itself is removed by the other side.
        if t and s and to == so and t.id != s.id and (b is None or b.id not in (t.id, s.id)):
            plan.removals.append(s.id)

        if bo == to == so:
            plan.unchanged += 1
        elif to == bo:  # only source changed
            if s:
                plan.auto_merged.append(s)
            if t and b and t.id != b.id:  # a re-committed copy of the base value would outlive the change
                plan.removals.append(t.id)
        elif so == bo:  # only target changed
            if t:
                plan.auto_merged.append(t)
            if s and b and s.id != b.id:
                plan.removals.append(s.id)
        elif to == so:  # same change on both sides (possibly both deleted)
            if t:
                plan.auto_merged.append(t)
        else:
            p = (t or s).p
            if rules.get(p, MergeStrategy.NEEDS_REVIEW) == MergeStrategy.LATEST_WINS:
                await _latest_wins(repo, plan, t, s)
            else:
                plan.conflicts.append(await _conflict(repo, plan, key, p, b, t, s))
    # A loser's dependent can itself be a one-sided change (auto_merged) that latest-wins then removes.
    removed = set(plan.removals)
    plan.auto_merged = [f for f in plan.auto_merged if f.id not in removed]
    return plan


async def _latest_wins(repo: MemoryRepo, plan: MergeResult, t: Fact | None, s: Fact | None) -> None:
    """Newer fact wins, a deleted side loses, a created_at tie goes to the incoming (source) side."""
    if t and s:
        source_wins = (s.created_at or 0) >= (t.created_at or 0)
    else:
        source_wins = s is not None
    winner, loser, loser_head = (s, t, plan.target_head) if source_wins else (t, s, plan.source_head)
    plan.auto_merged.append(winner)
    if loser:
        plan.removals.append(loser.id)
        plan.removals += [d.id for d in await repo.dependents_visible(loser.id, loser_head)]


async def _conflict(repo, plan, key, p, b, t, s) -> Conflict:
    prec = await repo.precedent(p)
    return Conflict(
        key=key,
        base=b,
        ours=t,
        theirs=s,
        strategy=MergeStrategy.NEEDS_REVIEW,
        dependents_ours=await repo.dependents_visible(t.id, plan.target_head) if t else [],
        dependents_theirs=await repo.dependents_visible(s.id, plan.source_head) if s else [],
        precedent=f"{prec[0]} chosen {prec[1]}x" if prec else None,
        precedent_choice=prec[0] if prec else None,
        precedent_count=prec[1] if prec else 0,
    )


async def apply_merge(repo: MemoryRepo, plan: MergeResult, choices: dict[str, str]) -> str:
    raise NotImplementedError("Phase 2 / Person A: see docs/team/person-a-graph-core.md")
