// Scoped DETACH DELETE of specific nodes (e.g. stale chunks). Deleting nodes is safe on the AOF
// server; only dropping unique constraints is not (docs/schema/falkordb.md).
MATCH (n:__LABEL__)
WHERE n.id IN $ids AND n.tenant_id = $tenant_id AND n.env = $env
DETACH DELETE n
RETURN count(*)
