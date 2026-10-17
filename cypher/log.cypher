// name: log
// Commit history of $branch, newest first, with author and fact counts.
// parents: ids of the commit's PARENT edges (two for a merge, none for the root) so the UI can draw the real
// DAG instead of guessing edges from log order. Unordered: FalkorDB's collect gives no edge order.
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
WITH h.ancestors + [h.id] AS anc
MATCH (c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (c)-[:PARENT]->(p:Commit)
WITH c, collect(p.id) AS parents
OPTIONAL MATCH (added:Fact)-[:ADDED_IN]->(c)
WITH c, parents, count(added) AS added
OPTIONAL MATCH (removed:Fact)-[:REMOVED_IN]->(c)
RETURN c.id AS id, c.seq AS seq, c.msg AS msg, c.agent_id AS agent_id, c.ts AS ts, c.kind AS kind,
       added, count(removed) AS removed, parents
ORDER BY c.seq DESC, c.ts DESC
LIMIT $limit
