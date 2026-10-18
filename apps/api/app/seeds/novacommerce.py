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

Unrelated failure modes, so the demo is not one story four times:
- INC-087 (Jul 2026, resolved). A notifications release shipped a template schema the consumer could
  not parse; one poison message crash-looped the consumer and order confirmations backed up. Scaling
  consumers out did not help (verified *failed*); dead-lettering the message did (verified *successful*).
- INC-096 (Sep 2026, resolved). Ledger v5.0 turned nightly reconciliation into one full-table
  transaction, and the read replica fell 842s behind. Failing reads over to the primary made it worse
  (verified *failed*); killing the transaction and rerunning it in batches fixed it (verified *successful*).
- INC-103 (now, sev3). Search v4.2 shipped an analyzer the indexer does not know, so 2 of 5 shards
  serve an empty segment and product search returns no results.
- INC-104 (now, sev1). The edge gateway certificate expired; TLS handshakes fail and storefront
  traffic never reaches checkout. No gateway release is involved - the renewal job stopped working.
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
    "pm_087": (
        "Summary: notifications v1.4 introduced template schema v3. One order-confirmation message written "
        "by the new producer could not be parsed by the running consumer, which rejected the whole batch and "
        "crash-looped. The order-confirmation queue reached 48,200 messages and the oldest confirmation was "
        "41 minutes late.\n\n"
        "What did not help: scaling consumers from 4 to 12 replicas at 02:48Z. Every replica picked up the "
        "same message and died on it, so throughput stayed at zero.\n\n"
        "Resolution: the offending message was moved to the dead-letter queue at 03:20Z and the consumer was "
        "redeployed. The queue drained to 120 messages by 04:35Z.\n\n"
        "Follow-up: alert on consumer restart rate, not only on queue depth; reject unparseable messages to "
        "the dead-letter queue instead of failing the batch."
    ),
    "pm_096": (
        "Summary: ledger v5.0 replaced the 5,000-row batched reconciliation with a single full-table "
        "transaction. The transaction ran for 1h52m over 42M settlement rows, the primary could not ship WAL "
        "fast enough, and the read replica fell 842 seconds behind. Order history and finance reports served "
        "stale data.\n\n"
        "What did not help: failing read traffic over to the primary at 23:02Z. Primary CPU reached 94 percent "
        "and checkout order lookups slowed to 4.1s, so the failover was reverted at 23:18Z.\n\n"
        "Resolution: the reconciliation transaction was killed at 23:45Z and rerun in 5,000-row batches. "
        "Replica lag was back to 3 seconds by 01:10Z.\n\n"
        "Follow-up: cap reconciliation transaction duration; alert on primary transaction age, not only on "
        "replica lag."
    ),
    "tls_policy": (
        "Status: active since 2026-02-01.\n\n"
        "Policy: edge TLS certificates are renewed automatically 30 days before expiry. A failed or skipped "
        "renewal pages the edge platform on-call and the alert may not be silenced without a tracking ticket. "
        "Certificate reissue and installation require approval from the edge platform lead "
        "(role approver:gateway); they are never automated by an agent.\n\n"
        "Rationale: an expired edge certificate takes down every storefront entry point at once."
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
    ("Team", "nova.team.edge_platform", {"name": "Edge Platform"}),
    ("Team", "nova.team.messaging", {"name": "Customer Messaging"}),
    ("Responder", "nova.rsp.payments_lead", {"handle": "payments-lead", "roles": ["approver:payment", "oncall:payment"]}),
    ("Responder", "nova.rsp.payments_oncall", {"handle": "payments-oncall", "roles": ["oncall:payment"]}),
    ("Responder", "nova.rsp.storefront_oncall", {"handle": "storefront-oncall", "roles": ["oncall:checkout"]}),
    ("Responder", "nova.rsp.identity_oncall", {"handle": "identity-oncall", "roles": ["oncall:auth"]}),
    ("Responder", "nova.rsp.ledger_lead", {"handle": "ledger-lead", "roles": ["approver:ledger"]}),
    ("Responder", "nova.rsp.edge_oncall", {"handle": "edge-oncall",
                                           "roles": ["oncall:gateway", "approver:gateway"]}),
    ("Responder", "nova.rsp.messaging_oncall", {"handle": "messaging-oncall", "roles": ["oncall:notifications"]}),
    ("Service", "nova.svc.checkout", {"name": "checkout", "tier": "tier1"}),
    ("Service", "nova.svc.payment", {"name": "payment", "tier": "tier1"}),
    ("Service", "nova.svc.inventory", {"name": "inventory", "tier": "tier2"}),
    ("Service", "nova.svc.auth", {"name": "auth", "tier": "tier1"}),
    ("Service", "nova.svc.ledger", {"name": "ledger", "tier": "tier1"}),
    ("Service", "nova.svc.gateway", {"name": "gateway", "tier": "tier1"}),
    ("Service", "nova.svc.search", {"name": "search", "tier": "tier2"}),
    ("Service", "nova.svc.notifications", {"name": "notifications", "tier": "tier2"}),
    # --- deployments
    ("Deployment", "nova.dep.payment.v2_3", {"version": "v2.3", "deployed_at_ms": ms("2026-08-12T09:05:00"),
                                             "status": "rolled_back", "source_ref": "synthetic://deploys/payment/v2.3"}),
    ("Deployment", "nova.dep.payment.v2_4", {"version": "v2.4", "deployed_at_ms": ms("2026-10-17T13:52:00"),
                                             "status": "live", "source_ref": "synthetic://deploys/payment/v2.4"}),
    ("Deployment", "nova.dep.inventory.v1_9", {"version": "v1.9", "deployed_at_ms": ms("2026-10-16T10:00:00"),
                                               "status": "live", "source_ref": "synthetic://deploys/inventory/v1.9"}),
    ("Deployment", "nova.dep.notifications.v1_4", {"version": "v1.4", "deployed_at_ms": ms("2026-07-03T01:55:00"),
                                                   "status": "live",
                                                   "source_ref": "synthetic://deploys/notifications/v1.4"}),
    ("Deployment", "nova.dep.ledger.v5_0", {"version": "v5.0", "deployed_at_ms": ms("2026-09-07T10:30:00"),
                                            "status": "live", "source_ref": "synthetic://deploys/ledger/v5.0"}),
    ("Deployment", "nova.dep.gateway.v7_1", {"version": "v7.1", "deployed_at_ms": ms("2026-10-02T09:15:00"),
                                             "status": "live", "source_ref": "synthetic://deploys/gateway/v7.1"}),
    ("Deployment", "nova.dep.search.v4_2", {"version": "v4.2", "deployed_at_ms": ms("2026-10-17T11:20:00"),
                                            "status": "live", "source_ref": "synthetic://deploys/search/v4.2"}),
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
    ("Document", "nova.doc.pm_087", {"title": "Postmortem INC-087 notification queue backlog",
                                     "doc_type": "postmortem", "uri": "synthetic://wiki/postmortems/087",
                                     "classification": "internal", "body_redacted": DOC_BODIES["pm_087"]}),
    ("Document", "nova.doc.pm_096", {"title": "Postmortem INC-096 ledger read replica lag",
                                     "doc_type": "postmortem", "uri": "synthetic://wiki/postmortems/096",
                                     "classification": "internal", "body_redacted": DOC_BODIES["pm_096"]}),
    ("Document", "nova.doc.tls_policy", {"title": "Edge TLS certificate rotation policy", "doc_type": "policy",
                                         "uri": "synthetic://wiki/policies/tls-rotation",
                                         "classification": "internal", "body_redacted": DOC_BODIES["tls_policy"]}),
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
    ("Decision", "nova.dec.gateway.cert_rotation", {
        "title": "Edge certificate rotation policy",
        "statement": "Edge TLS certificates renew automatically 30 days before expiry; reissue and install "
                     "require edge platform lead approval and are never automated by an agent.",
        "status": "active", "effective_from_ms": ms("2026-02-01T00:00:00"),
        "required_approver_role": "approver:gateway"}),
    ("Runbook", "nova.rb.payment.rollback", {"title": "Payment service deployment rollback", "version": "3",
                                             "uri": "synthetic://runbooks/payment-rollback",
                                             "allowed_action_types": ["rollback_deployment_simulated"]}),
    ("Runbook", "nova.rb.search.reindex", {"title": "Search index rebuild and shard recovery", "version": "2",
                                           "uri": "synthetic://runbooks/search-reindex",
                                           "allowed_action_types": ["rollback_deployment_simulated"]}),
    # No automatable action: certificate work is manual and approval-gated (see nova.doc.tls_policy).
    ("Runbook", "nova.rb.gateway.cert_rotation", {"title": "Edge gateway TLS certificate rotation",
                                                  "version": "4",
                                                  "uri": "synthetic://runbooks/gateway-cert-rotation"}),
    # --- INC-087 (resolved): notification queue backlog from a poison message
    ("Incident", "nova.inc.087", {"key": "INC-087", "title": "Order confirmation emails delayed: notification "
                                                             "queue backlog",
                                  "severity": "sev3", "status": "resolved",
                                  "started_at_ms": ms("2026-07-03T02:15:00"),
                                  "resolved_at_ms": ms("2026-07-03T04:40:00")}),
    ("Alert", "nova.alr.087.queue_depth", {"fingerprint": "notifications:queue_depth", "severity": "warning",
                                           "fired_at_ms": ms("2026-07-03T02:12:00"),
                                           "summary_redacted": "order-confirmation queue depth 48,200 messages "
                                                               "(threshold 5,000)",
                                           "source_ref": "synthetic://alerts/087-a"}),
    ("Alert", "nova.alr.087.consumer_restarts", {"fingerprint": "notifications:consumer_restart_rate",
                                                 "severity": "critical",
                                                 "fired_at_ms": ms("2026-07-03T02:22:00"),
                                                 "summary_redacted": "notifications consumer restarts 214 in 30m "
                                                                     "(threshold 5)",
                                                 "source_ref": "synthetic://alerts/087-b"}),
    ("Evidence", "nova.ev.087.queue_depth", {
        "kind": "metric", "source_ref": "synthetic://metrics/notifications/queue_depth?t=2026-07-03T02:12Z",
        "observed_at_ms": ms("2026-07-03T02:12:00"),
        "excerpt_redacted": "order-confirmation queue depth 48,200, rising 900 msg/min; oldest message age 41m"}),
    ("Evidence", "nova.ev.087.consumer_log", {
        "kind": "log", "source_ref": "synthetic://logs/notifications/consumer?t=2026-07-03T02:20Z",
        "observed_at_ms": ms("2026-07-03T02:20:00"),
        "excerpt_redacted": "consumer crash-looped 214 times in 30m: 'unsupported template version 3' on "
                            "message syn-7781; whole batch rejected and redelivered"}),
    ("Evidence", "nova.ev.087.deploy", {
        "kind": "deploy_event", "source_ref": "synthetic://deploys/notifications/v1.4",
        "observed_at_ms": ms("2026-07-03T01:55:00"),
        "excerpt_redacted": "notifications v1.4 rolled out 100% at 01:55Z; producer started writing template "
                            "schema v3, consumers still on v2"}),
    ("Evidence", "nova.ev.087.scale_out", {
        "kind": "ticket", "source_ref": "synthetic://tickets/OPS-5120",
        "observed_at_ms": ms("2026-07-03T03:05:00"),
        "excerpt_redacted": "consumer replicas scaled 4 -> 12 at 02:48Z; queue depth still 51,600 at 03:05Z and "
                            "throughput still 0 msg/s"}),
    ("Evidence", "nova.ev.087.drain", {
        "kind": "metric", "source_ref": "synthetic://metrics/notifications/queue_depth?t=2026-07-03T04:35Z",
        "observed_at_ms": ms("2026-07-03T04:35:00"),
        "excerpt_redacted": "queue drained 51,600 -> 120 messages by 04:35Z after message syn-7781 was moved to "
                            "the dead-letter queue and consumers were redeployed"}),
    ("TimelineEvent", "nova.tl.087.1", {"at_ms": ms("2026-07-03T02:12:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "notification queue depth alert",
                                        "ref_id": "nova.alr.087.queue_depth"}),
    ("TimelineEvent", "nova.tl.087.2", {"at_ms": ms("2026-07-03T02:15:00"), "type": "status_change",
                                        "actor": "messaging-oncall", "summary": "incident opened at sev3"}),
    ("TimelineEvent", "nova.tl.087.3", {"at_ms": ms("2026-07-03T02:22:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "consumer restart rate alert",
                                        "ref_id": "nova.alr.087.consumer_restarts"}),
    ("TimelineEvent", "nova.tl.087.4", {"at_ms": ms("2026-07-03T02:48:00"), "type": "human_action",
                                        "actor": "messaging-oncall",
                                        "summary": "scaled consumer replicas 4 -> 12"}),
    ("TimelineEvent", "nova.tl.087.5", {"at_ms": ms("2026-07-03T03:20:00"), "type": "human_action",
                                        "actor": "messaging-oncall",
                                        "summary": "moved poison message to the dead-letter queue and "
                                                   "redeployed consumers"}),
    ("TimelineEvent", "nova.tl.087.6", {"at_ms": ms("2026-07-03T04:40:00"), "type": "status_change",
                                        "actor": "messaging-oncall",
                                        "summary": "incident resolved; delayed confirmations sent"}),
    ("AgentMemory", "nova.mem.087.dead_letter_success", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Dead-lettering the unparseable message and redeploying consumers drained a 48k "
                   "order-confirmation backlog (INC-087); the backlog was a schema mismatch, not capacity.",
        "provenance_refs": ["nova.ev.087.consumer_log", "nova.ev.087.drain",
                            "synthetic://wiki/postmortems/087"],
        "model_version": "human-validated"}),
    ("AgentMemory", "nova.mem.087.scale_out_failed", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Scaling notification consumers from 4 to 12 did not drain the queue during INC-087; every "
                   "replica picked up the same poison message and crashed.",
        "provenance_refs": ["nova.ev.087.scale_out"], "model_version": "human-validated"}),
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
    # --- INC-096 (resolved): ledger read replica lag behind a long reconciliation transaction
    ("Incident", "nova.inc.096", {"key": "INC-096",
                                  "title": "Stale order history and finance reports: ledger replica lag",
                                  "severity": "sev2", "status": "resolved",
                                  "started_at_ms": ms("2026-09-08T22:40:00"),
                                  "resolved_at_ms": ms("2026-09-09T01:15:00")}),
    ("Alert", "nova.alr.096.replica_lag", {"fingerprint": "ledger:replica_lag_seconds", "severity": "critical",
                                           "fired_at_ms": ms("2026-09-08T22:38:00"),
                                           "summary_redacted": "ledger read replica lag 842s (threshold 60s)",
                                           "source_ref": "synthetic://alerts/096-a"}),
    ("Evidence", "nova.ev.096.replica_lag", {
        "kind": "metric", "source_ref": "synthetic://metrics/ledger/replica_lag?t=2026-09-08T22:38Z",
        "observed_at_ms": ms("2026-09-08T22:38:00"),
        "excerpt_redacted": "ledger replica lag 842s and growing about 1s per second; primary WAL send queue "
                            "11 GB"}),
    ("Evidence", "nova.ev.096.batch_job", {
        "kind": "log", "source_ref": "synthetic://logs/ledger/reconciliation?t=2026-09-08T22:45Z",
        "observed_at_ms": ms("2026-09-08T22:45:00"),
        "excerpt_redacted": "nightly reconciliation held one transaction open for 1h52m scanning 42M "
                            "settlement rows; oldest transaction age 6,720s"}),
    ("Evidence", "nova.ev.096.deploy", {
        "kind": "deploy_event", "source_ref": "synthetic://deploys/ledger/v5.0",
        "observed_at_ms": ms("2026-09-07T10:30:00"),
        "excerpt_redacted": "ledger v5.0 rolled out 2026-09-07 10:30Z; reconciliation changed from 5,000-row "
                            "batches to a single full-table transaction"}),
    ("Evidence", "nova.ev.096.failover_attempt", {
        "kind": "ticket", "source_ref": "synthetic://tickets/OPS-5533",
        "observed_at_ms": ms("2026-09-08T23:20:00"),
        "excerpt_redacted": "read traffic failed over to the primary at 23:02Z; primary CPU hit 94% and "
                            "checkout order lookups slowed to 4.1s, so it was reverted at 23:18Z"}),
    ("Evidence", "nova.ev.096.recovery", {
        "kind": "metric", "source_ref": "synthetic://metrics/ledger/replica_lag?t=2026-09-09T01:10Z",
        "observed_at_ms": ms("2026-09-09T01:10:00"),
        "excerpt_redacted": "replica lag 842s -> 3s by 01:10Z after the reconciliation transaction was killed "
                            "and rerun in 5,000-row batches"}),
    ("TimelineEvent", "nova.tl.096.1", {"at_ms": ms("2026-09-08T22:38:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "ledger replica lag alert",
                                        "ref_id": "nova.alr.096.replica_lag"}),
    ("TimelineEvent", "nova.tl.096.2", {"at_ms": ms("2026-09-08T22:40:00"), "type": "status_change",
                                        "actor": "ledger-lead", "summary": "incident opened at sev2"}),
    ("TimelineEvent", "nova.tl.096.3", {"at_ms": ms("2026-09-08T23:02:00"), "type": "human_action",
                                        "actor": "ledger-lead",
                                        "summary": "failed read traffic over to the primary"}),
    ("TimelineEvent", "nova.tl.096.4", {"at_ms": ms("2026-09-08T23:45:00"), "type": "human_action",
                                        "actor": "ledger-lead",
                                        "summary": "killed the reconciliation transaction and restarted it in "
                                                   "5,000-row batches"}),
    ("TimelineEvent", "nova.tl.096.5", {"at_ms": ms("2026-09-09T01:15:00"), "type": "status_change",
                                        "actor": "ledger-lead", "summary": "incident resolved"}),
    ("AgentMemory", "nova.mem.096.batch_the_job_success", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Killing the full-table reconciliation transaction and rerunning it in 5,000-row batches "
                   "cleared 842s of ledger replica lag (INC-096); check for long-running transactions on the "
                   "primary first when replica lag grows steadily.",
        "provenance_refs": ["nova.ev.096.batch_job", "nova.ev.096.recovery",
                            "synthetic://wiki/postmortems/096"],
        "model_version": "human-validated"}),
    ("AgentMemory", "nova.mem.096.primary_failover_failed", {
        "memory_type": "episodic", "verification_status": "draft", "outcome": "unknown",
        "summary": "Failing ledger read traffic over to the primary during INC-096 made things worse: primary "
                   "CPU saturated at 94% and checkout order lookups slowed to 4.1s.",
        "provenance_refs": ["nova.ev.096.failover_attempt"], "model_version": "human-validated"}),
    # --- INC-103 (current): search index rebuild left shards empty
    ("Incident", "nova.inc.103", {"key": "INC-103",
                                  "title": "Product search returning empty results after index rebuild",
                                  "severity": "sev3", "status": "investigating",
                                  "started_at_ms": ms("2026-10-17T12:10:00")}),
    ("Alert", "nova.alr.103.zero_results", {"fingerprint": "search:zero_result_rate", "severity": "warning",
                                            "fired_at_ms": ms("2026-10-17T12:08:00"),
                                            "summary_redacted": "search zero-result rate 37% (threshold 5%)",
                                            "source_ref": "synthetic://alerts/103-a"}),
    ("Alert", "nova.alr.103.index_lag", {"fingerprint": "search:index_replication_lag", "severity": "warning",
                                         "fired_at_ms": ms("2026-10-17T12:14:00"),
                                         "summary_redacted": "search index replication lag 19m (threshold 2m)",
                                         "source_ref": "synthetic://alerts/103-b"}),
    ("Evidence", "nova.ev.103.zero_results", {
        "kind": "metric", "source_ref": "synthetic://metrics/search/zero_result_rate?t=2026-10-17T12:08Z",
        "observed_at_ms": ms("2026-10-17T12:08:00"),
        "excerpt_redacted": "search zero-result rate 37% against a 7-day baseline of 4.1%; multi-word queries "
                            "worst hit at 61%"}),
    ("Evidence", "nova.ev.103.deploy", {
        "kind": "deploy_event", "source_ref": "synthetic://deploys/search/v4.2",
        "observed_at_ms": ms("2026-10-17T11:20:00"),
        "excerpt_redacted": "search v4.2 rolled out 100% at 11:20Z with an analyzer change that triggers a "
                            "full index rebuild"}),
    ("Evidence", "nova.ev.103.index_log", {
        "kind": "log", "source_ref": "synthetic://logs/search/indexer?t=2026-10-17T12:12Z",
        "observed_at_ms": ms("2026-10-17T12:12:00"),
        "excerpt_redacted": "indexer: rebuild aborted on shards 3 and 4 - 'analyzer nova_text_v2 not found'; "
                            "2 of 5 shards now serve an empty segment"}),
    ("Evidence", "nova.ev.103.catalog_unchanged", {
        "kind": "metric", "source_ref": "synthetic://metrics/inventory/active_skus?t=2026-10-17T12:20Z",
        "observed_at_ms": ms("2026-10-17T12:20:00"),
        "excerpt_redacted": "inventory reports 48,912 active SKUs at both 11:00Z and 12:20Z, so the catalog is "
                            "not the source of the empty results"}),
    ("TimelineEvent", "nova.tl.103.1", {"at_ms": ms("2026-10-17T12:08:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "search zero-result rate alert",
                                        "ref_id": "nova.alr.103.zero_results"}),
    ("TimelineEvent", "nova.tl.103.2", {"at_ms": ms("2026-10-17T12:10:00"), "type": "status_change",
                                        "actor": "storefront-oncall", "summary": "incident opened at sev3"}),
    ("TimelineEvent", "nova.tl.103.3", {"at_ms": ms("2026-10-17T12:14:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "search index replication lag alert",
                                        "ref_id": "nova.alr.103.index_lag"}),
    ("TimelineEvent", "nova.tl.103.4", {"at_ms": ms("2026-10-17T12:26:00"), "type": "human_action",
                                        "actor": "storefront-oncall",
                                        "summary": "re-ran the rebuild on shards 3 and 4; same analyzer error"}),
    # --- INC-104 (current): expired edge certificate, no release involved
    ("Incident", "nova.inc.104", {"key": "INC-104",
                                  "title": "Edge gateway TLS certificate expired: storefront traffic rejected",
                                  "severity": "sev1", "status": "open",
                                  "started_at_ms": ms("2026-10-17T14:32:00")}),
    ("Alert", "nova.alr.104.tls_handshake", {"fingerprint": "gateway:tls_handshake_failure_rate",
                                             "severity": "critical",
                                             "fired_at_ms": ms("2026-10-17T14:31:00"),
                                             "summary_redacted": "gateway TLS handshake failures 96% of "
                                                                 "requests (threshold 1%)",
                                             "source_ref": "synthetic://alerts/104-a"}),
    ("Alert", "nova.alr.104.checkout_traffic", {"fingerprint": "checkout:session_start_rate",
                                                "severity": "warning",
                                                "fired_at_ms": ms("2026-10-17T14:34:00"),
                                                "summary_redacted": "checkout session starts 41/min "
                                                                    "(threshold 300/min)",
                                                "source_ref": "synthetic://alerts/104-b"}),
    ("Evidence", "nova.ev.104.tls_errors", {
        "kind": "metric", "source_ref": "synthetic://metrics/gateway/tls_handshakes?t=2026-10-17T14:31Z",
        "observed_at_ms": ms("2026-10-17T14:31:00"),
        "excerpt_redacted": "96% of HTTPS handshakes failed with certificate_expired from 14:30Z; gateway "
                            "request success rate 4%"}),
    ("Evidence", "nova.ev.104.gateway_log", {
        "kind": "log", "source_ref": "synthetic://logs/gateway/tls?t=2026-10-17T14:33Z",
        "observed_at_ms": ms("2026-10-17T14:33:00"),
        "excerpt_redacted": "tls handshake error: certificate has expired - 18,400 occurrences in 60s across "
                            "the edge pool"}),
    ("Evidence", "nova.ev.104.cert_inventory", {
        "kind": "doc", "source_ref": "synthetic://configs/gateway/tls-cert-inventory",
        "observed_at_ms": ms("2026-10-17T14:36:00"),
        "excerpt_redacted": "edge certificate serial syn-4417 notAfter 2026-10-17T14:30:00Z; auto-renewal job "
                            "last succeeded 2026-07-19 and has been failing silently since"}),
    ("Evidence", "nova.ev.104.early_warning", {
        "kind": "alert", "source_ref": "synthetic://alerts/cert-expiry-14d",
        "observed_at_ms": ms("2026-10-03T06:00:00"),
        "excerpt_redacted": "cert_days_to_expiry warning on 2026-10-03: edge certificate expires in 14 days; "
                            "acknowledged, no ticket raised"}),
    ("Evidence", "nova.ev.104.no_deploy", {
        "kind": "deploy_event", "source_ref": "synthetic://deploys/gateway/v7.1",
        "observed_at_ms": ms("2026-10-02T09:15:00"),
        "excerpt_redacted": "gateway v7.1 rolled out 2026-10-02 09:15Z and is still live; no gateway release "
                            "in the 15 days before the incident"}),
    ("Evidence", "nova.ev.104.checkout_impact", {
        "kind": "metric", "source_ref": "synthetic://metrics/checkout/session_starts?t=2026-10-17T14:34Z",
        "observed_at_ms": ms("2026-10-17T14:34:00"),
        "excerpt_redacted": "checkout session starts 41/min against a 7-day baseline of 420/min; traffic is "
                            "not reaching checkout at all"}),
    ("TimelineEvent", "nova.tl.104.1", {"at_ms": ms("2026-10-17T14:31:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "gateway TLS handshake failure alert",
                                        "ref_id": "nova.alr.104.tls_handshake"}),
    ("TimelineEvent", "nova.tl.104.2", {"at_ms": ms("2026-10-17T14:32:00"), "type": "status_change",
                                        "actor": "edge-oncall", "summary": "incident opened at sev1"}),
    ("TimelineEvent", "nova.tl.104.3", {"at_ms": ms("2026-10-17T14:34:00"), "type": "alert_fired",
                                        "actor": "monitoring", "summary": "checkout session start rate alert",
                                        "ref_id": "nova.alr.104.checkout_traffic"}),
    ("TimelineEvent", "nova.tl.104.4", {"at_ms": ms("2026-10-17T14:38:00"), "type": "human_action",
                                        "actor": "edge-oncall",
                                        "summary": "confirmed the edge certificate expired at 14:30Z; reissue "
                                                   "needs edge platform lead approval"}),
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
    # --- services, teams and knowledge introduced by INC-087/096/103/104
    ("Team", "nova.team.edge_platform", "OWNS", "Service", "nova.svc.gateway"),
    ("Team", "nova.team.storefront", "OWNS", "Service", "nova.svc.search"),
    ("Team", "nova.team.messaging", "OWNS", "Service", "nova.svc.notifications"),
    ("Responder", "nova.rsp.edge_oncall", "MEMBER_OF", "Team", "nova.team.edge_platform"),
    ("Responder", "nova.rsp.messaging_oncall", "MEMBER_OF", "Team", "nova.team.messaging"),
    # The gateway fronts the storefront backends; search reads the catalogue; notifications reacts to orders.
    ("Service", "nova.svc.gateway", "DEPENDS_ON", "Service", "nova.svc.checkout"),
    ("Service", "nova.svc.gateway", "DEPENDS_ON", "Service", "nova.svc.search"),
    ("Service", "nova.svc.gateway", "DEPENDS_ON", "Service", "nova.svc.auth"),
    ("Service", "nova.svc.search", "DEPENDS_ON", "Service", "nova.svc.inventory"),
    ("Service", "nova.svc.notifications", "DEPENDS_ON", "Service", "nova.svc.checkout"),
    ("Deployment", "nova.dep.notifications.v1_4", "DEPLOYED_TO", "Service", "nova.svc.notifications"),
    ("Deployment", "nova.dep.ledger.v5_0", "DEPLOYED_TO", "Service", "nova.svc.ledger"),
    ("Deployment", "nova.dep.gateway.v7_1", "DEPLOYED_TO", "Service", "nova.svc.gateway"),
    ("Deployment", "nova.dep.search.v4_2", "DEPLOYED_TO", "Service", "nova.svc.search"),
    ("Decision", "nova.dec.gateway.cert_rotation", "GOVERNS", "Service", "nova.svc.gateway"),
    ("Decision", "nova.dec.gateway.cert_rotation", "DOCUMENTED_IN", "Document", "nova.doc.tls_policy"),
    ("Document", "nova.doc.tls_policy", "RELATES_TO", "Service", "nova.svc.gateway"),
    ("Document", "nova.doc.pm_087", "RELATES_TO", "Incident", "nova.inc.087"),
    ("Document", "nova.doc.pm_087", "RELATES_TO", "Service", "nova.svc.notifications"),
    ("Document", "nova.doc.pm_096", "RELATES_TO", "Incident", "nova.inc.096"),
    ("Document", "nova.doc.pm_096", "RELATES_TO", "Service", "nova.svc.ledger"),
    ("Runbook", "nova.rb.search.reindex", "APPLIES_TO", "Service", "nova.svc.search"),
    ("Runbook", "nova.rb.gateway.cert_rotation", "APPLIES_TO", "Service", "nova.svc.gateway"),
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
    # INC-087
    ("Incident", "nova.inc.087", "AFFECTS", "Service", "nova.svc.notifications"),
    ("Incident", "nova.inc.087", "HAS_ALERT", "Alert", "nova.alr.087.queue_depth"),
    ("Incident", "nova.inc.087", "HAS_ALERT", "Alert", "nova.alr.087.consumer_restarts"),
    ("Incident", "nova.inc.087", "HAS_EVIDENCE", "Evidence", "nova.ev.087.queue_depth"),
    ("Incident", "nova.inc.087", "HAS_EVIDENCE", "Evidence", "nova.ev.087.consumer_log"),
    ("Incident", "nova.inc.087", "HAS_EVIDENCE", "Evidence", "nova.ev.087.deploy"),
    ("Incident", "nova.inc.087", "HAS_EVIDENCE", "Evidence", "nova.ev.087.scale_out"),
    ("Incident", "nova.inc.087", "HAS_EVIDENCE", "Evidence", "nova.ev.087.drain"),
    ("Evidence", "nova.ev.087.queue_depth", "OBSERVED_ON", "Service", "nova.svc.notifications"),
    ("Evidence", "nova.ev.087.consumer_log", "OBSERVED_ON", "Service", "nova.svc.notifications"),
    ("Evidence", "nova.ev.087.deploy", "OBSERVED_ON", "Service", "nova.svc.notifications"),
    ("Evidence", "nova.ev.087.deploy", "REFERS_TO", "Deployment", "nova.dep.notifications.v1_4"),
    ("Evidence", "nova.ev.087.scale_out", "OBSERVED_ON", "Service", "nova.svc.notifications"),
    ("Evidence", "nova.ev.087.drain", "OBSERVED_ON", "Service", "nova.svc.notifications"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.1"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.2"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.3"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.4"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.5"),
    ("Incident", "nova.inc.087", "HAS_EVENT", "TimelineEvent", "nova.tl.087.6"),
    ("AgentMemory", "nova.mem.087.dead_letter_success", "ABOUT", "Incident", "nova.inc.087"),
    ("AgentMemory", "nova.mem.087.dead_letter_success", "GROUNDED_IN", "Evidence", "nova.ev.087.consumer_log"),
    ("AgentMemory", "nova.mem.087.dead_letter_success", "GROUNDED_IN", "Evidence", "nova.ev.087.drain"),
    ("AgentMemory", "nova.mem.087.scale_out_failed", "ABOUT", "Incident", "nova.inc.087"),
    ("AgentMemory", "nova.mem.087.scale_out_failed", "GROUNDED_IN", "Evidence", "nova.ev.087.scale_out"),
    # INC-096
    ("Incident", "nova.inc.096", "AFFECTS", "Service", "nova.svc.ledger"),
    ("Incident", "nova.inc.096", "HAS_ALERT", "Alert", "nova.alr.096.replica_lag"),
    ("Incident", "nova.inc.096", "HAS_EVIDENCE", "Evidence", "nova.ev.096.replica_lag"),
    ("Incident", "nova.inc.096", "HAS_EVIDENCE", "Evidence", "nova.ev.096.batch_job"),
    ("Incident", "nova.inc.096", "HAS_EVIDENCE", "Evidence", "nova.ev.096.deploy"),
    ("Incident", "nova.inc.096", "HAS_EVIDENCE", "Evidence", "nova.ev.096.failover_attempt"),
    ("Incident", "nova.inc.096", "HAS_EVIDENCE", "Evidence", "nova.ev.096.recovery"),
    ("Evidence", "nova.ev.096.replica_lag", "OBSERVED_ON", "Service", "nova.svc.ledger"),
    ("Evidence", "nova.ev.096.batch_job", "OBSERVED_ON", "Service", "nova.svc.ledger"),
    ("Evidence", "nova.ev.096.deploy", "OBSERVED_ON", "Service", "nova.svc.ledger"),
    ("Evidence", "nova.ev.096.deploy", "REFERS_TO", "Deployment", "nova.dep.ledger.v5_0"),
    ("Evidence", "nova.ev.096.failover_attempt", "OBSERVED_ON", "Service", "nova.svc.ledger"),
    ("Evidence", "nova.ev.096.recovery", "OBSERVED_ON", "Service", "nova.svc.ledger"),
    ("Incident", "nova.inc.096", "HAS_EVENT", "TimelineEvent", "nova.tl.096.1"),
    ("Incident", "nova.inc.096", "HAS_EVENT", "TimelineEvent", "nova.tl.096.2"),
    ("Incident", "nova.inc.096", "HAS_EVENT", "TimelineEvent", "nova.tl.096.3"),
    ("Incident", "nova.inc.096", "HAS_EVENT", "TimelineEvent", "nova.tl.096.4"),
    ("Incident", "nova.inc.096", "HAS_EVENT", "TimelineEvent", "nova.tl.096.5"),
    ("AgentMemory", "nova.mem.096.batch_the_job_success", "ABOUT", "Incident", "nova.inc.096"),
    ("AgentMemory", "nova.mem.096.batch_the_job_success", "GROUNDED_IN", "Evidence", "nova.ev.096.batch_job"),
    ("AgentMemory", "nova.mem.096.batch_the_job_success", "GROUNDED_IN", "Evidence", "nova.ev.096.recovery"),
    ("AgentMemory", "nova.mem.096.primary_failover_failed", "ABOUT", "Incident", "nova.inc.096"),
    ("AgentMemory", "nova.mem.096.primary_failover_failed", "GROUNDED_IN", "Evidence",
     "nova.ev.096.failover_attempt"),
    # INC-103
    ("Incident", "nova.inc.103", "AFFECTS", "Service", "nova.svc.search"),
    ("Incident", "nova.inc.103", "HAS_ALERT", "Alert", "nova.alr.103.zero_results"),
    ("Incident", "nova.inc.103", "HAS_ALERT", "Alert", "nova.alr.103.index_lag"),
    ("Incident", "nova.inc.103", "HAS_EVIDENCE", "Evidence", "nova.ev.103.zero_results"),
    ("Incident", "nova.inc.103", "HAS_EVIDENCE", "Evidence", "nova.ev.103.deploy"),
    ("Incident", "nova.inc.103", "HAS_EVIDENCE", "Evidence", "nova.ev.103.index_log"),
    ("Incident", "nova.inc.103", "HAS_EVIDENCE", "Evidence", "nova.ev.103.catalog_unchanged"),
    ("Evidence", "nova.ev.103.zero_results", "OBSERVED_ON", "Service", "nova.svc.search"),
    ("Evidence", "nova.ev.103.deploy", "OBSERVED_ON", "Service", "nova.svc.search"),
    ("Evidence", "nova.ev.103.deploy", "REFERS_TO", "Deployment", "nova.dep.search.v4_2"),
    ("Evidence", "nova.ev.103.index_log", "OBSERVED_ON", "Service", "nova.svc.search"),
    ("Evidence", "nova.ev.103.catalog_unchanged", "OBSERVED_ON", "Service", "nova.svc.inventory"),
    ("Incident", "nova.inc.103", "HAS_EVENT", "TimelineEvent", "nova.tl.103.1"),
    ("Incident", "nova.inc.103", "HAS_EVENT", "TimelineEvent", "nova.tl.103.2"),
    ("Incident", "nova.inc.103", "HAS_EVENT", "TimelineEvent", "nova.tl.103.3"),
    ("Incident", "nova.inc.103", "HAS_EVENT", "TimelineEvent", "nova.tl.103.4"),
    # INC-104
    ("Incident", "nova.inc.104", "AFFECTS", "Service", "nova.svc.gateway"),
    ("Incident", "nova.inc.104", "HAS_ALERT", "Alert", "nova.alr.104.tls_handshake"),
    ("Incident", "nova.inc.104", "HAS_ALERT", "Alert", "nova.alr.104.checkout_traffic"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.tls_errors"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.gateway_log"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.cert_inventory"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.early_warning"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.no_deploy"),
    ("Incident", "nova.inc.104", "HAS_EVIDENCE", "Evidence", "nova.ev.104.checkout_impact"),
    ("Evidence", "nova.ev.104.tls_errors", "OBSERVED_ON", "Service", "nova.svc.gateway"),
    ("Evidence", "nova.ev.104.gateway_log", "OBSERVED_ON", "Service", "nova.svc.gateway"),
    ("Evidence", "nova.ev.104.cert_inventory", "OBSERVED_ON", "Service", "nova.svc.gateway"),
    ("Evidence", "nova.ev.104.early_warning", "OBSERVED_ON", "Service", "nova.svc.gateway"),
    ("Evidence", "nova.ev.104.no_deploy", "OBSERVED_ON", "Service", "nova.svc.gateway"),
    ("Evidence", "nova.ev.104.no_deploy", "REFERS_TO", "Deployment", "nova.dep.gateway.v7_1"),
    ("Evidence", "nova.ev.104.checkout_impact", "OBSERVED_ON", "Service", "nova.svc.checkout"),
    ("Incident", "nova.inc.104", "HAS_EVENT", "TimelineEvent", "nova.tl.104.1"),
    ("Incident", "nova.inc.104", "HAS_EVENT", "TimelineEvent", "nova.tl.104.2"),
    ("Incident", "nova.inc.104", "HAS_EVENT", "TimelineEvent", "nova.tl.104.3"),
    ("Incident", "nova.inc.104", "HAS_EVENT", "TimelineEvent", "nova.tl.104.4"),
]

# Applied by the loader through app.services.memories (the only path to `verified`).
# (memory_id, validating responder, outcome, validated_at)
VALIDATIONS: list[tuple[str, str, str, int]] = [
    ("nova.mem.092.rollback_success", "nova.rsp.payments_lead", "successful", ms("2026-08-14T11:00:00")),
    ("nova.mem.092.restart_failed", "nova.rsp.storefront_oncall", "failed", ms("2026-08-14T11:00:00")),
    ("nova.mem.087.dead_letter_success", "nova.rsp.messaging_oncall", "successful", ms("2026-07-05T10:00:00")),
    ("nova.mem.087.scale_out_failed", "nova.rsp.messaging_oncall", "failed", ms("2026-07-05T10:00:00")),
    ("nova.mem.096.batch_the_job_success", "nova.rsp.ledger_lead", "successful", ms("2026-09-10T09:30:00")),
    ("nova.mem.096.primary_failover_failed", "nova.rsp.ledger_lead", "failed", ms("2026-09-10T09:30:00")),
]
