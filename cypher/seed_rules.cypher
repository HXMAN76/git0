// name: seed_rules
// Seed the per-predicate merge rules (Rule nodes) for a tenant graph. Idempotent: ON CREATE only, so a
// human-edited strategy survives a re-init. Rules live in the graph so the merge decision stays a query
// over data, not hard-coded Python.
UNWIND $rules AS r
MERGE (x:Rule {p: r.p})
ON CREATE SET x.strategy = r.strategy
RETURN count(x) AS rules
