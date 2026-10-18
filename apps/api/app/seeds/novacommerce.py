"""NovaCommerce: a fictional company. Every record here is synthetic; no real people, systems or data.

Story:
- INC-092 (Aug 2026). Payment v2.3 exhausted its DB connection pool, and checkout returned 5xx.
  Restarting checkout did not help (verified *failed* outcome). The payments lead approved a
  simulated rollback of payment to v2.2, and checkout recovered (verified *successful* outcome).
  An unvalidated cache-TTL idea stayed a *draft* memory.
- INC-101 (now). Checkout 5xx again, 13 minutes after payment v2.4 was deployed. Checkout
  DEPENDS_ON payment, and INC-101's evidence REFERS_TO the v2.4 deployment, so v2.4 is the
  rollback candidate. The active payment rollback policy (ADR-031) requires approval from the
  payments lead. It superseded ADR-017, which let on-call roll back alone.
- Inventory v1.9 was deployed the day before and is a red herring: reachable from checkout, but no
  INC-101 evidence refers to it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.actions import canonical_json, spec_hash

TENANT = "nova"
ENV = "prod"


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1000)


# Fixed so that re-seeding writes identical values (idempotent, no timestamp churn).
SEED_AT_MS = ms("2026-10-17T15:00:00")
SRC = "seed"

DOC_BODIES = {
    "adr_017": (
        "Status: superseded by ADR-031 on 2026-06-01.\n\n"
        "Decision: the payments on-call engineer may roll back a payment service deployment without further "
        "approval when checkout errors rise after a release.\n\n"
        "Consequence: fast mitigation, but ledger reconciliation was occasionally left running during rollbacks."
    ),
    "adr_031": (
        "Status: active since 2026-06-01. Supersedes ADR-017.\n\n"
        "Decision: a rollback of the payment service requires approval from the payments lead "
        "(role approver:payment). Ledger reconciliation must be paused before the rollback starts and resumed "
        "after error rates return to baseline.\n\n"
        "Rationale: two rollbacks under ADR-017 left the ledger with duplicate settlement entries."
    ),
    "pm_092": (
        "Summary: payment v2.3 exhausted its database connection pool. Checkout called payment, timed out and "
        "returned HTTP 5xx to customers at a 14 percent rate.\n\n"
        "What did not help: restarting checkout pods at 09:31Z. The fault was upstream in payment.\n\n"
        "Resolution: the payments lead approved a rollback of payment to v2.2 at 09:52Z after pausing ledger "
        "reconciliation. Checkout 5xx returned to 0.3 percent by 10:00Z.\n\n"
        "Follow-up: alert on payment DB pool wait time; review connection pool sizing in every payment release."
    ),
    "sec_handbook": (
        "Restricted. Escalation contacts and credential rotation steps for payment security incidents. "
        "Never shown to agents or used for retrieval."
    ),
}

_rollback_092_spec = canonical_json({
    "action_type": "rollback_deployment_simulated",
    "env": ENV,
    "from_version": "v2.3",
    "service_id": "nova.svc.payment",
    "tenant_id": TENANT,
    "to_version": "v2.2",
})

NODES: list[tuple[str, str, dict]] = [
    # --- organisation
    ("Team", "nova.team.payments", {"name": "Payments"}),
    ("Team", "nova.team.storefront", {"name": "Storefront"}),
    ("Team", "nova.team.identity", {"name": "Identity"}),
    ("Team", "nova.team.finance_platform", {"name": "Finance Platform"}),
    ("Responder", "nova.rsp.payments_lead", {"handle": "payments-lead", "roles": ["approver:payment", "oncall:payment"]}),
    ("Responder", "nova.rsp.payments_oncall", {"handle": "payments-oncall", "roles": ["oncall:payment"]}),
    ("Responder", "nova.rsp.storefront_oncall", {"handle": "storefront-oncall", "roles": ["oncall:checkout"]}),
    ("Responder", "nova.rsp.identity_oncall", {"handle": "identity-oncall", "roles": ["oncall:auth"]}),
    ("Responder", "nova.rsp.ledger_lead", {"handle": "ledger-lead", "roles": ["approver:ledger"]}),
    ("Service", "nova.svc.checkout", {"name": "checkout", "tier": "tier1"}),
    ("Service", "nova.svc.payment", {"name": "payment", "tier": "tier1"}),
    ("Service", "nova.svc.inventory", {"name": "inventory", "tier": "tier2"}),
    ("Service", "nova.svc.auth", {"name": "auth", "tier": "tier1"}),
    ("Service", "nova.svc.ledger", {"name": "ledger", "tier": "tier1"}),
    # --- deployments
    ("Deployment", "nova.dep.payment.v2_3", {"version": "v2.3", "deployed_at_ms": ms("2026-08-12T09:05:00"),
                                             "status": "rolled_back", "source_ref": "synthetic://deploys/payment/v2.3"}),
    ("Deployment", "nova.dep.payment.v2_4", {"version": "v2.4", "deployed_at_ms": ms("2026-10-17T13:52:00"),
                                             "status": "live", "source_ref": "synthetic://deploys/payment/v2.4"}),
    ("Deployment", "nova.dep.inventory.v1_9", {"version": "v1.9", "deployed_at_ms": ms("2026-10-16T10:00:00"),
                                               "status": "live", "source_ref": "synthetic://deploys/inventory/v1.9"}),
    # --- knowledge
    ("Document", "nova.doc.adr_017", {"title": "ADR-017 Payment rollbacks by on-call", "doc_type": "adr",
                                      "uri": "synthetic://wiki/adr/017", "classification": "internal",
                                      "body_redacted": DOC_BODIES["adr_017"]}),
    ("Document", "nova.doc.adr_031", {"title": "ADR-031 Payment rollbacks require payments lead approval",
                                      "doc_type": "adr", "uri": "synthetic://wiki/adr/031", "classification": "internal",
                                      "body_redacted": DOC_BODIES["adr_031"]}),
    ("Document", "nova.doc.pm_092", {"title": "Postmortem INC-092 payment connection pool exhaustion",
                                     "doc_type": "postmortem", "uri": "synthetic://wiki/postmortems/092",
                                     "classification": "internal", "body_redacted": DOC_BODIES["pm_092"]}),
    ("Document", "nova.doc.sec_handbook", {"title": "Security incident handbook (restricted)", "doc_type": "policy",
                                           "uri": "synthetic://wiki/security/handbook", "classification": "restricted",
                                           "body_redacted": DOC_BODIES["sec_handbook"]}),
    ("Decision", "nova.dec.payment.rollback_v1", {
        "title": "Payment rollback policy v1",
        "statement": "Payments on-call may roll back payment deployments without further approval.",
        "status": "superseded", "effective_from_ms": ms("2025-01-15T00:00:00"),
        "effective_to_ms": ms("2026-06-01T00:00:00"), "required_approver_role": "oncall:payment"}),
    ("Decision", "nova.dec.payment.rollback_v2", {
        "title": "Payment rollback policy v2",
        "statement": "Payment rollbacks require payments lead approval because ledger reconciliation must be paused.",
        "status": "active", "effective_from_ms": ms("2026-06-01T00:00:00"),
        "required_approver_role": "approver:payment"}),
    ("Runbook", "nova.rb.payment.rollback", {"title": "Payment service deployment rollback", "version": "3",
                                             "uri": "synthetic://runbooks/payment-rollback",
                                             "allowed_action_types": ["rollback_deployment_simulated"]}),
    # --- INC-092 (resolved)
    ("Incident", "nova.inc.092", {"key": "INC-092", "title": "Checkout 5xx: payment connection pool exhausted",
                                  "severity": "sev2", "status": "resolved",
                                  "started_at_ms": ms("2026-08-12T09:20:00"), "resolved_at_ms": ms("2026-08-12T10:05:00")}),
    ("Alert", "nova.alr.092.checkout_5xx", {"fingerprint": "checkout:http_5xx_rate", "severity": "critical",
                                            "fired_at_ms": ms("2026-08-12T09:18:00"),
                                            "summary_redacted": "checkout 5xx rate 14% (threshold 2%)",
                                            "source_ref": "synthetic://alerts/092-a"}),
    ("Evidence", "nova.ev.092.deploy", {"kind": "deploy_event", "source_ref": "synthetic://deploys/payment/v2.3",
                                        "observed_at_ms": ms("2026-08-12T09:05:00"),
                                        "excerpt_redacted": "payment v2.3 rolled out 100% at 09:05Z"}),
    ("Evidence", "nova.ev.092.checkout_errors", {"kind": "metric",
                                                 "source_ref": "synthetic://metrics/checkout/http_5xx?t=2026-08-12T09:18Z",
                                                 "observed_at_ms": ms("2026-08-12T09:18:00"),
                                                 "excerpt_redacted": "checkout 5xx 14%, upstream=payment timeouts"}),
    ("Evidence", "nova.ev.092.restart", {"kind": "ticket", "source_ref": "synthetic://tickets/OPS-4411",
                                         "observed_at_ms": ms("2026-08-12T09:35:00"),
                                         "excerpt_redacted": "checkout pods restarted 09:31Z; 5xx unchanged at 09:35Z"}),
    ("Evidence", "nova.ev.092.recovery", {"kind": "metric",
                                          "source_ref": "synthetic://metrics/checkout/http_5xx?t=2026-08-12T10:00Z",
                                          "observed_at_ms": ms("2026-08-12T10:00:00"),
                                          "excerpt_redacted": "checkout 5xx back to 0.3% after payment rollback"}),
    ("TimelineEvent", "nova.tl.092.1", {"at_ms": ms("2026-08-12T09:18:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "checkout 5xx alert",
                                        "ref_id": "nova.alr.092.checkout_5xx"}),
    ("TimelineEvent", "nova.tl.092.2", {"at_ms": ms("2026-08-12T09:31:00"), "type": "human_action",
                                        "actor": "storefront-oncall", "summary": "restarted checkout pods"}),
    ("TimelineEvent", "nova.tl.092.3", {"at_ms": ms("2026-08-12T09:52:00"), "type": "approval",
                                        "actor": "payments-lead", "summary": "approved payment rollback to v2.2",
                                        "ref_id": "nova.apr.092.rollback"}),
    ("TimelineEvent", "nova.tl.092.4", {"at_ms": ms("2026-08-12T10:05:00"), "type": "status_change",
                                        "actor": "payments-lead", "summary": "incident resolved"}),
    ("AgentSession", "nova.ses.092", {"thread_id": "seed-thread-nova-092", "run_id": "seed-run-092",
                                      "mode": "simulation", "status": "completed",
                                      "started_at_ms": ms("2026-08-12T09:40:00"),
                                      "ended_at_ms": ms("2026-08-12T10:05:00"), "revision_count": 0,
                                      "findings_json": canonical_json([{
                                          "claim_type": "confirmed",
                                          "statement": "payment v2.3 connection pool regression caused checkout 5xx",
                                          "evidence_ids": ["nova.ev.092.deploy", "nova.ev.092.checkout_errors",
                                                           "nova.ev.092.recovery"]}])}),
    ("AgentAction", "nova.act.092.rollback.v1", {
        "proposal_id": "nova.prop.092.rollback", "version": 1, "action_type": "rollback_deployment_simulated",
        "spec_json": _rollback_092_spec, "spec_hash": spec_hash(_rollback_092_spec),
        "target_service_id": "nova.svc.payment", "risk": "medium", "mode": "simulation",
        "status": "executed_simulated", "approval_expires_at_ms": ms("2026-08-12T10:22:00")}),
    ("ApprovalRecord", "nova.apr.092.rollback", {
        "decision": "APPROVE", "spec_hash": spec_hash(_rollback_092_spec), "action_version": 1,
        "approver_id": "nova.rsp.payments_lead", "decided_at_ms": ms("2026-08-12T09:52:00"),
        "expires_at_ms": ms("2026-08-12T10:22:00"), "scope": "single_execution",
        "policy_decision_id": "nova.dec.payment.rollback_v2",
        "comment": "Matches pool exhaustion pattern; ledger reconciliation paused."}),
    ("AgentMemory", "nova.mem.092.rollback_success", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Rolling back a payment deployment resolved checkout 5xx caused by payment DB connection pool "
                   "exhaustion (INC-092).",
        "provenance_refs": ["nova.ev.092.deploy", "nova.ev.092.recovery", "synthetic://wiki/postmortems/092"],
        "model_version": "human-validated"}),
    ("AgentMemory", "nova.mem.092.restart_failed", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Restarting checkout pods did not reduce checkout 5xx during INC-092; the fault was upstream in payment.",
        "provenance_refs": ["nova.ev.092.restart"], "model_version": "human-validated"}),
    ("AgentMemory", "nova.mem.092.cache_ttl_idea", {
        "memory_type": "procedural", "verification_status": "draft", "outcome": "unknown",
        "summary": "Increasing checkout cache TTL might reduce payment calls during incidents (unvalidated idea).",
        "model_version": "stub-llm-0"}),
    # --- INC-101 (current)
    ("Incident", "nova.inc.101", {"key": "INC-101", "title": "Checkout 5xx spike after payment release",
                                  "severity": "sev2", "status": "open", "started_at_ms": ms("2026-10-17T14:05:00")}),
    ("Alert", "nova.alr.101.checkout_5xx", {"fingerprint": "checkout:http_5xx_rate", "severity": "critical",
                                            "fired_at_ms": ms("2026-10-17T14:04:00"),
                                            "summary_redacted": "checkout 5xx rate 11% (threshold 2%)",
                                            "source_ref": "synthetic://alerts/101-a"}),
    ("Alert", "nova.alr.101.payment_latency", {"fingerprint": "payment:p99_latency", "severity": "warning",
                                               "fired_at_ms": ms("2026-10-17T14:06:00"),
                                               "summary_redacted": "payment p99 2.8s (threshold 800ms)",
                                               "source_ref": "synthetic://alerts/101-b"}),
    ("Evidence", "nova.ev.101.checkout_errors", {"kind": "metric",
                                                 "source_ref": "synthetic://metrics/checkout/http_5xx?t=2026-10-17T14:04Z",
                                                 "observed_at_ms": ms("2026-10-17T14:04:00"),
                                                 "excerpt_redacted": "checkout 5xx 11%, upstream=payment timeouts"}),
    ("Evidence", "nova.ev.101.payment_latency", {"kind": "metric",
                                                 "source_ref": "synthetic://metrics/payment/p99?t=2026-10-17T14:06Z",
                                                 "observed_at_ms": ms("2026-10-17T14:06:00"),
                                                 "excerpt_redacted": "payment p99 2.8s; db pool wait 2.1s"}),
    ("Evidence", "nova.ev.101.deploy", {"kind": "deploy_event", "source_ref": "synthetic://deploys/payment/v2.4",
                                        "observed_at_ms": ms("2026-10-17T13:52:00"),
                                        "excerpt_redacted": "payment v2.4 rolled out 100% at 13:52Z"}),
    ("TimelineEvent", "nova.tl.101.1", {"at_ms": ms("2026-10-17T14:04:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "checkout 5xx alert",
                                        "ref_id": "nova.alr.101.checkout_5xx"}),
    ("TimelineEvent", "nova.tl.101.2", {"at_ms": ms("2026-10-17T14:05:00"), "type": "status_change",
                                        "actor": "storefront-oncall", "summary": "incident opened"}),
    ("TimelineEvent", "nova.tl.101.3", {"at_ms": ms("2026-10-17T14:06:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "payment latency alert",
                                        "ref_id": "nova.alr.101.payment_latency"}),
]
NODES = [(label, nid, {"source": SRC, **props}) for label, nid, props in NODES]

EDGES: list[tuple[str, str, str, str, str]] = [
    ("Team", "nova.team.payments", "OWNS", "Service", "nova.svc.payment"),
    ("Team", "nova.team.storefront", "OWNS", "Service", "nova.svc.checkout"),
    ("Team", "nova.team.storefront", "OWNS", "Service", "nova.svc.inventory"),
    ("Team", "nova.team.identity", "OWNS", "Service", "nova.svc.auth"),
    ("Team", "nova.team.finance_platform", "OWNS", "Service", "nova.svc.ledger"),
    ("Responder", "nova.rsp.payments_lead", "MEMBER_OF", "Team", "nova.team.payments"),
    ("Responder", "nova.rsp.payments_oncall", "MEMBER_OF", "Team", "nova.team.payments"),
    ("Responder", "nova.rsp.storefront_oncall", "MEMBER_OF", "Team", "nova.team.storefront"),
    ("Responder", "nova.rsp.identity_oncall", "MEMBER_OF", "Team", "nova.team.identity"),
    ("Responder", "nova.rsp.ledger_lead", "MEMBER_OF", "Team", "nova.team.finance_platform"),
    ("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.payment"),
    ("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.inventory"),
    ("Service", "nova.svc.checkout", "DEPENDS_ON", "Service", "nova.svc.auth"),
    ("Service", "nova.svc.payment", "DEPENDS_ON", "Service", "nova.svc.ledger"),
    ("Service", "nova.svc.payment", "DEPENDS_ON", "Service", "nova.svc.auth"),
    ("Deployment", "nova.dep.payment.v2_3", "DEPLOYED_TO", "Service", "nova.svc.payment"),
    ("Deployment", "nova.dep.payment.v2_4", "DEPLOYED_TO", "Service", "nova.svc.payment"),
    ("Deployment", "nova.dep.inventory.v1_9", "DEPLOYED_TO", "Service", "nova.svc.inventory"),
    ("Decision", "nova.dec.payment.rollback_v1", "GOVERNS", "Service", "nova.svc.payment"),
    ("Decision", "nova.dec.payment.rollback_v2", "GOVERNS", "Service", "nova.svc.payment"),
    ("Decision", "nova.dec.payment.rollback_v2", "SUPERSEDES", "Decision", "nova.dec.payment.rollback_v1"),
    ("Decision", "nova.dec.payment.rollback_v1", "DOCUMENTED_IN", "Document", "nova.doc.adr_017"),
    ("Decision", "nova.dec.payment.rollback_v2", "DOCUMENTED_IN", "Document", "nova.doc.adr_031"),
    ("Document", "nova.doc.adr_031", "RELATES_TO", "Service", "nova.svc.payment"),
    ("Document", "nova.doc.pm_092", "RELATES_TO", "Incident", "nova.inc.092"),
    ("Document", "nova.doc.pm_092", "RELATES_TO", "Service", "nova.svc.payment"),
    ("Document", "nova.doc.sec_handbook", "RELATES_TO", "Service", "nova.svc.payment"),
    ("Runbook", "nova.rb.payment.rollback", "APPLIES_TO", "Service", "nova.svc.payment"),
    # INC-092
    ("Incident", "nova.inc.092", "AFFECTS", "Service", "nova.svc.checkout"),
    ("Incident", "nova.inc.092", "HAS_ALERT", "Alert", "nova.alr.092.checkout_5xx"),
    ("Incident", "nova.inc.092", "HAS_EVIDENCE", "Evidence", "nova.ev.092.deploy"),
    ("Incident", "nova.inc.092", "HAS_EVIDENCE", "Evidence", "nova.ev.092.checkout_errors"),
    ("Incident", "nova.inc.092", "HAS_EVIDENCE", "Evidence", "nova.ev.092.restart"),
    ("Incident", "nova.inc.092", "HAS_EVIDENCE", "Evidence", "nova.ev.092.recovery"),
    ("Evidence", "nova.ev.092.deploy", "OBSERVED_ON", "Service", "nova.svc.payment"),
    ("Evidence", "nova.ev.092.deploy", "REFERS_TO", "Deployment", "nova.dep.payment.v2_3"),
    ("Evidence", "nova.ev.092.checkout_errors", "OBSERVED_ON", "Service", "nova.svc.checkout"),
    ("Evidence", "nova.ev.092.restart", "OBSERVED_ON", "Service", "nova.svc.checkout"),
    ("Evidence", "nova.ev.092.recovery", "OBSERVED_ON", "Service", "nova.svc.checkout"),
    ("Incident", "nova.inc.092", "HAS_EVENT", "TimelineEvent", "nova.tl.092.1"),
    ("Incident", "nova.inc.092", "HAS_EVENT", "TimelineEvent", "nova.tl.092.2"),
    ("Incident", "nova.inc.092", "HAS_EVENT", "TimelineEvent", "nova.tl.092.3"),
    ("Incident", "nova.inc.092", "HAS_EVENT", "TimelineEvent", "nova.tl.092.4"),
    ("AgentSession", "nova.ses.092", "INVESTIGATES", "Incident", "nova.inc.092"),
    ("AgentAction", "nova.act.092.rollback.v1", "PART_OF", "AgentSession", "nova.ses.092"),
    ("AgentAction", "nova.act.092.rollback.v1", "TARGETS", "Service", "nova.svc.payment"),
    ("AgentAction", "nova.act.092.rollback.v1", "SUPPORTED_BY", "Evidence", "nova.ev.092.deploy"),
    ("AgentAction", "nova.act.092.rollback.v1", "SUPPORTED_BY", "Evidence", "nova.ev.092.checkout_errors"),
    ("AgentAction", "nova.act.092.rollback.v1", "HAS_REVIEW", "ApprovalRecord", "nova.apr.092.rollback"),
    ("ApprovalRecord", "nova.apr.092.rollback", "DECIDED_BY", "Responder", "nova.rsp.payments_lead"),
    ("AgentMemory", "nova.mem.092.rollback_success", "ABOUT", "Incident", "nova.inc.092"),
    ("AgentMemory", "nova.mem.092.rollback_success", "DERIVED_FROM", "AgentAction", "nova.act.092.rollback.v1"),
    ("AgentMemory", "nova.mem.092.rollback_success", "GROUNDED_IN", "Evidence", "nova.ev.092.deploy"),
    ("AgentMemory", "nova.mem.092.rollback_success", "GROUNDED_IN", "Evidence", "nova.ev.092.recovery"),
    ("AgentMemory", "nova.mem.092.restart_failed", "ABOUT", "Incident", "nova.inc.092"),
    ("AgentMemory", "nova.mem.092.restart_failed", "GROUNDED_IN", "Evidence", "nova.ev.092.restart"),
    ("AgentMemory", "nova.mem.092.cache_ttl_idea", "ABOUT", "Incident", "nova.inc.092"),
    # INC-101
    ("Incident", "nova.inc.101", "AFFECTS", "Service", "nova.svc.checkout"),
    ("Incident", "nova.inc.101", "HAS_ALERT", "Alert", "nova.alr.101.checkout_5xx"),
    ("Incident", "nova.inc.101", "HAS_ALERT", "Alert", "nova.alr.101.payment_latency"),
    ("Incident", "nova.inc.101", "HAS_EVIDENCE", "Evidence", "nova.ev.101.checkout_errors"),
    ("Incident", "nova.inc.101", "HAS_EVIDENCE", "Evidence", "nova.ev.101.payment_latency"),
    ("Incident", "nova.inc.101", "HAS_EVIDENCE", "Evidence", "nova.ev.101.deploy"),
    ("Evidence", "nova.ev.101.checkout_errors", "OBSERVED_ON", "Service", "nova.svc.checkout"),
    ("Evidence", "nova.ev.101.payment_latency", "OBSERVED_ON", "Service", "nova.svc.payment"),
    ("Evidence", "nova.ev.101.deploy", "OBSERVED_ON", "Service", "nova.svc.payment"),
    ("Evidence", "nova.ev.101.deploy", "REFERS_TO", "Deployment", "nova.dep.payment.v2_4"),
    ("Incident", "nova.inc.101", "HAS_EVENT", "TimelineEvent", "nova.tl.101.1"),
    ("Incident", "nova.inc.101", "HAS_EVENT", "TimelineEvent", "nova.tl.101.2"),
    ("Incident", "nova.inc.101", "HAS_EVENT", "TimelineEvent", "nova.tl.101.3"),
]

# Applied by the loader through app.services.memories (the only path to `verified`).
# (memory_id, validating responder, outcome, validated_at)
VALIDATIONS: list[tuple[str, str, str, int]] = [
    ("nova.mem.092.rollback_success", "nova.rsp.payments_lead", "successful", ms("2026-08-14T11:00:00")),
    ("nova.mem.092.restart_failed", "nova.rsp.storefront_oncall", "failed", ms("2026-08-14T11:00:00")),
]
