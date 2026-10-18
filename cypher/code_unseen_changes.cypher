// name: code_unseen_changes
// Other agents' Changes this agent has not ACKED yet, oldest first. Feeds the "heads-up" notices the hooks
// inject into an agent's tool results, so the agent learns about a peer's edit before it writes its own.
MATCH (ag:Agent)-[:MADE]->(c:Change)-[:TOUCHED]->(s:Symbol)
WHERE ag.id <> $agent
WITH ag, c, s, [(me:Agent)-[:ACKED]->(c) | me.id] AS ackers
WHERE NOT $agent IN ackers
RETURN c.id AS change_id, ag.id AS agent, s.id AS symbol, c.kind AS kind, c.summary AS summary, c.ts AS ts
ORDER BY ts
