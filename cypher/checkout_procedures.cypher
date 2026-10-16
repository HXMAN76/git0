// name: checkout_procedures
// Procedural memory visible at the HEAD of $branch (same visibility rule as `checkout`).
// Agents load these after a merge and follow them ("when launch date moves: notify QA, add 24h freeze").
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
WITH h.ancestors + [h.id] AS anc
MATCH (pr:Procedure)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (pr)-[:REMOVED_IN]->(r:Commit)
WITH pr, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN DISTINCT pr.id AS id, pr.trigger AS trigger, pr.steps AS steps, pr.confidence AS confidence,
       pr.agent_id AS agent_id
ORDER BY trigger
