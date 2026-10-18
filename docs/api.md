# API (Phases 2–3)

FastAPI with Pydantic v2 contracts. The live spec is at `/docs` (Swagger) and `/openapi.json`.

- **Data:** every response is built from graph records. No endpoint calls an LLM. The retrieval endpoint may call the local embedding model (Ollama), never a chat model.
- **Classification:** responses carry `data_classification: "synthetic"`.

## Identity and permissions: a demo, not authentication

Send `X-Demo-User: <user>`. In Swagger, use **Authorize** and the `DemoUser` scheme. The header picks a fictional principal, which fixes the tenant and env (all queries are scoped to them) and the permissions:

| User | Tenant / env | Permissions |
|---|---|---|
| `demo-viewer` | nova / prod | incident:read |
| `demo-responder` | nova / prod | + incident:write, alert:ingest, investigation:create |
| `payments-lead` | nova / prod | + action:review (used in Phase 5) |
| `acme-viewer` | acme / prod | incident:read. Decoy tenant, enabled only when `TENANT_ALLOWLIST` includes `acme` (tests) |

- **Missing or unknown user:** 401.
- **Missing permission, or tenant not enabled:** 403.
- **Another tenant's resource:** 404, so the API never confirms that it exists.

## Endpoints

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /healthz` | Liveness | |
| `GET /readyz` | FalkorDB and Postgres reachability | 503 if either is down |
| `POST /api/alerts` | Ingest one synthetic alert | 201 when a new alert is created, 200 for a duplicate or replay. See below |
| `GET /api/incidents` | List incidents, newest first | `status`, `limit` (1–100), `offset` (0–10000) |
| `GET /api/incidents/{id}` | Detail: alerts, evidence with `source_ref`, affected services, **explanation paths** | |
| `PATCH /api/incidents/{id}` | Change `status` and/or `severity` | Transitions only move forward, a reopen is 409. Every change goes on the timeline |
| `GET /api/incidents/{id}/timeline` | Auditable events, ordered by time | `actor`, `type`, `ref_id` |
| `GET /api/incidents/{id}/memories` | Memories about this incident or incidents sharing a service | Verified only by default; `include_unverified=true` adds drafts. `precedent`: supports / warns_against / none |
| `GET /api/incidents/{id}/retrieval` | Hybrid investigator context: graph + keyword + optional vector (`RetrievalBundle`) | incident:read. Read-only. Still 200 when the embedding provider is down (`steps.vector.status: failed`). See below and `docs/retrieval.md` |
| `GET /api/services/{id}/context` | Owners and members, `DEPENDS_ON` both ways, decisions in effect, runbooks, recent deployments | `depth` (1–3), `deployment_days` (1–90), `limit` |
| `POST /api/investigations` | Create an investigation (`AgentSession`, status `queued`) | `mode`: recommendation_only (default) or simulation. 200 returns the existing active run in the same mode; 409 if one is active in another mode, or the incident is resolved |
| `GET /api/investigations/{id}` | Status, per-branch state (graph / memory / telemetry, with `started_at` / `ended_at`), findings with `claim_type`, evidence refs, `proposed_actions` | Each action carries `required_approver_role`, `approval_policy_id`, `reviews[]` and, after a simulated execution, `execution` |
| `GET /api/incidents/{id}/investigations` | Runs for an incident, newest first | `limit` (1–50). Items: id, mode, status, requested_by, started_at, ended_at, revision_count, investigator, summary, error |
| `GET /api/investigations/{id}/events` | Orchestrator step events in causal order | Clients poll this; there is no SSE. Dedupe by `id`. `status`: started / completed / failed / skipped / waiting |
| `GET /api/investigations/{id}/retrieval` | The retrieval context the run actually used | 404 `no_snapshot` while the run is live or if none was stored. Not used by the web UI yet |
| `GET /api/actions/{id}` | One proposed action with its reviews and execution | |
| `POST /api/actions/{id}/review` | Record a human decision: `{decision: APPROVE\|REJECT\|REQUEST_REVISION\|ESCALATE, comment?}` | Needs `action:review` and the policy's `required_approver_role`. APPROVE on a simulation-mode action runs the **simulated** executor. See below |
| `POST /api/memories/{id}/validate` | `{outcome: successful\|failed}` verifies the draft memory written by an execution | Needs `action:review`. Only after validation does the memory appear in `GET .../memories` (precedent `supports` / `warns_against`) |
| `POST /api/memories/{id}/reject` | Discard a draft memory | Needs `action:review` |

### Review (Phase 5)

- The run pauses at `human_review` with LangGraph `interrupt()` (session status `awaiting_review`, checkpoint kept in Postgres). The review is a **separate authenticated request**: the API records the `ApprovalRecord`, then resumes the same thread with `Command(resume=...)` through the orchestrator. The approval is bound to the action's `spec_hash` and version.
- If no worker is attached to the API process (`ORCHESTRATOR_ENABLED=false`), the decision is still saved and the response says a worker will finish it; the worker's poll finds the decided review and resumes the run, so it survives a restart.
- The executor is idempotent through `ops.idempotency_records` (key `<action id>:<spec hash>`): a repeated resume or a replay never executes twice. An approval past its TTL turns the action `expired` and nothing runs.
- Only `simulation` runs produce a `pending_review` action. A `recommendation_only` run leaves the action `proposed`, and a review returns 409 `recommendation_only`.
- Errors: 403 `missing_approver_role`, 403 `no_responder_identity`, 409 `action_not_reviewable`, 409 `no_active_policy`, 409 `spec_hash_mismatch`, 404 unknown action.
- Outcomes: APPROVE then `executed_simulated` (investigation `completed`, a draft memory is written). REJECT then `rejected`. REQUEST_REVISION then `revision_requested`: **no new version is created**; the investigation is `completed` and the user starts a new run. ESCALATE then `escalated` (investigation `escalated`).
- Execution exists only for `rollback_deployment_simulated` and never touches a real system.
- New timeline types: `action_approved`, `action_rejected`, `action_revision_requested`, `action_escalated`, `action_executed_simulated`.

### Demo controls (Phase 6)

Off by default. Set `DEMO_CONTROLS_ENABLED=true` to let a presenter flip two graph edges and watch the recommendation change, with no manual database edits. Only the edges are written (`merge_edge` / `delete_edge`); nodes, constraints and indexes are never touched.

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /api/demo/controls` | State of both toggles plus the current recommendation | `incident_id` (optional). incident:read. Always 200; `enabled: false` and no toggles when the flag is off, so the UI hides the panel |
| `PUT /api/demo/controls/{toggle_id}` | `{present: bool}` adds or removes one edge | `demo:control` (`demo-responder`, `payments-lead`). Idempotent. 404 `demo_controls_disabled` when the flag is off |
| `PUT /api/demo/controls/reset` | Restore both edges (the seeded state) | `demo:control` |

