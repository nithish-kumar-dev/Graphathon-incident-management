// Atomic compare-and-set on an AgentAction's status. FalkorDB runs one write per graph at a time, so of
// two concurrent reviewers only the first sees $from_status; the second gets no row (-> 409).
MATCH (a:AgentAction {id: $id})
WHERE a.tenant_id = $tenant_id AND a.env = $env AND a.status = $from_status AND a.version = $version
SET a.status = $to_status, a.updated_at_ms = $now_ms
RETURN a.id
