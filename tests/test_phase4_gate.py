"""Safety gate: every violation code from a mutated golden output, and the decision table."""

import pytest
from app.agents.contracts import GateResult, InvestigatorOutput, Violation
from app.agents.investigator import StubInvestigator
from app.agents.safety_gate import decide, evaluate
from app.domain.actions import canonical_json, spec_hash
from app.graph.repository import GraphRepository, Scope
from app.rag.retrieval import MemoryContext

from .conftest import rctx
from .test_phase4_investigator import empty_input, golden_input

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def golden(rag_graph):
    inp = golden_input(rag_graph)
    return inp, StubInvestigator().investigate(inp)


def gate(graph, out, inp, *, revision=0, max_revisions=2) -> GateResult:
    return evaluate(out, inp, repo=rctx(graph).repo, revision=revision, max_revisions=max_revisions)


def mutate(out: InvestigatorOutput, *, hyp: dict | None = None, act: dict | None = None, i: int = 0):
    d = out.model_dump()
    if hyp:
        d["hypotheses"][i].update(hyp)
    if act:
        d["proposed_actions"][i].update(act)
    return InvestigatorOutput.model_validate(d)


def codes(res: GateResult) -> set[str]:
    return {v.code for v in res.violations}


# ------------------------------------------------------------------------------------------- accept
def test_golden_stub_output_is_accepted(rag_graph, golden):
    inp, out = golden
    res = gate(rag_graph, out, inp)
    assert res.decision == "accept" and res.violations == []
    assert res.hypotheses == out.hypotheses and res.proposed_actions == out.proposed_actions


def test_golden_accepted_without_telemetry(rag_graph):
    inp = golden_input(rag_graph, telemetry=False)
    assert gate(rag_graph, StubInvestigator().investigate(inp), inp).decision == "accept"


def test_gate_uses_read_only_repo(rag_graph, golden):
    inp, out = golden
    repo = rctx(rag_graph).repo
    evaluate(out, inp, repo=repo, revision=0, max_revisions=0)
    with pytest.raises(PermissionError):
        repo.graph.query("CREATE (:X)")


# ------------------------------------------------------------------------------------- hypotheses
@pytest.mark.parametrize("change, code", [
    ({"supporting_evidence_ids": ["nova.ev.101.deploy", "nova.ev.101.invented"]}, "unknown_evidence"),
    ({"contradicting_evidence_ids": ["nova.ev.tel.0000000000000000"]}, "unknown_evidence"),
    ({"supporting_evidence_ids": ["acme.ev.001.deploy"]}, "unknown_evidence"),
    ({"supporting_evidence_ids": ["not an id"]}, "unknown_evidence"),
    ({"claim_type": "confirmed"}, "confirmed_claim_not_allowed"),
    ({"supporting_evidence_ids": []}, "no_evidence"),
])
def test_hypothesis_violations(rag_graph, golden, change, code):
    inp, out = golden
    res = gate(rag_graph, mutate(out, hyp=change), inp)
    assert codes(res) == {code} and res.decision == "revise"
    assert all(v.target == "hypotheses[0]" for v in res.violations)
    assert out.hypotheses[0] not in res.hypotheses and len(res.hypotheses) == len(out.hypotheses) - 1
    assert res.proposed_actions == out.proposed_actions                  # valid items survive a revise


def test_known_but_missing_evidence_is_unknown(rag_graph, golden):
    """An id in the input context that does not exist in the graph (stale context) is rejected."""
    inp, out = golden
    ev = inp.graph_context.evidence[0].model_copy(update={"id": "nova.ev.101.ghost"})
    stale = inp.model_copy(update={"graph_context": inp.graph_context.model_copy(
        update={"evidence": [*inp.graph_context.evidence, ev]})})
    res = gate(rag_graph, mutate(out, hyp={"supporting_evidence_ids": ["nova.ev.101.ghost"]}), stale)
    assert codes(res) == {"unknown_evidence"} and "nova.ev.101.ghost" in res.violations[0].detail


