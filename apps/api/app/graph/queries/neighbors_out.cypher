// (anchor:__SRC__ {id})-[:__REL__]->(n:__DST__), scoped, ordered by an allowlisted property.
MATCH (a:__SRC__ {id: $id})-[:__REL__]->(n:__DST__)
WHERE a.tenant_id = $tenant_id AND a.env = $env AND n.tenant_id = $tenant_id AND n.env = $env
RETURN DISTINCT properties(n) AS props, n.__ORDER__ AS sort_key
ORDER BY sort_key __DIR__
LIMIT $limit
