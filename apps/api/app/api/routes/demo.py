from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import auth
from app.api.deps import NowMs, RepoDep, SettingsDep, require
from app.api.errors import ERROR_RESPONSES, NotFound
from app.api.models import DemoControlsOut, DemoToggleIn
from app.auth import Principal
from app.ids import id_pattern
from app.services import demo

router = APIRouter(prefix="/api/demo", tags=["demo"], responses=ERROR_RESPONSES)

IncidentQuery = Annotated[str | None, Query(pattern=id_pattern("inc"), max_length=128, examples=["nova.inc.101"],
                                            description="Also report the recommendation for this incident")]


def _enabled(settings: SettingsDep) -> bool:
    if not settings.demo_controls_enabled:
        raise NotFound("demo controls are disabled on this deployment", code="demo_controls_disabled")
    return True


Enabled = Annotated[bool, Depends(_enabled)]


@router.get("/controls", response_model=DemoControlsOut)
def get_controls(repo: RepoDep, settings: SettingsDep, now_ms: NowMs,
                 _: Annotated[Principal, Depends(require(auth.READ))],
                 incident_id: IncidentQuery = None) -> DemoControlsOut:
    """Current state of the demo edges. Always 200 so the UI can hide the panel: `enabled` is false when the
    deployment has not turned demo controls on."""
    return demo.state(repo, enabled=settings.demo_controls_enabled, incident_id=incident_id, now_ms=now_ms)


@router.put("/controls/reset", response_model=DemoControlsOut)
def reset_controls(repo: RepoDep, now_ms: NowMs, _on: Enabled,
                   principal: Annotated[Principal, Depends(require(auth.DEMO))],
                   incident_id: IncidentQuery = None) -> DemoControlsOut:
    """Restore both demo edges (the seeded state)."""
    demo.reset(repo, principal, now_ms)
    return demo.state(repo, enabled=True, incident_id=incident_id, now_ms=now_ms)


@router.put("/controls/{toggle_id}", response_model=DemoControlsOut)
def set_control(toggle_id: str, body: DemoToggleIn, repo: RepoDep, now_ms: NowMs, _on: Enabled,
                principal: Annotated[Principal, Depends(require(auth.DEMO))],
                incident_id: IncidentQuery = None) -> DemoControlsOut:
    """Add (`present: true`) or remove (`present: false`) one demo edge. Idempotent."""
    demo.set_edge(repo, toggle_id, body.present, principal, now_ms)
    return demo.state(repo, enabled=True, incident_id=incident_id, now_ms=now_ms)
