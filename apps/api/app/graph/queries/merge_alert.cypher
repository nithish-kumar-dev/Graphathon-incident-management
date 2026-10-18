// Create the alert under a deterministic id (fingerprint + window bucket). If a concurrent request
// already created it, MERGE matches instead and `created` is false (different source_ref).
MERGE (a:Alert {id: $id})
ON CREATE SET a += $props, a.tenant_id = $tenant_id, a.env = $env, a.created_at_ms = $now_ms,
              a.updated_at_ms = $now_ms, a.schema_version = $schema_version, a.dedup_count = 0
WITH a
WHERE a.tenant_id = $tenant_id AND a.env = $env
RETURN a.id AS alert_id, a.source_ref = $props.source_ref AS created
