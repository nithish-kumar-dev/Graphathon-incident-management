"""The Phase 4 investigation StateGraph.

    START -> intake_and_deduplicate -> coordinator -> {graph_context_retrieval, memory_retrieval,
             live_evidence_retrieval} -> fan_in (barrier) -> investigator <-> evidence_safety_gate
          -> persist_outcome -> notify_channel -> END                      (recommendation_only, not accepted)
          -> persist_outcome -> notify_channel -> human_review (interrupt) -> restricted_executor
             -> human_review (more actions pending) | finalize_review -> END     (simulation with actions)

See docs/orchestration.md for the diagram, state keys, status mapping and recovery semantics.
Nodes are closures over a `RunEnv` (dependencies, FalkorDB handle, settings). The tenant/env scope of a
run comes from its state, never from a global.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from falkordb import Graph
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.contracts import (
    GateResult,
    InvestigatorError,
    InvestigatorInput,
    InvestigatorOutput,
    InvestigatorResult,
    TelemetryContext,
)
from app.api.errors import NotFound
from app.config import Settings
from app.domain.actions import canonical_json
from app.graph.client import GraphUnavailable
from app.graph.repository import GraphRepository, Scope
from app.orchestrator import events
from app.orchestrator.dependencies import Dependencies
from app.orchestrator.executor import execute_approved, pending_action_ids
from app.orchestrator.persist import notify_channel, persist_outcome
from app.orchestrator.state import BRANCHES, DECISION_STATUS, InvestigationState
from app.rag.retrieval import RetrievalBundle
from app.tools import graph_tools as t
from app.tools.graph_tools import ToolContext

log = logging.getLogger("app.orchestrator")

WINDOW_BEFORE_START_MS = 2 * 3_600_000          # live evidence window: incident start - 2 h .. now
NODE_NAMES = ("intake_and_deduplicate", "coordinator", "graph_context_retrieval", "memory_retrieval",
              "live_evidence_retrieval", "fan_in", "investigator", "evidence_safety_gate", "human_review",
              "restricted_executor", "persist_outcome", "notify_channel", "finalize_review")


class RunTimedOut(RuntimeError):
    """The overall run deadline passed. The runner records status `timed_out`."""


class BranchTimeout(TimeoutError):
    pass


# ============================================================================ shared retrieval cache
class BundleCache:
    """One `retrieve()` call per (run, attempt), shared by the graph and memory branches.

    Both branches are separate nodes with separate state keys; they only share the expensive read.
    The future is computed in a daemon thread so a branch can stop waiting at its timeout.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: dict[tuple[str, int], Future] = {}

    def get(self, run_key: str, attempt: int, compute: Callable[[], RetrievalBundle]) -> Future:
        with self._lock:
            fut = self._futures.get((run_key, attempt))
            if fut is None:
                fut = self._futures[(run_key, attempt)] = Future()
                threading.Thread(target=_fill, args=(fut, compute), daemon=True,
                                 name=f"retrieve-{run_key[-8:]}-{attempt}").start()
            return fut

    def drop(self, run_key: str) -> None:
        with self._lock:
            for key in [k for k in self._futures if k[0] == run_key]:
                del self._futures[key]


def _fill(fut: Future, fn: Callable[[], Any]) -> None:
    try:
        fut.set_result(fn())
    except BaseException as exc:  # noqa: BLE001 - re-raised in the waiting branch
        fut.set_exception(exc)


