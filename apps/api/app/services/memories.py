"""AgentMemory lifecycle: the only place verification state changes.

Rules (Phase 3 brief):
- A memory starts as `draft` with outcome `unknown`.
- It becomes `verified` only through validation by a human (a Responder) or by accepted ground truth:
  evidence of an observed outcome (metric, ticket or log) observed after the incident started.
- It must be grounded in at least one existing Evidence node.
- A memory derived from an action can be verified only once that action actually ran
  (`executed_simulated`). A proposed fix is NOT a verified outcome.
- Failed outcomes are kept as verified `failed` memories, so the same mistake is not recommended twice.
- Verified memories are never edited. A correction is a new memory that SUPERSEDES the old one.
"""

from __future__ import annotations

from typing import Literal

from app.api.errors import Conflict, InvalidInput, NotFound
from app.graph.repository import GraphRepository
from app.ids import new_id

EXECUTED_STATUSES = {"executed_simulated"}
GROUND_TRUTH_KINDS = {"metric", "ticket", "log"}


def create_draft(repo: GraphRepository, *, about_incident_id: str, summary: str,
                 memory_type: Literal["episodic", "procedural"], grounded_in: list[str],
                 derived_from_action_ids: list[str] = (), model_version: str, provenance_refs: list[str] = (),
                 now_ms: int, memory_id: str | None = None) -> str:
    if repo.get_node("Incident", about_incident_id) is None:
        raise NotFound(f"incident {about_incident_id} not found")
    _require_all(repo, "Evidence", grounded_in)
    _require_all(repo, "AgentAction", list(derived_from_action_ids))
    memory_id = memory_id or new_id(repo.scope.tenant_id, "AgentMemory", now_ms)
    repo.merge_node("AgentMemory", memory_id, {
        "memory_type": memory_type, "verification_status": "draft", "outcome": "unknown", "summary": summary,
        "model_version": model_version, "provenance_refs": list(provenance_refs) or None, "source": "agent",
    }, at_ms=now_ms)
    repo.merge_edge("AgentMemory", memory_id, "ABOUT", "Incident", about_incident_id, at_ms=now_ms)
    for ev in grounded_in:
        repo.merge_edge("AgentMemory", memory_id, "GROUNDED_IN", "Evidence", ev, at_ms=now_ms)
    for act in derived_from_action_ids:
        repo.merge_edge("AgentMemory", memory_id, "DERIVED_FROM", "AgentAction", act, at_ms=now_ms)
    return memory_id


def validate_by_human(repo: GraphRepository, memory_id: str, *, responder_id: str,
                      outcome: Literal["successful", "failed"], now_ms: int) -> str:
    """Returns 'verified' or 'unchanged' (idempotent re-validation with the same outcome)."""
    detail = _detail(repo, memory_id)
    if repo.get_node("Responder", responder_id) is None:
        raise InvalidInput(f"unknown responder {responder_id}", code="unknown_reference")
    if (state := _check_validatable(detail, outcome)) == "unchanged":
        if responder_id not in detail["validator_ids"]:
            repo.merge_edge("AgentMemory", memory_id, "VALIDATED_BY", "Responder", responder_id, at_ms=now_ms)
        if detail["memory"].get("validation_method") is None:
            repo.set_memory_verification(memory_id, status="verified", outcome=outcome, method="human",
                                         validated_at_ms=detail["memory"].get("validated_at_ms") or now_ms,
                                         at_ms=now_ms)
        return state
    repo.merge_edge("AgentMemory", memory_id, "VALIDATED_BY", "Responder", responder_id, at_ms=now_ms)
    repo.set_memory_verification(memory_id, status="verified", outcome=outcome, validated_at_ms=now_ms,
                                 method="human", at_ms=now_ms)
    return "verified"


