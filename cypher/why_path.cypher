// name: why_path
// Provenance of one fact: Fact <- Commit <- Agent, plus the chat turn (Episode) that produced it.
MATCH (f:Fact {id: $fid})-[:ADDED_IN]->(c:Commit)<-[:AUTHORED]-(a:Agent)
OPTIONAL MATCH (c)-[:FROM_EPISODE]->(e:Episode)
RETURN f.id AS fact_id, f.key AS key, f.o AS o, c.id AS commit_id, c.msg AS msg,
       a.id AS agent_id, e.id AS episode_id, e.text AS episode_text
