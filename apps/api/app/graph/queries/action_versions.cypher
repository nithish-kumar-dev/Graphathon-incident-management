// Version history of one action proposal, oldest first, with every review recorded against each version.
MATCH (a:AgentAction {proposal_id: $proposal_id})
WHERE a.tenant_id = $tenant_id AND a.env = $env
OPTIONAL MATCH (a)-[:HAS_REVIEW]->(ar:ApprovalRecord)
WITH a, ar ORDER BY ar.decided_at_ms
RETURN a.id AS action_id, a.version AS version, a.spec_hash AS spec_hash, a.status AS status,
       collect(CASE WHEN ar IS NULL THEN NULL
               ELSE {id: ar.id, decision: ar.decision, spec_hash: ar.spec_hash, action_version: ar.action_version} END)
         AS reviews
ORDER BY version
