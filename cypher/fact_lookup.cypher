// name: fact_lookup
// "Is X in team memory?" (M10). 0 rows = no path from the branch HEAD = "not in memory", never a guess.
MATCH (:Branch {name: $branch})-[:HEAD]->(h:Commit)
WITH h.ancestors + [h.id] AS anc
MATCH (f:Fact {key: $key})-[:ADDED_IN]->(c:Commit)
WHERE c.id IN anc
OPTIONAL MATCH (f)-[:REMOVED_IN]->(r:Commit)
WITH f, anc, collect(r.id) AS rs
WHERE none(x IN rs WHERE x IN anc)
RETURN f.id AS id, f.o AS o
