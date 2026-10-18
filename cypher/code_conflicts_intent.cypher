// name: code_conflicts_intent
// intent (warn only): another agent has an active announced intent that targets a symbol this edit touches.
// Why warn and not block: an intent is a plan, not a change, and plans go stale. The human decides.
MATCH (ag:Agent)-[:INTENDS]->(i:Intent)-[:TARGETS]->(s:Symbol)
WHERE i.active = true AND ag.id <> $agent AND s.id IN $touched
RETURN s.id AS symbol, ag.id AS peer, ag.label AS peer_label, i.id AS intent_id, i.task AS task
