"""Safety gate: checks investigator output against the input it was given and the graph, then decides.

`evaluate()` only reads. `repo` must be a tenant-scoped (ideally read-only) GraphRepository for the
investigation's tenant/env; only get_node / get_nodes / neighbors are used.

Violation details name the offending item and ids (and only those), so they work as revision feedback:
    hypotheses[i] '<statement prefix>': ...
    proposed_actions[j] (<action_type> on <target>): ...
"""

from __future__ import annotations

from app.agents.contracts import (
    ALLOWED_ACTION_TYPES,
    GateDecision,
    GateResult,
    Hypothesis,
    InvestigatorInput,
    InvestigatorOutput,
    ProposedAction,
    Violation,
)
from app.graph import schema
from app.graph.repository import GraphRepository

ALLOWED_ENVS = frozenset({"prod", "staging", "dev"})
NEEDS_DEPLOYMENT = frozenset({"rollback_deployment_simulated"})     # a rollback must name what it rolls back


def evaluate(output: InvestigatorOutput, inp: InvestigatorInput, *, repo: GraphRepository, revision: int,
             max_revisions: int) -> GateResult:
    if repo.scope.tenant_id != inp.tenant_id:
        raise ValueError("safety gate repository is scoped to a different tenant than the investigation")
    if inp.env in ALLOWED_ENVS and repo.scope.env != inp.env:
        raise ValueError("safety gate repository is scoped to a different env than the investigation")
    chk = _Checker(inp, repo, output)

    hyp_violations = [chk.hypothesis(i, h) for i, h in enumerate(output.hypotheses)]
    act_violations = [chk.action(j, a) for j, a in enumerate(output.proposed_actions)]
    violations = [v for vs in hyp_violations + act_violations for v in vs]
    hyps = [h for h, vs in zip(output.hypotheses, hyp_violations, strict=True) if not vs]
    actions = [a for a, vs in zip(output.proposed_actions, act_violations, strict=True) if not vs]

    decision = decide(violations, valid_hypotheses=len(hyps), revision=revision, max_revisions=max_revisions)
    if decision == "inconclusive" and not violations:
        violations = [Violation(code="inconclusive", target="hypotheses",
                                detail="no evidence-backed hypothesis; nothing to recommend")]
    if decision in {"recommendation_only", "escalate", "inconclusive"}:
        actions = []
    if decision == "inconclusive":
        hyps = []
    return GateResult(decision=decision, hypotheses=hyps, proposed_actions=actions, violations=violations)


def decide(violations: list[Violation], *, valid_hypotheses: int, revision: int,
           max_revisions: int) -> GateDecision:
    """The decision table (docs/investigator.md)."""
    if not violations:
        return "accept" if valid_hypotheses else "inconclusive"
    if revision < max_revisions:
        return "revise"
    if any(v.target.startswith("proposed_actions") for v in violations):
        return "escalate"
    return "recommendation_only" if valid_hypotheses else "inconclusive"


