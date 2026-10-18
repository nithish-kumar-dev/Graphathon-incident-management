// (n:__SRC__)-[:__REL__]->(anchor:__DST__ {id}), scoped, ordered by an allowlisted property.
MATCH (n:__SRC__)-[:__REL__]->(a:__DST__ {id: $id})
WHERE a.tenant_id = $tenant_id AND a.env = $env AND n.tenant_id = $tenant_id AND n.env = $env
RETURN DISTINCT properties(n) AS props, n.__ORDER__ AS sort_key
ORDER BY sort_key __DIR__
LIMIT $limit
