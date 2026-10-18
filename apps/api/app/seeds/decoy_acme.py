"""Decoy tenant, used only by tests to prove tenant scoping.

Its shape mirrors NovaCommerce: a checkout service that depends on payment, plus a deployment
and an incident. A query that leaked across tenants would therefore return plausible-looking rows.
"""

from __future__ import annotations

from app.seeds.novacommerce import ms

TENANT = "acme"
ENV = "prod"
SEED_AT_MS = ms("2026-10-17T15:00:00")

NODES: list[tuple[str, str, dict]] = [
    ("Team", "acme.team.payments", {"name": "Payments"}),
    ("Service", "acme.svc.checkout", {"name": "checkout", "tier": "tier1"}),
    ("Service", "acme.svc.payment", {"name": "payment", "tier": "tier1"}),
    ("Deployment", "acme.dep.payment.v9", {"version": "v9", "deployed_at_ms": ms("2026-10-17T13:00:00"),
                                           "source_ref": "synthetic://acme/deploys/payment/v9"}),
    ("Decision", "acme.dec.payment.rollback", {"title": "Acme rollback policy", "statement": "Anyone may roll back.",
                                               "status": "active", "effective_from_ms": ms("2026-01-01T00:00:00"),
                                               "required_approver_role": "oncall:any"}),
    ("Incident", "acme.inc.7", {"key": "INC-7", "title": "Acme checkout errors", "severity": "sev3",
                                "status": "open", "started_at_ms": ms("2026-10-17T13:30:00")}),
    ("Evidence", "acme.ev.7.deploy", {"kind": "deploy_event", "source_ref": "synthetic://acme/deploys/payment/v9",
                                      "observed_at_ms": ms("2026-10-17T13:00:00")}),
]
NODES = [(label, nid, {"source": "seed", **props}) for label, nid, props in NODES]

EDGES: list[tuple[str, str, str, str, str]] = [
    ("Team", "acme.team.payments", "OWNS", "Service", "acme.svc.payment"),
    ("Team", "acme.team.payments", "OWNS", "Service", "acme.svc.checkout"),
    ("Service", "acme.svc.checkout", "DEPENDS_ON", "Service", "acme.svc.payment"),
    ("Deployment", "acme.dep.payment.v9", "DEPLOYED_TO", "Service", "acme.svc.payment"),
    ("Decision", "acme.dec.payment.rollback", "GOVERNS", "Service", "acme.svc.payment"),
    ("Incident", "acme.inc.7", "AFFECTS", "Service", "acme.svc.checkout"),
    ("Incident", "acme.inc.7", "HAS_EVIDENCE", "Evidence", "acme.ev.7.deploy"),
    ("Evidence", "acme.ev.7.deploy", "REFERS_TO", "Deployment", "acme.dep.payment.v9"),
]
