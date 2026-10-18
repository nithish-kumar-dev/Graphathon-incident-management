"""Phase 4 contracts shared by the orchestrator, the investigator and the safety gate.

The orchestrator (app/orchestrator), investigator + gate (app/agents) and telemetry (app/telemetry)
are built in parallel against these types. Change them only deliberately: every side depends on them.

Flow:  branches -> InvestigatorInput -> Investigator.run() -> InvestigatorOutput
       -> safety_gate.evaluate() -> GateResult (decision) -> persist / revise / escalate
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.rag.retrieval import GraphContext, KnowledgeContext, MemoryContext

ClaimType = Literal["observed", "correlated", "hypothesis", "confirmed"]
BranchName = Literal["graph_context", "memory_context", "telemetry_context"]
BranchStatus = Literal["pending", "running", "completed", "failed", "skipped"]
Mode = Literal["recommendation_only", "simulation"]
Risk = Literal["low", "medium", "high"]

# The only action types the restricted executor (Phase 5) will ever run. Anything else is rejected.
ALLOWED_ACTION_TYPES: tuple[str, ...] = ("rollback_deployment_simulated",)

_ID = r"^[a-z][a-z0-9_]{1,31}\.[a-z]+\.[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ telemetry (live evidence branch)
class TelemetryObservation(_Strict):
    """One reading from a permitted synthetic telemetry source. Becomes an Evidence node (kind metric)
    with this exact id when the outcome is persisted, so findings can cite it."""
    id: str = Field(pattern=_ID, description="<tenant>.ev.tel.<stable hash>")
    service_id: str = Field(pattern=_ID)
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    value: float
    unit: str = Field(max_length=16)
    baseline: float | None = None
    observed_at_ms: int
    source_ref: str = Field(pattern=r"^synthetic://telemetry/\S{1,400}$")
    summary: str = Field(max_length=300)


class TelemetryContext(_Strict):
    observations: list[TelemetryObservation] = Field(default_factory=list, max_length=100)
    window_start_ms: int
    window_end_ms: int
    sources: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ investigator
class InvestigatorInput(_Strict):
    """Everything the investigator may use. It must not use anything else, and cite only ids in here."""
    incident_id: str
    incident_key: str
    incident_title: str
    tenant_id: str
    env: str
    mode: Mode
    revision: int = Field(ge=0)
    branch_status: dict[BranchName, BranchStatus]
    graph_context: GraphContext | None = None
    memory_context: MemoryContext | None = None
    knowledge_context: KnowledgeContext | None = None
    telemetry_context: TelemetryContext | None = None
    feedback: list[str] = Field(default_factory=list, description="Gate violations from the previous revision")
    allowed_action_types: list[str] = Field(default_factory=lambda: list(ALLOWED_ACTION_TYPES))

    def known_evidence_ids(self) -> set[str]:
        """Ids the investigator may cite: incident evidence, path evidence, memory grounding, telemetry."""
        ids: set[str] = set()
        if self.graph_context:
            ids |= {e.id for e in self.graph_context.evidence}
            ids |= {e.id for p in self.graph_context.explanation_paths for e in p.evidence}
        if self.memory_context:
            ids |= {e.id for m in self.memory_context.items for e in m.grounded_in}
        if self.telemetry_context:
            ids |= {o.id for o in self.telemetry_context.observations}
        return ids


class Hypothesis(_Strict):
    claim_type: ClaimType = Field(description="observed | correlated | hypothesis. 'confirmed' is reserved for "
                                              "humans; the gate rejects it from the investigator.")
    statement: str = Field(min_length=1, max_length=600)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    contradicting_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(default="", max_length=400)


class ProposedAction(_Strict):
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    target_service_id: str = Field(pattern=_ID)
    deployment_id: str | None = Field(default=None, pattern=_ID)
    runbook_id: str = Field(pattern=_ID)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    rationale: str = Field(min_length=1, max_length=600)
    risk: Risk = "medium"


class InvestigatorOutput(_Strict):
    """Validated LLM (or stub) output. Anything that does not parse into this is `malformed`."""
    summary: str = Field(min_length=1, max_length=1000)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=10)
    proposed_actions: list[ProposedAction] = Field(default_factory=list, max_length=3)
    overall_uncertainty: str = Field(default="", max_length=600)


class InvestigatorResult(_Strict):
    output: InvestigatorOutput
    investigator: str = Field(description='e.g. "stub-v1", "ollama:qwen2.5:7b", "stub-fallback(ollama timeout)"')
    latency_ms: int = Field(ge=0)


class InvestigatorError(Exception):
    """Raised by Investigator.run. The orchestrator counts it as a failed revision."""

    def __init__(self, kind: Literal["malformed", "timeout", "unavailable"], message: str) -> None:
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------ safety gate
ViolationCode = Literal[
    "unknown_evidence", "no_evidence", "confirmed_claim_not_allowed", "unknown_service", "service_out_of_scope",
    "env_not_allowed", "unknown_runbook", "runbook_not_applicable", "action_not_allowed", "unknown_deployment",
    "deployment_not_on_target", "repeats_failed_action", "invalid_arguments", "inconclusive",
]


class Violation(_Strict):
    code: ViolationCode
    target: str = Field(description='e.g. "hypotheses[0]" or "proposed_actions[1]"')
    detail: str = Field(max_length=300)


GateDecision = Literal["accept", "revise", "recommendation_only", "escalate", "inconclusive"]


class GateResult(_Strict):
    """decision:
    - accept: no violations. The accepted items are used as they are.
    - revise: violations, and revision < max_revisions. The orchestrator re-runs the investigator with
      feedback = [v.detail for v in violations].
    - recommendation_only: revisions exhausted. Only valid hypotheses are kept and all actions are dropped.
    - escalate: revisions exhausted and an unsafe or invalid action was proposed. Escalate to a human.
    - inconclusive: no evidence-backed hypothesis survives.
    """
    decision: GateDecision
    hypotheses: list[Hypothesis]
    proposed_actions: list[ProposedAction]
    violations: list[Violation]
