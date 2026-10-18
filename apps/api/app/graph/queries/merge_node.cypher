// Upsert one node by globally unique id. __LABEL__ is substituted from the schema allowlist only.
// A node that already exists under another tenant/env is never modified: the WHERE drops the row
// and the caller raises TenantConflict. $create_only is applied on creation only (used for
// AgentMemory verification state, which generic writes must never change afterwards).
MERGE (n:__LABEL__ {id: $id})
ON CREATE SET n.tenant_id = $tenant_id, n.env = $env, n.created_at_ms = $now_ms, n += $create_only
WITH n
WHERE n.tenant_id = $tenant_id AND n.env = $env
SET n += $props, n.updated_at_ms = $now_ms, n.schema_version = $schema_version
RETURN n.id
