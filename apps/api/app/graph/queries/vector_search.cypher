// Vector candidates (cosine distance: 0 = identical). Only vectors from the current embedding model,
// version and dimension are eligible; anything else counts as missing.
CALL db.idx.vector.queryNodes($label, 'embedding', $k_raw, vecf32($vector)) YIELD node, score
WHERE node.tenant_id = $tenant_id AND node.env = $env AND node.embedding_model = $model
  AND node.embedding_version = $version AND node.embedding_dim = $dim
RETURN node.id AS id, score AS distance
ORDER BY distance, id
LIMIT $k
