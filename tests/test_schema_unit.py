"""Pure unit tests: schema allowlists, validation, hashing, config guards. No database needed."""

import pytest
from app.config import Settings, check_postgres_dsn
from app.domain.actions import approval_applies, canonical_json, spec_hash
from app.graph import schema
from app.graph.schema import SchemaViolation

PHASE1_EDGES = [
    ("Incident", "HAS_ALERT", "Alert"), ("Incident", "HAS_EVIDENCE", "Evidence"),
    ("Incident", "AFFECTS", "Service"), ("Service", "DEPENDS_ON", "Service"),
    ("Deployment", "DEPLOYED_TO", "Service"), ("Team", "OWNS", "Service"),
    ("Responder", "MEMBER_OF", "Team"), ("Decision", "GOVERNS", "Service"),
    ("Decision", "DOCUMENTED_IN", "Document"), ("Decision", "SUPERSEDES", "Decision"),
    ("Runbook", "APPLIES_TO", "Service"), ("Evidence", "OBSERVED_ON", "Service"),
    ("Evidence", "REFERS_TO", "Deployment"), ("AgentAction", "SUPPORTED_BY", "Evidence"),
    ("AgentAction", "TARGETS", "Service"), ("AgentAction", "PART_OF", "AgentSession"),
    ("AgentAction", "HAS_REVIEW", "ApprovalRecord"), ("AgentMemory", "ABOUT", "Incident"),
    ("AgentMemory", "DERIVED_FROM", "AgentAction"), ("AgentMemory", "GROUNDED_IN", "Evidence"),
    ("AgentMemory", "VALIDATED_BY", "Responder"), ("AgentMemory", "SUPERSEDES", "AgentMemory"),
    ("Document", "RELATES_TO", "Service"), ("Document", "RELATES_TO", "Incident"),
]


def test_thirteen_legacy_labels_plus_new_ones():
    legacy = {"Incident", "Alert", "AgentAction", "Runbook", "Responder", "TimelineEvent", "Service", "Team",
              "Deployment", "Decision", "Document", "AgentSession", "AgentMemory"}
    # Evidence + ApprovalRecord (Phase 1); DocumentChunk because Phase 3 RAG was selected;
    # AgentEvent (Phase 5) for live run progress.
    assert schema.LABELS == legacy | {"Evidence", "ApprovalRecord", "DocumentChunk", "AgentEvent"}


@pytest.mark.parametrize("edge", PHASE1_EDGES)
def test_every_phase1_edge_is_allowed(edge):
    assert schema.check_edge(*edge) == edge


@pytest.mark.parametrize("edge", [
    ("Alert", "HAS_ALERT", "Incident"),          # reversed
    ("Service", "OWNS", "Team"),                 # reversed
    ("Alert", "GROUPED_INTO", "Incident"),       # first-pass draft name
    ("Service", "OWNED_BY", "Team"),             # first-pass draft name
    ("Evidence", "ABOUT", "Incident"),           # first-pass draft
    ("Decision", "GOVERNS", "Incident"),         # wrong target label
])
def test_reversed_or_unknown_edges_rejected(edge):
    with pytest.raises(SchemaViolation):
        schema.check_edge(*edge)


def test_allowed_edges_are_phase1_plus_approved_additions_only():
    extra = schema.ALLOWED_EDGES - set(PHASE1_EDGES)
    assert extra == {("Incident", "HAS_EVENT", "TimelineEvent"), ("AgentSession", "INVESTIGATES", "Incident"),
                     ("ApprovalRecord", "DECIDED_BY", "Responder"), ("Document", "HAS_CHUNK", "DocumentChunk"),
                     ("AgentEvent", "PART_OF", "AgentSession")}


def test_props_validation():
    ok = {"key": "INC-1", "title": "t", "severity": "sev2", "status": "open", "started_at_ms": 1}
    assert schema.check_props("Incident", ok)
    with pytest.raises(SchemaViolation, match="unknown"):
        schema.check_props("Incident", {**ok, "tenant_id": "other"})   # system-managed, not settable
    with pytest.raises(SchemaViolation, match="missing"):
        schema.check_props("Incident", {"title": "t"})
    with pytest.raises(SchemaViolation, match="not in"):
        schema.check_props("Incident", {**ok, "severity": "critical"})
    with pytest.raises(SchemaViolation, match="epoch"):
        schema.check_props("Incident", {**ok, "started_at_ms": "2026-10-17T14:05:00Z"})
    with pytest.raises(SchemaViolation, match="missing"):
        schema.check_props("Evidence", {"kind": "metric", "observed_at_ms": 1})  # source_ref required


@pytest.mark.parametrize("bad", ["x", "a b", "n}) DETACH DELETE (m", "", None, "a" * 200])
def test_bad_ids_rejected(bad):
    with pytest.raises(SchemaViolation):
        schema.check_id(bad)


@pytest.mark.parametrize("bad", [4, -1, "3", True, 2.0])
def test_depth_bounds(bad):
    with pytest.raises(SchemaViolation):
        schema.check_depth(bad)


def test_label_injection_rejected():
    with pytest.raises(SchemaViolation):
        schema.check_label("Service) DETACH DELETE (n")


def test_canonical_hash_is_order_independent_and_change_sensitive():
    a = canonical_json({"b": 1, "a": "x"})
    b = canonical_json({"a": "x", "b": 1})
    assert a == b == '{"a":"x","b":1}'
    assert spec_hash(a) == spec_hash(b)
    assert spec_hash(canonical_json({"a": "x", "b": 2})) != spec_hash(a)
    with pytest.raises(ValueError):
        canonical_json({"a": float("nan")})


def test_approval_applies_only_to_exact_unexpired_version():
    action = {"spec_hash": "h1", "version": 1}
    approval = {"decision": "APPROVE", "spec_hash": "h1", "action_version": 1, "expires_at_ms": 100}
    assert approval_applies(action, approval, now_ms=50)
    assert not approval_applies(action, approval, now_ms=100)                       # expired
    assert not approval_applies({"spec_hash": "h2", "version": 2}, approval, 50)    # revised spec
    assert not approval_applies(action, {**approval, "decision": "REJECT"}, 50)
    assert not approval_applies(action, {**approval, "expires_at_ms": None}, 50)


@pytest.mark.parametrize("dsn", [
    "postgresql://u:p@127.0.0.1:5432/postgres",
    "postgresql://u:p@127.0.0.1:5432/accountsdb",
    "postgresql://u:p@127.0.0.1:55432/",
    "not a dsn ===",
])
def test_dsn_guard_rejects_other_databases(dsn):
    with pytest.raises(ValueError):
        check_postgres_dsn(dsn)


def test_dsn_guard_error_never_leaks_password():
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None, postgres_dsn="postgresql://u:SECRETPW@127.0.0.1:5432/postgres")
    assert "SECRETPW" not in str(exc.value)


def test_settings_rejects_bad_graph_name_and_llm():
    dsn = "postgresql://u:p@127.0.0.1:55432/graphathon"
    with pytest.raises(ValueError):
        Settings(_env_file=None, postgres_dsn=dsn, graph_name="__probe")
    with pytest.raises(ValueError):
        Settings(_env_file=None, postgres_dsn=dsn, llm_provider="openai")
    assert Settings(_env_file=None, postgres_dsn=dsn, llm_provider="ollama").llm_provider == "ollama"
