"""Typed, per-kind identifiers and runtime ID generation.

Every node id has the form `<tenant>.<kind>.<suffix>`, e.g. `nova.inc.101` or `nova.alr.01k7…`.
API path and body parameters use the kind-specific patterns below, so a service id can never be
passed where an incident id is expected. Malformed ids are rejected with 422 before any query runs.
"""

from __future__ import annotations

import secrets
import time
from typing import Annotated

from fastapi import Path
from pydantic import Field

_TENANT = r"[a-z][a-z0-9_]{1,31}"
_SUFFIX = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}"
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"

KINDS = {
    "Incident": "inc", "Alert": "alr", "Evidence": "ev", "TimelineEvent": "tl", "Service": "svc",
    "Team": "team", "Responder": "rsp", "Deployment": "dep", "Runbook": "rb", "Decision": "dec",
    "Document": "doc", "AgentSession": "ses", "AgentAction": "act", "ApprovalRecord": "apr", "AgentMemory": "mem",
    "DocumentChunk": "chunk", "AgentEvent": "evt",
}


def id_pattern(kind: str) -> str:
    return rf"^{_TENANT}\.{kind}\.{_SUFFIX}$"


def _path(kind: str, example: str):
    return Annotated[str, Path(pattern=id_pattern(kind), max_length=128, examples=[example])]


def _field(kind: str, example: str):
    return Annotated[str, Field(pattern=id_pattern(kind), max_length=128, examples=[example])]


IncidentIdPath = _path("inc", "nova.inc.101")
ServiceIdPath = _path("svc", "nova.svc.payment")
InvestigationIdPath = _path("ses", "nova.ses.092")
ActionIdPath = _path("act", "nova.act.01k7example.1.v1")
MemoryIdPath = _path("mem", "nova.mem.092.rollback_success")

IncidentId = _field("inc", "nova.inc.101")
ServiceId = _field("svc", "nova.svc.checkout")


def ulid(now_ms: int | None = None) -> str:
    """Lowercase Crockford ULID: 48-bit ms timestamp + 80 random bits, lexically time-ordered."""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    value = (ts << 80) | secrets.randbits(80)
    out = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        out.append(_CROCKFORD[rem])
    return "".join(reversed(out))


def new_id(tenant_id: str, label: str, now_ms: int | None = None) -> str:
    return f"{tenant_id}.{KINDS[label]}.{ulid(now_ms)}"
