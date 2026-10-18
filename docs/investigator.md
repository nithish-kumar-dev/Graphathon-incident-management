# Phase 4: investigator, safety gate, telemetry

Contract: `apps/api/app/agents/contracts.py` (`InvestigatorInput` -> `InvestigatorOutput` -> `GateResult`). Code: `app/agents/{investigator,prompts,safety_gate}.py`, `app/telemetry/synthetic.py`. Tests: `tests/test_phase4_{investigator,gate,telemetry}.py`.

The investigator proposes; the gate decides. The gate never trusts the investigator: it re-checks every id against the input and the graph.

## Investigators (`LLM_PROVIDER`)

### `stub` (`stub-v1`, the default)

Deterministic and offline. It builds output from the graph context and telemetry:

1. **One `correlated` hypothesis per explanation path** (skipped if it has no supporting evidence). Supporting evidence: the path evidence, incident evidence observed on the target or affected services, and the latest anomalous reading per (service, metric) after the deployment. Contradicting evidence: the latest normal readings after the deployment on the target, the affected services and the target's dependents. At most 20 ids each. Confidence `min(0.8, 0.25 + 0.08 x supporting) - 0.12 x contradicting`, floor 0.05. The uncertainty text says it is a correlation that a human must confirm, and cites a `supports` memory as precedent, not proof.
2. **Actions from path runbooks only.** For each runbook on the path and each of its `allowed_action_types` that is in `ALLOWED_ACTION_TYPES` (and in the input's allowed list; today only `rollback_deployment_simulated`): target = the path target, `deployment_id` = the path deployment, evidence = the path evidence (must be non-empty), risk `medium`. At most 3. Skipped when a verified `warns_against` memory says the same kind of action failed. The rationale says it is pending human approval.
3. **One `observed` hypothesis per anomalous (service, metric)**, confidence 0.85.
4. **One `observed` hypothesis (confidence 0.75) for normal telemetry on services that are neither affected nor a path target**, which narrows the alternatives (for example an unrelated recent deployment).
5. **Feedback.** Evidence ids, actions (`<type> on <target>`) and hypotheses named in the gate's feedback are dropped on the next revision. At most 10 hypotheses.

The summary and `overall_uncertainty` always say a human must confirm any cause, list unavailable branches, and cite memories as precedent, not proof. It never emits `confirmed`.

### `ollama` (`ollama:<OLLAMA_MODEL>`)

A local LLM through `POST /api/chat`: `stream: false`, `temperature: 0`, `num_ctx: 8192`, the system prompt plus one compact JSON user message (`prompts.py`: ids, source refs, short excerpts, numbers; telemetry reduced to anomalous readings plus the latest normal reading per series).

- **Output format.** `format` is the `InvestigatorOutput` JSON schema, made stricter for the model: `deployment_id` is a required string (`output_format_schema()`). Without this, a 7B model picks `null` and the gate rejects every rollback with `invalid_arguments`. The reply is still validated against the real contract.
- **Action candidates.** The prompt lists `action_candidates`: the exact `{action_type, target_service_id, deployment_id, runbook_id, evidence_ids}` combinations that exist on the explanation paths. The model must copy one. The gate is unchanged.
- **Errors.** `timeout`, `unavailable` (connection or HTTP error) and `malformed` (invalid JSON or schema) raise `InvestigatorError`. The orchestrator counts that as a failed revision.
- **Fallback labelling.** With `LLM_FALLBACK_TO_STUB=true`, a failure is answered by the stub and the result's `investigator` is `stub-fallback(ollama <kind>)`. It is stored on the session and shown in the API and the UI (with a fallback warning), so a fallback is never silent.
- **Live check.** `tests/test_phase4_investigator.py` has one test against a running Ollama (skipped when it is down, fallback off): the gate must `accept` and no `invalid_arguments` may occur. The model name comes from `OLLAMA_MODEL`; the run was done with `qwen2.5:7b`.

## Safety gate (`safety_gate.evaluate`)

Read-only. Checks each hypothesis and each proposed action.

| Violation | Meaning |
|---|---|
| `confirmed_claim_not_allowed` | claim type `confirmed` (humans only) |
| `no_evidence` | a hypothesis with no supporting evidence id |
| `unknown_evidence` | a cited id that was not in the input, or is not in the graph (telemetry ids are checked against the telemetry input) |
| `action_not_allowed` | action type not in `ALLOWED_ACTION_TYPES` or the input's allowed list |
| `env_not_allowed` | env not in prod, staging, dev |
| `invalid_arguments` | a rollback without `deployment_id`, or any id outside the tenant |
| `unknown_service`, `service_out_of_scope` | target missing, or neither affected nor an explanation-path target |
| `unknown_runbook`, `runbook_not_applicable` | runbook missing, not `APPLIES_TO` the target, or it does not allow the action type |
| `unknown_deployment`, `deployment_not_on_target` | deployment missing, or not `DEPLOYED_TO` the target |
| `repeats_failed_action` | a verified `warns_against` memory records this action as failed |
| `inconclusive` | no evidence-backed hypothesis |

The orchestrator adds `investigator_timeout`, `investigator_unavailable` and `investigator_malformed` when an attempt produced no output. They follow the same `revise` / `inconclusive` rule: retry while `revision < max`, then `inconclusive`.

Violation details name the offending item and ids, so they work as revision feedback.

### Decision table

| Violations | Valid hypotheses | `revision < max` | Decision | Result |
|---|---|---|---|---|
| none | at least one | any | `accept` | hypotheses and actions kept |
| none | none | any | `inconclusive` | nothing kept |
| any | any | yes | `revise` | feedback to the investigator |
| in `proposed_actions[*]` | any | no | `escalate` | valid hypotheses kept, all actions dropped, a human looks |
| only in `hypotheses[*]` | at least one | no | `recommendation_only` | valid hypotheses kept, all actions dropped |
| only in `hypotheses[*]` | none | no | `inconclusive` | nothing kept |

Only a hypothesis or action that passes every check is ever kept. `decide()` is a pure function, tested directly.

For the session status each decision maps to, see `docs/orchestration.md`.

## Synthetic telemetry (`telemetry_context`)

The only permitted source of the live evidence branch. Deterministic, read-only, no network. Allowlisted tenant/env: `nova/prod` and `acme/prod` (acme has no series, so it returns nothing). At most 100 observations per call, anomalous ones first. An observation is anomalous when it is at least 3x above or below its baseline.

Observation ids are `<tenant>.ev.tel.<sha256(service|metric|ts)[:16]>`: the same reading always has the same id. `persist_outcome` stores each as an `Evidence` node (kind `metric`) under that id, so findings can cite it.

| Incident | Series |
|---|---|
| INC-101 (2026-10-17, 13:00-15:00Z, every 15 min) | payment `db_pool_wait_ms` 40 -> 2100, `p99_latency_ms` 320 -> 2800, `error_rate` 0.2 -> 4.5 after v2.4 (13:52Z); checkout `http_5xx_rate` 0.3 -> 11, `upstream_timeout_count` 2 -> 480 after 14:00Z; inventory, auth and ledger stay at baseline (exclusion evidence) |
| INC-092 (2026-08-12, 09:00-10:10Z, every 10 min) | payment pool wait and p99 spike after v2.3 (09:05Z), checkout 5xx at 14% from 09:20Z, recovery from 10:00Z after the rollback |
