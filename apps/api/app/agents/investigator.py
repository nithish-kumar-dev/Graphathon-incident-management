"""Investigators: InvestigatorInput -> InvestigatorOutput. Their output is always checked by safety_gate.

- StubInvestigator ("stub-v1"): deterministic, offline. Builds hypotheses from explanation paths and
  telemetry, and proposes actions only from the runbooks on each path.
- OllamaInvestigator ("ollama:<model>"): a local LLM through Ollama /api/chat with the output JSON schema
  as `format`. Errors map to InvestigatorError(timeout | unavailable | malformed). With fallback on, the
  stub answers instead and the result is labelled "stub-fallback(ollama <kind>)", so it is never silent.

Neither investigator ever claims `confirmed`: only humans confirm.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.agents import prompts
from app.agents.contracts import (
    ALLOWED_ACTION_TYPES,
    Hypothesis,
    InvestigatorError,
    InvestigatorInput,
    InvestigatorOutput,
    InvestigatorResult,
    ProposedAction,
    TelemetryObservation,
)
from app.telemetry.synthetic import is_anomalous

DEFAULT_TIMEOUT_S = 90.0
_ID_TOKEN = re.compile(r"[a-z][a-z0-9_]{1,31}\.[a-z]+\.[A-Za-z0-9][A-Za-z0-9._:-]*[A-Za-z0-9]")
_VERB_FORMS = {"rollback": ("rollback", "roll back", "rolling back", "rolled back"),
               "restart": ("restart",), "scale": ("scale", "scaling")}


class Investigator(Protocol):
    name: str

    def run(self, inp: InvestigatorInput, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> InvestigatorResult: ...


# ============================================================================================ stub
class StubInvestigator:
    name = "stub-v1"

    def run(self, inp: InvestigatorInput, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> InvestigatorResult:
        t0 = time.perf_counter()
        out = self.investigate(inp)
        return InvestigatorResult(output=out, investigator=self.name, latency_ms=_elapsed(t0))

    def investigate(self, inp: InvestigatorInput) -> InvestigatorOutput:
        fb = _Feedback(inp.feedback)
        gc, mc = inp.graph_context, inp.memory_context
        tel = list(inp.telemetry_context.observations) if inp.telemetry_context else []
        affected = set(gc.incident.affected_service_ids) if gc else set()
        names = _service_names(inp)
        supports = [m for m in (mc.items if mc else []) if m.precedent == "supports"]
        warns = [m for m in (mc.items if mc else []) if m.precedent == "warns_against"]

        hyps: list[Hypothesis] = []
        actions: list[ProposedAction] = []
        targets: set[str] = set()

        # 1. one correlated hypothesis per explanation path
        for p in gc.explanation_paths if gc else []:
            target, dep = p.target_service_id, p.deployment
            targets.add(target)
            relevant = {target} | affected | _dependents(inp, target)
            dep_ms = int(dep.deployed_at.timestamp() * 1000)
            after = [o for o in tel if o.service_id in relevant and o.observed_at_ms >= dep_ms]
            latest = _latest_per_key(after)
            support = [e.id for e in p.evidence]
            support += [e.id for e in gc.evidence if set(e.observed_on_service_ids) & ({target} | affected)]
            support += [o.id for o in _latest_per_key([o for o in after if is_anomalous(o)]).values()]
            contra = [o.id for o in latest.values() if not is_anomalous(o)]
            support, contra = fb.keep(_dedupe(support))[:20], fb.keep(_dedupe(contra))[:20]
            if not support:
                continue
            tname = names.get(target, _tail(target))
            via = ", ".join(sorted(names.get(s, _tail(s)) for s in affected)) or "the affected services"
            statement = (f"Deployment {dep.version} of {tname} ({dep.id}, deployed {_hhmm(dep.deployed_at)}) "
                         f"correlates with {inp.incident_key} ({inp.incident_title}); {tname} is on the "
                         f"DEPENDS_ON path from {via}.")
            unc = (f"Correlation from timing and the dependency path, not a confirmed cause: {len(support)} "
                   f"supporting and {len(contra)} contradicting item(s). A human must confirm.")
            prec = [m for m in supports if target in m.shared_service_ids or m.applicability == "same_incident"
                    or tname.lower() in m.summary.lower()]
            if prec:
                unc += f" Precedent, not proof: {prec[0].id} ({prec[0].about_incident_key or 'past incident'})."
            if not tel:
                unc += " No telemetry was available to check this."
            conf = max(0.05, min(0.8, 0.25 + 0.08 * len(support)) - 0.12 * len(contra))
            hyps.append(Hypothesis(claim_type="correlated", statement=_cut(statement, 600),
                                   supporting_evidence_ids=support, contradicting_evidence_ids=contra,
                                   confidence=round(conf, 2), uncertainty=_cut(unc, 400)))

            # actions: path runbooks only, allowed types only, never something a failed memory warns against
            path_ev = fb.keep([e.id for e in p.evidence])[:20]
            for rb in p.runbooks:
                for at in rb.allowed_action_types:
                    if at not in inp.allowed_action_types or at not in ALLOWED_ACTION_TYPES or not path_ev:
                        continue
                    if fb.names_action(at, target) or _warned(at, tname, warns):
                        continue
                    if any((a.action_type, a.target_service_id, a.deployment_id) == (at, target, dep.id)
                           for a in actions):
                        continue
                    actions.append(ProposedAction(
                        action_type=at, target_service_id=target, deployment_id=dep.id, runbook_id=rb.id,
                        evidence_ids=path_ev, risk="medium",
                        rationale=_cut(f"Recommend {at.replace('_', ' ')} of {tname} {dep.version} per runbook "
                                       f"{rb.id} ({rb.title}); pending human approval under "
                                       f"{p.approval_policy.replace('_', ' ')}.", 600)))

        # 2. one observed hypothesis per anomalous telemetry signal (service, metric)
        by_key: dict[tuple[str, str], list[TelemetryObservation]] = {}
        for o in sorted(tel, key=lambda o: o.observed_at_ms):
            if is_anomalous(o):
                by_key.setdefault((o.service_id, o.metric), []).append(o)
        for (_sid, _metric), obs in sorted(by_key.items()):
            ids = fb.keep([o.id for o in obs])[-20:]
            if not ids:
                continue
            last = next(o for o in reversed(obs) if o.id in ids)
            hyps.append(Hypothesis(
                claim_type="observed", supporting_evidence_ids=ids, confidence=0.85,
                statement=_cut(f"{last.summary}; anomalous in {len(obs)} reading(s) from "
                               f"{_hhmm_ms(obs[0].observed_at_ms)}.", 600),
                uncertainty="Synthetic telemetry reading. It shows a symptom, not its cause."))

        # 3. normal telemetry on other services narrows the alternatives (e.g. a recent unrelated deploy)
        others = {o.service_id for o in tel} - targets - affected
        latest_other = _latest_per_key([o for o in tel if o.service_id in others])
        normal_svcs = sorted({o.service_id for o in latest_other.values()}
                             - {o.service_id for o in latest_other.values() if is_anomalous(o)})
        if normal_svcs:
            ids = fb.keep([o.id for o in latest_other.values() if o.service_id in normal_svcs])[:20]
            alt = [d for d in (gc.recent_deployments if gc else []) if d.service_id in normal_svcs]
            stmt = (f"Telemetry for {', '.join(names.get(s, _tail(s)) for s in normal_svcs)} stayed at baseline "
                    "in the window.")
            if alt:
                stmt += " Recent deployment(s) " + ", ".join(f"{d.id} ({d.version})" for d in alt) + \
                        " show no matching symptoms and no incident evidence refers to them."
            if ids:
                hyps.append(Hypothesis(claim_type="observed", statement=_cut(stmt, 600), supporting_evidence_ids=ids,
                                       confidence=0.75, uncertainty="Normal readings make these services less "
                                       "likely origins; they do not rule them out."))

        hyps = [h for h in hyps if not fb.names_hypothesis(h.statement)][:10]
        actions = actions[:3]

        # summary and overall uncertainty
        if not hyps:
            summary = f"No evidence available for {inp.incident_key}; no hypotheses or actions proposed."
        else:
            corr = [h for h in hyps if h.claim_type == "correlated"]
            summary = (f"{inp.incident_key}: {len(corr)} correlated explanation(s), "
                       f"{sum(1 for h in hyps if h.claim_type == 'observed')} observation(s).")
            if corr:
                summary += f" Leading correlation: {corr[0].statement}"
            if actions:
                summary += " Recommendation only, pending human approval: " + "; ".join(
                    f"{a.action_type} on {a.target_service_id}" for a in actions) + "."
        notes = [f"{b} {s}" for b, s in sorted(inp.branch_status.items()) if s in {"failed", "skipped"}]
        overall = "Nothing here is confirmed; a human must confirm any cause."
        if notes:
            overall += " Branches not available: " + ", ".join(notes) + "."
        for m in supports[:2]:
            overall += f" Precedent (not proof): {m.id}: {_cut(m.summary, 120)}"
        for m in warns[:2]:
            overall += f" Do not repeat: {_cut(m.summary, 120)} ({m.id})."
        return InvestigatorOutput(summary=_cut(summary, 1000), hypotheses=hyps, proposed_actions=actions,
                                  overall_uncertainty=_cut(overall, 600))


class _Feedback:
    """Gate feedback from the previous revision. Items it names are dropped."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.ids = {m.group(0) for line in lines for m in _ID_TOKEN.finditer(line)}

    def keep(self, ids: list[str]) -> list[str]:
        return [i for i in ids if i not in self.ids]

    def names_action(self, action_type: str, target: str) -> bool:
        return any(f"{action_type} on {target}" in line for line in self.lines)

    def names_hypothesis(self, statement: str) -> bool:
        return any(f"'{statement[:60]}" in line for line in self.lines)


