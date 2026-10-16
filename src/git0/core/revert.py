"""revert: undo one commit with a new revert commit, cascading to facts derived from what it added."""

from git0.core.models import CommitRequest, Fact, NewFact, RevertResult
from git0.core.repo import CommitConflictError, MemoryRepo, new_id


async def revert(
    repo: MemoryRepo, branch: str, commit_id: str, agent_id: str = "human", retries: int = 8
) -> RevertResult:
    """Revert `commit_id` on `branch`: remove what it added (and anything derived from that), and bring back
    the values it replaced. History is never rewritten; the result is one new commit of kind "revert"."""
    for _ in range(retries):
        head = await repo.head(branch)
        if commit_id not in [*await repo.ancestors(head), head]:
            raise ValueError(f"commit {commit_id} is not in the history of {branch}")

        visible = {f.id: f for f in await repo.checkout(branch)}
        added, removed_by_commit = await repo.commit_changes(commit_id)
        reverted = [f.id for f in added if f.id in visible]

        # Dependents were derived from a value that is going away, so they go too (same rule as a merge).
        cascaded: dict[str, Fact] = {}
        for fid in reverted:
            for d in await repo.dependents_visible(fid, head):
                if d.id not in reverted:
                    cascaded[d.id] = d

        # Bring back a value the commit replaced, unless its key is still held by some other visible fact.
        gone = {*reverted, *cascaded}
        live_keys = {f.key for i, f in visible.items() if i not in gone}
        restore: dict[str, NewFact] = {}
        for old in removed_by_commit:
            if old.key not in live_keys and old.key not in restore:
                restore[old.key] = NewFact(
                    id=new_id(), s=old.s, p=old.p, o=old.o, confidence=old.confidence or 1.0
                )
        restored = list(restore.values())

        if not (reverted or cascaded or restored):
            raise ValueError("nothing to revert")

        done = await repo.try_commit(
            CommitRequest(
                branch=branch,
                agent_id=agent_id,
                kind="revert",
                msg=f"revert {commit_id}",
                removed=[*reverted, *cascaded],
                facts=restored,
            ),
            expected=head,
        )
        if done:  # None = HEAD moved under us: recompute everything against the new head
            return RevertResult(
                revert_commit=done.id,
                reverted=reverted,
                cascaded=list(cascaded),
                restored=[f.id for f in restored],
                unchanged=len(visible) - len(gone),
            )
    raise CommitConflictError(f"{branch}: HEAD moved {retries} times during revert")
