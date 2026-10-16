// name: fact_links
// Direct DERIVED_FROM neighbours of fact $fid: `children` derive from it, `parents` it derives from.
// Restoring a fact (merge "keep the base value", revert) creates a fresh copy under a new id; the copy must
// inherit these edges or later merges cannot see what depends on it (and would skip the dependency conflict).
// Read-only. OPTIONAL MATCH + collect keeps the row (with empty lists) when the fact has no links.
MATCH (x:Fact {id: $fid})
OPTIONAL MATCH (c:Fact)-[:DERIVED_FROM]->(x)
WITH x, collect(DISTINCT c.id) AS children
OPTIONAL MATCH (x)-[:DERIVED_FROM]->(p:Fact)
RETURN children, collect(DISTINCT p.id) AS parents
