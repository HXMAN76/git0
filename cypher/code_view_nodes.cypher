// name: code_view_nodes
// Every File, Symbol, Change, Agent, Intent and Conflict node for the IDE's graph panel, one row each.
// Why coalesce(id, path): File nodes are keyed by path; every other label has an id. The UI wants one id field.
// Only the properties the panel shows are returned, so the response stays small. ts is returned for Change,
// Intent and Conflict so the panel can draw a timeline.
MATCH (n)
WHERE n:File OR n:Symbol OR n:Change OR n:Agent OR n:Intent OR n:Conflict
RETURN labels(n)[0] AS label, coalesce(n.id, n.path) AS id, n.name AS name, n.path AS path,
       n.kind AS kind, n.signature AS signature, n.summary AS summary, n.task AS task,
       n.label AS agent_label, n.agent AS agent, n.active AS active, n.removed AS removed,
       n.ts AS ts, n.peer AS peer, n.message AS message, n.resolution AS resolution
