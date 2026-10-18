"""0002 hybrid retrieval: DocumentChunk identity, keyword and vector indexes.

The vector dimension is the *measured* output of the configured embedding model
(nomic-embed-text via Ollama 0.19.0: 768, L2-normalised; docs/retrieval.md). FalkorDB does not
reject vectors of another dimension, so the application checks dimensions on every write and query,
and the runner refuses to continue if an existing index was built with a different dimension.
"""

VERSION = 2
NAME = "hybrid_retrieval"

EMBEDDING_DIM = 768
SIMILARITY = "cosine"

RANGE_INDEXES: list[tuple[str, str]] = [
    ("DocumentChunk", "id"),
    ("DocumentChunk", "document_id"),
]

UNIQUE_CONSTRAINTS: list[tuple[str, str]] = [("DocumentChunk", "id")]

FULLTEXT_INDEXES: list[tuple[str, str]] = [
    ("DocumentChunk", "text_excerpt"),
    ("AgentMemory", "summary"),
]

# (label, property, dimension, similarity function)
VECTOR_INDEXES: list[tuple[str, str, int, str]] = [
    ("DocumentChunk", "embedding", EMBEDDING_DIM, SIMILARITY),
    ("AgentMemory", "embedding", EMBEDDING_DIM, SIMILARITY),
]
