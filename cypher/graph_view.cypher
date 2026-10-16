// name: graph_view
// The memory graph behind a branch, for the UI's live graph view (judges see what the agents remember).
// One row per Fact visible at the HEAD of $branch (same visibility rule as `checkout`), newest first and capped
// at $limit so the canvas stays fast. Each row carries the commit that added the fact, the agents that
// AUTHORED that commit, the commit's episodes as [id, text] pairs, and the ids of the facts it is
// DERIVED_FROM. Parents can be hidden or past the cap; the caller keeps only edges between returned facts.
// Pattern comprehensions (one level, never nested) keep it one row per fact without collect() bookkeeping.
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
WITH h.ancestors + [h.id] AS anc
MATCH (f:Fact)-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, c, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
WITH f, c
ORDER BY f.created_at DESC, f.id
LIMIT $limit
RETURN f.id AS id, f.s AS s, f.p AS p, f.o AS o, f.key AS key, f.confidence AS confidence,
       f.agent_id AS agent_id,
       c.id AS commit_id, c.msg AS commit_msg, c.kind AS commit_kind, c.seq AS commit_seq,
       [(a:Agent)-[:AUTHORED]->(c) | a.id] AS authors,
       [(c)-[:FROM_EPISODE]->(e:Episode) | [e.id, e.text]] AS episodes,
       [(f)-[:DERIVED_FROM]->(parent:Fact) | parent.id] AS parents
