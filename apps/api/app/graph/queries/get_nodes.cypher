// Batch fetch by id within scope. Ids that do not exist (or belong to another tenant) are simply absent.
MATCH (n:__LABEL__)
WHERE n.id IN $ids AND n.tenant_id = $tenant_id AND n.env = $env
RETURN n.id AS id, properties(n) AS props
