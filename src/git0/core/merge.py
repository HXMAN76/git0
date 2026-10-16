"""3-way semantic merge (M1, Person A, Phase 2). Cypher does the graph work; this is pure Python on top.

plan_merge(repo, source, target) -> MergeResult
    Reads both heads and the merge base once, indexes each view by Fact.key and classifies every key:
    unchanged, auto-merged (one side changed, or both made the same change), latest-wins (per-predicate
    rule) or a needs-review Conflict that carries both sides' dependents and any past Precedent.
    A one-sided change is still flagged (reason="dependency") when the other side derived new facts from the
    value being replaced: they would auto-merge silently and go stale ("merge by meaning").
    Deterministic and read-only, no LLM call (M4).

apply_merge(repo, plan, choices, agent_id, msg) -> MergeApplied
    Turns the human's choices into ONE two-parent merge commit (repo.try_merge_commit). The commit's
    ancestors already contain both histories, so it only has to REMOVE the losing facts, their
    dependents (the cascade) and the plan's own removals. It also records a Conflict + Precedent per key.
"""

from git0.core.models import Conflict, Derivation, Fact, MergeApplied, MergeResult, MergeStrategy, NewFact
from git0.core.repo import CommitConflictError, MemoryRepo, new_id

DELETE = "__delete__"  # choice sentinel: drop both sides of a conflict


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
            if b and await _dependency(repo, plan, rules, key, b, t, s, source_changed=True):
                continue
            if s:
                plan.auto_merged.append(s)
            if t and b and t.id != b.id:  # a re-committed copy of the base value would outlive the change
                plan.removals.append(t.id)
        elif so == bo:  # only target changed
            if b and await _dependency(repo, plan, rules, key, b, t, s, source_changed=False):
                continue
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


async def _dependency(repo, plan, rules, key, b, t, s, source_changed: bool) -> bool:
    """One side (X) changed the value, the other (Y) kept the base value. Check Y for dependents it gained.

    Returns True when a needs-review dependency Conflict was appended (caller skips its one-sided handling).
    Under latest-wins the stale dependents are queued for removal and the caller proceeds as usual.
    """
    x, y = (s, t) if source_changed else (t, s)
    x_head, y_head = (
        (plan.source_head, plan.target_head) if source_changed else (plan.target_head, plan.source_head)
    )
    y_deps = await repo.dependents_visible(y.id, y_head)  # Y's value is the base value, so y exists
    if not y_deps:
        return False
    # Dependents that already existed at the merge base are shared history, not something Y added.
    at_base = {d.id for d in await repo.dependents_visible(b.id, plan.base_commit)}
    stale = [d for d in y_deps if d.id not in at_base]
    if not stale:
        return False
    if rules.get(b.p, MergeStrategy.NEEDS_REVIEW) == MergeStrategy.LATEST_WINS:
        plan.removals += [d.id for d in stale]
        plan.invalidated_auto += stale
        return False
    plan.conflicts.append(
        await _conflict(
            repo,
            plan,
            key,
            b.p,
            b,
            t,
            s,
            reason="dependency",
            stale=stale,
            stale_is_ours=source_changed,  # Y is the target (ours) when the source changed
            x_deps=await repo.dependents_visible(x.id, x_head) if x else [],
        )
    )
    return True


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
        deps = await repo.dependents_visible(loser.id, loser_head)
        plan.removals += [d.id for d in deps]
        plan.invalidated_auto += deps


async def _conflict(
    repo, plan, key, p, b, t, s, reason="value", stale=None, stale_is_ours=False, x_deps=None
) -> Conflict:
    """Build a Conflict. For "dependency": `stale` = Y's new dependents, `x_deps` = the changed side's."""
    prec = await repo.precedent(p)
    if reason == "dependency":
        deps_ours, deps_theirs = (stale, x_deps) if stale_is_ours else (x_deps, stale)
    else:
        deps_ours = await repo.dependents_visible(t.id, plan.target_head) if t else []
        deps_theirs = await repo.dependents_visible(s.id, plan.source_head) if s else []
    return Conflict(
        key=key,
        base=b,
        ours=t,
        theirs=s,
        strategy=MergeStrategy.NEEDS_REVIEW,
        reason=reason,
        dependents_ours=deps_ours,
        dependents_theirs=deps_theirs,
        precedent=f"{prec[0]} chosen {prec[1]}x" if prec else None,
        precedent_choice=prec[0] if prec else None,
        precedent_count=prec[1] if prec else 0,
    )


