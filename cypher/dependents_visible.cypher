// name: dependents_visible
// Dependents of fact $fid (DERIVED_FROM up to 6 hops) that are still visible at commit $head.
// plan_merge needs this per side: a conflict card shows what each choice would orphan, and latest-wins
// removes the loser's visible dependents. Same visibility rule as checkout (ancestors list + none()).
MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(:Fact {id: $fid})
MATCH (h:Commit {id: $head})
WITH d, h.ancestors + [h.id] AS anc
MATCH (d)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (d)-[:REMOVED_IN]->(r:Commit)
WITH d, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN DISTINCT d.id AS id, d.s AS s, d.p AS p, d.o AS o, d.key AS key,
       d.confidence AS confidence, d.agent_id AS agent_id, d.created_at AS created_at
ORDER BY key
