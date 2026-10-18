// The ONLY write path for AgentMemory verification state. Called by app.services.memories after its
// rules pass (human validator or accepted ground truth; never for a merely proposed fix).
MATCH (m:AgentMemory {id: $id})
WHERE m.tenant_id = $tenant_id AND m.env = $env
SET m.verification_status = $status, m.outcome = $outcome, m.validated_at_ms = $validated_at_ms,
    m.validation_method = $method, m.updated_at_ms = $now_ms
RETURN m.id
