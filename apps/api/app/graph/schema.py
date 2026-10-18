"""Graph schema v1: the single source of truth for labels, properties and allowed edges.

Mirrors docs/refactor-plan.md §3 (signed off 2026-10-18) and docs/schema/falkordb.md.
Every label, relationship type and property key that reaches a Cypher string must come
from here. Values always go in as query parameters.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1

# Present on every domain node. Set by the repository, never by callers.
SYSTEM_PROPS = frozenset({"id", "tenant_id", "env", "created_at_ms", "updated_at_ms", "schema_version"})
# Optional on every domain node, settable by callers.
COMMON_PROPS = frozenset({"source", "source_ref"})

LABEL_PROPS: dict[str, frozenset[str]] = {
    "Incident": frozenset({"key", "title", "severity", "status", "started_at_ms", "resolved_at_ms"}),
    "Alert": frozenset({
        "fingerprint", "severity", "fired_at_ms", "summary_redacted", "service_id",
        # ingest dedup bookkeeping (Phase 2, additive)
        "dedup_count", "last_fired_at_ms", "dedup_source_refs",
    }),
    "Evidence": frozenset({"kind", "excerpt_redacted", "observed_at_ms", "content_hash"}),
    "TimelineEvent": frozenset({"at_ms", "type", "actor", "summary", "ref_id"}),
    "Service": frozenset({"name", "tier"}),
    "Team": frozenset({"name"}),
    "Responder": frozenset({"handle", "roles"}),
    "Deployment": frozenset({"version", "deployed_at_ms", "status"}),
    "Runbook": frozenset({"title", "version", "uri", "allowed_action_types"}),
    "Decision": frozenset({
        "title", "statement", "status", "effective_from_ms", "effective_to_ms", "required_approver_role",
    }),
    "Document": frozenset({"title", "uri", "doc_type", "classification", "body_redacted"}),
    # Phase 3 hybrid retrieval. `id` is the chunk_id. Embedding fields are written only by set_embedding().
    "DocumentChunk": frozenset({"document_id", "ordinal", "text_excerpt", "content_hash"}),
    "AgentSession": frozenset({
        "thread_id", "run_id", "mode", "status", "started_at_ms", "ended_at_ms", "revision_count",
        "findings_json", "branch_status_json", "requested_by",
        # Phase 4 outcome
        "summary", "investigator", "overall_uncertainty", "gate_json", "error",
    }),
    "AgentAction": frozenset({
        "proposal_id", "version", "action_type", "spec_json", "spec_hash", "target_service_id", "risk",
        "mode", "status", "approval_expires_at_ms",
        # Phase 4 proposals
        "deployment_id", "runbook_id", "rationale",
    }),
    "ApprovalRecord": frozenset({
        "decision", "spec_hash", "action_version", "approver_id", "decided_at_ms", "expires_at_ms", "scope",
        "policy_decision_id", "comment",
    }),
    "AgentMemory": frozenset({
        "memory_type", "verification_status", "outcome", "summary", "provenance_refs", "model_version",
        "validated_at_ms", "validation_method", "content_hash",
    }),
}

# Written only through GraphRepository.set_embedding (vecf32 + dimension check), never by merge/update.
EMBEDDING_LABELS = frozenset({"DocumentChunk", "AgentMemory"})
EMBEDDING_PROPS = frozenset({"embedding", "embedding_model", "embedding_version", "embedding_dim", "embedded_hash"})

# Memory verification state changes only through app.services.memories (validate/reject/supersede).
# Generic writes may create a memory only as draft/unknown and can never change these afterwards.
MEMORY_VERIFICATION_PROPS = frozenset({"verification_status", "outcome", "validated_at_ms", "validation_method"})
LABELS = frozenset(LABEL_PROPS)

# Bookkeeping label written only by the migration runner. Not tenant-scoped.
MIGRATION_LABEL = "SchemaMigration"

REQUIRED_PROPS: dict[str, frozenset[str]] = {
    "Incident": frozenset({"key", "title", "severity", "status", "started_at_ms"}),
    "Alert": frozenset({"fingerprint", "severity", "fired_at_ms"}),
    "Evidence": frozenset({"kind", "source_ref", "observed_at_ms"}),
    "TimelineEvent": frozenset({"at_ms", "type"}),
    "Service": frozenset({"name"}),
    "Team": frozenset({"name"}),
    "Responder": frozenset({"handle"}),
    "Deployment": frozenset({"version", "deployed_at_ms"}),
    "Runbook": frozenset({"title", "version"}),
    "Decision": frozenset({"title", "statement", "status", "effective_from_ms"}),
    "Document": frozenset({"title", "doc_type"}),
    "AgentSession": frozenset({"thread_id", "mode", "status", "started_at_ms"}),
    "AgentAction": frozenset({
        "proposal_id", "version", "action_type", "spec_json", "spec_hash", "target_service_id", "mode", "status",
    }),
    "ApprovalRecord": frozenset({"decision", "spec_hash", "action_version", "approver_id", "decided_at_ms"}),
    "AgentMemory": frozenset({"memory_type", "verification_status", "outcome", "summary"}),
    "DocumentChunk": frozenset({"document_id", "ordinal", "text_excerpt", "content_hash", "source_ref"}),
}

ENUMS: dict[tuple[str, str], frozenset[str]] = {
    ("Incident", "severity"): frozenset({"sev1", "sev2", "sev3", "sev4"}),
    ("Incident", "status"): frozenset({"open", "investigating", "mitigated", "resolved"}),
    ("Alert", "severity"): frozenset({"critical", "warning", "info"}),
    ("Evidence", "kind"): frozenset({"metric", "log", "deploy_event", "alert", "ticket", "doc"}),
    ("Decision", "status"): frozenset({"active", "superseded"}),
    ("Document", "doc_type"): frozenset({"adr", "policy", "postmortem", "runbook"}),
    ("AgentSession", "mode"): frozenset({"recommendation_only", "simulation"}),
    ("AgentSession", "status"): frozenset({
        "queued", "running", "awaiting_review", "completed", "failed", "escalated", "inconclusive", "timed_out",
    }),
    ("AgentAction", "mode"): frozenset({"recommendation_only", "simulation"}),
    ("AgentAction", "risk"): frozenset({"low", "medium", "high"}),
    ("AgentAction", "status"): frozenset({
        "proposed", "pending_review", "approved", "rejected", "revision_requested", "escalated",
        "executed_simulated", "failed", "expired", "superseded",
    }),
    ("ApprovalRecord", "decision"): frozenset({"APPROVE", "REJECT", "REQUEST_REVISION", "ESCALATE"}),
    ("AgentMemory", "memory_type"): frozenset({"episodic", "procedural"}),
    ("AgentMemory", "verification_status"): frozenset({"draft", "verified", "rejected", "superseded"}),
    ("AgentMemory", "outcome"): frozenset({"successful", "failed", "unknown"}),
    ("AgentMemory", "validation_method"): frozenset({"human", "ground_truth"}),
    ("Document", "classification"): frozenset({"public", "internal", "confidential", "restricted"}),
}

# (source label, relationship type, target label). Direction matters.
# Phase 1 essential list, verbatim:
_PHASE1_EDGES = {
    ("Incident", "HAS_ALERT", "Alert"),
    ("Incident", "HAS_EVIDENCE", "Evidence"),
    ("Incident", "AFFECTS", "Service"),
    ("Service", "DEPENDS_ON", "Service"),
    ("Deployment", "DEPLOYED_TO", "Service"),
    ("Team", "OWNS", "Service"),
    ("Responder", "MEMBER_OF", "Team"),
    ("Decision", "GOVERNS", "Service"),
    ("Decision", "DOCUMENTED_IN", "Document"),
    ("Decision", "SUPERSEDES", "Decision"),
    ("Runbook", "APPLIES_TO", "Service"),
    ("Evidence", "OBSERVED_ON", "Service"),
    ("Evidence", "REFERS_TO", "Deployment"),
    ("AgentAction", "SUPPORTED_BY", "Evidence"),
    ("AgentAction", "TARGETS", "Service"),
    ("AgentAction", "PART_OF", "AgentSession"),
    ("AgentAction", "HAS_REVIEW", "ApprovalRecord"),
    ("AgentMemory", "ABOUT", "Incident"),
    ("AgentMemory", "DERIVED_FROM", "AgentAction"),
    ("AgentMemory", "GROUNDED_IN", "Evidence"),
    ("AgentMemory", "VALIDATED_BY", "Responder"),
    ("AgentMemory", "SUPERSEDES", "AgentMemory"),
    ("Document", "RELATES_TO", "Service"),
    ("Document", "RELATES_TO", "Incident"),
}
# Additions approved with the schema sign-off (refactor-plan §3.3, O5):
_APPROVED_ADDITIONS = {
    ("Incident", "HAS_EVENT", "TimelineEvent"),
    ("AgentSession", "INVESTIGATES", "Incident"),
    ("ApprovalRecord", "DECIDED_BY", "Responder"),
    ("Document", "HAS_CHUNK", "DocumentChunk"),   # Phase 3 hybrid retrieval (approved: RAG selected)
}
ALLOWED_EDGES = frozenset(_PHASE1_EDGES | _APPROVED_ADDITIONS)
REL_TYPES = frozenset(rel for _, rel, _ in ALLOWED_EDGES)

# Globally unique: tenant-prefixed slugs for seeds ("nova.svc.checkout"), prefix+ULID at runtime.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
TENANT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
ENV_VALUES = frozenset({"dev", "staging", "prod"})

MAX_TRAVERSAL_DEPTH = 3


class SchemaViolation(ValueError):
    """A write would break schema v1. The message is safe to show to callers."""


def check_label(label: str) -> str:
    if label not in LABELS:
        raise SchemaViolation(f"unknown label {label!r}")
    return label


def check_edge(src: str, rel: str, dst: str) -> tuple[str, str, str]:
    if (src, rel, dst) not in ALLOWED_EDGES:
        raise SchemaViolation(f"relationship ({src})-[:{rel}]->({dst}) is not in schema v1")
    return src, rel, dst


def check_id(node_id: str) -> str:
    if not isinstance(node_id, str) or not ID_PATTERN.match(node_id):
        raise SchemaViolation(f"invalid id {node_id!r}")
    return node_id


def check_props(label: str, props: dict[str, object], *, partial: bool = False) -> dict[str, object]:
    allowed = LABEL_PROPS[check_label(label)] | COMMON_PROPS
    unknown = set(props) - allowed
    if unknown:
        raise SchemaViolation(f"{label}: unknown or system-managed properties {sorted(unknown)}")
    if not partial:
        missing = REQUIRED_PROPS[label] - {k for k, v in props.items() if v is not None}
        if missing:
            raise SchemaViolation(f"{label}: missing required properties {sorted(missing)}")
    for key, value in props.items():
        allowed_values = ENUMS.get((label, key))
        if allowed_values is not None and value not in allowed_values:
            raise SchemaViolation(f"{label}.{key}={value!r} not in {sorted(allowed_values)}")
        if key.endswith("_ms") and value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise SchemaViolation(f"{label}.{key} must be integer epoch milliseconds (UTC)")
    return props


def check_order_prop(label: str, prop: str) -> str:
    """Property names used in ORDER BY are inlined, so they must come from the schema."""
    if prop not in LABEL_PROPS[check_label(label)] | SYSTEM_PROPS:
        raise SchemaViolation(f"cannot order {label} by {prop!r}")
    return prop


def check_depth(depth: int) -> int:
    """Path bounds cannot be query parameters in FalkorDB (see falkordb-capabilities.md),
    so they are validated integers inlined into the query text."""
    if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= MAX_TRAVERSAL_DEPTH:
        raise SchemaViolation(f"depth must be an integer in 0..{MAX_TRAVERSAL_DEPTH}")
    return depth
