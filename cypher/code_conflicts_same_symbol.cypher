// name: code_conflicts_same_symbol
// same_symbol (block): another agent's Change touched a symbol this edit also touches, and the checking agent
// has not ACKED that Change yet. Git would conflict here or silently keep one side. Read-only.
// Why the ACKED test is a pattern comprehension and not EXISTS {}: FalkorDB has no EXISTS, and a list of
// acking agent ids plus NOT IN is the same check.
MATCH (ag:Agent)-[:MADE]->(peer:Change)-[:TOUCHED]->(s:Symbol)
WHERE s.id IN $touched AND ag.id <> $agent
WITH ag, peer, s, [(me:Agent)-[:ACKED]->(peer) | me.id] AS ackers
WHERE NOT $agent IN ackers
RETURN ag.id AS peer, ag.label AS peer_label, peer.id AS change_id, peer.summary AS summary,
       peer.kind AS change_kind, s.id AS symbol
