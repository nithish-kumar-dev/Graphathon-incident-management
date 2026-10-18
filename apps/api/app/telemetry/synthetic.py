"""Synthetic telemetry: the only permitted source for the live evidence branch (telemetry_context).

- Deterministic, read-only, no network. The dataset is generated from fixed tables in this module.
- Only tenants/envs in ALLOWLIST have data. The decoy tenant `acme` is allowlisted but has no series,
  so it returns an empty context. Anything else returns empty too. Unknown services have no data.
- Observation ids are `<tenant>.ev.tel.<sha256(service_id|metric|ts_ms)[:16]>`, so the same reading
  always gets the same id. The orchestrator persists them as Evidence (kind metric) under that id.
- At most MAX_OBSERVATIONS per call. Anomalous readings are kept first if the cap cuts.

NovaCommerce story (consistent with app/seeds/novacommerce.py):
- INC-101 (2026-10-17, 13:00-15:00Z, every 15 min): payment DB pool wait jumps from ~40 ms to ~2100 ms
  after v2.4 at 13:52Z, with payment p99 and error rate up; checkout 5xx and upstream timeouts spike
  after 14:00Z. Inventory, auth and ledger stay normal (useful contradicting / exclusion evidence).
- INC-092 (2026-08-12, 09:00-10:10Z, every 10 min): payment pool spike after v2.3 at 09:05Z, checkout
  5xx at 14% from 09:20Z, recovery from 10:00Z after the rollback.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.agents.contracts import TelemetryContext, TelemetryObservation

MAX_OBSERVATIONS = 100
ANOMALY_RATIO = 3.0                    # value >= 3x baseline (or <= baseline/3) counts as anomalous
ALLOWLIST: frozenset[tuple[str, str]] = frozenset({("nova", "prod"), ("acme", "prod")})


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1000)


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%MZ")


@dataclass(frozen=True)
class _Series:
    service_id: str
    metric: str
    unit: str
    baseline: float
    value_at: Callable[[int], float]        # ts_ms -> value


def _step(baseline: float, after_ms: int, value: float, until_ms: int | None = None) -> Callable[[int], float]:
    """Baseline, then `value` from after_ms (exclusive) up to until_ms (exclusive), then baseline again."""
    def f(ts: int) -> float:
        return value if ts > after_ms and (until_ms is None or ts < until_ms) else baseline
    return f


def _flat(baseline: float) -> Callable[[int], float]:
    return lambda ts: baseline


def _grid(start_iso: str, end_iso: str, step_min: int) -> list[int]:
    start, end = _ms(start_iso), _ms(end_iso)
    return list(range(start, end + 1, step_min * 60_000))


# ------------------------------------------------------------------------------------- dataset
_DEP_V24 = _ms("2026-10-17T13:52:00")
_CHECKOUT_101 = _ms("2026-10-17T14:00:00")
_DEP_V23 = _ms("2026-08-12T09:05:00")
_CHECKOUT_092 = _ms("2026-08-12T09:15:00")
_RECOVERY_092 = _ms("2026-08-12T10:00:00")

_INC101_SERIES = [
    _Series("nova.svc.payment", "db_pool_wait_ms", "ms", 40, _step(40, _DEP_V24, 2100)),
    _Series("nova.svc.payment", "p99_latency_ms", "ms", 320, _step(320, _DEP_V24, 2800)),
    _Series("nova.svc.payment", "error_rate", "%", 0.2, _step(0.2, _DEP_V24, 4.5)),
    _Series("nova.svc.checkout", "http_5xx_rate", "%", 0.3, _step(0.3, _CHECKOUT_101, 11.0)),
    _Series("nova.svc.checkout", "upstream_timeout_count", "count/min", 2, _step(2, _CHECKOUT_101, 480)),
    _Series("nova.svc.inventory", "p99_latency_ms", "ms", 180, _flat(180)),
    _Series("nova.svc.inventory", "error_rate", "%", 0.1, _flat(0.1)),
    _Series("nova.svc.auth", "p99_latency_ms", "ms", 90, _flat(90)),
    _Series("nova.svc.auth", "error_rate", "%", 0.05, _flat(0.05)),
    _Series("nova.svc.ledger", "error_rate", "%", 0.1, _flat(0.1)),
]
_INC092_SERIES = [
    _Series("nova.svc.payment", "db_pool_wait_ms", "ms", 40, _step(40, _DEP_V23, 1900, _RECOVERY_092)),
    _Series("nova.svc.payment", "p99_latency_ms", "ms", 320, _step(320, _DEP_V23, 2500, _RECOVERY_092)),
    _Series("nova.svc.checkout", "http_5xx_rate", "%", 0.3, _step(0.3, _CHECKOUT_092, 14.0, _RECOVERY_092)),
]

# (tenant, env) -> [(ts_ms, series)]
_DATA: dict[tuple[str, str], list[tuple[int, _Series]]] = {
    ("nova", "prod"): sorted(
        [(ts, s) for s in _INC101_SERIES for ts in _grid("2026-10-17T13:00:00", "2026-10-17T15:00:00", 15)]
        + [(ts, s) for s in _INC092_SERIES for ts in _grid("2026-08-12T09:00:00", "2026-08-12T10:10:00", 10)],
        key=lambda x: (x[0], x[1].service_id, x[1].metric)),
    ("acme", "prod"): [],               # decoy tenant: allowlisted, no data
}


# ------------------------------------------------------------------------------------- public API
def observation_id(tenant_id: str, service_id: str, metric: str, ts_ms: int) -> str:
    digest = hashlib.sha256(f"{service_id}|{metric}|{ts_ms}".encode()).hexdigest()[:16]
    return f"{tenant_id}.ev.tel.{digest}"


def is_anomalous(obs: TelemetryObservation) -> bool:
    """A reading at least ANOMALY_RATIO times above (or below) its baseline."""
    if obs.baseline is None or obs.baseline <= 0:
        return False
    return obs.value >= obs.baseline * ANOMALY_RATIO or obs.value <= obs.baseline / ANOMALY_RATIO


def collect(tenant_id: str, env: str, service_ids: Iterable[str], window_start_ms: int,
            window_end_ms: int) -> TelemetryContext:
    """Readings for the given services inside [window_start_ms, window_end_ms] (inclusive)."""
    wanted = set(service_ids)
    rows = [] if (tenant_id, env) not in ALLOWLIST or window_end_ms < window_start_ms else [
        (ts, s) for ts, s in _DATA.get((tenant_id, env), [])
        if s.service_id in wanted and window_start_ms <= ts <= window_end_ms]
    obs = [_observation(tenant_id, ts, s) for ts, s in rows]
    if len(obs) > MAX_OBSERVATIONS:     # keep anomalies first, then the latest normal readings
        keep = sorted(obs, key=lambda o: (not is_anomalous(o), -o.observed_at_ms, o.id))[:MAX_OBSERVATIONS]
        obs = sorted(keep, key=lambda o: (o.observed_at_ms, o.service_id, o.metric))
    sources = sorted({f"synthetic://telemetry/{_name(o.service_id)}" for o in obs})
    return TelemetryContext(observations=obs, window_start_ms=window_start_ms, window_end_ms=window_end_ms,
                            sources=sources)


def _name(service_id: str) -> str:
    return service_id.rsplit(".", 1)[-1]


def _fmt(v: float) -> str:
    return f"{v:g}"


def _observation(tenant_id: str, ts: int, s: _Series) -> TelemetryObservation:
    value = float(s.value_at(ts))
    name = _name(s.service_id)
    unit = "" if s.unit in {"ms", "count/min"} else s.unit
    return TelemetryObservation(
        id=observation_id(tenant_id, s.service_id, s.metric, ts), service_id=s.service_id, metric=s.metric,
        value=value, unit=s.unit, baseline=float(s.baseline), observed_at_ms=ts,
        source_ref=f"synthetic://telemetry/{name}/{s.metric}?t={_iso(ts)}",
        summary=f"{name} {s.metric} {_fmt(value)}{unit} (baseline {_fmt(s.baseline)}{unit}) at {_iso(ts)}")