def call_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run fn in a daemon thread; raise BranchTimeout if it has not finished in time.
    A stuck call is abandoned (it cannot be killed) but never blocks the run or process exit."""
    fut: Future = Future()
    threading.Thread(target=_fill, args=(fut, fn), daemon=True, name="branch-call").start()
    try:
        return fut.result(timeout=max(0.0, timeout_s))
    except TimeoutError:
        if fut.done():
            return fut.result()
        raise BranchTimeout(f"timed out after {timeout_s:g}s") from None


# ============================================================================ run environment
@dataclass
class RunEnv:
    deps: Dependencies
    falkor: Graph
    settings: Settings
    run_timeout_s: float
    cache: BundleCache = field(default_factory=BundleCache)

    def repo(self, state: InvestigationState) -> GraphRepository:
        return GraphRepository(self.falkor, Scope(state["tenant_id"], state["env"]),
                               timeout_ms=self.settings.graph_query_timeout_ms)

    def ro(self, state: InvestigationState) -> ToolContext:
        return ToolContext.read_only(self.falkor, Scope(state["tenant_id"], state["env"]),
                                     now_ms=state.get("window_end_ms") or self.deps.clock(),
                                     timeout_ms=self.settings.graph_query_timeout_ms)

    def remaining_s(self, state: InvestigationState) -> float:
        deadline = state.get("deadline_ms")
        return float("inf") if deadline is None else (deadline - self.deps.clock()) / 1000


def _traced(env: RunEnv, name: str, fn: Callable[[InvestigationState], dict],
            revision_of: Callable[[InvestigationState], int] | None = None) -> Callable[[InvestigationState], dict]:
    """Write a `started` and a closing AgentEvent around a node so progress is visible while the run is live."""
    def node(state: InvestigationState) -> dict:
        repo = env.repo(state)
        revision = revision_of(state) if revision_of else int(state.get("revision") or 0)
        events.record(repo, state, name, "started", now_ms=env.deps.clock(), revision=revision)
        try:
            update = fn(state)
        except Exception as exc:
            detail = str(exc) if isinstance(exc, (RunTimedOut, NotFound)) else f"unexpected {type(exc).__name__}"
            events.record(repo, state, name, "failed", now_ms=env.deps.clock(), detail=detail, revision=revision)
            raise
        status, detail = events.describe(name, state, update)
        events.record(repo, state, name, status, now_ms=env.deps.clock(), detail=detail, revision=revision)
        return update
    node.__name__ = name
    return node


def _guard(env: RunEnv, name: str, fn: Callable[[InvestigationState], dict]) -> Callable[[InvestigationState], dict]:
    """Every node checks the overall run deadline first; a late run stops with RunTimedOut."""
    def node(state: InvestigationState) -> dict:
        if env.remaining_s(state) <= 0:
            raise RunTimedOut(f"run deadline passed before {name}")
        return fn(state)
    node.__name__ = name
    return node


# ============================================================================ nodes
def build(env: RunEnv) -> StateGraph:
    deps, settings = env.deps, env.settings

    # ---- 1. intake_and_deduplicate
    def intake(state: InvestigationState) -> dict:
        repo = env.repo(state)
        ses = repo.get_node("AgentSession", state["session_id"])
        if ses is None:
            raise NotFound(f"investigation {state['session_id']} not found")
        base = {"thread_id": ses["thread_id"], "mode": ses["mode"], "revision": 0, "feedback": [],
                "status": "running", "stop_reason": None, "error": None}
        incs = repo.neighbors("AgentSession", ses["id"], "INVESTIGATES", "Incident", outgoing=True, limit=1)
        if not incs:
            return {**base, "incident": None, "stop_reason": "incident_missing", "status": "failed",
                    "error": "incident_missing: the investigated incident no longer exists"}
        inc = incs[0]
        incident = {k: inc.get(k) for k in ("id", "key", "title", "status", "started_at_ms")}
        if inc["status"] == "resolved":
            return {**base, "incident": incident, "stop_reason": "incident_resolved", "status": "failed",
                    "error": "incident_resolved: nothing to investigate"}
        mine = (ses["started_at_ms"], ses["id"])
        others = [s for s in repo.neighbors("Incident", inc["id"], "INVESTIGATES", "AgentSession", outgoing=False,
                                            order_by="started_at_ms", limit=50)
                  if s["id"] != ses["id"] and s.get("status") == "running" and (s["started_at_ms"], s["id"]) < mine]
        if others:
            return {**base, "incident": incident, "stop_reason": "duplicate", "status": "failed",
                    "error": f"duplicate: investigation {others[0]['id']} is already running for this incident"}
        return {**base, "incident": incident}

    def route_intake(state: InvestigationState) -> str:
        return "persist_outcome" if state.get("stop_reason") else "coordinator"

    # ---- 2. coordinator: scope + required branches + run metadata. Never approves or executes.
    def coordinator(state: InvestigationState) -> dict:
        repo = env.repo(state)
        now = deps.clock()
        affected = sorted(s["id"] for s in repo.neighbors("Incident", state["incident"]["id"], "AFFECTS", "Service",
                                                          outgoing=True, limit=20))
        required = ["graph_context", "memory_context"] + (["telemetry_context"] if affected else [])
        status = {b: ({"status": "running"} if b in required else
                      {"status": "skipped", "detail": "no affected services to observe"}) for b in BRANCHES}
        repo.update_node("AgentSession", state["session_id"], {
            "status": "running", "branch_status_json": canonical_json(status),
            "investigator": getattr(deps.investigator, "name", None)}, at_ms=now)
        return {"required_branches": required, "affected_service_ids": affected,
                "window_start_ms": int(state["incident"]["started_at_ms"]) - WINDOW_BEFORE_START_MS,
                "window_end_ms": now, "deadline_ms": now + int(env.run_timeout_s * 1000),
                "investigator_name": getattr(deps.investigator, "name", None)}

    # ---- 3. three parallel branches
    def _branch(state: InvestigationState, branch: str, work: Callable[[int], tuple[dict, str]]) -> tuple:
        """Run `work(attempt)` with the branch timeout and one retry on GraphUnavailable.
        Returns (status_entry, value_or_None). A failure is recorded, never papered over."""
        if branch not in (state.get("required_branches") or []):
            return {"status": "skipped", "detail": "not required for this incident"}, None
        budget = min(settings.branch_timeout_s, env.remaining_s(state))
        start = time.monotonic()
        for attempt in (0, 1):
            left = budget - (time.monotonic() - start)
            try:
                value, detail = call_with_timeout(lambda a=attempt: work(a), left)
                return {"status": "completed", "detail": detail[:300]}, value
            except BranchTimeout:
                return {"status": "failed", "detail": f"timed out after {settings.branch_timeout_s:g}s"}, None
            except GraphUnavailable:
                if attempt == 0:
                    log.warning("branch %s: graph unavailable, retrying once", branch,
                                extra={"investigation_id": state["session_id"]})
                    continue
                return {"status": "failed", "detail": "graph database unavailable (after 1 retry)"}, None
            except NotFound as exc:
                return {"status": "failed", "detail": str(exc)[:300]}, None
            except Exception as exc:  # a broken branch must not invent data or kill the run
                log.exception("branch %s failed", branch, extra={"investigation_id": state["session_id"]})
                return {"status": "failed", "detail": f"unexpected {type(exc).__name__}; see server log"}, None
        raise AssertionError("unreachable")

    def _bundle(state: InvestigationState, attempt: int) -> RetrievalBundle:
        ctx = env.ro(state)
        fut = env.cache.get(state["thread_id"], attempt, lambda: deps.retrieve(ctx, state["incident"]["id"]))
        return fut.result()

    def graph_branch(state: InvestigationState) -> dict:
        def work(attempt: int):
            b = _bundle(state, attempt)
            allowed = settings.allowed_classifications
            knowledge = b.knowledge_context.model_copy(update={
                "items": [c for c in b.knowledge_context.items if c.document_classification in allowed]})
            gc = b.graph_context
            detail = (f"{len(gc.evidence)} evidence, {len(gc.explanation_paths)} explanation path(s), "
                      f"{len(knowledge.items)} knowledge chunk(s)")
            return (gc.model_dump(mode="json"), knowledge.model_dump(mode="json")), detail
        entry, value = _branch(state, "graph_context", work)
        gc, kc = value or (None, None)
        return {"graph_context": gc, "knowledge_context": kc, "retrieval_status": {"graph_context": entry}}

    def memory_branch(state: InvestigationState) -> dict:
        def work(attempt: int):
            mc = _bundle(state, attempt).memory_context
            # Defence in depth: retrieval already filters, but only verified, grounded, validated items pass.
            kept = [x for x in mc.items if x.verification_status == "verified" and x.grounded_in
                    and (x.validated_by or x.validation_method == "ground_truth")]
            excluded = dict(mc.excluded)
            if len(kept) != len(mc.items):
                excluded["failed_recheck"] = len(mc.items) - len(kept)
            mc = mc.model_copy(update={"items": kept, "excluded": excluded})
            ex = ", ".join(f"{k} {v}" for k, v in sorted(excluded.items()))
            return mc.model_dump(mode="json"), f"{len(kept)} verified memory item(s)" + (f"; excluded: {ex}" if ex else "")
        entry, value = _branch(state, "memory_context", work)
        return {"memory_context": value, "retrieval_status": {"memory_context": entry}}

    def telemetry_branch(state: InvestigationState) -> dict:
        def work(attempt: int):
            ctx = env.ro(state)
            paths = t.get_explanation_path(ctx, t.ExplanationPathArgs(incident_id=state["incident"]["id"])).paths
            services = sorted(set(state.get("affected_service_ids") or []) | {p.target_service_id for p in paths})
            tel = deps.telemetry(state["tenant_id"], state["env"], services, state["window_start_ms"],
                                 state["window_end_ms"])
            tel = TelemetryContext.model_validate(tel.model_dump() if hasattr(tel, "model_dump") else tel)
            return tel.model_dump(mode="json"), f"{len(tel.observations)} observation(s) on {', '.join(services)}"
        entry, value = _branch(state, "telemetry_context", work)
        return {"telemetry_context": value, "retrieval_status": {"telemetry_context": entry}}

    # ---- 4. fan_in barrier
    def fan_in(state: InvestigationState) -> dict:
        rs = state.get("retrieval_status") or {}
        if any(rs.get(b, {}).get("status") == "completed" for b in BRANCHES):
            return {}
        return {"status": "inconclusive", "gate": {
            "decision": "inconclusive", "hypotheses": [], "proposed_actions": [],
            "violations": [{"code": "inconclusive", "target": "retrieval",
                            "detail": "no retrieval branch completed; nothing to investigate with"}]}}

    def route_fan_in(state: InvestigationState) -> str:
        return "persist_outcome" if state.get("status") == "inconclusive" else "investigator"

    # ---- 5. investigator
    def investigator(state: InvestigationState) -> dict:
        inp = build_input(state)
        timeout = max(0.1, min(settings.llm_timeout_s, env.remaining_s(state)))
        try:
            res = deps.investigator.run(inp, timeout_s=timeout)
            res = InvestigatorResult.model_validate(res.model_dump() if hasattr(res, "model_dump") else res)
            return {"investigator_result": res.model_dump(mode="json"), "investigator_error": None,
                    "investigator_name": res.investigator}
        except InvestigatorError as exc:
            log.warning("investigator %s on revision %s", exc.kind, inp.revision,
                        extra={"investigation_id": state["session_id"]})
            return {"investigator_result": None, "investigator_error": {"kind": exc.kind, "message": str(exc)[:300]},
                    "investigator_name": getattr(deps.investigator, "name", None)}

    # ---- 6. evidence_safety_gate
    def gate_node(state: InvestigationState) -> dict:
        revision, max_rev = int(state.get("revision") or 0), settings.max_investigation_revisions
        err = state.get("investigator_error")
        if err:
            violation = {"code": f"investigator_{err['kind']}", "target": "investigator",
                         "detail": f"previous attempt failed ({err['kind']}): {err['message']}"[:300]}
            if revision < max_rev:
                return {"gate": {"decision": "revise", "hypotheses": [], "proposed_actions": [],
                                 "violations": [violation]},
                        "revision": revision + 1, "feedback": [violation["detail"]], "status": "running"}
            violation["detail"] = f"investigator failed after {revision + 1} attempt(s): {err['kind']}"
            return {"gate": {"decision": "inconclusive", "hypotheses": [], "proposed_actions": [],
                             "violations": [violation]}, "status": "inconclusive"}

        inp = build_input(state)
        output = InvestigatorOutput.model_validate(state["investigator_result"]["output"])
        result: GateResult = deps.gate(output, inp, repo=env.ro(state).repo, revision=revision, max_revisions=max_rev)
        g = GateResult.model_validate(result.model_dump() if hasattr(result, "model_dump") else result)
        if g.decision == "revise" and revision >= max_rev:   # contract guard: never loop past the limit
            g = g.model_copy(update={"decision": "recommendation_only" if g.hypotheses else "inconclusive",
                                     "proposed_actions": []})
        gate = g.model_dump(mode="json")
        if g.decision == "revise":
            return {"gate": gate, "revision": revision + 1, "feedback": [v.detail for v in g.violations],
                    "status": "running"}
        if g.decision == "accept":
            status = "awaiting_review" if state["mode"] == "simulation" and g.proposed_actions else "completed"
        else:
            status = DECISION_STATUS[g.decision]
        return {"gate": gate, "status": status}

    def route_gate(state: InvestigationState) -> str:
        return "investigator" if (state.get("gate") or {}).get("decision") == "revise" else "persist_outcome"

    # ---- 7. human_review: the run PAUSES here (LangGraph interrupt) until a human has decided. Actions and the
    # session (`awaiting_review`) were persisted before the pause, so they are visible while it waits. Nothing is
    # approved or executed here; the decision itself is made by the authenticated review API.
    def human_review(state: InvestigationState) -> dict:
        repo, rnd, now = env.repo(state), int((state.get("review") or {}).get("round") or 0), deps.clock()
        pending = pending_action_ids(repo.session_actions(state["session_id"]))
        events.record(repo, state, "human_review", "started", now_ms=now, revision=rnd, first_only=True)
        events.record(repo, state, "human_review", "waiting", now_ms=now, revision=rnd, first_only=True,
                      detail=f"awaiting a human decision on {len(pending)} action(s)")
        interrupt({"session_id": state["session_id"], "action_ids": pending})
        events.record(repo, state, "human_review", "completed", now_ms=deps.clock(), revision=rnd,
                      detail="a human decision was recorded")
        return {"review": {"round": rnd + 1, "pending": pending}}

    # ---- 8. restricted_executor: re-reads graph state; runs only approved, allowlisted, unexpired, simulation actions
    def restricted_executor(state: InvestigationState) -> dict:
        if state.get("mode") != "simulation":
            raise PermissionError("restricted_executor refuses recommendation_only runs")
        repo = env.repo(state)
        results = execute_approved(repo, deps.idempotency, state["session_id"], now_ms=deps.clock())
        done = {r["action_id"] for r in results}
        prior = [r for r in (state.get("execution") or {}).get("results", []) if r["action_id"] not in done]
        review = state.get("review") or {}
        return {"execution": {"results": prior + results},
                "review": {**review, "pending": pending_action_ids(repo.session_actions(state["session_id"]))}}

    def route_executor(state: InvestigationState) -> str:
        return "human_review" if (state.get("review") or {}).get("pending") else "finalize_review"

    # ---- 8b. finalize_review: the session leaves `awaiting_review` once no action is left for a human
    def finalize_review(state: InvestigationState) -> dict:
        repo, now = env.repo(state), deps.clock()
        rows = repo.session_actions(state["session_id"])
        final = "escalated" if any(r["action"]["status"] == "escalated" for r in rows) else "completed"
        repo.update_node("AgentSession", state["session_id"], {"status": final, "ended_at_ms": now}, at_ms=now)
        return {"status": final}

    # ---- 9-10. persist + notify
    def persist(state: InvestigationState) -> dict:
        return {"action_ids": persist_outcome(env.repo(state), state, now_ms=deps.clock())}

    def notify(state: InvestigationState) -> dict:
        notify_channel(env.repo(state), state, now_ms=deps.clock())
        return {}

    g = StateGraph(InvestigationState)
    for name, fn in (("intake_and_deduplicate", intake), ("coordinator", coordinator),
                     ("graph_context_retrieval", graph_branch), ("memory_retrieval", memory_branch),
                     ("live_evidence_retrieval", telemetry_branch), ("fan_in", fan_in),
                     ("investigator", investigator), ("evidence_safety_gate", gate_node)):
        g.add_node(name, _traced(env, name, _guard(env, name, fn)))
    # After a human pause the run deadline no longer applies, so the review/executor nodes are not guarded;
    # human_review records its own (once-only) events because it re-executes from the top on resume.
    g.add_node("human_review", human_review)
    g.add_node("restricted_executor", _traced(env, "restricted_executor", restricted_executor,
                                              lambda s: max(int((s.get("review") or {}).get("round") or 1) - 1, 0)))
    g.add_node("persist_outcome", persist)
    g.add_node("notify_channel", notify)
    g.add_node("finalize_review", finalize_review)
    g.add_edge(START, "intake_and_deduplicate")
    g.add_conditional_edges("intake_and_deduplicate", route_intake, ["coordinator", "persist_outcome"])
    for branch in ("graph_context_retrieval", "memory_retrieval", "live_evidence_retrieval"):
        g.add_edge("coordinator", branch)
    g.add_edge(["graph_context_retrieval", "memory_retrieval", "live_evidence_retrieval"], "fan_in")
    g.add_conditional_edges("fan_in", route_fan_in, ["investigator", "persist_outcome"])
    g.add_edge("investigator", "evidence_safety_gate")
    g.add_conditional_edges("evidence_safety_gate", route_gate, ["investigator", "persist_outcome"])
    g.add_edge("persist_outcome", "notify_channel")
    g.add_conditional_edges("notify_channel", route_after_notify, ["human_review", END])
    g.add_edge("human_review", "restricted_executor")
    g.add_conditional_edges("restricted_executor", route_executor, ["human_review", "finalize_review"])
    g.add_edge("finalize_review", END)
    return g


def route_after_notify(state: InvestigationState) -> str:
    """Only a simulation run with accepted, persisted actions pauses for a human. recommendation_only never does:
    it cannot reach human_review, so it can never reach the executor."""
    if state.get("mode") == "simulation" and state.get("status") == "awaiting_review" and state.get("action_ids"):
        return "human_review"
    return END


def build_input(state: InvestigationState) -> InvestigatorInput:
    """Only completed branch outputs reach the investigator."""
    rs = state.get("retrieval_status") or {}
    done = {b for b in BRANCHES if rs.get(b, {}).get("status") == "completed"}
    inc = state["incident"]
    return InvestigatorInput(
        incident_id=inc["id"], incident_key=inc["key"], incident_title=inc["title"], tenant_id=state["tenant_id"],
        env=state["env"], mode=state["mode"], revision=int(state.get("revision") or 0),
        branch_status={b: rs.get(b, {}).get("status", "pending") for b in BRANCHES},
        graph_context=state.get("graph_context") if "graph_context" in done else None,
        knowledge_context=state.get("knowledge_context") if "graph_context" in done else None,
        memory_context=state.get("memory_context") if "memory_context" in done else None,
        telemetry_context=state.get("telemetry_context") if "telemetry_context" in done else None,
        feedback=list(state.get("feedback") or []),
    )
