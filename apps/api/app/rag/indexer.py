"""Chunk and embed authorised documents; embed memory summaries. Idempotent and incremental.

- **Only authorised documents are indexed.** A document's `classification` must be in
  RETRIEVAL_ALLOWED_CLASSIFICATIONS (default public, internal). If a document is reclassified out of that
  set, its chunks are deleted.
- **Text is redacted** before it is stored or embedded, with one vector per chunk.
- **Re-embedding happens only when needed:** when the content hash or the embedding model/version changed.
- **Embedding failures never block indexing.** Chunks are stored without vectors and counted as `missing`,
  and retrieval then falls back to keyword search.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.domain.redact import redact
from app.graph.repository import GraphRepository
from app.rag.embeddings import Embedder, EmbeddingUnavailable

MAX_CHUNK_CHARS = 700


@dataclass
class IndexReport:
    documents_indexed: int = 0
    documents_skipped_unauthorised: list[str] = field(default_factory=list)
    chunks_written: int = 0
    chunks_deleted: int = 0
    embedded: int = 0
    embeddings_missing: int = 0
    memories_embedded: int = 0
    embedding_error: str | None = None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Paragraph chunks, merged up to max_chars. Paragraphs longer than that are split on sentences."""
    chunks: list[str] = []
    current = ""
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        pieces = [para] if len(para) <= max_chars else _split_sentences(para, max_chars)
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _split_sentences(text: str, max_chars: int) -> list[str]:
    out, cur = [], ""
    for sent in text.replace("? ", "?|").replace(". ", ".|").split("|"):
        if cur and len(cur) + 1 + len(sent) > max_chars:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur[:max_chars])
    return out


def chunk_id(doc_id: str, ordinal: int) -> str:
    tenant, _, suffix = doc_id.split(".", 2)
    return f"{tenant}.chunk.{suffix}.{ordinal}"


def index_all(repo: GraphRepository, embedder: Embedder | None, *, allowed_classifications: frozenset[str],
              now_ms: int) -> IndexReport:
    rep = IndexReport()
    pending: list[tuple[str, str, str, str]] = []  # (label, id, text, hash) needing vectors
    for doc in repo.list_nodes("Document"):
        existing = {c["id"]: c for c in repo.neighbors("Document", doc["id"], "HAS_CHUNK", "DocumentChunk",
                                                       outgoing=True, limit=200)}
        if doc.get("classification") not in allowed_classifications or not doc.get("body_redacted"):
            if doc.get("classification") not in allowed_classifications:
                rep.documents_skipped_unauthorised.append(doc["id"])
            rep.chunks_deleted += repo.delete_nodes("DocumentChunk", list(existing))
            continue
        rep.documents_indexed += 1
        keep = set()
        for ordinal, text in enumerate(chunk_text(redact(doc["body_redacted"]))):
            cid = chunk_id(doc["id"], ordinal)
            h = content_hash(text)
            keep.add(cid)
            repo.merge_node("DocumentChunk", cid, {
                "document_id": doc["id"], "ordinal": ordinal, "text_excerpt": text, "content_hash": h,
                "source_ref": f"{doc.get('uri') or doc['id']}#chunk-{ordinal}", "source": "seed",
            }, at_ms=now_ms)
            repo.merge_edge("Document", doc["id"], "HAS_CHUNK", "DocumentChunk", cid, at_ms=now_ms)
            rep.chunks_written += 1
            if _stale(existing.get(cid), h, embedder):
                pending.append(("DocumentChunk", cid, text, h))
        rep.chunks_deleted += repo.delete_nodes("DocumentChunk", [c for c in existing if c not in keep])

    for mem in repo.list_nodes("AgentMemory"):
        h = content_hash(mem["summary"])
        if _stale(mem, h, embedder):
            pending.append(("AgentMemory", mem["id"], mem["summary"], h))

    if embedder is None:
        rep.embeddings_missing = sum(1 for p in pending if p[0] == "DocumentChunk")
        return rep
    try:
        version = embedder.version
        for i in range(0, len(pending), 16):
            batch = pending[i:i + 16]
            vectors = embedder.embed([t for _, _, t, _ in batch], "document")
            for (label, node_id, _, h), vec in zip(batch, vectors, strict=True):
                repo.set_embedding(label, node_id, vec, model=embedder.model, version=version, dim=embedder.dim,
                                   content_hash=h, at_ms=now_ms)
                if label == "DocumentChunk":
                    rep.embedded += 1
                else:
                    rep.memories_embedded += 1
    except EmbeddingUnavailable as exc:
        rep.embedding_error = f"{type(exc).__name__}: {exc}"
        rep.embeddings_missing = sum(1 for p in pending if p[0] == "DocumentChunk") - rep.embedded
    return rep


def _stale(node: dict | None, h: str, embedder: Embedder | None) -> bool:
    if node is None:
        return True
    if node.get("embedded_hash") != h:
        return True
    if embedder is None:
        return False
    try:
        return node.get("embedding_model") != embedder.model or node.get("embedding_version") != embedder.version
    except EmbeddingUnavailable:
        return True
