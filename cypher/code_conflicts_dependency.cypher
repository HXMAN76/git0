// name: code_conflicts_dependency
// dependency (block): the checking edit calls a function that another agent just changed the contract of
// (signature or removed) and that the checking agent has not ACKED. $edges are [{src, dst}] taken from the
// new code of the added and modified symbols, so src is the checking agent's own symbol.
// Why UNWIND first: each edge is matched on its own; an empty $edges correctly yields no conflicts.
UNWIND $edges AS e
MATCH (s:Symbol)
WHERE s.id = e.dst
MATCH (ag:Agent)-[:MADE]->(peer:Change)-[:TOUCHED]->(s)
WHERE peer.kind IN ['signature', 'removed'] AND ag.id <> $agent
WITH e, ag, peer, s, [(me:Agent)-[:ACKED]->(peer) | me.id] AS ackers
WHERE NOT $agent IN ackers
RETURN e.src AS src, s.id AS dst, ag.id AS peer, ag.label AS peer_label, peer.id AS change_id,
       peer.summary AS summary
