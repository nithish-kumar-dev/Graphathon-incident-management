"""0001 schema v1: indexes and constraints for the hot lookups in refactor-plan §3.4.

Declarative on purpose. The runner compares this spec with what the server reports, so a
re-run creates nothing. (FalkorDB errors when it re-creates an index or constraint that already exists.)
"""

VERSION = 1
NAME = "schema_v1"

# Frozen literal: an applied migration must never change, so it must not derive from schema.LABELS
# (which grows: DocumentChunk arrived in 0002).
_ID_LABELS = [
    "AgentAction", "AgentMemory", "AgentSession", "Alert", "ApprovalRecord", "Decision", "Deployment", "Document",
    "Evidence", "Incident", "Responder", "Runbook", "SchemaMigration", "Service", "Team", "TimelineEvent",
]

RANGE_INDEXES: list[tuple[str, str]] = [
    *((label, "id") for label in _ID_LABELS),
    ("Incident", "tenant_id"),
    ("Incident", "status"),
    ("Incident", "started_at_ms"),
    ("Alert", "fingerprint"),
    ("Alert", "fired_at_ms"),
    ("Deployment", "deployed_at_ms"),
    ("Decision", "status"),
    ("AgentMemory", "verification_status"),
    ("AgentAction", "spec_hash"),
    ("AgentAction", "proposal_id"),
    ("AgentSession", "thread_id"),
]

# Unique constraints. Each requires the matching range index above (probe-verified).
UNIQUE_CONSTRAINTS: list[tuple[str, str]] = [(label, "id") for label in _ID_LABELS]

# Phase 3 keyword fallback (probe-verified: db.idx.fulltext.createNodeIndex / queryNodes).
FULLTEXT_INDEXES: list[tuple[str, str]] = [
    ("Runbook", "title"),
    ("Document", "title"),
]