Toggle ids and what they change on INC-101:

| `toggle_id` | Edge | With the edge removed |
|---|---|---|
| `checkout_depends_on_payment` | `nova.svc.checkout -[DEPENDS_ON]-> nova.svc.payment` | Recommendation `no_rollback_path`: the payment deployment is not reachable from the affected service (rollback paths: 0), and the explanation paths in `GET /api/incidents/{id}` disappear |
| `rollback_policy_governs_payment` | `nova.dec.payment.rollback_v2 -[GOVERNS]-> nova.svc.payment` | Recommendation `no_active_policy_escalate`: a rollback would have to escalate instead of going to the payment approver |

Every change is logged (`app.demo`). Nothing is cached, so the next read reflects the change.

## Explanation paths

Each element of `explanation_paths` is a **graph correlation**, not a cause:

- `claim_type` is always `correlated`.
- `hops` are the real stored edges, in their stored direction.

For the golden case INC-101:

```
nova.inc.101 -[AFFECTS]-> nova.svc.checkout
nova.svc.checkout -[DEPENDS_ON]-> nova.svc.payment
nova.dep.payment.v2_4 -[DEPLOYED_TO]-> nova.svc.payment
nova.inc.101 -[HAS_EVIDENCE]-> nova.ev.101.deploy
nova.ev.101.deploy -[REFERS_TO]-> nova.dep.payment.v2_4
```

Alongside the hops, each path carries:

- `evidence`: ids plus `source_ref`
- `governing_decisions`: decisions in effect now, each with `documented_in` documents
- `runbooks`, with `allowed_action_types`
- `approval_policy`: `policy_in_force`, or `no_active_policy_escalate` when nothing governs the target service

An incident with no qualifying path returns `explanation_paths: []`, never an error.

## Retrieval bundle

`GET /api/incidents/{id}/retrieval` returns `RetrievalBundle` (`app/rag/retrieval.py`), which is also its OpenAPI response model. It is the context the Phase 4 investigator receives. Scoring, fallbacks and the memory rules are in [`retrieval.md`](retrieval.md).

