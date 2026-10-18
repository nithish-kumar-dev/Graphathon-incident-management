# Hybrid retrieval (Phase 3)

How the investigator gets its context: named graph tools, then keyword and optional vector search, filtered and reranked into a typed `RetrievalBundle`. All data is synthetic.

- **Code:** `apps/api/app/tools/graph_tools.py` (tools), `apps/api/app/rag/{embeddings,indexer,retrieval}.py`, `apps/api/app/services/memories.py` (memory lifecycle)
- **HTTP:** `GET /api/incidents/{id}/retrieval` (`docs/api.md`). The response model is `RetrievalBundle`.
- **CLI:** `scripts/index_documents.py`, `scripts/retrieve_context.py nova.inc.101 [--full]`
- **Tests:** `tests/test_phase3_{tools,memory,retrieval}.py`, `tests/test_api_retrieval.py`

## Graph tools

Eight named tools in `TOOLS`. Phase 4 agents call them through `run_tool(ctx, name, args)`.

- **Read-only by construction.** `ToolContext.read_only()` wraps the graph in `ReadOnlyGraph`, which exposes only `GRAPH.RO_QUERY`. Any write raises `ReadOnlyViolation` (a `PermissionError`) before reaching the server. The repository re-raises it as is, so it is never reported as an outage.
- **Strict arguments.** Each tool takes a frozen Pydantic model with `extra="forbid"`. Ids are typed by kind (`nova.svc.*`, `nova.inc.*`). Errors list field locations only, never the submitted values.
- **Bounded.** Depth is at most 3, every list is capped, and each query has a timeout (`timeout_ms`, default 1500; the API passes `GRAPH_QUERY_TIMEOUT_MS`). `truncated: true` says a cap cut results off.
- **Scoped.** Every query filters on the caller's `tenant_id` and `env`. Another tenant's id gives `NotFound`.
- **No invented Cypher.** Tools use only the named queries in `app/graph/queries/`.

| Tool | Arguments (default) and bounds | Returns |
|---|---|---|
| `expand_dependencies` | `service_id`; `direction` downstream \| upstream; `max_depth` 1–3 (2); `limit` 1–50 (25) | Services over `DEPENDS_ON` with depth and path |
| `get_recent_deployments` | `service_ids` 1–10; `window_hours` 1–720 (72); `limit` 1–50 (20) | Deployments in `[now − window, now]`, newest first |
| `get_incident_evidence` | `incident_id`; `limit` 1–100 (50) | Evidence with `source_ref`, observed-on services, referred deployments |
| `get_service_ownership` | `service_id` | Owning teams and their responders |
| `get_current_decisions` | `service_id` | Decisions in effect at `now`, with documents and supersedes |
| `get_applicable_runbooks` | `service_id`; `action_type` (`^[a-z][a-z0-9_]{2,63}$`, optional); `limit` 1–20 (10) | Runbooks that apply, optionally for one action type |
| `get_verified_memories` | `incident_id`; `include_failed` (true); `limit` 1–20 (10) | Verified, grounded, validated memories only; drafts, rejected and superseded are counted in `excluded_unverified` |
| `get_explanation_path` | `incident_id` | Evidence-backed paths to candidate deployments, `claim_type: correlated` |

## Retrieval steps

`retrieve(ctx, incident_id, embedder=..., allowed_classifications=...)` runs these steps. `steps.graph|keyword|vector` report `completed`, `skipped` or `failed`, with `candidates` and a `detail`.

1. **Extract.** Affected service ids and names, and error terms (regex: `5xx`, `timeout`, `latency`, `p99`, `pool`, `exhaustion`, `connection`, …) from the incident title, alerts and evidence excerpts. These build the query text (at most 1000 chars).
2. **Graph** (required). Evidence, explanation paths, dependencies (depth 3), and for each affected or target service (at most 10): ownership, current decisions, runbooks, plus recent deployments (72 h). A graph failure fails the request (503).
3. **Keyword.** Full-text search on `AgentMemory.summary` and `DocumentChunk.text_excerpt`. Terms are reduced to `[a-z0-9]`, at least 3 chars, at most 20, OR-joined. Top 15 per label.
4. **Vector** (optional). Query embedding, then `db.idx.vector.queryNodes` for 4×15 raw neighbours. Only nodes whose `embedding_model`, `embedding_version` and `embedding_dim` match the current embedder are kept, top 15. Similarity = clamp(1 − cosine distance, 0, 1).
5. **Dedupe** by node id, recording which steps matched (`matched_by`).
6. **Filter.**
   - Memories must be verified, grounded in evidence that exists, validated by a Responder or by ground truth, and not derived from an unexecuted action.
   - Chunks are dropped if the parent document's `classification` is not in `RETRIEVAL_ALLOWED_CLASSIFICATIONS`. This is re-checked at read time.
   - Reasons are counted in `excluded`: `draft`, `rejected`, `superseded`, `missing_provenance`, `unexecuted_action`, `unauthorised`, `over_limit`.
