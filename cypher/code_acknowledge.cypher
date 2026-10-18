// name: code_acknowledge
// The agent has seen (or, on "override", accepted) these Changes. An ACKED edge is what makes a Change stop
// counting as a conflict for that agent. One write; the count of matched Changes comes back from the
// subquery's RETURN so the caller knows how many ids were real.
// Why a non-unit subquery here: the count has to come back, so this one does return rows.
MERGE (me:Agent {id: $agent})
WITH me
CALL {
  WITH me
  UNWIND $ids AS cid
  MATCH (c:Change {id: cid})
  MERGE (me)-[:ACKED]->(c)
  RETURN count(c) AS n
}
RETURN n
