// name: touch_room
// Stamp visitor activity on this tenant's single `(:Room)` node (#30). Runs after every seed (= every page load)
// and every POST route, so the background sweep can delete rooms idle longer than TENANT_TTL_SECONDS and evict
// the least recently seen ones when there are more than MAX_ROOMS. MERGE keeps it to one Room per graph.
MERGE (r:Room)
ON CREATE SET r.created_at = timestamp()
SET r.last_seen = timestamp()
RETURN r.last_seen AS last_seen
