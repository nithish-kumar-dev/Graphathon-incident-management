"""Phase 4 orchestrator: the LangGraph run, persistence, recovery, the worker claim and the API fields.

Each test runs on its own seeded graph on the ephemeral test server. Dependencies are injected through
`Dependencies`; retrieval, telemetry, the gate and the stub investigator are the real ones, wrapped to count
calls and to inject delays and failures. Most tests use an in-memory checkpointer; the golden path and the
restart recovery also run against the real PostgresSaver on the project database (skipped if unreachable).
"""

from __future__ import annotations

import collections
import hashlib
import threading
import time

import pytest
from app import auth
from app.agents import safety_gate
from app.agents.contracts import Hypothesis, InvestigatorError, InvestigatorResult
from app.agents.investigator import StubInvestigator
from app.api import models as m
from app.domain.actions import canonical_json
from app.graph.client import GraphUnavailable
from app.graph.repository import GraphRepository, Scope
from app.orchestrator.dependencies import Dependencies
from app.orchestrator.graph import route_review
from app.orchestrator.persist import persist_outcome
from app.orchestrator.runner import Orchestrator, Worker
from app.orchestrator.state import TERMINAL
from app.rag.embeddings import HashingEmbedder
from app.rag.retrieval import retrieve as real_retrieve
from app.services import investigations
from app.telemetry import synthetic
from langgraph.checkpoint.memory import MemorySaver

from .conftest import ALLOWED, NOW, RESPONDER

pytestmark = pytest.mark.integration

SCOPE = Scope("nova", "prod")
INC = "nova.inc.101"
_THREADS: list[str] = []


class Crash(BaseException):
    """Simulates a killed process: not an Exception, so the orchestrator cannot record it."""


class Clock:
    def __init__(self) -> None:
        self.offset_ms = 0

    def __call__(self) -> int:
        return NOW + self.offset_ms


class Calls:
    def __init__(self) -> None:
        self.n: collections.Counter = collections.Counter()
        self.log: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def hit(self, name: str) -> int:
        with self._lock:
            self.n[name] += 1
            self.log.append((name, time.monotonic()))
            return self.n[name]

    def at(self, name: str) -> list[float]:
        return [t for n, t in self.log if n == name]


class FakeInvestigator:
    """The stub investigator by default; `behave(inp, call_number)` may return a custom output or raise."""

    def __init__(self, calls: Calls, behave=None, name: str = "stub-v1") -> None:
        self.calls, self.behave, self.name = calls, behave, name
        self.stub = StubInvestigator()
        self.inputs: list = []

    def run(self, inp, *, timeout_s: float) -> InvestigatorResult:
        n = self.calls.hit("investigator")
        self.inputs.append(inp)
        out = self.behave(inp, n) if self.behave else self.stub.investigate(inp)
        return InvestigatorResult(output=out, investigator=self.name, latency_ms=1)


def make_deps(calls: Calls, *, before_retrieve=None, before_telemetry=None, behave=None, clock=None) -> Dependencies:
    embedder = HashingEmbedder()

    def retrieve(ctx, incident_id):
        n = calls.hit("retrieve")
        if before_retrieve:
            before_retrieve(n)
        out = real_retrieve(ctx, incident_id, embedder=embedder, allowed_classifications=ALLOWED)
        calls.hit("retrieve_done")
        return out

    def telemetry(tenant_id, env, service_ids, window_start_ms, window_end_ms):
        n = calls.hit("telemetry")
        if before_telemetry:
            before_telemetry(n)
        out = synthetic.collect(tenant_id, env, service_ids, window_start_ms, window_end_ms)
        calls.hit("telemetry_done")
        return out

    def gate(output, inp, *, repo, revision, max_revisions):
        calls.hit("gate")
        return safety_gate.evaluate(output, inp, repo=repo, revision=revision, max_revisions=max_revisions)

    return Dependencies(retrieve=retrieve, telemetry=telemetry, investigator=FakeInvestigator(calls, behave),
                        gate=gate, clock=clock or (lambda: NOW))


def make_orch(graph, settings, deps, *, saver=None, **kw) -> Orchestrator:
    s = settings.model_copy(update={"graph_name": graph.name, **kw.pop("overrides", {})})
    return Orchestrator(falkor=graph, checkpointer=saver or MemorySaver(), settings=s, deps=deps, **kw)


