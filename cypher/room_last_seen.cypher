// name: room_last_seen
// When was this room last used? Read by the room sweep (#30) for every `team_*` graph.
// Rooms created before the Room node existed have none, so fall back to the earliest commit's ts (the root
// commit from `init`). Both `CALL {}`s aggregate, so an empty graph still returns one row: `last_seen` = null,
// which the sweep treats as "oldest possible".
CALL { OPTIONAL MATCH (r:Room) RETURN max(r.last_seen) AS room_seen }
CALL { OPTIONAL MATCH (c:Commit) RETURN min(c.ts) AS root_ts }
RETURN coalesce(room_seen, root_ts) AS last_seen
