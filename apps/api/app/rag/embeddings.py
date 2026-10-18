"""Embedding providers. Every vector is checked for dimension and finiteness before use.

- OllamaEmbedder: local Ollama, default `nomic-embed-text`. Measured on Ollama 0.19.0:
  768 dimensions, L2-normalised, about 30 ms per batch warm (0.8 s cold).
  It uses nomic's task prefixes (`search_document:` / `search_query:`).
- HashingEmbedder: deterministic bag-of-words hashing for OFFLINE TESTS ONLY. It is never selected by
  configuration, and it does not capture meaning; it only lets tests exercise the vector path.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import ClassVar, Literal, Protocol

import httpx

Kind = Literal["document", "query"]


class EmbeddingUnavailable(RuntimeError):
    """Provider unreachable, timed out, or returned an unusable response."""


class EmbeddingDimensionMismatch(EmbeddingUnavailable):
    """Provider returned vectors of the wrong size. FalkorDB would accept them silently; we refuse."""


class Embedder(Protocol):
    model: str
    dim: int

    @property
    def version(self) -> str: ...

    def embed(self, texts: list[str], kind: Kind) -> list[list[float]]: ...


def check_vectors(vectors: list[list[float]], dim: int, expected_count: int) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise EmbeddingUnavailable(f"expected {expected_count} vectors, got {len(vectors)}")
    for v in vectors:
        if len(v) != dim:
            raise EmbeddingDimensionMismatch(f"vector has {len(v)} dimensions, configured {dim}")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            raise EmbeddingUnavailable("vector contains non-finite values")
    return vectors


class OllamaEmbedder:
    PREFIX: ClassVar[dict[str, str]] = {"document": "search_document: ", "query": "search_query: "}

    def __init__(self, base_url: str, model: str, dim: int, timeout_s: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout_s = timeout_s
        self._version: str | None = None

    @property
    def version(self) -> str:
        """Model digest prefix, so vectors from a different model build count as missing."""
        if self._version is None:
            try:
                r = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout_s)
                r.raise_for_status()
                models = {m["name"]: m for m in r.json().get("models", [])}
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise EmbeddingUnavailable("embedding provider unreachable") from exc
            entry = models.get(self.model) or models.get(f"{self.model}:latest")
            if entry is None:
                raise EmbeddingUnavailable(f"embedding model {self.model!r} is not installed")
            self._version = str(entry.get("digest", "unknown"))[:12]
        return self._version

    def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model, "input": [self.PREFIX[kind] + t for t in texts]}
        try:
            r = httpx.post(f"{self.base_url}/api/embed", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            vectors = r.json()["embeddings"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise EmbeddingUnavailable("embedding request failed") from exc
        return check_vectors(vectors, self.dim, len(texts))


class HashingEmbedder:
    """TEST-ONLY deterministic embedder: hashed unigram counts, L2-normalised."""

    def __init__(self, dim: int = 768, model: str = "test-hashing", version: str = "v1") -> None:
        self.dim = dim
        self.model = model
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 64) % 2 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


def from_settings(settings) -> Embedder | None:
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.ollama_base_url, settings.embedding_model, settings.embedding_dim,
                              settings.embedding_timeout_s)
    return None