7. **Rerank** with the weights below. Ties sort by id.
8. **Context.** At most 10 memories and 8 chunks. Every item carries real ids, `source_ref`s, non-zero score `components` and a plain-language `rationale`.

### Scoring weights (exact, from `retrieval.py`)

**Memories** (maximum about 1.0):

| Component | Value |
|---|---|
| `applicability` | same_incident 0.35 · shared_service 0.30 · dependency_related 0.15 · text_similarity_only 0.0 |
| `environment` | 0.05 (always; tenant/env scope guarantees the match) |
| `error_terms` | 0.15 × (shared error terms ÷ query error terms), capped at 1 |
| `recency` | 0.10 × exp(−age_days ÷ 90), age from `validated_at_ms` (else `created_at_ms`) |
| `verified_outcome` | successful 0.15 · failed 0.12 |
| `vector_similarity` | 0.15 × similarity |
| `keyword` | 0.05 if a keyword hit |

**Knowledge chunks:**

| Component | Value |
|---|---|
| `graph_link` | 0.40 if the chunk's document is linked to this incident's graph: a governing decision `DOCUMENTED_IN` it, or it `RELATES_TO` an affected/target service or the incident |
| `vector_similarity` | 0.35 × similarity |
| `keyword` | 0.15 if a keyword hit |
| `error_terms` | 0.10 × term overlap, capped at 1 |

## Applicability and precedent

| Applicability | When | Precedent |
|---|---|---|
| `same_incident` | The memory is `ABOUT` this incident | from the outcome |
| `shared_service` | Its incident `AFFECTS` a service this incident affects | from the outcome |
| `dependency_related` | Its incident affects a service in this incident's dependency neighbourhood | `none` |
| `text_similarity_only` | Reached only by keyword or vector | `none` |

Precedent from the outcome is `supports` for successful and `warns_against` for failed.

**Similar text is never a cause.**

- A memory found only by text similarity cannot support or warn against an action, and its rationale says so.
- Knowledge chunks always have `claim_type: "context"`. They are never findings.
- The bundle never contains `confirmed` or `hypothesis`; only Phase 4 findings may.
- Explanation paths remain `correlated`.

## Fallbacks

Retrieval never fails because of embeddings or missing search indexes. The graph step always runs.

| Situation | `steps` result |
|---|---|
| `EMBEDDING_PROVIDER=none` | `vector: skipped` ("embedding provider disabled; graph + keyword only") |
| Provider unreachable, timed out, model not installed, bad response | `vector: failed` (`EmbeddingUnavailable`; graph + keyword only) |
| Provider returns the wrong dimension | `vector: failed` (`EmbeddingDimensionMismatch`) |
| Vector index dimension differs from the embedder's | `vector: failed` ("vector index … has dimension 768, embedder has 384") |
| No vectors stored, or all from another model/version/dimension | `vector: completed`, `candidates: 0`, "no vectors stored for the current model/version". Counts as missing, never mixed |
| Indexes absent (migration 0002 not applied) | `keyword: failed` ("full-text index missing …; apply migration 0002") and `vector: failed` ("vector index missing"). Graph context is still returned |

FalkorDB 4.22 answers a full-text query on a **missing** index with zero rows, not an error. Retrieval therefore checks `db.indexes()` first, so a missing migration doesn't look like "no hits".

Indexing (`index_all`) also degrades: if embedding fails, chunks are stored without vectors and counted in `embeddings_missing`. The script exits 1 so the failure is visible, and keyword retrieval still works.

## Indexing

`scripts/index_documents.py [--tenant nova] [--no-embed]` is idempotent and incremental.

- **Authorised documents only.** Classification must be in `RETRIEVAL_ALLOWED_CLASSIFICATIONS` (default `public,internal`). The restricted `nova.doc.sec_handbook` is never chunked. If a document is reclassified out of the set, its chunks are deleted on the next run.
- **Chunking.** `body_redacted` is redacted again, then split into paragraphs merged up to 700 chars. Long paragraphs are split on sentences. Each chunk is `nova.chunk.<doc>.<ordinal>`, with `source_ref = <doc uri>#chunk-<n>`, and is linked by `(Document)-[:HAS_CHUNK]->(DocumentChunk)`.
- **Re-embedding** happens only when the content hash or the model/version changes. Memory summaries are embedded too.
- **Example on the dev graph** (first run, then a re-run): 3 documents indexed, 1 skipped (restricted), 3 chunks and 3 memories embedded; the re-run embeds 0.

## Embeddings

