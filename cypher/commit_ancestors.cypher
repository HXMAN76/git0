// name: commit_ancestors
// The immutable ancestor id list of commit $commit (empty for the root). revert uses it to check that the
// commit being reverted is actually on the branch history, without walking PARENT edges.
MATCH (h:Commit {id: $commit})
RETURN h.ancestors AS ancestors