def start(graph, mode: str = "recommendation_only") -> str:
    """Create an investigation through the service and claim it, as the worker would."""
    repo = GraphRepository(graph, SCOPE)
    out, _ = investigations.create(repo, m.InvestigationIn(incident_id=INC, mode=mode),
                                   auth.DEMO_USERS["demo-responder"], NOW)
    assert repo.claim_session(out.id, now_ms=NOW)
    _THREADS.append(out.thread_id)
    return out.id


def run_actions(graph, sid: str) -> list[dict]:
    """AgentAction nodes created by this run (the seed already holds actions from past incidents)."""
    marker = f".act.{sid.split('.', 2)[2]}."
    return [a for a in GraphRepository(graph, SCOPE).list_nodes("AgentAction") if marker in a["id"]]


def get(graph, sid: str) -> m.InvestigationOut:
    return investigations.get(GraphRepository(graph, SCOPE), sid)


def run_golden(graph, settings, mode="recommendation_only", **deps_kw):
    calls = Calls()
    orch = make_orch(graph, settings, make_deps(calls, **deps_kw))
    sid = start(graph, mode)
    return orch, calls, sid, orch.run(sid, SCOPE)


@pytest.fixture(params=["memory", "postgres"])
def saver(request, settings):
    if request.param == "memory":
        yield MemorySaver()
        return
    from app.orchestrator.checkpoint import make_saver, open_pool
    try:
        pool = open_pool(settings.postgres_dsn.get_secret_value(), max_size=4)
    except Exception:
        pytest.skip("project Postgres not reachable; run `docker compose up -d postgres`")
    s = make_saver(pool, setup=True)
    yield s
    for tid in _THREADS:
        s.delete_thread(tid)
    pool.close()


# ================================================================================ golden path (end to end)
def test_golden_recommendation_only_end_to_end(mutable_graph, settings, saver):
    """Real stub investigator + gate + synthetic telemetry on INC-101."""
    repo = GraphRepository(mutable_graph, SCOPE)
    memories_before = {x["id"]: x.get("verification_status") for x in repo.list_nodes("AgentMemory")}
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls), saver=saver)
    sid = start(mutable_graph)
    assert orch.run(sid, SCOPE) == "completed"

    out = get(mutable_graph, sid)
    assert out.status == "completed" and out.error is None and out.ended_at is not None
    assert out.investigator == "stub-v1" and out.summary and out.overall_uncertainty
    assert {b: s.status for b, s in out.branches.items()} == {
        "graph_context": "completed", "memory_context": "completed", "telemetry_context": "completed"}
    assert out.gate is not None and out.gate.decision == "accept" and out.gate.violations == []
    assert out.revision_count == 0

    claims = {f.claim_type for f in out.findings}
    assert "correlated" in claims and "confirmed" not in claims            # only humans confirm
    for f in out.findings:
        assert f.evidence and f.confidence is not None
        assert all(e.id.startswith("nova.ev.") for e in f.evidence + f.contradicting_evidence)

    [action] = out.proposed_actions
    assert action.id.startswith("nova.act.") and action.id.endswith(".1.v1") and action.version == 1
    assert action.proposal_id == action.id.replace(".act.", ".prop.").removesuffix(".v1")
    assert action.action_type == "rollback_deployment_simulated" and action.status == "proposed"
    assert (action.target_service_id, action.deployment_id) == ("nova.svc.payment", "nova.dep.payment.v2_4")
    assert action.runbook_id == "nova.rb.payment.rollback" and action.mode == "recommendation_only"
    assert action.spec == {"action_type": "rollback_deployment_simulated", "tenant_id": "nova", "env": "prod",
                           "service_id": "nova.svc.payment", "deployment_id": "nova.dep.payment.v2_4",
                           "runbook_id": "nova.rb.payment.rollback"}
    assert action.spec_hash == hashlib.sha256(canonical_json(action.spec).encode()).hexdigest()
    assert action.evidence and action.integrity_warnings == []

    # every cited id exists in the graph, and telemetry became kind=metric evidence on the incident
    cited = {e.id for f in out.findings for e in f.evidence + f.contradicting_evidence}
    cited |= {e.id for e in action.evidence}
    assert cited <= set(repo.get_nodes("Evidence", sorted(cited)))
    tel = [e for e in repo.get_nodes("Evidence", sorted(cited)).values() if e["id"].startswith("nova.ev.tel.")]
    assert tel and all(e["kind"] == "metric" for e in tel)
    inc_evidence = {e["id"] for e in repo.neighbors("Incident", INC, "HAS_EVIDENCE", "Evidence", outgoing=True,
                                                    limit=200)}
    assert {e["id"] for e in tel} <= inc_evidence

    # recommendation_only: nothing executed, no memory verified, an outcome event on the timeline
    state = orch.graph.get_state(orch.config(out.thread_id)).values
    assert state.get("execution") is None and state["status"] == "completed"
    assert {x["id"]: x.get("verification_status") for x in repo.list_nodes("AgentMemory")} == memories_before
    events = repo.neighbors("Incident", INC, "HAS_EVENT", "TimelineEvent", outgoing=True, limit=100)
    assert any(e["type"] == "investigation_completed" and e["ref_id"] == sid for e in events)
    assert orch.run(sid, SCOPE) == "completed"                           # a finished run is not re-run
    assert calls.n["investigator"] == 1 and calls.n["retrieve"] == 1


