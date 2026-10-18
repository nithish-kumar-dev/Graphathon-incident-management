// Stored vectors whose recorded dimension differs from the configured one (FalkorDB would accept them).
MATCH (n) WHERE n.embedding_dim IS NOT NULL AND n.embedding_dim <> $dim
RETURN labels(n)[0] AS label, n.id AS id