def _warned(action_type: str, target_name: str, warns: list) -> bool:
    verb = action_type.split("_")[0]
    forms = _VERB_FORMS.get(verb, (verb,))
    return any(any(f in m.summary.lower() for f in forms) and target_name.lower() in m.summary.lower()
               for m in warns)


def _service_names(inp: InvestigatorInput) -> dict[str, str]:
    names: dict[str, str] = {}
    if inp.graph_context:
        for deps in inp.graph_context.dependencies.values():
            for d in deps:
                if d.service.name:
                    names[d.service.id] = d.service.name
    return names


def _dependents(inp: InvestigatorInput, target: str) -> set[str]:
    """Services that call `target` directly, from the DEPENDS_ON paths in the graph context."""
    out: set[str] = set()
    for deps in (inp.graph_context.dependencies.values() if inp.graph_context else []):
        for d in deps:
            for a, b in zip(d.path, d.path[1:], strict=False):
                if b == target:
                    out.add(a)
    return out


def _latest_per_key(obs: list[TelemetryObservation]) -> dict[tuple[str, str], TelemetryObservation]:
    out: dict[tuple[str, str], TelemetryObservation] = {}
    for o in sorted(obs, key=lambda o: (o.observed_at_ms, o.id)):
        out[(o.service_id, o.metric)] = o
    return dict(sorted(out.items()))


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _tail(service_id: str) -> str:
    return service_id.rsplit(".", 1)[-1]


