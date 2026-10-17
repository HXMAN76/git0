// name: facts_by_ids
// Facts by id regardless of visibility. The Arbiter re-derives facts a merge just removed, so they are
// no longer in any checkout; the API receives only their ids and must load the rows to describe them.
MATCH (f:Fact)
WHERE f.id IN $ids
RETURN f.id AS id, f.s AS s, f.p AS p, f.o AS o, f.key AS key,
       f.confidence AS confidence, f.agent_id AS agent_id, f.created_at AS created_at
ORDER BY key
