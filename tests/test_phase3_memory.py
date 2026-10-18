"""Verified-memory rules: only human or ground-truth validation verifies; proposed fixes never do."""

import pytest
from app.api.errors import Conflict, InvalidInput
from app.domain.actions import canonical_json, spec_hash
from app.graph import integrity
from app.graph.repository import GraphRepository, Scope
from app.graph.schema import SchemaViolation
from app.seeds import novacommerce
from app.seeds.loader import apply_seed
from app.seeds.novacommerce import ms
from app.services import memories
from app.tools.graph_tools import run_tool

from .conftest import NOW, rctx

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(mutable_graph):
    return GraphRepository(mutable_graph, Scope("nova", "prod"))


def _draft(repo, **over):
    args = {"about_incident_id": "nova.inc.101", "summary": "draft about payment pool", "memory_type": "episodic",
            "grounded_in": ["nova.ev.101.payment_latency"], "model_version": "stub-llm-0", "now_ms": NOW}
    return memories.create_draft(repo, **{**args, **over})


def test_generic_writes_cannot_verify(repo):
    with pytest.raises(SchemaViolation, match="draft"):
        repo.merge_node("AgentMemory", "nova.mem.x", {"memory_type": "episodic", "verification_status": "verified",
                                                      "outcome": "successful", "summary": "s"})
    with pytest.raises(SchemaViolation):
        repo.update_node("AgentMemory", "nova.mem.092.cache_ttl_idea", {"verification_status": "verified"})
    with pytest.raises(SchemaViolation):
        repo.update_node("AgentMemory", "nova.mem.092.rollback_success", {"outcome": "failed"})


def test_reseed_never_downgrades_verified(repo, mutable_graph):
    apply_seed(mutable_graph, novacommerce)
    m = repo.get_node("AgentMemory", "nova.mem.092.rollback_success")
    assert (m["verification_status"], m["outcome"], m["validation_method"]) == ("verified", "successful", "human")
    assert integrity.run(mutable_graph).ok


def test_human_validation_flow(repo):
    mid = _draft(repo)
    assert repo.get_node("AgentMemory", mid)["verification_status"] == "draft"
    assert memories.validate_by_human(repo, mid, responder_id="nova.rsp.payments_lead", outcome="failed",
                                      now_ms=NOW) == "verified"
    m = repo.get_node("AgentMemory", mid)
    assert (m["verification_status"], m["outcome"], m["validation_method"], m["validated_at_ms"]) == (
        "verified", "failed", "human", NOW)
    assert memories.validate_by_human(repo, mid, responder_id="nova.rsp.payments_lead", outcome="failed",
                                      now_ms=NOW + 1) == "unchanged"
    with pytest.raises(Conflict, match="supersede"):
        memories.validate_by_human(repo, mid, responder_id="nova.rsp.payments_lead", outcome="successful", now_ms=NOW)
    with pytest.raises(InvalidInput):
        memories.validate_by_human(repo, _draft(repo), responder_id="nova.rsp.ghost", outcome="failed", now_ms=NOW)


def test_proposed_fix_is_not_a_verified_outcome(repo):
    spec = canonical_json({"action_type": "rollback_deployment_simulated", "service_id": "nova.svc.payment"})
    repo.merge_node("AgentAction", "nova.act.101.rollback.v1", {
        "proposal_id": "nova.prop.101.rollback", "version": 1, "action_type": "rollback_deployment_simulated",
        "spec_json": spec, "spec_hash": spec_hash(spec), "target_service_id": "nova.svc.payment",
        "mode": "recommendation_only", "status": "pending_review"})
    mid = _draft(repo, derived_from_action_ids=["nova.act.101.rollback.v1"],
                 summary="Rolling back payment v2.4 will fix checkout")
    for fn, kwargs in [(memories.validate_by_human, {"responder_id": "nova.rsp.payments_lead"}),
                       (memories.validate_by_ground_truth, {"evidence_ids": ["nova.ev.101.payment_latency"]})]:
        with pytest.raises(Conflict) as exc:
            fn(repo, mid, outcome="successful", now_ms=NOW, **kwargs)
        assert exc.value.code == "unexecuted_action"
    assert repo.get_node("AgentMemory", mid)["verification_status"] == "draft"
    assert memories._detail(repo, mid)["evidence_ids"] == ["nova.ev.101.payment_latency"]   # no partial writes


def test_ungrounded_memory_cannot_be_verified(repo):
    mid = _draft(repo, grounded_in=[])
    with pytest.raises(Conflict) as exc:
        memories.validate_by_human(repo, mid, responder_id="nova.rsp.payments_lead", outcome="successful", now_ms=NOW)
    assert exc.value.code == "missing_evidence"


