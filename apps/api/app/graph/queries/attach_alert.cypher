// Attach an alert to an incident in ONE atomic write (FalkorDB runs each write query alone per graph):
//   1. already attached        -> return that incident (idempotent replay / healing)
//   2. else open incident on the service -> attach to the newest one
//   3. else                     -> create an incident with the next INC-<n> key, AFFECTS the service
// Doing this in separate queries let concurrent requests open duplicate incidents.
MATCH (s:Service {id: $service_id})
WHERE s.tenant_id = $tenant_id AND s.env = $env
MATCH (a:Alert {id: $alert_id})
WHERE a.tenant_id = $tenant_id AND a.env = $env
OPTIONAL MATCH (prev:Incident)-[:HAS_ALERT]->(a)
WHERE prev.tenant_id = $tenant_id
WITH s, a, prev ORDER BY prev.started_at_ms DESC LIMIT 1
OPTIONAL MATCH (open:Incident)-[:AFFECTS]->(s)
WHERE prev IS NULL AND open.tenant_id = $tenant_id AND open.env = $env
  AND open.status IN ['open', 'investigating', 'mitigated']
WITH s, a, prev, open ORDER BY open.started_at_ms DESC, open.id LIMIT 1
OPTIONAL MATCH (x:Incident)
WHERE prev IS NULL AND open IS NULL AND x.tenant_id = $tenant_id AND x.key STARTS WITH 'INC-'
WITH s, a, prev, open, coalesce(max(toInteger(substring(x.key, 4))), 0) + 1 AS n
FOREACH (_ IN CASE WHEN prev IS NULL AND open IS NOT NULL THEN [1] ELSE [] END |
    MERGE (open)-[r:HAS_ALERT]->(a)
    ON CREATE SET r.tenant_id = $tenant_id, r.created_at_ms = $now_ms)
FOREACH (_ IN CASE WHEN prev IS NULL AND open IS NULL THEN [1] ELSE [] END |
    CREATE (i:Incident {id: $new_incident_id})
    SET i += $incident_props, i.key = 'INC-' + toString(n), i.tenant_id = $tenant_id, i.env = $env,
        i.created_at_ms = $now_ms, i.updated_at_ms = $now_ms, i.schema_version = $schema_version
    CREATE (i)-[:AFFECTS {tenant_id: $tenant_id, created_at_ms: $now_ms}]->(s)
    CREATE (i)-[:HAS_ALERT {tenant_id: $tenant_id, created_at_ms: $now_ms}]->(a))
WITH a, prev
MATCH (inc:Incident)-[:HAS_ALERT]->(a)
WHERE inc.tenant_id = $tenant_id
RETURN inc.id AS incident_id, inc.key AS incident_key, inc.id = $new_incident_id AS created,
       prev IS NOT NULL AS already_attached
ORDER BY inc.started_at_ms DESC
LIMIT 1
