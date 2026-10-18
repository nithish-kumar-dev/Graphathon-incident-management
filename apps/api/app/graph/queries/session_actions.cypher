// Action proposals PART_OF one investigation session, with the evidence each is SUPPORTED_BY.
MATCH (a:AgentAction)-[:PART_OF]->(s:AgentSession {id: $session_id})
WHERE s.tenant_id = $tenant_id AND s.env = $env AND a.tenant_id = $tenant_id AND a.env = $env
OPTIONAL MATCH (a)-[:SUPPORTED_BY]->(e:Evidence)
WHERE e.tenant_id = $tenant_id AND e.env = $env
WITH a, collect(DISTINCT CASE WHEN e IS NULL THEN NULL ELSE properties(e) END) AS evidence
RETURN properties(a) AS action, evidence
ORDER BY action.id