def test_ground_truth_validation_rules(repo):
    mid = _draft(repo)
    with pytest.raises(InvalidInput, match="not an observed outcome"):
        memories.validate_by_ground_truth(repo, mid, evidence_ids=["nova.ev.101.deploy"], outcome="successful",
                                          now_ms=NOW)
    old = _draft(repo, about_incident_id="nova.inc.101")
    with pytest.raises(InvalidInput, match="predates"):
        memories.validate_by_ground_truth(repo, old, evidence_ids=["nova.ev.092.recovery"], outcome="successful",
                                          now_ms=NOW)
    # checkout_errors (14:04Z) is the symptom that opened INC-101 (14:05Z), so it is not an outcome.
    with pytest.raises(InvalidInput, match="predates"):
        memories.validate_by_ground_truth(repo, mid, evidence_ids=["nova.ev.101.checkout_errors"],
                                          outcome="failed", now_ms=NOW)
    assert memories.validate_by_ground_truth(repo, mid, evidence_ids=["nova.ev.101.payment_latency"],
                                             outcome="failed", now_ms=NOW) == "verified"
    assert repo.get_node("AgentMemory", mid)["validation_method"] == "ground_truth"


def test_rejected_and_superseded_are_never_retrieved(repo, mutable_graph):
    ctx = rctx(mutable_graph)
    rejected = _draft(repo, summary="checkout cache flush fixes payment")
    memories.reject(repo, rejected, responder_id="nova.rsp.payments_lead", now_ms=NOW)
    newer = _draft(repo, about_incident_id="nova.inc.092", grounded_in=["nova.ev.092.recovery"],
                   summary="Payment rollback resolved INC-092; ledger reconciliation must be paused first")
    memories.validate_by_human(repo, newer, responder_id="nova.rsp.payments_lead", outcome="successful", now_ms=NOW)
    memories.supersede(repo, new_memory_id=newer, old_memory_id="nova.mem.092.rollback_success", now_ms=NOW)

    got = run_tool(ctx, "get_verified_memories", {"incident_id": "nova.inc.101"})
    ids = {x.id for x in got.items}
    assert newer in ids and "nova.mem.092.restart_failed" in ids
    assert rejected not in ids and "nova.mem.092.rollback_success" not in ids
    assert got.excluded_unverified >= 3                       # draft idea + rejected + superseded
    assert integrity.run(mutable_graph).ok


def test_failed_outcomes_are_kept_as_warnings(seeded_graph):
    got = run_tool(rctx(seeded_graph), "get_verified_memories", {"incident_id": "nova.inc.101"})
    failed = next(x for x in got.items if x.outcome == "failed")
    assert (failed.id, failed.precedent) == ("nova.mem.092.restart_failed", "warns_against")


def test_integrity_flags_verified_memory_from_unexecuted_action(mutable_graph):
    mutable_graph.query(
        "MATCH (m:AgentMemory {id:'nova.mem.092.rollback_success'})-[:DERIVED_FROM]->(a:AgentAction) "
        "SET a.status = 'pending_review'")
    assert integrity.run(mutable_graph).unvalidated_verified_memory == ["nova.mem.092.rollback_success"]


def test_validated_at_is_the_validation_time(seeded_graph):
    m = GraphRepository(seeded_graph, Scope("nova", "prod")).get_node("AgentMemory", "nova.mem.092.rollback_success")
    assert m["validated_at_ms"] == ms("2026-08-14T11:00:00")


def test_pre_phase3_verified_memory_is_flagged_and_healed_by_reseed(repo, mutable_graph):
    """Memories verified before Phase 3 had no validation_method or VALIDATED_BY edge. Integrity flags them,
    and re-seeding heals them through app.services.memories (no raw writes, no downgrade)."""
    mutable_graph.query("MATCH (m:AgentMemory {id:'nova.mem.092.restart_failed'})-[v:VALIDATED_BY]->() DELETE v")
    mutable_graph.query("MATCH (m:AgentMemory {id:'nova.mem.092.restart_failed'}) REMOVE m.validation_method")
    assert integrity.run(mutable_graph).unvalidated_verified_memory == ["nova.mem.092.restart_failed"]
    apply_seed(mutable_graph, novacommerce)
    m = repo.get_node("AgentMemory", "nova.mem.092.restart_failed")
    assert (m["verification_status"], m["outcome"], m["validation_method"], m["validated_at_ms"]) == (
        "verified", "failed", "human", ms("2026-08-14T11:00:00"))
    assert integrity.run(mutable_graph).ok
