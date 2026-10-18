"""Demo controls: flip two graph relationships so the recommendation visibly changes, without manual database edits.

Only plain edge writes (`merge_edge` / `delete_edge`) are used. Nodes are never touched and no constraint or index is
dropped, so this is safe on the append-only dev server. The two edges are exactly the ones the golden path depends on:

* `checkout -[DEPENDS_ON]-> payment`: without it the payment deployment is no longer reachable from the affected
  checkout service, so the incident has no rollback path.
* `rollback_v2 -[GOVERNS]-> payment`: without it no Decision is in force for payment, so a rollback would have to
  escalate instead of going to the payment approver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.api import models as m
from app.api.errors import NotFound
from app.auth import Principal
from app.graph.repository import EndpointNotFound, GraphRepository
from app.services import incidents

log = logging.getLogger("app.demo")


@dataclass(frozen=True)
class Toggle:
    id: str
    label: str
    description: str
    src: tuple[str, str]        # (label, id suffix after the tenant prefix, e.g. "svc.checkout")
    rel: str
    dst: tuple[str, str]

    def ids(self, tenant: str) -> tuple[str, str]:
        return f"{tenant}.{self.src[1]}", f"{tenant}.{self.dst[1]}"


TOGGLES: tuple[Toggle, ...] = (
    Toggle("checkout_depends_on_payment", "Checkout depends on Payment",
           "With the link removed, the payment deployment is not reachable from the affected checkout service, "
           "so the incident has no rollback path.",
           ("Service", "svc.checkout"), "DEPENDS_ON", ("Service", "svc.payment")),
    Toggle("rollback_policy_governs_payment", "Rollback policy v2 governs Payment",
           "With the link removed, no Decision is in force for payment, so a rollback would have to escalate "
           "instead of going to the payment approver.",
           ("Decision", "dec.payment.rollback_v2"), "GOVERNS", ("Service", "svc.payment")),
)
BY_ID = {t.id: t for t in TOGGLES}


def _present(repo: GraphRepository, t: Toggle) -> bool:
    src, dst = t.ids(repo.scope.tenant_id)
    # neighbors() reads the anchor's outgoing edges of one allowlisted relationship, scoped to the tenant and env.
    return any(n["id"] == dst for n in repo.neighbors(t.src[0], src, t.rel, t.dst[0], outgoing=True))


def _out(repo: GraphRepository, t: Toggle) -> m.DemoToggleOut:
    src, dst = t.ids(repo.scope.tenant_id)
    return m.DemoToggleOut(id=t.id, label=t.label, description=t.description,
                           edge=f"{src} -[{t.rel}]-> {dst}", present=_present(repo, t))


def effect(repo: GraphRepository, incident_id: str, now_ms: int) -> m.RecommendationEffect:
    """What the recommendation looks like right now, from the same explanation paths the incident page shows."""
    incidents.require_incident(repo, incident_id)
    paths = incidents.explanation_paths(repo, incident_id, {}, now_ms)
    if not paths:
        return m.RecommendationEffect(
            incident_id=incident_id, rollback_paths=0, approval_policy="no_rollback_path",
            summary="No rollback is recommended: no deployment referenced by the incident evidence is reachable "
                    "through the dependency graph.")
    covered = all(p.governing_decisions for p in paths)
    top = paths[0]
    roles = sorted({d.required_approver_role for p in paths for d in p.governing_decisions if d.required_approver_role})
    if covered:
        summary = (f"Roll back deployment {top.deployment.version} of {top.target_service_id}"
                   f"{'; approver: ' + ', '.join(roles) if roles else ''}.")
    else:
        summary = (f"Deployment {top.deployment.version} of {top.target_service_id} is implicated, but no Decision is in "
                   "force for it: a rollback must escalate instead of being approved.")
    return m.RecommendationEffect(
        incident_id=incident_id, rollback_paths=len(paths), target_service_ids=sorted({p.target_service_id for p in paths}),
        deployment_ids=sorted({p.deployment.id for p in paths}), approval_policy="policy_in_force" if covered
        else "no_active_policy_escalate", summary=summary)


def state(repo: GraphRepository, *, enabled: bool, incident_id: str | None, now_ms: int) -> m.DemoControlsOut:
    if not enabled:
        return m.DemoControlsOut(enabled=False)
    return m.DemoControlsOut(enabled=True, toggles=[_out(repo, t) for t in TOGGLES],
                             effect=effect(repo, incident_id, now_ms) if incident_id else None)


def set_edge(repo: GraphRepository, toggle_id: str, present: bool, principal: Principal, now_ms: int) -> None:
    """Idempotent: merge when `present`, delete otherwise. Raises NotFound if an endpoint is missing from the graph."""
    t = BY_ID.get(toggle_id)
    if t is None:
        raise NotFound("unknown demo toggle", code="unknown_toggle")
    src, dst = t.ids(repo.scope.tenant_id)
    if present:
        try:
            repo.merge_edge(t.src[0], src, t.rel, t.dst[0], dst, at_ms=now_ms)
        except EndpointNotFound as exc:                   # the seed is not loaded in this graph
            raise NotFound("demo data is not seeded in this graph", code="demo_data_missing") from exc
    else:
        repo.delete_edge(t.src[0], src, t.rel, t.dst[0], dst)
    log.info("demo toggle", extra={"toggle": t.id, "present": present, "user": principal.user_id})


def reset(repo: GraphRepository, principal: Principal, now_ms: int) -> None:
    for t in TOGGLES:
        set_edge(repo, t.id, True, principal, now_ms)
