// name: checkout_traversal
// Showcase version of checkout that walks the commit DAG with a variable-length path.
// Same result as `checkout`; kept for the README and for cross-checking in tests.
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
MATCH (h)-[:PARENT*0..200]->(a:Commit)
WITH collect(DISTINCT a.id) AS anc
MATCH (f:Fact)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN DISTINCT f.id AS id, f.key AS key, f.o AS o
ORDER BY key
