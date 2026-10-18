// name: code_view_links
// Every edge the IDE's graph panel draws: DEFINES, CALLS, MADE, TOUCHED, INTENDS, TARGETS, ACKED.
// Endpoints are returned as the same ids code_view_nodes uses (coalesce(id, path)), so the UI can join them.
MATCH (a)-[r]->(b)
WHERE type(r) IN ['DEFINES', 'CALLS', 'MADE', 'TOUCHED', 'INTENDS', 'TARGETS', 'ACKED']
RETURN coalesce(a.id, a.path) AS source, coalesce(b.id, b.path) AS target, type(r) AS type
