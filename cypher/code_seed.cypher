// name: code_seed
// Seeds one IDE session's code graph in a single write: File and Symbol nodes, DEFINES, CALLS and Agents.
// Why one query: FalkorDB has no multi-query transactions, so a half-seeded graph must not be possible.
// Re-running is safe: every node and edge is MERGEd by its domain id.
// Why UNWIND [1] first: CALL {} subqueries need an outer row to start from. Each CALL is a unit subquery
// (no RETURN), so it runs once per outer row and an empty input list only skips its own work.
UNWIND [1] AS _once
CALL {
  WITH _once
  UNWIND $files AS fp
  MERGE (:File {path: fp})
}
CALL {
  WITH _once
  UNWIND $symbols AS s
  MATCH (f:File {path: s.path})
  MERGE (n:Symbol {id: s.id})
  SET n.name = s.name, n.path = s.path, n.kind = s.kind, n.signature = s.signature,
      n.body_hash = s.body_hash, n.line = s.line, n.end_line = s.end_line, n.removed = false
  MERGE (f)-[:DEFINES]->(n)
}
CALL {
  WITH _once
  UNWIND $calls AS c
  MATCH (a:Symbol {id: c.src}), (b:Symbol {id: c.dst})
  MERGE (a)-[:CALLS]->(b)
}
CALL {
  WITH _once
  UNWIND $agents AS ag
  MERGE (a:Agent {id: ag.id})
  SET a.label = ag.label
}
RETURN _once AS ok
