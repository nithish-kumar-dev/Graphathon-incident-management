// Upsert one relationship. Both endpoints must exist in the same tenant/env.
// __SRC__, __REL__ and __DST__ are substituted from the ALLOWED_EDGES allowlist only.
MATCH (a:__SRC__ {id: $src_id})
WHERE a.tenant_id = $tenant_id AND a.env = $env
MATCH (b:__DST__ {id: $dst_id})
WHERE b.tenant_id = $tenant_id AND b.env = $env
MERGE (a)-[r:__REL__]->(b)
ON CREATE SET r.tenant_id = $tenant_id, r.created_at_ms = $now_ms
RETURN count(r)
