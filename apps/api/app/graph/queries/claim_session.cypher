// Atomic worker claim: queued -> running in ONE write query. FalkorDB runs one write per graph at a
// time, so of two concurrent claimers only the first sees status 'queued'; the second gets no row.
MATCH (s:AgentSession {id: $id})
WHERE s.tenant_id = $tenant_id AND s.env = $env AND s.status = 'queued'
SET s.status = 'running', s.updated_at_ms = $now_ms
RETURN s.id
