// name: merge_base
// Latest common ancestor of two branch HEADs: intersect ancestor lists, highest seq wins.
// seq is strictly increasing along PARENT edges (merge commits use max(parent seqs) + 1).
MATCH (:Branch {name: $a})-[:HEAD]->(ha:Commit), (:Branch {name: $b})-[:HEAD]->(hb:Commit)
WITH ha.ancestors + [ha.id] AS aa, hb.ancestors + [hb.id] AS bb
MATCH (c:Commit)
WHERE c.id IN aa AND c.id IN bb
RETURN c.id AS id, c.seq AS seq
ORDER BY c.seq DESC
LIMIT 1
