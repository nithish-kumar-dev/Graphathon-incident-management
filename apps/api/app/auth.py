"""Demo permission context. NOT authentication.

The `X-Demo-User` header selects one of the fictional demo users below. It exists so the API can
enforce tenant scoping and per-endpoint permissions consistently. Production needs a real identity
provider; nothing here claims to be one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

READ = "incident:read"
WRITE = "incident:write"
INGEST = "alert:ingest"
INVESTIGATE = "investigation:create"
REVIEW = "action:review"  # used from Phase 5


@dataclass(frozen=True)
class Principal:
    user_id: str
    display_name: str
    tenant_id: str
    env: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    responder_id: str | None = None

    def can(self, permission: str) -> bool:
        return permission in self.permissions


DEMO_USERS: dict[str, Principal] = {
    p.user_id: p
    for p in [
        Principal("demo-viewer", "Demo viewer (read-only)", "nova", "prod", frozenset({READ})),
        Principal("demo-responder", "Demo responder (storefront on-call)", "nova", "prod",
                  frozenset({READ, WRITE, INGEST, INVESTIGATE}), responder_id="nova.rsp.storefront_oncall"),
        Principal("payments-lead", "Payments lead (approver)", "nova", "prod",
                  frozenset({READ, WRITE, INVESTIGATE, REVIEW}), responder_id="nova.rsp.payments_lead"),
        Principal("acme-viewer", "Decoy tenant viewer (tests only)", "acme", "prod", frozenset({READ})),
    ]
}
