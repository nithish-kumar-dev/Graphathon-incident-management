"""Investigators: the deterministic stub on the real INC-101 context, and the Ollama client (mocked transport;
one live test, skipped when Ollama or the model is missing)."""

import json

import httpx
import pytest
from app.agents import prompts
from app.agents.contracts import InvestigatorError, InvestigatorInput, InvestigatorOutput
from app.agents.investigator import OllamaInvestigator, StubInvestigator, from_settings
from app.rag.embeddings import HashingEmbedder
from app.rag.retrieval import MemoryContext, retrieve
from app.seeds.novacommerce import ms
from app.telemetry import synthetic

from .conftest import ALLOWED, NOW, rctx

WINDOW_START = ms("2026-10-17T13:00:00")
MODEL = "qwen2.5:7b"
OLLAMA = "http://127.0.0.1:11434"


def golden_input(graph, *, telemetry: bool = True, **overrides) -> InvestigatorInput:
    """InvestigatorInput for INC-101 the way the orchestrator builds it: retrieval + synthetic telemetry."""
    b = retrieve(rctx(graph), "nova.inc.101", embedder=HashingEmbedder(), allowed_classifications=ALLOWED)
    gc = b.graph_context
    services = sorted(set(gc.incident.affected_service_ids) | {p.target_service_id for p in gc.explanation_paths}
                      | {d.service.id for deps in gc.dependencies.values() for d in deps})
    fields = {
        "incident_id": "nova.inc.101", "incident_key": gc.incident.key, "incident_title": gc.incident.title,
        "tenant_id": "nova", "env": "prod", "mode": "recommendation_only", "revision": 0,
        "branch_status": {"graph_context": "completed", "memory_context": "completed",
                       "telemetry_context": "completed" if telemetry else "failed"},
        "graph_context": gc, "memory_context": b.memory_context, "knowledge_context": b.knowledge_context,
        "telemetry_context": synthetic.collect("nova", "prod", services, WINDOW_START, NOW) if telemetry else None}
    fields.update(overrides)
    return InvestigatorInput(**fields)


def empty_input(**overrides) -> InvestigatorInput:
    fields = {"incident_id": "nova.inc.101", "incident_key": "INC-101", "incident_title": "Checkout 5xx", "tenant_id": "nova",
                  "env": "prod", "mode": "recommendation_only", "revision": 0,
                  "branch_status": {"graph_context": "failed", "memory_context": "failed", "telemetry_context": "failed"}}
    fields.update(overrides)
    return InvestigatorInput(**fields)


