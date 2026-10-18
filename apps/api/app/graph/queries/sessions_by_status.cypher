// Investigation sessions in the given statuses, oldest first (worker poll and restart recovery).
MATCH (s:AgentSession)
WHERE s.tenant_id = $tenant_id AND s.env = $env AND s.status IN $statuses
RETURN s.id AS id, s.thread_id AS thread_id, s.status AS status, s.started_at_ms AS started_at_ms
ORDER BY started_at_ms, id
LIMIT $limit
