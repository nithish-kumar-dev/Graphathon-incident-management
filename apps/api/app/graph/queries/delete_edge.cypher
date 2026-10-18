// Remove one relationship (demo controls / tests). Endpoints are tenant-scoped.
MATCH (a:__SRC__ {id: $src_id})-[r:__REL__]->(b:__DST__ {id: $dst_id})
WHERE a.tenant_id = $tenant_id AND a.env = $env AND b.tenant_id = $tenant_id AND b.env = $env
DELETE r
RETURN count(*)