def test_simulation_awaits_review_and_executes_nothing(mutable_graph, settings):
    orch, _, sid, status = run_golden(mutable_graph, settings, mode="simulation")
    assert status == "awaiting_review"
    out = get(mutable_graph, sid)
    [action] = out.proposed_actions
    assert action.status == "pending_review" and action.mode == "simulation"
    state = orch.graph.get_state(orch.config(out.thread_id)).values
    assert state["review"]["decision"] == "pending" and state.get("execution") is None
    assert [a["status"] for a in run_actions(mutable_graph, sid)] == ["pending_review"]


# ================================================================================ branches
def test_branch_failure_is_recorded_and_not_invented(mutable_graph, settings):
    def boom(_n):
        raise RuntimeError("password=hunter2 host=db.internal")

    orch, calls, sid, status = run_golden(mutable_graph, settings, before_telemetry=boom)
    assert status == "completed"
    out = get(mutable_graph, sid)
    assert out.branches["telemetry_context"].status == "failed"
    assert "hunter2" not in (out.branches["telemetry_context"].detail or "")
    assert out.branches["graph_context"].status == out.branches["memory_context"].status == "completed"
    inp = orch.env.deps.investigator.inputs[0]
    assert inp.telemetry_context is None and inp.branch_status["telemetry_context"] == "failed"
    assert not any(e.id.startswith("nova.ev.tel.") for f in out.findings for e in f.evidence)
    assert "telemetry_context failed" in (out.overall_uncertainty or "")


def test_missing_branch_is_skipped(mutable_graph, settings):
    repo = GraphRepository(mutable_graph, SCOPE)
    assert repo.delete_edge("Incident", INC, "AFFECTS", "Service", "nova.svc.checkout") == 1
    orch, calls, sid, status = run_golden(mutable_graph, settings)
    out = get(mutable_graph, sid)
    assert out.branches["telemetry_context"].status == "skipped" and calls.n["telemetry"] == 0
    assert out.branches["graph_context"].status == "completed" and status in TERMINAL


def test_all_branches_failing_is_inconclusive_without_calling_the_investigator(mutable_graph, settings):
    def boom(_n):
        raise RuntimeError("x")

    calls = Calls()
    deps = make_deps(calls, before_retrieve=boom, before_telemetry=boom)
    orch = make_orch(mutable_graph, settings, deps)
    sid = start(mutable_graph)
    assert orch.run(sid, SCOPE) == "inconclusive"
    out = get(mutable_graph, sid)
    assert {s.status for s in out.branches.values()} == {"failed"}
    assert calls.n["investigator"] == 0 and out.proposed_actions == [] and out.gate.decision == "inconclusive"


def test_barrier_waits_for_delayed_branches(mutable_graph, settings):
    orch, calls, sid, status = run_golden(mutable_graph, settings,
                                          before_retrieve=lambda _n: time.sleep(0.5),
                                          before_telemetry=lambda _n: time.sleep(0.8))
    assert status == "completed" and calls.n["investigator"] == 1
    [started] = calls.at("investigator")
    assert started >= max(calls.at("retrieve_done")) and started >= max(calls.at("telemetry_done"))
    assert set(orch.env.deps.investigator.inputs[0].branch_status.values()) == {"completed"}


