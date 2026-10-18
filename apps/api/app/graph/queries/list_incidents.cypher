MATCH (i:Incident)
WHERE i.tenant_id = $tenant_id AND i.env = $env AND ($status IS NULL OR i.status = $status)
WITH i ORDER BY i.started_at_ms DESC, i.id SKIP $offset LIMIT $limit
OPTIONAL MATCH (i)-[:AFFECTS]->(s:Service)
WHERE s.tenant_id = $tenant_id
WITH i, collect(DISTINCT s.id) AS service_ids
OPTIONAL MATCH (i)-[:HAS_ALERT]->(a:Alert)
WHERE a.tenant_id = $tenant_id
RETURN properties(i) AS incident, service_ids, count(DISTINCT a) AS alert_count
ORDER BY incident.started_at_ms DESC, incident.id
