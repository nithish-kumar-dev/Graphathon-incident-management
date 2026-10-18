// Store one embedding as a native vecf32 (required by the vector index). Dimension is checked by
// the caller: FalkorDB 4.22 accepts vectors of the wrong dimension without error.
MATCH (n:__LABEL__ {id: $id})
WHERE n.tenant_id = $tenant_id AND n.env = $env
SET n.embedding = vecf32($vector), n.embedding_model = $model, n.embedding_version = $version,
    n.embedding_dim = $dim, n.embedded_hash = $hash, n.updated_at_ms = $now_ms
RETURN n.id
