// name: code_conflicts_reverse
// reverse_dependency (block): the checking edit changes the contract (signature) or removes a function that
// code another agent just wrote relies on. Walks CALLS up to 3 hops from each changed symbol back to callers
// that a peer touched and the checking agent has not ACKED. path = caller ... changed symbol, for the graph.
// Why the peer's Change must touch the caller: that is the code that was written against the old contract.
UNWIND $contract AS cid
MATCH (target:Symbol)
WHERE target.id = cid
MATCH p = (caller:Symbol)-[:CALLS*1..3]->(target)
MATCH (ag:Agent)-[:MADE]->(peer:Change)-[:TOUCHED]->(caller)
WHERE ag.id <> $agent
WITH target, caller, ag, peer, [n IN nodes(p) | n.id] AS path,
     [(me:Agent)-[:ACKED]->(peer) | me.id] AS ackers
WHERE NOT $agent IN ackers
RETURN target.id AS symbol, caller.id AS caller, ag.id AS peer, ag.label AS peer_label,
       peer.id AS change_id, peer.summary AS summary, path
