// name: commit_changes
// What one commit changed: facts ADDED_IN and facts REMOVED_IN commit $commit, tagged by change type.
// revert needs both halves: the added facts get removed, the removed ones (e.g. the old value a new fact
// replaced) get restored. Not visibility-filtered: the caller intersects with the branch checkout.
MATCH (f:Fact)-[:ADDED_IN]->(:Commit {id: $commit})
RETURN 'added' AS change, f.id AS id, f.s AS s, f.p AS p, f.o AS o, f.key AS key, f.confidence AS confidence
UNION ALL
MATCH (f:Fact)-[:REMOVED_IN]->(:Commit {id: $commit})
RETURN 'removed' AS change, f.id AS id, f.s AS s, f.p AS p, f.o AS o, f.key AS key, f.confidence AS confidence