async def apply_merge(
    repo: MemoryRepo,
    plan: MergeResult,
    choices: dict[str, str],
    agent_id: str = "human",
    msg: str | None = None,
) -> MergeApplied:
    """Commit the merge. `choices` maps conflict key -> chosen fact id (ours.id / theirs.id) or DELETE."""
    by_key = {c.key: c for c in plan.conflicts}
    unknown = choices.keys() - by_key.keys()
    if unknown:
        raise ValueError(f"choices for keys with no conflict: {sorted(unknown)}")

    removed = list(plan.removals)
    winners: set[str] = set()
    # Dependents removed by the latest-wins cascade count too: the Arbiter re-derives every invalidated fact.
    dependents: dict[str, Fact] = {f.id: f for f in plan.invalidated_auto}
    resolutions = []
    restore: list[NewFact] = []
    derived: list[Derivation] = []  # lineage for the restored copies
    for key, c in by_key.items():
        if key not in choices:
            raise ValueError(f"no choice for conflict {key!r}")
        choice = choices[key]
        allowed = {f.id for f in (c.ours, c.theirs) if f} | {DELETE}
        if choice not in allowed:
            raise ValueError(f"choice {choice!r} for {key!r} is not one of {sorted(allowed)}")

        side = "delete" if choice == DELETE else "target" if c.ours and choice == c.ours.id else "source"
        # The losers go, and so does everything derived from them on their own branch: it was built on a value
        # that is no longer true. A kept side's dependents stay.
        if side != "target":
            removed += [c.ours.id] if c.ours else []
            removed += [f.id for f in c.dependents_ours]
            dependents.update({f.id: f for f in c.dependents_ours})
        if side != "source":
            removed += [c.theirs.id] if c.theirs else []
            removed += [f.id for f in c.dependents_theirs]
            dependents.update({f.id: f for f in c.dependents_theirs})
        if side != "delete":
            winners.add(choice)
            # Dependency conflict, base-valued side wins: the other side's commits REMOVED that fact, so the
            # merge union hides it. Re-create it as a fresh copy so the chosen value is actually visible. (A
            # re-committed copy of the base value has its own id, is not hidden, and needs no restoring.)
            w = c.ours if side == "target" else c.theirs
            if c.reason == "dependency" and c.base and w.id == c.base.id:
                copy = NewFact(id=new_id(), s=w.s, p=w.p, o=w.o, confidence=w.confidence or 1.0)
                restore.append(copy)
                derived += await repo.restore_links(w.id, copy.id)
        resolutions.append(
            {
                "key": key,
                "p": key.split("|", 1)[1],  # keys are `subject|predicate`
                "side": side,
                "base_id": c.base.id if c.base else None,
                "ours_id": c.ours.id if c.ours else None,
                "theirs_id": c.theirs.id if c.theirs else None,
            }
        )

    # A winner must survive even if it is also another loser's dependent or was queued for removal.
    removed = [i for i in dict.fromkeys(removed) if i not in winners]
    commit = await repo.try_merge_commit(
        target=plan.target,
        expected_target=plan.target_head,
        source_head=plan.source_head,
        removed=removed,
        resolutions=resolutions,
        msg=msg or f"merge {plan.source} into {plan.target}",
        agent_id=agent_id,
        facts=restore,
        derived=derived,
    )
    if commit is None:  # no silent retry: the human decided on a stale picture
        raise CommitConflictError("target moved since plan; re-plan")
    return MergeApplied(
        merge_commit=commit.id,
        removed=removed,
        invalidated=[f for i, f in dependents.items() if i in removed],
        restored=[f.id for f in restore],
    )
