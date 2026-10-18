"""GET /api/services/{id}/context: bounded neighbourhood of one service."""

from __future__ import annotations

from app.api import models as m
from app.api.errors import NotFound
from app.graph.repository import GraphRepository


def in_effect(decision: dict, now_ms: int) -> bool:
    end = decision.get("effective_to_ms")
    return (decision.get("status") == "active" and decision["effective_from_ms"] <= now_ms
            and (end is None or end > now_ms))


def _deps(rows: list[dict]) -> list[m.DependencyOut]:
    best: dict[str, m.DependencyOut] = {}
    for r in rows:  # rows arrive ordered by depth, so the first path per service is a shortest one
        svc = r["service"]
        best.setdefault(svc["id"], m.DependencyOut(
            service=m.ServiceRef(id=svc["id"], name=svc.get("name"), tier=svc.get("tier")),
            depth=r["depth"], path=r["path"]))
    return list(best.values())


def get_context(repo: GraphRepository, service_id: str, *, depth: int, deployment_days: int, limit: int,
                now_ms: int) -> m.ServiceContext:
    svc = repo.get_node("Service", service_id)
    if svc is None:
        raise NotFound(f"service {service_id} not found")
    since = now_ms - deployment_days * 86_400_000
    deployments = [d for d in repo.neighbors("Service", service_id, "DEPLOYED_TO", "Deployment", outgoing=False,
                                             order_by="deployed_at_ms", descending=True, limit=limit)
                   if since <= d["deployed_at_ms"] <= now_ms]
    return m.ServiceContext(
        service=m.ServiceRef(id=svc["id"], name=svc.get("name"), tier=svc.get("tier")),
        owners=[m.TeamOut(id=t["team_id"], name=t["team_name"],
                          members=[m.ResponderRef(id=r["id"], handle=r["handle"], roles=r.get("roles") or [])
                                   for r in sorted(t["members"], key=lambda x: x["id"])])
                for t in repo.service_owners(service_id)],
        dependencies=_deps(repo.service_neighbourhood(service_id, upstream=False, depth=depth, limit=limit)),
        dependents=_deps(repo.service_neighbourhood(service_id, upstream=True, depth=depth, limit=limit)),
        active_decisions=[
            m.DecisionOut(id=p["id"], title=p["title"], statement=p["statement"], status=p["status"],
                          effective_from=m.to_dt(p["effective_from_ms"]), effective_to=m.to_dt(p.get("effective_to_ms")),
                          required_approver_role=p.get("required_approver_role"),
                          documented_in=[m.DocumentRef(**doc) for doc in d["documents"]],
                          supersedes=sorted(d["supersedes"]))
            for d in repo.service_decisions(service_id) if in_effect(p := d["decision"], now_ms)
        ],
        runbooks=[m.RunbookRef(id=rb["id"], title=rb["title"], version=rb["version"], uri=rb.get("uri"),
                               allowed_action_types=rb.get("allowed_action_types") or [])
                  for rb in repo.neighbors("Service", service_id, "APPLIES_TO", "Runbook", outgoing=False, limit=limit)],
        recent_deployments=[m.DeploymentRef(id=d["id"], version=d["version"], deployed_at=m.to_dt(d["deployed_at_ms"]),
                                            status=d.get("status"), source_ref=d.get("source_ref")) for d in deployments],
        depth=depth,
        as_of=m.to_dt(now_ms),
    )