class _Checker:
    def __init__(self, inp: InvestigatorInput, repo: GraphRepository, output: InvestigatorOutput) -> None:
        self.inp, self.repo = inp, repo
        self.prefix = f"{inp.tenant_id}."
        self.known = inp.known_evidence_ids()
        self.telemetry = {o.id for o in inp.telemetry_context.observations} if inp.telemetry_context else set()
        gc = inp.graph_context
        self.scope = (set(gc.incident.affected_service_ids) | {p.target_service_id for p in gc.explanation_paths}
                      if gc else set())

        cited = {i for h in output.hypotheses for i in h.supporting_evidence_ids + h.contradicting_evidence_ids}
        cited |= {i for a in output.proposed_actions for i in a.evidence_ids}
        lookup = [i for i in cited if i in self.known and i not in self.telemetry and self._own(i)]
        self.graph_evidence = set(repo.get_nodes("Evidence", lookup))
        self.failed = self._failed_actions()
        self._cache: dict[tuple, object] = {}

    # ---------------------------------------------------------------------------------- items
    def hypothesis(self, i: int, h: Hypothesis) -> list[Violation]:
        where = f"hypotheses[{i}]"
        label = f"{where} '{h.statement[:60]}'"
        out = []
        if h.claim_type == "confirmed":
            out.append(_v("confirmed_claim_not_allowed", where,
                          f"{label}: claim_type confirmed is reserved for humans; use correlated or hypothesis"))
        if not h.supporting_evidence_ids:
            out.append(_v("no_evidence", where, f"{label}: no supporting evidence id"))
        bad = self._bad_evidence(h.supporting_evidence_ids + h.contradicting_evidence_ids)
        if bad:
            out.append(_v("unknown_evidence", where, f"{where}: cites unknown evidence id(s) {', '.join(bad)}"))
        return out

    def action(self, j: int, a: ProposedAction) -> list[Violation]:
        where = f"proposed_actions[{j}]"
        label = f"{where} ({a.action_type} on {a.target_service_id})"
        out = []

        if a.action_type not in ALLOWED_ACTION_TYPES or a.action_type not in self.inp.allowed_action_types:
            out.append(_v("action_not_allowed", where, f"{label}: action type is not allowed"))
        if self.inp.env not in ALLOWED_ENVS:
            out.append(_v("env_not_allowed", where, f"{label}: env {self.inp.env!r} is not allowed"))

        if a.action_type in NEEDS_DEPLOYMENT and not a.deployment_id:
            out.append(_v("invalid_arguments", where, f"{label}: {a.action_type} needs deployment_id (the "
                          "explanation-path deployment)"))
        foreign = [x for x in [a.target_service_id, a.runbook_id, a.deployment_id, *a.evidence_ids]
                   if x and not self._own(x)]
        if foreign:
            out.append(_v("invalid_arguments", where,
                          f"{label}: ids outside tenant {self.inp.tenant_id}: {', '.join(foreign)}"))

        target_ok = False
        if self._own(a.target_service_id):
            if self._node("Service", a.target_service_id) is None:
                out.append(_v("unknown_service", where, f"{label}: service {a.target_service_id} does not exist"))
            else:
                target_ok = True
                if a.target_service_id not in self.scope:
                    out.append(_v("service_out_of_scope", where, f"{label}: {a.target_service_id} is neither an "
                                  "affected service nor an explanation-path target"))

        if self._own(a.runbook_id):
            rb = self._node("Runbook", a.runbook_id)
            if rb is None:
                out.append(_v("unknown_runbook", where, f"{label}: runbook {a.runbook_id} does not exist"))
            elif target_ok and (a.runbook_id not in self._linked(a.target_service_id, "APPLIES_TO", "Runbook")
                                or a.action_type not in (rb.get("allowed_action_types") or [])):
                out.append(_v("runbook_not_applicable", where, f"{label}: runbook {a.runbook_id} does not apply to "
                              f"{a.target_service_id} or does not allow {a.action_type}"))

        if a.deployment_id and self._own(a.deployment_id):
            if self._node("Deployment", a.deployment_id) is None:
                out.append(_v("unknown_deployment", where, f"{label}: deployment {a.deployment_id} does not exist"))
            elif target_ok and a.deployment_id not in self._linked(a.target_service_id, "DEPLOYED_TO", "Deployment"):
                out.append(_v("deployment_not_on_target", where,
                              f"{label}: deployment {a.deployment_id} is not deployed to {a.target_service_id}"))

        bad = self._bad_evidence(a.evidence_ids)
        if bad:
            out.append(_v("unknown_evidence", where, f"{label}: cites unknown evidence id(s) {', '.join(bad)}"))

        memory = self.failed.get((a.action_type, a.target_service_id))
        if memory:
            out.append(_v("repeats_failed_action", where,
                          f"{label}: repeats an action that verified memory {memory} records as failed"))
        return out

    # -------------------------------------------------------------------------------- lookups
    def _own(self, node_id: str) -> bool:
        return node_id.startswith(self.prefix) and bool(schema.ID_PATTERN.match(node_id))

    def _bad_evidence(self, ids: list[str]) -> list[str]:
        bad = [i for i in dict.fromkeys(ids)
               if i not in self.known or (i not in self.telemetry and i not in self.graph_evidence)]
        return bad[:8]

    def _node(self, label: str, node_id: str) -> dict | None:
        key = ("node", label, node_id)
        if key not in self._cache:
            self._cache[key] = self.repo.get_node(label, node_id)
        return self._cache[key]

    def _linked(self, service_id: str, rel: str, label: str) -> set[str]:
        key = ("in", service_id, rel, label)
        if key not in self._cache:
            self._cache[key] = {n["id"] for n in self.repo.neighbors("Service", service_id, rel, label,
                                                                     outgoing=False, limit=200)}
        return self._cache[key]

    def _failed_actions(self) -> dict[tuple[str, str], str]:
        """(action_type, target) of actions that verified-failed memories in the context were derived from."""
        mc = self.inp.memory_context
        warns = [m for m in (mc.items if mc else []) if m.precedent == "warns_against"]
        ids = {i: m.id for m in warns for i in m.derived_from_action_ids if self._own(i)}
        if not ids:
            return {}
        out: dict[tuple[str, str], str] = {}
        for aid, props in self.repo.get_nodes("AgentAction", sorted(ids)).items():
            targets = {props.get("target_service_id")} - {None}
            if not targets:
                targets = {n["id"] for n in self.repo.neighbors("AgentAction", aid, "TARGETS", "Service",
                                                                outgoing=True, limit=10)}
            for t in targets:
                out.setdefault((props.get("action_type"), t), ids[aid])
        return out


def _v(code, target: str, detail: str) -> Violation:
    return Violation(code=code, target=target, detail=detail if len(detail) <= 300 else detail[:299] + "…")


__all__ = ["ALLOWED_ENVS", "NEEDS_DEPLOYMENT", "decide", "evaluate"]
