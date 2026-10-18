// Memories about this incident, or about any incident that affected one of the same services.
// FalkorDB does not enforce relationship uniqueness inside a pattern, so `other` can be `i` itself;
// WITH DISTINCT after UNWIND collapses that.
MATCH (i:Incident {id: $incident_id})
WHERE i.tenant_id = $tenant_id AND i.env = $env
OPTIONAL MATCH (i)-[:AFFECTS]->(s:Service)<-[:AFFECTS]-(other:Incident)
WHERE s.tenant_id = $tenant_id AND other.tenant_id = $tenant_id AND other.env = $env
WITH i, collect(DISTINCT other) AS others
UNWIND [i] + others AS candidate
WITH DISTINCT candidate AS inc
MATCH (m:AgentMemory)-[:ABOUT]->(inc)
WHERE m.tenant_id = $tenant_id AND m.env = $env
  AND ($include_unverified OR m.verification_status = 'verified')
OPTIONAL MATCH (m)-[:GROUNDED_IN]->(ev:Evidence)
WHERE ev.tenant_id = $tenant_id
WITH inc, m, collect(DISTINCT ev.id) AS evidence_ids
OPTIONAL MATCH (m)-[:VALIDATED_BY]->(r:Responder)
WHERE r.tenant_id = $tenant_id
WITH inc, m, evidence_ids, collect(DISTINCT r.id) AS validator_ids
OPTIONAL MATCH (m)-[:DERIVED_FROM]->(a:AgentAction)
WHERE a.tenant_id = $tenant_id
WITH inc, m, evidence_ids, validator_ids, collect(DISTINCT a.id) AS action_ids
OPTIONAL MATCH (inc)-[:AFFECTS]->(x:Service)
WHERE x.tenant_id = $tenant_id
RETURN properties(m) AS memory, inc.id AS incident_id, inc.key AS incident_key, evidence_ids, validator_ids,
       action_ids, collect(DISTINCT x.id) AS incident_service_ids
LIMIT $limit
