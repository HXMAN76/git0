// name: derived_edge_count
// Number of DERIVED_FROM edges from fact $child to fact $parent. Deliberately NOT DISTINCT: duplicate edges
// must show up as n > 1. Tests use it to prove one commit writes one edge per (child, parent) pair.
// Read-only. count() over no matches returns a single 0 row.
MATCH (:Fact {id: $child})-[r:DERIVED_FROM]->(:Fact {id: $parent})
RETURN count(r) AS n
