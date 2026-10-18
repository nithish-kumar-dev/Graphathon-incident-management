"""Synthetic alert ingest: scoped sliding-window dedup, idempotent on source_ref, incident correlation.

Flow (every step is one atomic FalkorDB write query; FalkorDB runs one write per graph at a time):
1. Dedup: look for an alert with the same fingerprint within +/- window in this tenant/env.
   Same source_ref -> `replayed` (nothing changes). Otherwise -> `deduplicated` (count + remember).
2. If none: create the alert under a deterministic id (fingerprint + window bucket), so concurrent
   creators collapse onto one node; the loser falls back to step 1.
3. Attach: existing link, else the newest unresolved incident on the service, else a new incident.
   Always run, so a replay of a request that died after step 2 finishes the job (no orphan alerts).

Known limit: two *different* events in adjacent buckets arriving at the same instant can both be created.
Timeline events are separate writes; a crash between steps can lose one (the alert and incident remain).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.api import models as m
from app.api.errors import InvalidInput
from app.auth import Principal
from app.config import Settings
from app.domain.redact import redact
from app.graph.repository import GraphRepository
from app.ids import new_id
from app.services.incidents import add_timeline

SEVERITY_MAP = {"critical": "sev2", "warning": "sev3", "info": "sev4"}
INGEST_ACTOR = "alert-ingest"


@dataclass
class IngestOutcome:
    result: m.AlertIngestResult
    created: bool


def ingest(repo: GraphRepository, alert: m.AlertIn, principal: Principal, settings: Settings,
           now_ms: int) -> IngestOutcome:
    at = int(alert.fired_at.timestamp() * 1000)
    if at > now_ms + settings.alert_max_future_skew_s * 1000:
        raise InvalidInput("fired_at is in the future", code="fired_at_out_of_range")
    if at < now_ms - settings.alert_max_age_s * 1000:
        raise InvalidInput("fired_at is older than the ingest window", code="fired_at_out_of_range")
    service = repo.get_node("Service", alert.service_id)
    if service is None:
        raise InvalidInput(f"unknown service_id {alert.service_id}", code="unknown_reference")

    window_ms = settings.alert_dedup_window_s * 1000
    dedup_args = {"fingerprint": alert.fingerprint, "source_ref": alert.source_ref, "at_ms": at,
                  "window_ms": window_ms, "now": now_ms}

    hit = repo.alert_dedup(**dedup_args)
    created_alert = False
    if hit is None:
        alert_id = _bucket_id(repo, alert.fingerprint, at, window_ms)
        created_alert = repo.merge_alert(alert_id, {
            "fingerprint": alert.fingerprint, "severity": alert.severity, "fired_at_ms": at,
            "last_fired_at_ms": at, "summary_redacted": redact(alert.summary), "source_ref": alert.source_ref,
            "service_id": alert.service_id, "source": "ingest",
        }, at_ms=now_ms)
        if not created_alert:
            hit = repo.alert_dedup(**dedup_args)  # lost a creation race: count against the winner
    alert_id = alert_id if created_alert else hit["alert_id"]

    incident = repo.attach_alert(alert_id, alert.service_id, at_ms=now_ms,
                                 new_incident_id=new_id(repo.scope.tenant_id, "Incident", now_ms),
                                 incident_props={
                                     "title": redact(f"{service['name']}: {alert.summary}")[:200],
                                     "severity": SEVERITY_MAP[alert.severity], "status": "open",
                                     "started_at_ms": at, "source": "ingest", "source_ref": alert.source_ref})
    if incident["created"]:
        add_timeline(repo, incident["incident_id"], "incident_opened", INGEST_ACTOR,
                     f"opened from alert {alert.fingerprint}", now_ms, ref_id=alert_id, source="ingest")
    if created_alert:
        add_timeline(repo, incident["incident_id"], "alert_fired", INGEST_ACTOR,
                     f"{alert.severity} alert {alert.fingerprint} on {alert.service_id}", now_ms,
                     ref_id=alert_id, source="ingest")
        outcome = "created_incident" if incident["created"] else "attached_to_incident"
        dedup_count = 0
    else:
        outcome = "replayed" if hit["replay"] else "deduplicated"
        dedup_count = hit["dedup_count"]
    return IngestOutcome(m.AlertIngestResult(
        outcome=outcome, alert_id=alert_id, incident_id=incident["incident_id"],
        incident_key=incident["incident_key"], dedup_count=dedup_count,
        dedup_window_seconds=settings.alert_dedup_window_s), created=created_alert)


def _bucket_id(repo: GraphRepository, fingerprint: str, at_ms: int, window_ms: int) -> str:
    digest = hashlib.sha256(f"{repo.scope.env}|{fingerprint}|{at_ms // window_ms}".encode()).hexdigest()[:24]
    return f"{repo.scope.tenant_id}.alr.{digest}"
