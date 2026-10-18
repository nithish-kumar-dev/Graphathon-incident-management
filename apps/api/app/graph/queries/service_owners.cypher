MATCH (t:Team)-[:OWNS]->(s:Service {id: $service_id})
WHERE s.tenant_id = $tenant_id AND s.env = $env AND t.tenant_id = $tenant_id AND t.env = $env
OPTIONAL MATCH (r:Responder)-[:MEMBER_OF]->(t)
WHERE r.tenant_id = $tenant_id AND r.env = $env
RETURN t.id AS team_id, t.name AS team_name,
       collect(DISTINCT {id: r.id, handle: r.handle, roles: r.roles}) AS members
ORDER BY team_id