def test_branch_timeout(mutable_graph, settings):
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls, before_telemetry=lambda _n: time.sleep(2.5)),
                     overrides={"branch_timeout_s": 0.4})
    sid = start(mutable_graph)
    t0 = time.monotonic()
    assert orch.run(sid, SCOPE) == "completed"
    assert time.monotonic() - t0 < 2.4                      # did not wait for the stuck call
    out = get(mutable_graph, sid)
    assert out.branches["telemetry_context"].status == "failed"
    assert "timed out" in out.branches["telemetry_context"].detail
    assert out.branches["graph_context"].status == "completed"


def test_transient_graph_outage_is_retried_once(mutable_graph, settings):
    def flaky(n):
        if n == 1:
            raise GraphUnavailable("graph database unavailable")

    orch, calls, sid, status = run_golden(mutable_graph, settings, before_telemetry=flaky, before_retrieve=flaky)
    assert status == "completed"
    assert calls.n["telemetry"] == 2 and calls.n["retrieve"] == 2
    assert {s.status for s in get(mutable_graph, sid).branches.values()} == {"completed"}


def test_persistent_graph_outage_fails_the_branch_after_one_retry(mutable_graph, settings):
    def down(_n):
        raise GraphUnavailable("graph database unavailable")

    orch, calls, sid, status = run_golden(mutable_graph, settings, before_telemetry=down)
    out = get(mutable_graph, sid)
    assert calls.n["telemetry"] == 2
    assert out.branches["telemetry_context"].status == "failed" and "1 retry" in out.branches["telemetry_context"].detail


# ================================================================================ revision loop
def test_malformed_output_then_valid_output(mutable_graph, settings):
    stub = StubInvestigator()

    def behave(inp, n):
        if n == 1:
            raise InvestigatorError("malformed", "output failed validation")
        assert inp.revision == 1 and any("malformed" in f for f in inp.feedback)
        return stub.investigate(inp)

    orch, calls, sid, status = run_golden(mutable_graph, settings, behave=behave)
    out = get(mutable_graph, sid)
    assert status == "completed" and out.revision_count == 1 and calls.n["investigator"] == 2
    assert out.gate.decision == "accept" and len(out.proposed_actions) == 1


def test_malformed_forever_is_inconclusive(mutable_graph, settings):
    def behave(inp, n):
        raise InvestigatorError("malformed", "output failed validation")

    orch, calls, sid, status = run_golden(mutable_graph, settings, behave=behave)
    out = get(mutable_graph, sid)
    assert status == "inconclusive" and calls.n["investigator"] == 3          # initial + MAX_REVISIONS (2)
    assert out.revision_count == 2 and out.proposed_actions == [] and out.findings == []
    assert out.gate.decision == "inconclusive" and out.summary is None


def _bad_action(inp, n):
    out = StubInvestigator().investigate(inp.model_copy(update={"feedback": []}))   # ignores gate feedback
    bad = out.proposed_actions[0].model_copy(update={"runbook_id": "nova.rb.payment.nonexistent"})
    return out.model_copy(update={"proposed_actions": [bad]})


def test_revisions_exhausted_with_unsafe_action_escalates(mutable_graph, settings):
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls, behave=_bad_action))
    sid = start(mutable_graph, "simulation")
    assert orch.run(sid, SCOPE) == "escalated"
    out = get(mutable_graph, sid)
    assert calls.n["investigator"] == 3 and calls.n["gate"] == 3 and out.revision_count == 2
    assert out.gate.decision == "escalate" and "unknown_runbook" in {v.code for v in out.gate.violations}
    assert out.proposed_actions == []
    assert run_actions(mutable_graph, sid) == []


def test_revisions_exhausted_with_bad_hypothesis_keeps_violations(mutable_graph, settings):
    def behave(inp, n):
        out = StubInvestigator().investigate(inp)
        extra = Hypothesis(claim_type="hypothesis", statement="Cache layer is at fault.", confidence=0.3,
                           supporting_evidence_ids=["nova.ev.does_not_exist"])
        return out.model_copy(update={"hypotheses": [*out.hypotheses, extra]})

    orch, calls, sid, status = run_golden(mutable_graph, settings, behave=behave)
    out = get(mutable_graph, sid)
    assert status == "completed" and out.gate.decision == "recommendation_only"
    assert [v.code for v in out.gate.violations] == ["unknown_evidence"]
    assert out.proposed_actions == [] and out.findings
    assert all("Cache layer" not in f.statement for f in out.findings)


