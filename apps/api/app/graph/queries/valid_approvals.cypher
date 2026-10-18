// Approvals that still authorize this exact action version: same spec hash, same version, unexpired.
MATCH (a:AgentAction {id: $action_id})-[:HAS_REVIEW]->(ar:ApprovalRecord)
WHERE a.tenant_id = $tenant_id AND a.env = $env AND ar.tenant_id = $tenant_id
  AND ar.decision = 'APPROVE' AND ar.spec_hash = a.spec_hash AND ar.action_version = a.version
  AND ar.expires_at_ms > $now_ms
OPTIONAL MATCH (ar)-[:DECIDED_BY]->(r:Responder)
RETURN ar.id AS approval_id, ar.approver_id AS approver_id, r.id AS responder_id, ar.expires_at_ms AS expires_at_ms
ORDER BY ar.decided_at_ms