# ===================================================================================== stub (integration)
@pytest.mark.integration
class TestStub:
    def test_golden_output(self, rag_graph):
        inp = golden_input(rag_graph)
        res = StubInvestigator().run(inp)
        out = InvestigatorOutput.model_validate_json(res.output.model_dump_json())
        assert res.investigator == "stub-v1" and res.latency_ms >= 0

        corr = [h for h in out.hypotheses if h.claim_type == "correlated"]
        assert len(corr) == 1 and "nova.ev.101.deploy" in corr[0].supporting_evidence_ids
        assert corr[0].statement.startswith("Deployment v2.4 of payment (nova.dep.payment.v2_4")
        assert {"nova.ev.101.payment_latency", "nova.ev.101.checkout_errors"} <= set(corr[0].supporting_evidence_ids)
        assert corr[0].contradicting_evidence_ids == [] and 0 < corr[0].confidence <= 0.8
        assert "not a confirmed cause" in corr[0].uncertainty and "nova.mem.092.rollback_success" in corr[0].uncertainty

        observed = {h.statement.split(" ")[1] for h in out.hypotheses if h.claim_type == "observed"
                    and "baseline in the window" not in h.statement}
        assert observed == {"db_pool_wait_ms", "p99_latency_ms", "error_rate", "http_5xx_rate", "upstream_timeout_count"}
        tel_ids = {o.id for o in inp.telemetry_context.observations}
        assert all(set(h.supporting_evidence_ids) <= tel_ids for h in out.hypotheses if h.claim_type == "observed")
        baseline = [h for h in out.hypotheses if "baseline in the window" in h.statement]
        assert len(baseline) == 1 and "inventory" in baseline[0].statement and "nova.dep.inventory.v1_9" in \
            baseline[0].statement

        known = inp.known_evidence_ids()
        assert all(set(h.supporting_evidence_ids + h.contradicting_evidence_ids) <= known for h in out.hypotheses)
        assert all(h.claim_type != "confirmed" for h in out.hypotheses)
        assert "confirmed" not in {h.claim_type for h in out.hypotheses}

        [a] = out.proposed_actions
        assert (a.action_type, a.target_service_id, a.deployment_id, a.runbook_id) == (
            "rollback_deployment_simulated", "nova.svc.payment", "nova.dep.payment.v2_4", "nova.rb.payment.rollback")
        assert a.evidence_ids == ["nova.ev.101.deploy"] and "pending human approval" in a.rationale
        text = out.model_dump_json().lower()
        assert not any("restart" in x.action_type or x.target_service_id == "nova.svc.checkout"
                       for x in out.proposed_actions)
        assert "do not repeat" in out.overall_uncertainty.lower() and "restart" in text   # noted, never proposed
        assert StubInvestigator().investigate(inp) == out                                  # deterministic

    def test_without_telemetry_lower_confidence_and_says_so(self, rag_graph):
        full = StubInvestigator().investigate(golden_input(rag_graph)).hypotheses[0]
        bare = StubInvestigator().investigate(golden_input(rag_graph, telemetry=False))
        [h] = bare.hypotheses
        assert h.claim_type == "correlated" and h.confidence < full.confidence
        assert "No telemetry" in h.uncertainty and "telemetry_context failed" in bare.overall_uncertainty
        assert len(bare.proposed_actions) == 1

    def test_no_paths_no_actions(self, rag_graph):
        inp = golden_input(rag_graph)
        inp = inp.model_copy(update={"graph_context": inp.graph_context.model_copy(update={"explanation_paths": []})})
        out = StubInvestigator().investigate(inp)
        assert out.proposed_actions == [] and all(h.claim_type == "observed" for h in out.hypotheses)

    def test_no_evidence_no_hypotheses(self):
        out = StubInvestigator().investigate(empty_input())
        assert out.hypotheses == [] and out.proposed_actions == [] and "No evidence" in out.summary

    def test_disallowed_action_types_are_not_proposed(self, rag_graph):
        out = StubInvestigator().investigate(golden_input(rag_graph, allowed_action_types=[]))
        assert out.proposed_actions == [] and out.hypotheses

    def test_never_proposes_what_a_failed_memory_warns_against(self, rag_graph):
        inp = golden_input(rag_graph)
        warn = inp.memory_context.items[0].model_copy(update={
            "id": "nova.mem.t.rollback_failed", "precedent": "warns_against", "outcome": "failed",
            "summary": "Rolling back payment did not reduce checkout 5xx."})
        inp = inp.model_copy(update={"memory_context": MemoryContext(items=[warn], excluded={})})
        out = StubInvestigator().investigate(inp)
        assert out.proposed_actions == [] and "Do not repeat: Rolling back payment" in out.overall_uncertainty

    def test_feedback_drops_named_items(self, rag_graph):
        inp = golden_input(rag_graph)
        first = StubInvestigator().investigate(inp)
        tel_id = first.hypotheses[1].supporting_evidence_ids[-1]
        feedback = ["proposed_actions[0] (rollback_deployment_simulated on nova.svc.payment): runbook x",
                    f"hypotheses[1]: cites unknown evidence id(s) {tel_id}",
                    f"hypotheses[0] '{first.hypotheses[0].statement[:60]}': claim_type confirmed is reserved"]
        out = StubInvestigator().investigate(inp.model_copy(update={"feedback": feedback}))
        assert out.proposed_actions == []
        assert all(h.statement != first.hypotheses[0].statement for h in out.hypotheses)
        assert all(tel_id not in h.supporting_evidence_ids for h in out.hypotheses)


# ===================================================================================== ollama (offline)
def _ollama(handler, **kw) -> OllamaInvestigator:
    return OllamaInvestigator(OLLAMA, MODEL, transport=httpx.MockTransport(handler), **kw)


def _content(text: str):
    return lambda request: httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


GOOD = InvestigatorOutput(summary="No evidence; nothing to recommend.").model_dump_json()


def test_ollama_request_shape_and_success():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"content": GOOD}})

    res = _ollama(handler, fallback_to_stub=False).run(empty_input(), timeout_s=5)
    assert res.investigator == f"ollama:{MODEL}" and res.output.summary.startswith("No evidence")
    assert seen["url"] == f"{OLLAMA}/api/chat" and seen["stream"] is False and seen["model"] == MODEL
    assert seen["format"] == InvestigatorOutput.model_json_schema() and seen["options"]["temperature"] == 0
    assert seen["messages"][0] == {"role": "system", "content": prompts.SYSTEM_PROMPT}
    assert json.loads(seen["messages"][1]["content"])["incident"]["id"] == "nova.inc.101"


