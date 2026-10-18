// Provenance for specific memories: the incident they are about (and its services), grounding
// evidence, validators and the actions they derive from (with status, to spot proposed-only fixes).
MATCH (m:AgentMemory)
WHERE m.id IN $ids AND m.tenant_id = $tenant_id AND m.env = $env
OPTIONAL MATCH (m)-[:ABOUT]->(inc:Incident)
WHERE inc.tenant_id = $tenant_id
OPTIONAL MATCH (inc)-[:AFFECTS]->(s:Service)
WHERE s.tenant_id = $tenant_id
WITH m, inc, collect(DISTINCT s.id) AS incident_service_ids
OPTIONAL MATCH (m)-[:GROUNDED_IN]->(ev:Evidence)
WHERE ev.tenant_id = $tenant_id
WITH m, inc, incident_service_ids, collect(DISTINCT ev.id) AS evidence_ids
OPTIONAL MATCH (m)-[:VALIDATED_BY]->(r:Responder)
WHERE r.tenant_id = $tenant_id
WITH m, inc, incident_service_ids, evidence_ids, collect(DISTINCT r.id) AS validator_ids
OPTIONAL MATCH (m)-[:DERIVED_FROM]->(a:AgentAction)
WHERE a.tenant_id = $tenant_id
RETURN properties(m) AS memory, inc.id AS incident_id, inc.key AS incident_key, incident_service_ids,
       evidence_ids, validator_ids, collect(DISTINCT {id: a.id, status: a.status}) AS actions
