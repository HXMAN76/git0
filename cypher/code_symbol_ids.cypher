// name: code_symbol_ids
// Live symbol ids (not removed) for the IDE's symbol picker and for auto-filling an intent's targets.
// Why coalesce on removed: a symbol written by an older seed may have no removed flag at all; that means live.
MATCH (s:Symbol)
WHERE coalesce(s.removed, false) = false
RETURN s.id AS id
ORDER BY id
