"""Run progress: one AgentEvent per orchestrator step, written as the step starts and ends.

Events are observability, never control flow: a failed write is logged and the run continues. Ids are
deterministic (`<tenant>.evt.<session>.<node>.<revision>.<status>`), so parallel branches never touch the same
row and a replayed node after a crash rewrites its own rows instead of duplicating them.
"""

from __future__ import annotations

import logging

from app.graph.repository import GraphRepository
from app.orchestrator.persist import session_suffix
from app.orchestrator.state import InvestigationState

log = logging.getLogger("app.orchestrator")

# Causal order of nodes, used to sort events that share a millisecond.
NODE_ORDER = ("intake_and_deduplicate", "coordinator", "graph_context_retrieval", "memory_retrieval",
              "live_evidence_retrieval", "fan_in", "investigator", "evidence_safety_gate", "human_review",
              "restricted_executor")
BRANCH_OF = {"graph_context_retrieval": "graph_context", "memory_retrieval": "memory_context",
             "live_evidence_retrieval": "telemetry_context"}
STATUS_ORDER = {"started": 0, "waiting": 1, "completed": 1, "failed": 1, "skipped": 1}


def event_id(tenant_id: str, session_id: str, kind: str, revision: int, status: str) -> str:
    return f"{tenant_id}.evt.{session_suffix(session_id)}.{kind}.{revision}.{status}"


def record(repo: GraphRepository, state: InvestigationState, kind: str, status: str, *, now_ms: int,
           detail: str | None = None, revision: int = 0, first_only: bool = False) -> None:
    """`first_only` keeps the original row when the event already exists (a node that re-executes after an
    interrupt must not move its own `waiting` timestamp)."""
    try:
        sid = state["session_id"]
        eid = event_id(repo.scope.tenant_id, sid, kind, revision, status)
        if first_only and repo.get_node("AgentEvent", eid) is not None:
            return
        repo.merge_node("AgentEvent", eid, {"kind": kind, "status": status, "at_ms": now_ms, "revision": revision,
                                            "detail": (detail or "")[:300] or None},
                        at_ms=now_ms)
        repo.merge_edge("AgentEvent", eid, "PART_OF", "AgentSession", sid, at_ms=now_ms)
    except Exception:
        log.warning("could not record %s %s event", kind, status, exc_info=True,
                    extra={"investigation_id": state.get("session_id")})


def describe(kind: str, state: InvestigationState, update: dict) -> tuple[str, str | None]:
    """The closing event (status, detail) for a node that returned `update`. Only values already in the state."""
    if kind in BRANCH_OF:
        entry = (update.get("retrieval_status") or {}).get(BRANCH_OF[kind]) or {}
        status = entry.get("status")
        return (status if status in {"completed", "failed", "skipped"} else "completed"), entry.get("detail")
    if kind == "intake_and_deduplicate" and update.get("stop_reason"):
        return "failed", update.get("error")
    if kind == "coordinator":
        return "completed", "branches: " + ", ".join(update.get("required_branches") or [])
    if kind == "fan_in":
        return "completed", ("no retrieval branch completed" if update.get("status") == "inconclusive"
                             else "all branches reported")
    if kind == "investigator":
        err = update.get("investigator_error")
        name = update.get("investigator_name") or "investigator"
        if err:
            return "failed", f"{name}: {err['kind']}"
        return "completed", name
    if kind == "evidence_safety_gate":
        gate = update.get("gate") or {}
        n = len(gate.get("violations") or [])
        return "completed", f"{gate.get('decision', 'n/a')}; {n} violation(s)"
    if kind == "restricted_executor":
        results = (update.get("execution") or {}).get("results") or []
        ran = sum(1 for r in results if r.get("result") == "succeeded" and not r.get("replayed"))
        return "completed", f"{ran} simulated execution(s); no real system changed"
    return "completed", None


def sort_key(row: dict) -> tuple:
    kind = row.get("kind")
    return (row["at_ms"], NODE_ORDER.index(kind) if kind in NODE_ORDER else len(NODE_ORDER),
            row.get("revision") or 0, STATUS_ORDER.get(row.get("status"), 1), row["id"])