def test_overall_run_timeout(mutable_graph, settings):
    clock, stub = Clock(), StubInvestigator()

    def slow(inp, n):
        clock.offset_ms = 24 * 3_600_000          # the run budget is gone when the investigator returns
        return stub.investigate(inp)

    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls, behave=slow, clock=clock))
    sid = start(mutable_graph)
    assert orch.run(sid, SCOPE) == "timed_out"
    out = get(mutable_graph, sid)
    assert out.status == "timed_out" and "deadline" in out.error and out.gate is None
    assert out.proposed_actions == [] and calls.n["gate"] == 0


def test_unexpected_error_is_failed_without_leaking_details(mutable_graph, settings):
    def broken(inp, n):
        raise ValueError("dsn=postgresql://user:secret@host/db")

    orch, calls, sid, status = run_golden(mutable_graph, settings, behave=broken)
    out = get(mutable_graph, sid)
    assert status == "failed" and out.status == "failed" and out.error
    assert "secret" not in out.error and out.proposed_actions == []


# ================================================================================ executor / review
def test_recommendation_only_never_reaches_review_or_executor(mutable_graph, settings):
    called = []
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls),
                     review_policy=lambda s: called.append(s) or {"review": {"decision": "APPROVE"}})
    sid = start(mutable_graph)
    assert orch.run(sid, SCOPE) == "completed"
    assert called == []
    assert orch.graph.get_state(orch.config(get(mutable_graph, sid).thread_id)).values.get("execution") is None


def test_route_review_only_executes_approved_simulation():
    assert route_review({"mode": "recommendation_only", "review": {"decision": "APPROVE"}}) == "persist_outcome"
    assert route_review({"mode": "simulation", "review": {"decision": "pending"}}) == "persist_outcome"
    assert route_review({"mode": "simulation", "review": {"decision": "REJECT"}}) == "persist_outcome"
    assert route_review({"mode": "simulation"}) == "persist_outcome"
    assert route_review({"mode": "simulation", "review": {"decision": "APPROVE"}}) == "restricted_executor"


def test_placeholder_executor_runs_nothing_even_when_approved(mutable_graph, settings):
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls),
                     review_policy=lambda s: {"review": {"decision": "APPROVE"}})
    sid = start(mutable_graph, "simulation")
    assert orch.run(sid, SCOPE) == "awaiting_review"
    state = orch.graph.get_state(orch.config(get(mutable_graph, sid).thread_id)).values
    assert state["execution"]["executed"] is False
    assert [a["status"] for a in run_actions(mutable_graph, sid)] == ["pending_review"]


# ================================================================================ restart recovery
def test_crash_then_resume_does_not_rerun_completed_nodes(mutable_graph, settings, saver):
    calls, crashed = Calls(), []
    stub = StubInvestigator()

    def behave(inp, n):
        if n == 1:
            crashed.append(1)
            raise Crash("process killed during the investigator node")
        return stub.investigate(inp)

    orch1 = make_orch(mutable_graph, settings, make_deps(calls, behave=behave), saver=saver)
    sid = start(mutable_graph)
    with pytest.raises(Crash):
        orch1.run(sid, SCOPE)
    assert crashed and get(mutable_graph, sid).status == "running"
    before = dict(calls.n)
    assert before["retrieve"] == 1 and before["telemetry"] == 1

    # a new process: a new Orchestrator on the same checkpointer; the worker resumes `running` sessions
    orch2 = make_orch(mutable_graph, settings, make_deps(calls, behave=behave), saver=saver)
    worker = Worker(orch2.settings, orchestrator=orch2)
    worker.start()
    try:
        deadline = time.monotonic() + 30
        while get(mutable_graph, sid).status == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        worker.stop()
    out = get(mutable_graph, sid)
    assert out.status == "completed" and out.gate.decision == "accept"
    assert calls.n["retrieve"] == before["retrieve"] and calls.n["telemetry"] == before["telemetry"]
    assert calls.n["investigator"] == 2 and len(out.proposed_actions) == 1