@pytest.mark.parametrize("handler, kind", [
    (_content("not json at all"), "malformed"),
    (_content('{"hypotheses": []}'), "malformed"),                                       # schema: summary missing
    (_content('{"summary": "x", "extra": 1}'), "malformed"),                             # extra="forbid"
    (lambda r: httpx.Response(200, text="<html>"), "malformed"),
    (lambda r: httpx.Response(200, json={"done": True}), "malformed"),                   # no message.content
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "timeout"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("slow", request=r)), "timeout"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r)), "unavailable"),
    (lambda r: httpx.Response(500, text="boom"), "unavailable"),
    (lambda r: httpx.Response(404, json={"error": "model not found"}), "unavailable"),
])
def test_ollama_error_mapping_without_fallback(handler, kind):
    with pytest.raises(InvestigatorError) as err:
        _ollama(handler, fallback_to_stub=False).run(empty_input(), timeout_s=1)
    assert err.value.kind == kind


@pytest.mark.parametrize("handler, label", [
    (_content("{not json"), "stub-fallback(ollama malformed)"),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "stub-fallback(ollama timeout)"),
    (lambda r: httpx.Response(503), "stub-fallback(ollama unavailable)"),
])
def test_ollama_fallback_is_labelled(handler, label):
    inp = empty_input()
    res = _ollama(handler, fallback_to_stub=True).run(inp, timeout_s=1)
    assert res.investigator == label and res.output == StubInvestigator().investigate(inp)


def test_from_settings(settings):
    assert isinstance(from_settings(settings.model_copy(update={"llm_provider": "stub"})), StubInvestigator)
    inv = from_settings(settings.model_copy(update={"llm_provider": "ollama", "ollama_model": MODEL,
                                                    "llm_fallback_to_stub": False}))
    assert isinstance(inv, OllamaInvestigator) and inv.name == f"ollama:{MODEL}" and not inv.fallback_to_stub
    with pytest.raises(ValueError):
        from_settings(settings.model_copy(update={"llm_provider": "ollama", "ollama_model": ""}))
    with pytest.raises(ValueError):
        OllamaInvestigator(OLLAMA, "  ")


@pytest.mark.integration
def test_prompt_is_compact_and_cites_only_context_ids(rag_graph):
    inp = golden_input(rag_graph)
    doc = json.loads(prompts.build_user_content(inp))
    assert len(prompts.build_user_content(inp)) < 12_000
    assert set(doc["citable_evidence_ids"]) <= inp.known_evidence_ids()
    assert {"nova.ev.101.deploy", "nova.ev.101.payment_latency"} <= set(doc["citable_evidence_ids"])
    assert {t["id"] for t in doc["telemetry"]} <= set(doc["citable_evidence_ids"])
    assert doc["allowed_action_types"] == ["rollback_deployment_simulated"]
    assert doc["explanation_paths"][0]["runbooks"][0]["id"] == "nova.rb.payment.rollback"
    assert "nova.doc.sec_handbook" not in json.dumps(doc)


# ===================================================================================== live ollama
def _ollama_ready() -> bool:
    try:
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=2).json()
    except (httpx.HTTPError, ValueError):
        return False
    return any(m.get("name") == MODEL for m in tags.get("models", []))


@pytest.mark.integration
@pytest.mark.skipif(not _ollama_ready(), reason=f"local Ollama with {MODEL} not available")
def test_live_ollama_golden(rag_graph, record_property, capsys):
    from app.agents.safety_gate import evaluate

    inp = golden_input(rag_graph)
    res = OllamaInvestigator(OLLAMA, MODEL, fallback_to_stub=False).run(inp, timeout_s=180)
    gate = evaluate(res.output, inp, repo=rctx(rag_graph).repo, revision=0, max_revisions=2)
    record_property("ollama_latency_ms", res.latency_ms)
    record_property("gate_decision", gate.decision)
    with capsys.disabled():
        print(f"\n[live ollama] {res.investigator} latency={res.latency_ms}ms gate={gate.decision} "
              f"hypotheses={len(res.output.hypotheses)} actions={len(res.output.proposed_actions)} "
              f"violations={[v.code for v in gate.violations]}")
    assert res.investigator == f"ollama:{MODEL}"
    assert gate.decision in {"accept", "revise"}
