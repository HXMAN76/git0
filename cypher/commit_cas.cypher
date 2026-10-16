// name: commit_cas
// Atomic compare-and-set commit (M15: one query = one transaction).
// Moves HEAD only if it still points at $expected; 0 rows back = HEAD moved, caller rebases + retries.
// Writes the commit, author, session + episodes, facts, procedures, removals and DERIVED_FROM edges together.
// NOTE: use CALL {} unit subqueries, never a bare UNWIND: UNWIND [] drops the row and a successful
// commit would look like a CAS failure (verified on FalkorDB, see docs/research/01-falkordb.md).
MATCH (b:Branch {name: $branch})-[r:HEAD]->(h:Commit {id: $expected})
CREATE (n:Commit {id: $id, seq: h.seq + 1, msg: $msg, ts: timestamp(), agent_id: $agent_id,
                  ancestors: h.ancestors + [h.id]})-[:PARENT]->(h)
DELETE r
CREATE (b)-[:HEAD]->(n)
MERGE (a:Agent {id: $agent_id})
CREATE (a)-[:AUTHORED]->(n)
WITH n
CALL {
  WITH n
  UNWIND $episodes AS e
  MERGE (s:Session {id: e.session_id})
  ON CREATE SET s.started_at = timestamp()
  CREATE (ep:Episode {id: e.id, text: e.text, session_id: e.session_id, ts: timestamp()})
  CREATE (s)-[:HAS_TURN]->(ep)
  CREATE (n)-[:FROM_EPISODE]->(ep)
}
CALL {
  WITH n
  UNWIND $facts AS f
  CREATE (:Fact {id: f.id, s: f.s, p: f.p, o: f.o, key: f.s + '|' + f.p, confidence: f.confidence,
                 agent_id: n.agent_id, created_at: timestamp()})-[:ADDED_IN]->(n)
}
CALL {
  WITH n
  UNWIND $procedures AS pr
  CREATE (:Procedure {id: pr.id, trigger: pr.trigger, steps: pr.steps, confidence: pr.confidence,
                      agent_id: n.agent_id, created_at: timestamp()})-[:ADDED_IN]->(n)
}
CALL {
  WITH n
  UNWIND $removed_procedures AS pid
  MATCH (x:Procedure {id: pid})
  CREATE (x)-[:REMOVED_IN]->(n)
}
CALL {
  WITH n
  UNWIND $removed AS rid
  MATCH (x:Fact {id: rid})
  CREATE (x)-[:REMOVED_IN]->(n)
}
CALL {
  WITH n
  UNWIND $derived AS d
  MATCH (child:Fact {id: d.child}), (parent:Fact {id: d.parent})
  CREATE (child)-[:DERIVED_FROM]->(parent)
}
RETURN n.id AS id, n.seq AS seq