# ---------------------------------------------------------------------------------------- actions
@pytest.mark.parametrize("change, code", [
    ({"action_type": "run_shell"}, "action_not_allowed"),
    ({"target_service_id": "nova.svc.ledger"}, "service_out_of_scope"),
    ({"target_service_id": "nova.svc.nope"}, "unknown_service"),
    ({"runbook_id": "nova.rb.nope"}, "unknown_runbook"),
    ({"target_service_id": "nova.svc.checkout", "deployment_id": None}, "runbook_not_applicable"),
    ({"deployment_id": "nova.dep.inventory.v1_9"}, "deployment_not_on_target"),
    ({"deployment_id": "nova.dep.payment.v9_9"}, "unknown_deployment"),
    ({"target_service_id": "acme.svc.payment"}, "invalid_arguments"),
    ({"evidence_ids": ["nova.ev.101.invented"]}, "unknown_evidence"),
])
def test_action_violations(rag_graph, golden, change, code):
    inp, out = golden
    res = gate(rag_graph, mutate(out, act=change), inp)
    assert code in codes(res) and res.decision == "revise"
    assert all(v.target == "proposed_actions[0]" for v in res.violations)
    assert res.proposed_actions == [] and res.hypotheses == out.hypotheses
    a = mutate(out, act=change).proposed_actions[0]
    assert all(f"({a.action_type} on {a.target_service_id})" in v.detail for v in res.violations)


def test_exact_codes_for_isolated_action_mutations(rag_graph, golden):
    inp, out = golden
    assert codes(gate(rag_graph, mutate(out, act={"deployment_id": "nova.dep.inventory.v1_9"}), inp)) == \
        {"deployment_not_on_target"}
    assert codes(gate(rag_graph, mutate(out, act={"runbook_id": "nova.rb.nope"}), inp)) == {"unknown_runbook"}
    assert codes(gate(rag_graph, mutate(out, act={"target_service_id": "acme.svc.payment"}), inp)) == \
        {"invalid_arguments"}


def test_action_type_outside_input_allowlist(rag_graph, golden):
    inp, out = golden
    res = gate(rag_graph, out, inp.model_copy(update={"allowed_action_types": []}))
    assert codes(res) == {"action_not_allowed"}


def test_env_not_allowed(rag_graph, golden):
    inp, out = golden
    res = gate(rag_graph, out, inp.model_copy(update={"env": "qa"}))
    assert codes(res) == {"env_not_allowed"}


def test_repo_for_another_tenant_is_refused(rag_graph, golden):
    inp, out = golden
    with pytest.raises(ValueError):
        evaluate(out, inp, repo=rctx(rag_graph, tenant="acme").repo, revision=0, max_revisions=2)


def test_repeats_failed_action(rag_graph, mutable_graph, golden):
    inp, out = golden
    spec = canonical_json({"action_type": "rollback_deployment_simulated", "env": "prod", "service_id":
                           "nova.svc.payment", "tenant_id": "nova", "from_version": "v2.4", "to_version": "v2.3"})
    GraphRepository(mutable_graph, Scope("nova", "prod")).merge_node("AgentAction", "nova.act.t.rollback_failed", {
        "proposal_id": "nova.prop.t.rollback", "version": 1, "action_type": "rollback_deployment_simulated",
        "spec_json": spec, "spec_hash": spec_hash(spec), "target_service_id": "nova.svc.payment",
        "mode": "simulation", "status": "executed_simulated", "source": "test"})
    warn = inp.memory_context.items[0].model_copy(update={
        "id": "nova.mem.t.rollback_failed", "precedent": "warns_against", "outcome": "failed",
        "summary": "A simulated payment rollback did not help.",
        "derived_from_action_ids": ["nova.act.t.rollback_failed"]})
    warned = inp.model_copy(update={"memory_context": MemoryContext(items=[*inp.memory_context.items, warn],
                                                                    excluded={})})
    res = evaluate(out, warned, repo=rctx(mutable_graph).repo, revision=0, max_revisions=2)
    assert codes(res) == {"repeats_failed_action"} and "nova.mem.t.rollback_failed" in res.violations[0].detail
    # the same memory with a supporting precedent (or a different target) is not a repeat
    ok = warned.model_copy(update={"memory_context": MemoryContext(
        items=[*inp.memory_context.items, warn.model_copy(update={"precedent": "supports"})], excluded={})})
    assert evaluate(out, ok, repo=rctx(mutable_graph).repo, revision=0, max_revisions=2).decision == "accept"
    # seed: the verified-failed "restart checkout" memory has no action, so the rollback is not blocked
    assert gate(rag_graph, out, inp).decision == "accept"