def validate_by_ground_truth(repo: GraphRepository, memory_id: str, *, evidence_ids: list[str],
                             outcome: Literal["successful", "failed"], now_ms: int) -> str:
    detail = _detail(repo, memory_id)
    if not evidence_ids:
        raise InvalidInput("ground truth needs at least one observed-outcome evidence id", code="missing_evidence")
    evidence = _require_all(repo, "Evidence", evidence_ids)
    incident = repo.get_node("Incident", detail["incident_id"]) if detail["incident_id"] else None
    for ev in evidence.values():
        if ev["kind"] not in GROUND_TRUTH_KINDS:
            raise InvalidInput(f"evidence {ev['id']} ({ev['kind']}) is not an observed outcome", code="invalid_evidence")
        if incident and ev["observed_at_ms"] < incident["started_at_ms"]:
            raise InvalidInput(f"evidence {ev['id']} predates the incident", code="invalid_evidence")
    # Check every rule before writing anything, so a refused validation leaves the memory untouched.
    detail["evidence_ids"] = sorted(set(detail["evidence_ids"]) | set(evidence_ids))
    state = _check_validatable(detail, outcome)
    for ev_id in evidence_ids:
        repo.merge_edge("AgentMemory", memory_id, "GROUNDED_IN", "Evidence", ev_id, at_ms=now_ms)
    if state == "unchanged":
        return "unchanged"
    repo.set_memory_verification(memory_id, status="verified", outcome=outcome, validated_at_ms=now_ms,
                                 method="ground_truth", at_ms=now_ms)
    return "verified"


def reject(repo: GraphRepository, memory_id: str, *, responder_id: str, now_ms: int) -> None:
    detail = _detail(repo, memory_id)
    if detail["memory"]["verification_status"] != "draft":
        raise Conflict(f"memory is {detail['memory']['verification_status']}; only drafts can be rejected",
                       code="invalid_transition")
    if repo.get_node("Responder", responder_id) is None:
        raise InvalidInput(f"unknown responder {responder_id}", code="unknown_reference")
    repo.merge_edge("AgentMemory", memory_id, "VALIDATED_BY", "Responder", responder_id, at_ms=now_ms)
    repo.set_memory_verification(memory_id, status="rejected", outcome=detail["memory"]["outcome"],
                                 validated_at_ms=now_ms, method="human", at_ms=now_ms)


def supersede(repo: GraphRepository, *, new_memory_id: str, old_memory_id: str, now_ms: int) -> None:
    old = _detail(repo, old_memory_id)["memory"]
    _detail(repo, new_memory_id)
    if old["verification_status"] in {"superseded", "rejected"}:
        raise Conflict(f"memory {old_memory_id} is already {old['verification_status']}", code="invalid_transition")
    repo.merge_edge("AgentMemory", new_memory_id, "SUPERSEDES", "AgentMemory", old_memory_id, at_ms=now_ms)
    repo.set_memory_verification(old_memory_id, status="superseded", outcome=old["outcome"],
                                 validated_at_ms=old.get("validated_at_ms"), method=old.get("validation_method"),
                                 at_ms=now_ms)


# ---------------------------------------------------------------------------------------------
def _detail(repo: GraphRepository, memory_id: str) -> dict:
    rows = repo.memory_details([memory_id])
    if not rows:
        raise NotFound(f"memory {memory_id} not found")
    return rows[0]


def _check_validatable(detail: dict, outcome: str) -> str:
    mem = detail["memory"]
    if outcome not in {"successful", "failed"}:
        raise InvalidInput("outcome must be successful or failed", code="invalid_outcome")
    if mem["verification_status"] == "verified":
        if mem["outcome"] != outcome:
            raise Conflict("memory is already verified with a different outcome; supersede it instead",
                           code="invalid_transition")
        return "unchanged"
    if mem["verification_status"] != "draft":
        raise Conflict(f"memory is {mem['verification_status']}", code="invalid_transition")
    if not detail["evidence_ids"]:
        raise Conflict("memory has no grounding evidence", code="missing_evidence")
    pending = [a["id"] for a in detail["actions"] if a.get("status") not in EXECUTED_STATUSES]
    if pending:
        raise Conflict(f"derived action(s) {pending} were not executed; a proposed fix is not a verified outcome",
                       code="unexecuted_action")
    return "validatable"


def _require_all(repo: GraphRepository, label: str, ids: list[str]) -> dict[str, dict]:
    found = repo.get_nodes(label, list(ids))
    missing = sorted(set(ids) - set(found))
    if missing:
        raise InvalidInput(f"unknown {label} id(s) {missing}", code="unknown_reference")
    return found
