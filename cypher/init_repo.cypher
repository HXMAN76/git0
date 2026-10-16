// name: init_repo
// Create the root commit and the `main` branch for a fresh tenant graph. Idempotent.
MERGE (b:Branch {name: 'main'})
WITH b
OPTIONAL MATCH (b)-[:HEAD]->(existing:Commit)
WITH b, existing
WHERE existing IS NULL
CREATE (root:Commit {id: $root_id, seq: 0, msg: 'init', ts: timestamp(), agent_id: 'system', ancestors: []})
CREATE (b)-[:HEAD]->(root)
RETURN root.id AS id
