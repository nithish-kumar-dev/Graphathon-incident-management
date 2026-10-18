"""Synthetic telemetry: deterministic, windowed, allowlisted, consistent with the NovaCommerce story. Offline."""

import hashlib
import re

from app.agents.contracts import TelemetryContext
from app.seeds.novacommerce import ms
from app.telemetry import synthetic
from app.telemetry.synthetic import collect, is_anomalous

SERVICES = ["nova.svc.checkout", "nova.svc.payment", "nova.svc.inventory", "nova.svc.auth", "nova.svc.ledger"]
W101 = (ms("2026-10-17T13:00:00"), ms("2026-10-17T15:00:00"))
W092 = (ms("2026-08-12T09:00:00"), ms("2026-08-12T10:10:00"))


def by(ctx: TelemetryContext, service: str, metric: str):
    return sorted((o for o in ctx.observations if o.service_id == service and o.metric == metric),
                  key=lambda o: o.observed_at_ms)


def test_deterministic_and_valid():
    a = collect("nova", "prod", SERVICES, *W101)
    b = collect("nova", "prod", list(reversed(SERVICES)), *W101)
    assert a == b and a.model_dump() == TelemetryContext.model_validate(a.model_dump()).model_dump()
    assert 0 < len(a.observations) <= synthetic.MAX_OBSERVATIONS
    assert len({o.id for o in a.observations}) == len(a.observations)
    assert a.sources == sorted(f"synthetic://telemetry/{s.rsplit('.', 1)[-1]}" for s in SERVICES)


def test_id_and_source_ref_format():
    for o in collect("nova", "prod", SERVICES, *W101).observations:
        digest = hashlib.sha256(f"{o.service_id}|{o.metric}|{o.observed_at_ms}".encode()).hexdigest()[:16]
        assert o.id == f"nova.ev.tel.{digest}"
        name = o.service_id.rsplit(".", 1)[-1]
        assert re.fullmatch(rf"synthetic://telemetry/{name}/{o.metric}\?t=\d{{4}}-\d\d-\d\dT\d\d:\d\dZ", o.source_ref)
        assert o.summary.startswith(f"{name} {o.metric} ") and "baseline" in o.summary and len(o.summary) < 120


def test_window_filtering_is_inclusive_and_bounded():
    start, end = ms("2026-10-17T14:00:00"), ms("2026-10-17T14:30:00")
    ctx = collect("nova", "prod", ["nova.svc.payment"], start, end)
    assert ctx.observations and all(start <= o.observed_at_ms <= end for o in ctx.observations)
    assert {o.observed_at_ms for o in ctx.observations} == {start, start + 15 * 60_000, end}
    assert (ctx.window_start_ms, ctx.window_end_ms) == (start, end)
    assert collect("nova", "prod", SERVICES, end, start).observations == []         # inverted window
    assert collect("nova", "prod", SERVICES, ms("2026-01-01T00:00:00"), ms("2026-01-02T00:00:00")).observations == []


def test_cap_keeps_anomalies_first():
    ctx = collect("nova", "prod", SERVICES, W092[0], W101[1])                        # both incidents: 114 points
    assert len(ctx.observations) == synthetic.MAX_OBSERVATIONS
    full = [o for w in (W092, W101) for o in collect("nova", "prod", SERVICES, *w).observations]
    assert len(full) > synthetic.MAX_OBSERVATIONS
    assert {o.id for o in full if is_anomalous(o)} <= {o.id for o in ctx.observations}
    assert [o.observed_at_ms for o in ctx.observations] == sorted(o.observed_at_ms for o in ctx.observations)


def test_tenant_env_and_service_allowlist():
    assert collect("acme", "prod", ["acme.svc.payment"], *W101).observations == []    # decoy: allowlisted, empty
    assert collect("nova", "staging", SERVICES, *W101).observations == []
    assert collect("evil", "prod", SERVICES, *W101).observations == []
    assert collect("acme", "prod", SERVICES, *W101).observations == []                # nova ids under acme: none
    assert collect("nova", "prod", ["nova.svc.unknown"], *W101).observations == []


def test_inc101_pool_spike_after_v24_and_checkout_5xx_after_1400():
    ctx = collect("nova", "prod", SERVICES, *W101)
    pool = by(ctx, "nova.svc.payment", "db_pool_wait_ms")
    deploy = ms("2026-10-17T13:52:00")
    assert all(o.value == 40 and not is_anomalous(o) for o in pool if o.observed_at_ms < deploy)
    assert all(o.value == 2100 and is_anomalous(o) for o in pool if o.observed_at_ms > deploy)
    assert any(o.summary.startswith("payment db_pool_wait_ms 2100 (baseline 40)") for o in pool)
    five = by(ctx, "nova.svc.checkout", "http_5xx_rate")
    assert all(not is_anomalous(o) for o in five if o.observed_at_ms <= ms("2026-10-17T14:00:00"))
    assert all(is_anomalous(o) for o in five if o.observed_at_ms > ms("2026-10-17T14:00:00"))
    for metric in ("p99_latency_ms", "error_rate"):
        assert is_anomalous(by(ctx, "nova.svc.payment", metric)[-1])
    assert is_anomalous(by(ctx, "nova.svc.checkout", "upstream_timeout_count")[-1])


def test_inventory_auth_ledger_stay_normal():
    ctx = collect("nova", "prod", ["nova.svc.inventory", "nova.svc.auth", "nova.svc.ledger"], *W101)
    assert ctx.observations and not any(is_anomalous(o) for o in ctx.observations)
    assert {o.service_id for o in ctx.observations} == {"nova.svc.inventory", "nova.svc.auth", "nova.svc.ledger"}


def test_inc092_spike_and_recovery():
    ctx = collect("nova", "prod", SERVICES, *W092)
    pool = by(ctx, "nova.svc.payment", "db_pool_wait_ms")
    assert not is_anomalous(pool[0])                                                  # 09:00, before v2.3
    assert all(is_anomalous(o) for o in pool if ms("2026-08-12T09:05:00") < o.observed_at_ms
               < ms("2026-08-12T10:00:00"))
    assert all(not is_anomalous(o) for o in pool if o.observed_at_ms >= ms("2026-08-12T10:00:00"))
    five = by(ctx, "nova.svc.checkout", "http_5xx_rate")
    assert max(o.value for o in five) == 14.0 and five[-1].value == 0.3
