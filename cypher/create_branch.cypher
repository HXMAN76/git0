// name: create_branch
// Fork a new branch at the current HEAD of $from. Returns 0 rows if $from is missing or $name exists.
MATCH (:Branch {name: $from})-[:HEAD]->(h:Commit)
OPTIONAL MATCH (dup:Branch {name: $name})
WITH h, dup
WHERE dup IS NULL
CREATE (b:Branch {name: $name, created_at: timestamp()})-[:HEAD]->(h)
RETURN h.id AS head
