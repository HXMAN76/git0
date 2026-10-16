// name: checkout
// Facts visible at the HEAD of $branch: added in an ancestor, not removed in an ancestor.
// Uses the immutable Commit.ancestors list instead of a PARENT* walk (no path blow-up on merges).
// FalkorDB has no EXISTS {} subqueries, hence OPTIONAL MATCH + none().
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
WITH h.ancestors + [h.id] AS anc
MATCH (f:Fact)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN DISTINCT f.id AS id, f.s AS s, f.p AS p, f.o AS o, f.key AS key,
       f.confidence AS confidence, f.agent_id AS agent_id
ORDER BY key
