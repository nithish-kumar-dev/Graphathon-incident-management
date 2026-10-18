"""Regenerate apps/web/src/test/fixtures/investigation_*_101.json from the real API.

    .venv/bin/python scripts/gen_web_fixtures.py [--out DIR]

Each scenario runs on a throwaway graph on the ephemeral `falkordb-test` server (never the dev server;
the script refuses a server with persistence), with the real stub investigator, safety gate and synthetic
telemetry, the in-process orchestrator and a fixed clock. `escalated` and `failed` use a stub that is made
to misbehave (an action on a runbook that does not exist; an exception), because the real stub never does.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import _bootstrap  # noqa: F401
from app.agents import safety_gate
from app.agents.contracts import InvestigatorResult
from app.agents.investigator import StubInvestigator
from app.api import deps
from app.config import Settings, get_settings
from app.graph import client, migrate
from app.graph.repository import GraphRepository, Scope
from app.main import app
from app.orchestrator.dependencies import Dependencies, make_retrieve
from app.orchestrator.runner import Orchestrator
from app.rag.embeddings import HashingEmbedder
from app.seeds import decoy_acme, novacommerce
from app.seeds.loader import apply_seed
from app.telemetry import synthetic
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

ROOT = Path(__file__).resolve().parents[1]
NOW = novacommerce.SEED_AT_MS
HEADERS = {"X-Demo-User": "demo-responder"}


class Misbehaving(StubInvestigator):
    """The stub, plus one fault: `bad_runbook` (an action on a runbook that is not in the graph) or `crash`."""

    def __init__(self, fault: str) -> None:
        self.fault = fault

    def run(self, inp, *, timeout_s):
        if self.fault == "crash":
            raise RuntimeError("synthetic investigator fault")
        out = self.investigate(inp.model_copy(update={"feedback": []}))
        bad = out.proposed_actions[0].model_copy(update={"runbook_id": "nova.rb.payment.nonexistent"})
        return InvestigatorResult(output=out.model_copy(update={"proposed_actions": [bad]}),
                                  investigator=self.name, latency_ms=1)


SCENARIOS = {
    "completed": ("recommendation_only", StubInvestigator),
    "awaiting_review": ("simulation", StubInvestigator),
    "escalated": ("simulation", lambda: Misbehaving("bad_runbook")),
    "failed": ("recommendation_only", lambda: Misbehaving("crash")),
}


def generate(db, settings: Settings, name: str, mode: str, investigator) -> dict:
    graph_name = f"graphathon_fixtures_{uuid.uuid4().hex[:8]}"
    migrate.migrate(db, graph_name)
    graph = db.select_graph(graph_name)
    apply_seed(graph, novacommerce)
    apply_seed(graph, decoy_acme)
    s = settings.model_copy(update={"graph_name": graph_name, "orchestrator_enabled": False})
    app.dependency_overrides[get_settings] = lambda: s
    app.dependency_overrides[deps.get_now_ms] = lambda: NOW
    try:
        http = TestClient(app)
        created = http.post("/api/investigations", json={"incident_id": "nova.inc.101", "mode": mode},
                            headers=HEADERS)
        created.raise_for_status()
        sid = created.json()["id"]
        scope = Scope("nova", "prod")
        GraphRepository(graph, scope).claim_session(sid, now_ms=NOW)
        embedder = HashingEmbedder()
        orch = Orchestrator(falkor=graph, checkpointer=MemorySaver(), settings=s, deps=Dependencies(
            retrieve=make_retrieve(embedder, s.allowed_classifications), telemetry=synthetic.collect,
            investigator=investigator(),
            gate=lambda o, i, *, repo, revision, max_revisions: safety_gate.evaluate(
                o, i, repo=repo, revision=revision, max_revisions=max_revisions),
            clock=lambda: NOW))
        status = orch.run(sid, scope)
        print(f"{name}: {status}")
        return http.get(f"/api/investigations/{sid}", headers=HEADERS).json()
    finally:
        app.dependency_overrides.clear()
        graph.delete()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "apps/web/src/test/fixtures")
    args = parser.parse_args()
    url = os.environ.get("TEST_FALKORDB_URL", "redis://127.0.0.1:56390")
    settings = Settings(falkordb_url=url, tenant_allowlist="nova,acme")
    db = client.connect(url)
    if (db.connection.config_get("appendonly")["appendonly"], db.connection.config_get("save")["save"]) != ("no", ""):
        print(f"refusing: {url} has persistence; use the ephemeral falkordb-test server", file=sys.stderr)
        return 2
    for name, (mode, investigator) in SCENARIOS.items():
        body = generate(db, settings, name, mode, investigator)
        (args.out / f"investigation_{name}_101.json").write_text(json.dumps(body, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
