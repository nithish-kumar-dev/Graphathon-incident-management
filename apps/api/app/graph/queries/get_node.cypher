MATCH (n:__LABEL__ {id: $id})
WHERE n.tenant_id = $tenant_id AND n.env = $env
RETURN properties(n)
