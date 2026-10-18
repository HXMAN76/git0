// name: code_record_conflicts
// Writes the conflicts a blocked edit raised as Conflict nodes, in one query, so the graph shows the story:
// (Agent)-[:RAISED]->(Conflict)-[:ON]->(Symbol the checking agent touched) and, when a peer Change is involved,
// (Conflict)-[:AGAINST]->(Change). Every Conflict starts with resolution 'pending'; code_resolve_conflicts sets it.
// Why unit CALL blocks: each step needs the UNWIND rows and must not stop the others. An intent conflict has no
// peer Change, so its change_id is '' and the AGAINST step simply matches nothing for it.
// Why the ids come from the caller: the harness puts them in the `conflict` SSE event, so the UI can link the card.
// Why the final MATCH: it confirms each Conflict exists before the caller treats the ids as recorded.
MERGE (me:Agent {id: $agent})
WITH me
CALL {
  WITH me
  UNWIND $conflicts AS c
  CREATE (x:Conflict {id: c.id, agent: $agent, peer: c.peer, kind: c.kind, message: c.message, ts: c.ts,
                      resolution: 'pending'})
  CREATE (me)-[:RAISED]->(x)
}
CALL {
  WITH me
  UNWIND $conflicts AS c
  MATCH (x:Conflict {id: c.id})
  MATCH (s:Symbol {id: c.symbol})
  MERGE (x)-[:ON]->(s)
}
CALL {
  WITH me
  UNWIND $conflicts AS c
  MATCH (x:Conflict {id: c.id})
  MATCH (ch:Change)
  WHERE ch.id = c.change_id
  MERGE (x)-[:AGAINST]->(ch)
}
WITH me
UNWIND $conflicts AS c
MATCH (x:Conflict {id: c.id})
RETURN x.id AS id
