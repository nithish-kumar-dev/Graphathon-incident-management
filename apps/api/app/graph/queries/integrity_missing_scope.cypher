MATCH (n) WHERE NOT n:SchemaMigration AND (n.id IS NULL OR n.tenant_id IS NULL OR n.env IS NULL)
RETURN labels(n)[0] AS label, n.id AS id
