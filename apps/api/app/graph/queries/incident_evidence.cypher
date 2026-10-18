// Evidence attached to an incident, with the services it was observed on and deployments it refers to.
MATCH (i:Incident {id: $incident_id})-[:HAS_EVIDENCE]->(e:Evidence)
WHERE i.tenant_id = $tenant_id AND i.env = $env AND e.tenant_id = $tenant_id AND e.env = $env
OPTIONAL MATCH (e)-[:OBSERVED_ON]->(s:Service)
WHERE s.tenant_id = $tenant_id
WITH e, collect(DISTINCT s.id) AS observed_on
OPTIONAL MATCH (e)-[:REFERS_TO]->(d:Deployment)
WHERE d.tenant_id = $tenant_id
RETURN properties(e) AS evidence, observed_on, collect(DISTINCT d.id) AS refers_to
ORDER BY evidence.observed_at_ms, evidence.id
LIMIT $limit
