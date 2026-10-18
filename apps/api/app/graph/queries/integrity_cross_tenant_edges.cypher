MATCH (a)-[r]->(b)
WHERE a.tenant_id <> b.tenant_id OR a.env <> b.env OR r.tenant_id IS NULL OR r.tenant_id <> a.tenant_id
RETURN a.id AS src_id, type(r) AS rel, b.id AS dst_id