def _hhmm(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")


def _hhmm_ms(ms: int) -> str:
    return _hhmm(datetime.fromtimestamp(ms / 1000, tz=UTC))


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _elapsed(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


# ============================================================================================ ollama
def output_format_schema() -> dict:
    """The JSON schema sent to Ollama. Stricter than the contract: a 7B model otherwise picks `null` for
    deployment_id, which the gate rejects for a rollback. Validation of the reply still uses the contract."""
    schema = InvestigatorOutput.model_json_schema()
    action = schema["$defs"]["ProposedAction"]
    action["properties"]["deployment_id"] = next(
        b for b in action["properties"]["deployment_id"]["anyOf"] if b.get("type") == "string")
    action["required"] = sorted({*action.get("required", []), "deployment_id"})
    return schema


class OllamaInvestigator:
    """Local LLM via Ollama /api/chat with `format` = the InvestigatorOutput JSON schema, temperature 0."""

    def __init__(self, base_url: str, model: str, *, fallback_to_stub: bool = True, num_ctx: int = 8192,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not model or not model.strip():
            raise ValueError("OllamaInvestigator needs a model name (OLLAMA_MODEL)")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.fallback_to_stub = fallback_to_stub
        self.num_ctx = num_ctx
        self._transport = transport          # tests inject httpx.MockTransport; never real network in tests
        self.name = f"ollama:{self.model}"
        self.stub = StubInvestigator()

    def run(self, inp: InvestigatorInput, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> InvestigatorResult:
        t0 = time.perf_counter()
        try:
            out = self.investigate(inp, timeout_s=timeout_s)
            return InvestigatorResult(output=out, investigator=self.name, latency_ms=_elapsed(t0))
        except InvestigatorError as exc:
            if not self.fallback_to_stub:
                raise
            out = self.stub.investigate(inp)
            return InvestigatorResult(output=out, investigator=f"stub-fallback(ollama {exc.kind})",
                                      latency_ms=_elapsed(t0))

    def investigate(self, inp: InvestigatorInput, *, timeout_s: float) -> InvestigatorOutput:
        body = {"model": self.model, "messages": prompts.messages(inp), "stream": False,
                "format": output_format_schema(),
                "options": {"temperature": 0, "num_ctx": self.num_ctx}}
        try:
            with httpx.Client(transport=self._transport, timeout=timeout_s) as client:
                r = client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise InvestigatorError("timeout", f"ollama did not answer within {timeout_s:g}s") from exc
        except httpx.HTTPError as exc:
            raise InvestigatorError("unavailable", f"ollama unreachable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            raise InvestigatorError("unavailable", f"ollama returned HTTP {r.status_code}")
        try:
            content = r.json()["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content is not a string")
            return InvestigatorOutput.model_validate_json(content)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise InvestigatorError("malformed", f"ollama output failed validation ({type(exc).__name__})") from exc


# ============================================================================================ factory
def from_settings(settings) -> StubInvestigator | OllamaInvestigator:
    if settings.llm_provider == "stub":
        return StubInvestigator()
    if settings.llm_provider == "ollama":
        return OllamaInvestigator(settings.ollama_base_url, settings.ollama_model,
                                  fallback_to_stub=settings.llm_fallback_to_stub)
    raise ValueError(f"unknown llm_provider {settings.llm_provider!r}")


__all__ = ["DEFAULT_TIMEOUT_S", "Investigator", "OllamaInvestigator", "StubInvestigator", "from_settings"]
