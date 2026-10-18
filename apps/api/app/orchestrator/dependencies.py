"""Everything the orchestrator calls out to, injectable so tests can use fakes.

The real investigator, safety gate and telemetry modules are imported lazily inside
`default_dependencies`, so the orchestrator imports cleanly even where they are absent.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.contracts import (
    GateResult,
    InvestigatorInput,
    InvestigatorOutput,
    InvestigatorResult,
    TelemetryContext,
)
from app.config import Settings
from app.graph.repository import GraphRepository
from app.rag.embeddings import Embedder
from app.rag.retrieval import RetrievalBundle
from app.tools.graph_tools import ToolContext


class Investigator(Protocol):
    name: str

    def run(self, inp: InvestigatorInput, *, timeout_s: float) -> InvestigatorResult: ...


RetrieveFn = Callable[[ToolContext, str], RetrievalBundle]
TelemetryFn = Callable[..., TelemetryContext]        # (tenant_id, env, service_ids, window_start_ms, window_end_ms)
GateFn = Callable[..., GateResult]                   # (output, inp, *, repo, revision, max_revisions)


def wall_clock_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Dependencies:
    retrieve: RetrieveFn
    telemetry: TelemetryFn
    investigator: Investigator
    gate: GateFn
    clock: Callable[[], int] = wall_clock_ms
    embedder: Embedder | None = None


def make_retrieve(embedder: Embedder | None, allowed_classifications: frozenset[str]) -> RetrieveFn:
    from app.rag.retrieval import retrieve

    def _retrieve(ctx: ToolContext, incident_id: str) -> RetrievalBundle:
        return retrieve(ctx, incident_id, embedder=embedder, allowed_classifications=allowed_classifications)
    return _retrieve


def default_dependencies(settings: Settings) -> Dependencies:
    """The production wiring: hybrid retrieval, synthetic telemetry, the configured investigator, the gate."""
    from app.agents import investigator as investigator_mod
    from app.agents import safety_gate
    from app.rag import embeddings
    from app.telemetry import synthetic

    embedder = embeddings.from_settings(settings)

    def gate(output: InvestigatorOutput, inp: InvestigatorInput, *, repo: GraphRepository, revision: int,
             max_revisions: int) -> GateResult:
        return safety_gate.evaluate(output, inp, repo=repo, revision=revision, max_revisions=max_revisions)

    def telemetry(tenant_id: str, env: str, service_ids: list[str], window_start_ms: int,
                  window_end_ms: int) -> Any:
        return synthetic.collect(tenant_id, env, service_ids, window_start_ms, window_end_ms)

    return Dependencies(
        retrieve=make_retrieve(embedder, settings.allowed_classifications),
        telemetry=telemetry,
        investigator=investigator_mod.from_settings(settings),
        gate=gate,
        clock=wall_clock_ms,
        embedder=embedder,
    )
