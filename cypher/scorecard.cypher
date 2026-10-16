// name: scorecard
// Live counts for the demo scorecard, in ONE read query so the whole thing is a single measurable round trip.
// Each `CALL {}` ends in an aggregation, which always yields one row, so an empty graph returns zeros
// instead of zero rows (chained MATCH ... WITH would drop the row). `commits` counts every commit that has a
// `kind` (commit, merge, revert, handoff, seed) and so excludes the kind-less root created by `init`.
// `facts_on_main` / `procedures_on_main` use the standard visibility rule (see `checkout`).
// `precedents_reused` = how many resolutions were answered by an existing precedent (count - 1 per node).
CALL { MATCH (e:Episode) RETURN count(e) AS episodes }
CALL { MATCH (s:Session) RETURN count(s) AS sessions }
CALL {
  MATCH (:Branch {name: 'main'})-[:HEAD]->(h:Commit)
  WITH h.ancestors + [h.id] AS anc
  MATCH (f:Fact)-[:ADDED_IN]->(c:Commit)
  WHERE c.id IN anc
  OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
  WITH f, anc, collect(r.id) AS rs
  WHERE none(x IN rs WHERE x IN anc)
  RETURN count(DISTINCT f) AS facts_on_main
}
CALL {
  MATCH (:Branch {name: 'main'})-[:HEAD]->(h:Commit)
  WITH h.ancestors + [h.id] AS anc
  MATCH (pr:Procedure)-[:ADDED_IN]->(c:Commit)
  WHERE c.id IN anc
  OPTIONAL MATCH (pr)-[:REMOVED_IN]->(r:Commit)
  WITH pr, anc, collect(r.id) AS rs
  WHERE none(x IN rs WHERE x IN anc)
  RETURN count(DISTINCT pr) AS procedures_on_main
}
CALL {
  MATCH (c:Commit)
  WHERE c.kind IS NOT NULL
  RETURN count(c) AS commits,
         sum(CASE WHEN c.kind = 'merge' THEN 1 ELSE 0 END) AS merges,
         sum(CASE WHEN c.kind = 'revert' THEN 1 ELSE 0 END) AS reverts,
         sum(CASE WHEN c.kind = 'handoff' THEN 1 ELSE 0 END) AS handoffs
}
CALL { MATCH (cf:Conflict {status: 'resolved'}) RETURN count(cf) AS conflicts_resolved }
CALL {
  MATCH (p:Precedent)
  WHERE p.count > 1
  RETURN coalesce(sum(p.count - 1), 0) AS precedents_reused
}
CALL { MATCH (a:Agent) RETURN count(a) AS agents }
RETURN episodes, sessions, facts_on_main, procedures_on_main, commits, merges, reverts, handoffs,
       conflicts_resolved, precedents_reused, agents
