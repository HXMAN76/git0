// name: code_record_edit
// Records one file write in one query: upserts the file's symbols, marks symbols that vanished as removed,
// rebuilds the CALLS edges out of this file's symbols, and adds one Change per touched symbol.
// Why one query: a write must land all-or-nothing (FalkorDB has no transactions).
// Why CALLS are deleted before they are recreated: a call the author removed must not keep an edge alive.
// Why removed symbols stay as nodes (removed = true): a Change needs a TOUCHED target that later checks find.
// Why the sweep: a symbol the graph still DEFINES but the new source no longer has (graph drift) is retired too.
MERGE (f:File {path: $path})
WITH f
MERGE (me:Agent {id: $agent})
WITH f, me
CALL {
  WITH f
  UNWIND $syms AS s
  MERGE (n:Symbol {id: s.id})
  SET n.name = s.name, n.path = s.path, n.kind = s.kind, n.signature = s.signature,
      n.body_hash = s.body_hash, n.line = s.line, n.end_line = s.end_line, n.removed = false
  MERGE (f)-[:DEFINES]->(n)
}
CALL {
  WITH f
  UNWIND $gone AS g
  MERGE (n:Symbol {id: g.id})
  SET n.name = g.name, n.path = g.path, n.kind = g.kind, n.removed = true
  WITH f, n
  MATCH (f)-[d:DEFINES]->(n)
  DELETE d
}
CALL {
  WITH f
  MATCH (f)-[d:DEFINES]->(n:Symbol)
  WHERE NOT n.id IN $ids
  SET n.removed = true
  DELETE d
}
CALL {
  WITH f
  MATCH (f)-[:DEFINES]->(n:Symbol)-[c:CALLS]->()
  DELETE c
}
CALL {
  WITH f
  UNWIND $gone AS g
  MATCH (n:Symbol {id: g.id})-[c:CALLS]->()
  DELETE c
}
CALL {
  WITH f
  UNWIND $calls AS c
  MATCH (a:Symbol {id: c.src}), (b:Symbol {id: c.dst})
  MERGE (a)-[:CALLS]->(b)
}
CALL {
  WITH f, me
  UNWIND $changes AS ch
  CREATE (c:Change {id: ch.id, agent: $agent, ts: $ts, path: $path, symbol: ch.symbol, kind: ch.kind,
                    summary: ch.summary, old_signature: ch.old_signature, new_signature: ch.new_signature})
  CREATE (me)-[:MADE]->(c)
  WITH c, ch
  MATCH (s:Symbol {id: ch.symbol})
  CREATE (c)-[:TOUCHED]->(s)
}
RETURN f.path AS path
