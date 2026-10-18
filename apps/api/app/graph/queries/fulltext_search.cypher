// Keyword lookup on a full-text index. The index is graph-wide, so the tenant filter is applied to the
// candidates (demo: one permitted tenant; see docs/retrieval.md "Multi-tenant limits").
// $query is built from sanitised [a-z0-9] terms only.
CALL db.idx.fulltext.queryNodes($label, $query) YIELD node, score
WHERE node.tenant_id = $tenant_id AND node.env = $env
RETURN node.id AS id, score
ORDER BY score DESC, id
LIMIT $k
