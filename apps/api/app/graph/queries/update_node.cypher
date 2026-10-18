// Partial update of an existing node within scope. Returns nothing if the node is absent.
MATCH (n:__LABEL__ {id: $id})
WHERE n.tenant_id = $tenant_id AND n.env = $env
SET n += $props, n.updated_at_ms = $now_ms
RETURN n.id
