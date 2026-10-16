// name: merge_commit
// Atomic merge commit (one query = one transaction). CAS on the target HEAD: 0 rows back = target HEAD
// moved, caller re-diffs and retries. The merge commit has TWO parents (target head, source head) and its
// ancestors are the deduped union of both histories, so checkout (which reads Commit.ancestors) sees the
// union of both branches' facts with no extra work.
// $removed: fact ids the merge decided to hide (REMOVED_IN the merge commit). MERGE, not CREATE, so a fact
// already removed by this commit is not linked twice.
// $resolutions: one map per resolved conflict {key, p, side, base_id, ours_id, theirs_id}; ids may be null
// (a side that did not exist). Each becomes a Conflict node linked to its facts, plus a Precedent counter
// keyed by (predicate, chosen side) that the "learns from your resolutions" feature reads.
// NOTE: CALL {} unit subqueries, never a bare UNWIND: UNWIND [] drops the row and fakes a CAS failure.
MATCH (b:Branch {name: $target})-[r:HEAD]->(ht:Commit {id: $expected_target})
MATCH (hs:Commit {id: $source_head})
CREATE (n:Commit {id: $id, kind: 'merge', msg: $msg, ts: timestamp(), agent_id: $agent_id,
                  seq: CASE WHEN ht.seq > hs.seq THEN ht.seq ELSE hs.seq END + 1,
                  ancestors: list.dedup(ht.ancestors + hs.ancestors + [ht.id, hs.id])})
CREATE (n)-[:PARENT]->(ht)
CREATE (n)-[:PARENT]->(hs)
DELETE r
CREATE (b)-[:HEAD]->(n)
MERGE (a:Agent {id: $agent_id})
CREATE (a)-[:AUTHORED]->(n)
WITH n
CALL {
  WITH n
  UNWIND $removed AS rid
  MATCH (x:Fact {id: rid})
  MERGE (x)-[:REMOVED_IN]->(n)
}
CALL {
  WITH n
  UNWIND $resolutions AS r
  CREATE (cf:Conflict {key: r.key, status: 'resolved', side: r.side, ts: timestamp()})-[:RESOLVED_IN]->(n)
  WITH cf, r
  OPTIONAL MATCH (ours:Fact {id: r.ours_id})
  OPTIONAL MATCH (theirs:Fact {id: r.theirs_id})
  OPTIONAL MATCH (base:Fact {id: r.base_id})
  FOREACH (_ IN CASE WHEN ours IS NULL THEN [] ELSE [1] END | CREATE (cf)-[:SIDE_A]->(ours))
  FOREACH (_ IN CASE WHEN theirs IS NULL THEN [] ELSE [1] END | CREATE (cf)-[:SIDE_B]->(theirs))
  FOREACH (_ IN CASE WHEN base IS NULL THEN [] ELSE [1] END | CREATE (cf)-[:BASE]->(base))
  MERGE (pr:Precedent {key_pattern: r.p, choice: r.side})
  ON CREATE SET pr.count = 1
  ON MATCH SET pr.count = pr.count + 1
  CREATE (cf)-[:RESOLVED_BY]->(pr)
}
RETURN n.id AS id, n.seq AS seq
