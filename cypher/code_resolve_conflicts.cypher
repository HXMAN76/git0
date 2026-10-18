// name: code_resolve_conflicts
// The human's choice on a blocked write: sets resolution on each Conflict (pending -> adopt | override | pause).
// Why MATCH and not MERGE: a Conflict is created when the write is blocked, so an unknown id must not invent one.
// Why count(x): the caller gets back how many Conflicts matched, so a stale id is visible instead of silent.
UNWIND $ids AS cid
MATCH (x:Conflict {id: cid})
SET x.resolution = $resolution
RETURN count(x) AS n