| Field | Content |
|---|---|
| `incident_id`, `as_of`, `data_classification` | `as_of` is the server clock; `data_classification` is always `synthetic` |
| `extracted` | `service_ids`, `service_names`, `error_terms`, `query_text` |
| `graph_context` | `incident`, `alerts`, `evidence`, `explanation_paths` (`claim_type: correlated`), and per service id: `dependencies`, `ownership`, `decisions`, `runbooks`; plus `recent_deployments` |
| `memory_context.items[]` | Verified memories only: `applicability` (same_incident / shared_service / dependency_related / text_similarity_only), `precedent` (supports / warns_against / none), `grounded_in` evidence with `source_ref`, `validated_by`, `matched_by`, `score`, `components`, `rationale` |
| `memory_context.excluded` | Counts by reason: `draft`, `rejected`, `superseded`, `missing_provenance`, `unexecuted_action`, `over_limit` |
| `knowledge_context.items[]` | Document chunks, always `claim_type: context`: `document_id`, `document_title`, `document_classification`, `source_ref` (`<doc uri>#chunk-<n>`), `text_excerpt`, `graph_links`, `matched_by`, `score`, `components`, `rationale` |
| `knowledge_context.excluded` | `unauthorised` (classification not in `RETRIEVAL_ALLOWED_CLASSIFICATIONS`), `over_limit` |
| `steps.graph` / `steps.keyword` / `steps.vector` | `status` completed / skipped / failed, `candidates`, `detail` |
| `embedding_model` | Model used for the query vector, or `null` if the vector step did not run |

- **Errors.** 404 for a missing incident or another tenant's; 422 for an id that is not `<tenant>.inc.*`; 503 if FalkorDB is down. Embedding problems are never errors; they show up in `steps.vector`.
- **Ids.** Every id in the bundle was read from the graph in this request. Restricted documents are never indexed or returned.

## Evidence integrity

Every evidence id in a response has just been read from the graph.

- If stored findings cite an id that doesn't exist, that id is **omitted** and the finding carries an `integrity_warnings` entry.
- If stored findings fail schema validation, they are withheld entirely, and a warning explains why.

## Alert ingest semantics

| Situation | Outcome | Status |
|---|---|---|
| Same `source_ref` already ingested | `replayed`: nothing changes | 200 |
| Same `fingerprint` within ±`ALERT_DEDUP_WINDOW_S` (default 900 s) in the same tenant and env | `deduplicated`: increments `dedup_count`, updates `last_fired_at`, remembers `source_ref` | 200 |
| New alert, and the service already has an unresolved incident | `attached_to_incident` | 201 |
| New alert, and the service has no unresolved incident | `created_incident` with the next `INC-<n>` key, severity mapped critical→sev2, warning→sev3, info→sev4 | 201 |

Validation and storage:

- `fired_at` needs a timezone and must lie within [now − 7 days, now + 5 minutes]; otherwise the request fails with 422 `fired_at_out_of_range`.
- A `service_id` that is unknown or belongs to another tenant fails with 422 `unknown_reference`.
- Summaries are redacted before storage (emails, IPs, long numbers, `token=`-style secrets).

**Atomicity.** Dedup, alert creation and "attach, or open an incident" are each **one** FalkorDB write query; FalkorDB runs one write per graph at a time.

- A test fires 20 concurrent duplicates and checks the result: 1 alert, 1 incident, `dedup_count` 19.
- A replay of a request that died halfway completes the attach, so no alert is left orphaned.

**Known limits:**

- Two *different* events in adjacent window buckets that arrive at the same instant can both be created.
- Timeline writes are separate, so a crash can lose one timeline event.

## Errors

Every non-2xx response has the same shape:

```json
{"error": {"code": "not_found", "message": "incident nova.inc.999 not found", "request_id": "…", "details": null}}
```

| Status | Codes |
|---|---|
| 401 / 403 | `unauthenticated`, `forbidden` |
| 404 | `not_found` |
| 409 | `conflict`, `invalid_transition`, `incident_resolved`, `investigation_in_progress`, `tenant_conflict` |
| 413 | `payload_too_large` (bodies over `MAX_REQUEST_BYTES`, default 64 KiB, chunked bodies included) |
| 422 | `validation_error` (`details` gives only location and reason, never the submitted value), `invalid_input`, `fired_at_out_of_range`, `unknown_reference`, `schema_violation` |
| 503 | `dependency_unavailable`, `dependency_timeout`, with `Retry-After: 5` |
| 500 | `internal_error`. The body carries no exception text; the details are logged under the same `request_id` |

## Typed IDs and query safety

- **Path and body ids are typed by kind:** `<tenant>.inc.*`, `<tenant>.svc.*`, `<tenant>.ses.*` and so on. A malformed id, or an id of the wrong kind (a service id where an incident is expected), fails with 422 before any query runs.
- **User strings never become Cypher.** Values go in as parameters. Labels, relationship types, `ORDER BY` properties and path depths come only from the allowlists in `app/graph/schema.py`.

## Logs

Logs are JSON lines on stderr. Each request writes one `app.access` line with `request_id`, `user`, `method`, `path`, `status` and `duration_ms`.

- **Request ids:** `X-Request-ID` is accepted when it matches `[A-Za-z0-9._-]{8,64}`; otherwise the server generates one. Either way it is echoed in the response header.
- **What is never logged:** request and response bodies.
- **Running the server:** use `--no-access-log`, so uvicorn's plain-text access log doesn't duplicate these lines.