# ================================================================================ persist / claim
def test_persist_is_idempotent_and_never_resets_a_reviewed_action(mutable_graph, settings):
    orch, calls, sid, status = run_golden(mutable_graph, settings)
    repo = GraphRepository(mutable_graph, SCOPE)
    state = dict(orch.graph.get_state(orch.config(get(mutable_graph, sid).thread_id)).values)

    def census():
        return {label: sorted(n["id"] for n in repo.list_nodes(label))
                for label in ("AgentAction", "Evidence", "TimelineEvent", "AgentSession")}

    before = census()
    assert persist_outcome(repo, state, now_ms=NOW + 1) == persist_outcome(repo, state, now_ms=NOW + 2)
    assert census() == before

    [act] = run_actions(mutable_graph, sid)
    repo.update_node("AgentAction", act["id"], {"status": "approved"}, at_ms=NOW + 3)
    persist_outcome(repo, state, now_ms=NOW + 4)
    assert repo.get_node("AgentAction", act["id"])["status"] == "approved"


def test_claim_is_atomic(mutable_graph):
    sid = start_unclaimed(mutable_graph)
    results, barrier = [], threading.Barrier(8)

    def claim():
        repo = GraphRepository(mutable_graph, SCOPE)
        barrier.wait()
        results.append(repo.claim_session(sid, now_ms=NOW))

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]
    assert GraphRepository(mutable_graph, SCOPE).get_node("AgentSession", sid)["status"] == "running"


def start_unclaimed(graph, mode: str = "recommendation_only") -> str:
    out, _ = investigations.create(GraphRepository(graph, SCOPE), m.InvestigationIn(incident_id=INC, mode=mode),
                                   auth.DEMO_USERS["demo-responder"], NOW)
    _THREADS.append(out.thread_id)
    return out.id


def test_two_workers_never_claim_the_same_session(mutable_graph, settings):
    sid = start_unclaimed(mutable_graph)
    calls = Calls()
    workers = [Worker(settings.model_copy(update={"graph_name": mutable_graph.name}),
                      orchestrator=make_orch(mutable_graph, settings, make_deps(calls))) for _ in range(2)]
    claimed = []
    barrier = threading.Barrier(2)

    def go(w):
        barrier.wait()
        claimed.extend(sid_ for sid_, _ in w.claim_queued(limit=5))

    threads = [threading.Thread(target=go, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert claimed == [sid]


def test_worker_runs_a_queued_session(mutable_graph, settings):
    sid = start_unclaimed(mutable_graph)
    calls = Calls()
    orch = make_orch(mutable_graph, settings, make_deps(calls))
    worker = Worker(orch.settings, orchestrator=orch)
    worker.start()
    try:
        deadline = time.monotonic() + 30
        while get(mutable_graph, sid).status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        worker.stop()
    assert get(mutable_graph, sid).status == "completed" and calls.n["investigator"] == 1


# ================================================================================ API
def test_api_returns_the_new_fields(mutable_graph, settings, make_client):
    http = make_client(mutable_graph.name)
    created = http.post("/api/investigations", json={"incident_id": INC, "mode": "recommendation_only"},
                        headers=RESPONDER)
    assert created.status_code == 201, created.text
    queued = created.json()
    for key in ("summary", "investigator", "overall_uncertainty", "error", "gate"):
        assert key in queued and queued[key] is None
    assert queued["proposed_actions"] == [] and queued["findings"] == []

    sid = queued["id"]
    GraphRepository(mutable_graph, SCOPE).claim_session(sid, now_ms=NOW)
    make_orch(mutable_graph, settings, make_deps(Calls())).run(sid, SCOPE)

    body = http.get(f"/api/investigations/{sid}", headers=RESPONDER).json()
    assert body["status"] == "completed" and body["investigator"] == "stub-v1"
    assert body["summary"] and body["overall_uncertainty"] and body["error"] is None
    assert body["gate"] == {"decision": "accept", "violations": []}
    [action] = body["proposed_actions"]
    assert set(action) >= {"id", "proposal_id", "version", "action_type", "status", "mode", "target_service_id",
                           "deployment_id", "runbook_id", "risk", "rationale", "spec", "spec_hash", "evidence"}
    assert action["evidence"] and all(e["id"] for e in action["evidence"])
    for finding in body["findings"]:
        assert {"contradicting_evidence", "confidence", "uncertainty"} <= set(finding)
        assert finding["claim_type"] != "confirmed"
