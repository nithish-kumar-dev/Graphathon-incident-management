MATCH (n:__LABEL__)
WHERE n.tenant_id = $tenant_id AND n.env = $env
RETURN properties(n) AS props
ORDER BY n.id
LIMIT $limit