| Fact | Value (measured) |
|---|---|
| Provider / model | Local Ollama 0.19.0, `nomic-embed-text` |
| Dimension | 768 |
| Normalisation | L2-normalised (norm 1.0) |
| Latency | About 30 ms per request warm (median 28 ms over 10 single-text calls); about 0.8 s cold |
| Task prefixes | `search_document: ` for indexing, `search_query: ` for queries |
| Version | First 12 chars of the model digest from `/api/tags`. A model rebuild makes old vectors count as missing |

`HashingEmbedder` is a deterministic bag-of-words hash for **offline tests only**. It is never selected by configuration and captures no meaning.

In the API, `get_embedder` (`app/api/deps.py`) builds the embedder from settings on each request, so each request also makes one `/api/tags` call. Tests override this dependency.

### Wrong-dimension vectors

**FalkorDB accepts a stored vector of the wrong dimension silently.** Writing a 2-d `vecf32` into a property with a 4-d vector index succeeds, and the node is simply not usable by the index. (A *query* vector of the wrong size is rejected: "Vector dimension mismatch, expected 4 but got 2". Re-verified 2026-10-18 on 4.22.) Our checks are in application code:

1. `check_vectors()` rejects any provider response with the wrong count, the wrong dimension or non-finite values.
2. `GraphRepository.set_embedding()` is the only write path for embedding properties. It re-checks the dimension and finiteness, then stores `vecf32` together with `embedding_model`, `embedding_version`, `embedding_dim` and `embedded_hash`. `merge_node` and `update_node` cannot set these properties.
3. `vector_search()` rejects a query vector of the wrong size, and its query keeps only nodes with matching model, version and dimension.
4. Retrieval compares the vector index's `dimension` with the embedder's before querying.
5. The migration runner refuses to continue if an existing vector index has a different dimension or similarity function. A new model needs a new migration.
6. The integrity check `bad_embeddings` lists nodes whose `embedding_dim` differs from the configured one (`scripts/inventory_graph.py`).

## Multi-tenant limits

Full-text and vector indexes in FalkorDB are **graph-wide**: one index covers every tenant's nodes of that label.

- **Demo.** The named queries filter candidates to the caller's `tenant_id` and `env` after the index lookup. Vector search over-fetches (4×k) before that filter.
- **Risk.** With many tenants in one graph, another tenant's nodes can crowd a tenant's results out of the top-k, and index scoring statistics (e.g. term frequencies) mix tenants.
- **Production.** Use one graph per tenant, so each index covers exactly one tenant. Tenant filters stay in place as defence in depth.

## Memory verification rules

`app/services/memories.py` is the only code that changes verification state, and it writes through `GraphRepository.set_memory_verification`.

```
            create_draft                    validate_by_human / validate_by_ground_truth
   (none) ─────────────▶ draft/unknown ─────────────────────────────────────────▶ verified/{successful|failed}
                              │                                                          │
                              │ reject (human)                        supersede (new memory SUPERSEDES old)
                              ▼                                                          ▼
                           rejected                                                 superseded
```

- **Creation.** A memory starts as `draft` with outcome `unknown`. `merge_node` refuses any other initial state, and `update_node` refuses any change to `verification_status`, `outcome`, `validated_at_ms` or `validation_method`. Re-seeding never downgrades a verified memory, because these properties are set only on creation.
- **Verification** happens only through:
  - `validate_by_human`: a `VALIDATED_BY` edge to an existing Responder, with `validation_method: human`, or
  - `validate_by_ground_truth`: observed-outcome evidence (`metric`, `ticket` or `log`) observed at or after the incident started, with `validation_method: ground_truth`.
- **Requirements for verification:**
  - The memory is grounded in at least one existing Evidence node (`GROUNDED_IN`).
  - Every `DERIVED_FROM` action has status `executed_simulated`. **A proposed fix is never a verified outcome.**
  - All rules are checked before anything is written, so a refused validation leaves the memory untouched.
- **Failed outcomes are kept** as verified `failed` memories. They surface as `warns_against`, so a failed fix is not recommended twice.
- **Verified memories are never edited.** Re-validating with the same outcome is a no-op (`unchanged`); a different outcome is a 409 ("supersede it instead"). Only drafts can be rejected.
- **Integrity.** `integrity_unvalidated_verified_memory` flags a verified memory that:
  - has no grounding, or
  - has neither a validator nor ground truth, or
  - lacks `validation_method` or `validated_at_ms`, or
  - derives from an unexecuted action.

  Memories verified before Phase 3 lacked `validation_method`. `scripts/seed.py` heals them through `validate_by_human`, which is idempotent.
- **Seeding.** The seed creates memories as drafts, then verifies them through `VALIDATIONS` in the loader, which calls `validate_by_human`. Retrieval returns only memories that pass all of the above.
