// name: precedent_lookup
// Most-chosen past resolution for predicate $p (a (:Precedent) is saved on every human resolution).
// plan_merge shows it on the conflict card as a suggestion; it never decides anything.
MATCH (pr:Precedent {key_pattern: $p})
RETURN pr.choice AS choice, pr.count AS count
ORDER BY pr.count DESC
LIMIT 1
