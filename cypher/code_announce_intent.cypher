// name: code_announce_intent
// An agent says "I am about to work on these symbols". Deactivates the agent's older intents so only its
// latest task reads as active. One query: the deactivation, the new Intent and its TARGETS edges together.
// Intents are warnings only (see code_conflicts_intent): announcing is cheap and can go stale.
MERGE (me:Agent {id: $agent})
WITH me
CALL {
  WITH me
  MATCH (me)-[:INTENDS]->(old:Intent)
  WHERE old.active = true
  SET old.active = false
}
WITH me
CREATE (i:Intent {id: $id, agent: $agent, task: $task, ts: $ts, active: true})
CREATE (me)-[:INTENDS]->(i)
WITH i
CALL {
  WITH i
  UNWIND $symbols AS sid
  MATCH (s:Symbol {id: sid})
  MERGE (i)-[:TARGETS]->(s)
}
RETURN i.id AS id
