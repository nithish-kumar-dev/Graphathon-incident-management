// Upstream: services that DEPENDS_ON this one, up to __DEPTH__ hops (validated integer 1..3).
MATCH (s:Service {id: $service_id})
WHERE s.tenant_id = $tenant_id AND s.env = $env
MATCH p = (x:Service)-[:DEPENDS_ON*1..__DEPTH__]->(s)
WHERE all(n IN nodes(p) WHERE n.tenant_id = $tenant_id AND n.env = $env) AND x.id <> s.id
RETURN properties(x) AS service, [n IN nodes(p) | n.id] AS path, length(p) AS depth
ORDER BY depth, service.id
LIMIT $limit
