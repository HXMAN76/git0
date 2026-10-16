// name: rules
// All merge rules: predicate -> strategy. Read by the merge engine to classify a conflicting key.
MATCH (r:Rule)
RETURN r.p AS p, r.strategy AS strategy