def test_feedback_round_trip_converges(rag_graph, golden):
    """Gate details fed back to the stub drop the offending items; the next revision passes."""
    inp, out = golden
    bad = mutate(out, act={"runbook_id": "nova.rb.nope"})
    res = gate(rag_graph, bad, inp)
    nxt = StubInvestigator().investigate(inp.model_copy(update={"revision": 1,
                                                                "feedback": [v.detail for v in res.violations]}))
    res2 = gate(rag_graph, nxt, inp, revision=1)
    assert res2.decision == "accept" and nxt.proposed_actions == []


# ----------------------------------------------------------------------------------- decision table
def _v(target="hypotheses[0]", code="no_evidence"):
    return Violation(code=code, target=target, detail="x")


@pytest.mark.parametrize("violations, valid, revision, max_rev, decision", [
    ([], 3, 0, 2, "accept"),
    ([], 0, 0, 2, "inconclusive"),
    ([_v()], 2, 0, 2, "revise"),
    ([_v()], 2, 1, 2, "revise"),
    ([_v()], 2, 2, 2, "recommendation_only"),
    ([_v()], 0, 2, 2, "inconclusive"),
    ([_v("proposed_actions[0]", "action_not_allowed")], 2, 1, 2, "revise"),
    ([_v("proposed_actions[0]", "action_not_allowed")], 2, 2, 2, "escalate"),
    ([_v("proposed_actions[0]", "action_not_allowed")], 0, 2, 2, "escalate"),
    ([_v()], 2, 0, 0, "recommendation_only"),
])
def test_decide_table(violations, valid, revision, max_rev, decision):
    assert decide(violations, valid_hypotheses=valid, revision=revision, max_revisions=max_rev) == decision


def test_exhausted_hypothesis_violation_is_recommendation_only(rag_graph, golden):
    inp, out = golden
    res = gate(rag_graph, mutate(out, hyp={"claim_type": "confirmed"}), inp, revision=2, max_revisions=2)
    assert res.decision == "recommendation_only" and res.proposed_actions == []
    assert len(res.hypotheses) == len(out.hypotheses) - 1 and all(h.claim_type != "confirmed" for h in res.hypotheses)


def test_exhausted_action_violation_escalates(rag_graph, golden):
    inp, out = golden
    res = gate(rag_graph, mutate(out, act={"action_type": "run_shell"}), inp, revision=2, max_revisions=2)
    assert res.decision == "escalate" and res.proposed_actions == [] and res.hypotheses == out.hypotheses


def test_exhausted_without_valid_hypotheses_is_inconclusive(rag_graph, golden):
    inp, out = golden
    d = out.model_dump()
    d["hypotheses"] = [{**h, "supporting_evidence_ids": []} for h in d["hypotheses"]]
    d["proposed_actions"] = []
    res = gate(rag_graph, InvestigatorOutput.model_validate(d), inp, revision=2, max_revisions=2)
    assert res.decision == "inconclusive" and res.hypotheses == [] and res.proposed_actions == []


def test_no_evidence_at_all_is_inconclusive(rag_graph):
    inp = empty_input()
    res = gate(rag_graph, StubInvestigator().investigate(inp), inp)
    assert res.decision == "inconclusive" and codes(res) == {"inconclusive"}
