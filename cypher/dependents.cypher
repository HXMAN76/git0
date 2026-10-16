// name: dependents
// Facts that were derived (directly or transitively) from fact $fid. Feeds conflict cards + revert cascade.
MATCH (d:Fact)-[:DERIVED_FROM*1..6]->(:Fact {id: $fid})
RETURN DISTINCT d.id AS id, d.key AS key, d.o AS o, d.agent_id AS agent_id
