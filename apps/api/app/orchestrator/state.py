"""LangGraph state for one investigation run.

Every value is JSON-serialisable (dicts from `model_dump(mode="json")`, never model instances), so the
Postgres checkpoint holds plain JSON and a resumed run never depends on pickled Python objects.

Branch nodes run in parallel. Each writes only its own key(s) plus `retrieval_status`, which is the
only key with a reducer (a dict merge), so parallel writes never collide.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

BRANCHES = ("graph_context", "memory_context", "telemetry_context")

# Terminal AgentSession statuses written by the orchestrator.
TERMINAL = frozenset({"awaiting_review", "completed", "failed", "escalated", "inconclusive", "timed_out"})

# Gate decision -> session status (accept is refined by mode and actions in the gate node).
DECISION_STATUS = {"recommendation_only": "completed", "escalate": "escalated", "inconclusive": "inconclusive"}

# Session status -> timeline event type written by notify_channel.
TIMELINE_TYPE = {
    "completed": "investigation_completed",
    "awaiting_review": "investigation_awaiting_review",
    "escalated": "investigation_escalated",
    "inconclusive": "investigation_inconclusive",
    "failed": "investigation_failed",
    "timed_out": "investigation_failed",
}


def merge_status(left: dict | None, right: dict | None) -> dict:
    """Reducer for `retrieval_status`: per-branch entries merged, the later write wins per branch."""
    return {**(left or {}), **(right or {})}


class InvestigationState(TypedDict, total=False):
    # ---- input (the only keys a fresh run is started with)
    session_id: str
    tenant_id: str
    env: str
    # ---- intake_and_deduplicate
    thread_id: str
    mode: str                         # recommendation_only | simulation
    incident: dict[str, Any] | None   # {id, key, title, status, started_at_ms}
    stop_reason: str | None           # set when intake ends the run early
    # ---- coordinator
    required_branches: list[str]
    affected_service_ids: list[str]
    window_start_ms: int
    window_end_ms: int
    deadline_ms: int                  # overall run deadline (wall clock), checked before every node
    # ---- branches (each writes only its own keys)
    graph_context: dict | None        # graph_context_retrieval
    knowledge_context: dict | None    # graph_context_retrieval
    memory_context: dict | None       # memory_retrieval
    telemetry_context: dict | None    # live_evidence_retrieval
    retrieval_status: Annotated[dict[str, dict], merge_status]   # {branch: {status, detail}}
    # ---- investigator / gate loop
    revision: int
    feedback: list[str]
    investigator_name: str | None
    investigator_result: dict | None  # InvestigatorResult (JSON) of the latest attempt, or None
    investigator_error: dict | None   # {kind, message} of the latest attempt, or None
    gate: dict | None                 # GateResult (JSON) or an orchestrator-synthesised equivalent
    # ---- review / execution (Phase 4 placeholders)
    review: dict | None
    execution: dict | None
    # ---- outcome
    status: str
    error: str | None
    action_ids: list[str]
