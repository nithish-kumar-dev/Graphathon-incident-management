// Golden evidence path (refactor-plan §4).
// A deployment is a rollback candidate for an incident only if BOTH:
//   (1) it targets a service reachable from an affected service within __DEPTH__ DEPENDS_ON hops, and
//   (2) the incident's own evidence REFERS_TO that deployment.
// The active, in-effect Decision governing the target service decides who may approve.
// __DEPTH__ is a validated integer 0..3 (FalkorDB rejects parameterised path bounds).
MATCH (i:Incident {id: $incident_id})-[:AFFECTS]->(affected:Service)
WHERE i.tenant_id = $tenant_id AND i.env = $env
MATCH p = (affected)-[:DEPENDS_ON*0..__DEPTH__]->(target:Service)
WHERE all(n IN nodes(p) WHERE n.tenant_id = $tenant_id AND n.env = $env)
MATCH (i)-[:HAS_EVIDENCE]->(ev:Evidence)-[:REFERS_TO]->(d:Deployment)-[:DEPLOYED_TO]->(target)
WHERE ev.tenant_id = $tenant_id AND d.tenant_id = $tenant_id
WITH i, affected, p, target, d, collect(DISTINCT ev) AS evs
OPTIONAL MATCH (dec:Decision)-[:GOVERNS]->(target)
WHERE dec.tenant_id = $tenant_id AND dec.status = 'active' AND dec.effective_from_ms <= $now_ms
  AND (dec.effective_to_ms IS NULL OR dec.effective_to_ms > $now_ms)
WITH i, affected, p, target, d, evs, collect(DISTINCT dec) AS decs
OPTIONAL MATCH (rb:Runbook)-[:APPLIES_TO]->(target)
WHERE rb.tenant_id = $tenant_id
RETURN i.id AS incident_id,
       affected.id AS affected_service_id,
       [n IN nodes(p) | n.id] AS service_path,
       [r IN relationships(p) | type(r)] AS path_rels,
       target.id AS target_service_id,
       d.id AS deployment_id,
       d.version AS deployment_version,
       [e IN evs | e.id] AS evidence_ids,
       [e IN evs | e.source_ref] AS evidence_source_refs,
       [x IN decs | x.id] AS active_decision_ids,
       [x IN decs | x.required_approver_role] AS required_approver_roles,
       collect(DISTINCT rb.id) AS runbook_ids
ORDER BY size(service_path), deployment_id
