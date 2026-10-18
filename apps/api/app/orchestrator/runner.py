"""Running investigations: the Orchestrator (one compiled graph + checkpointer) and the Worker (claims queued
sessions, runs them in a small thread pool, resumes interrupted ones on startup).

- **Claim.** `queued -> running` is one FalkorDB write query (`claim_session.cypher`). FalkorDB executes one
  write per graph at a time, so of several claimers exactly one wins.
- **Checkpoints.** PostgresSaver, `thread_id = AgentSession.thread_id`, `durability="sync"`: every superstep
  is committed before the next starts.
- **Recovery.** A session still `running` when a worker starts is resumed with `graph.invoke(None, config)` on
  the same thread id. Nodes that completed are not re-run.
- **Abnormal ends.** The overall run deadline -> `timed_out`; any other unexpected exception -> `failed` with a
  short error. Both are persisted (session + timeline) outside the graph.

Run exactly ONE worker per graph (in the API process or `scripts/run_worker.py`): claims are atomic, but
startup recovery of `running` sessions is not leased.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from falkordb import Graph

from app.api.errors import NotFound
from app.config import Settings
from app.graph import client
from app.graph.repository import GraphRepository, Scope
from app.graph.schema import ENV_VALUES
from app.orchestrator.dependencies import Dependencies, default_dependencies
from app.orchestrator.graph import RunEnv, RunTimedOut, build
from app.orchestrator.persist import notify_channel, persist_outcome
from app.orchestrator.state import TERMINAL, InvestigationState

log = logging.getLogger("app.orchestrator")


def default_run_timeout_s(settings: Settings) -> float:
    """Generous overall budget: two branch timeouts, every allowed investigator attempt, plus slack."""
    return settings.branch_timeout_s * 2 + settings.llm_timeout_s * (settings.max_investigation_revisions + 1) + 60


class Orchestrator:
    def __init__(self, *, falkor: Graph, checkpointer, settings: Settings, deps: Dependencies,
                 run_timeout_s: float | None = None,
                 review_policy: Callable[[InvestigationState], dict] | None = None) -> None:
        self.settings = settings
        self.env = RunEnv(deps=deps, falkor=falkor, settings=settings,
                          run_timeout_s=run_timeout_s or default_run_timeout_s(settings), review_policy=review_policy)
        self.graph = build(self.env).compile(checkpointer=checkpointer)

    def repo(self, scope: Scope) -> GraphRepository:
        return GraphRepository(self.env.falkor, scope, timeout_ms=self.settings.graph_query_timeout_ms)

    @staticmethod
    def config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def run(self, session_id: str, scope: Scope) -> str:
        """Start, or resume from its checkpoint, the run for one claimed session. Returns the final status.
        Exceptions that are not `Exception` (process-level crashes) propagate and leave the session `running`
        with its checkpoint intact, exactly as a killed process would."""
        ses = self.repo(scope).get_node("AgentSession", session_id)
        if ses is None:
            raise NotFound(f"investigation {session_id} not found")
        thread_id = ses["thread_id"]
        config = self.config(thread_id)
        snapshot = self.graph.get_state(config)
        if snapshot.next:
            log.info("resuming investigation at %s", ",".join(snapshot.next), extra={"investigation_id": session_id})
            inp = None
        elif snapshot.values.get("session_id"):
            # The graph already finished; make sure the outcome reached the graph (idempotent).
            state = dict(snapshot.values)
            if ses["status"] not in TERMINAL and state.get("status") in TERMINAL:
                self._finalize(scope, state)
            return self.repo(scope).get_node("AgentSession", session_id)["status"]
        else:
            inp = {"session_id": session_id, "tenant_id": scope.tenant_id, "env": scope.env}
        try:
            out = self.graph.invoke(inp, config, durability="sync")
            return out["status"]
        except RunTimedOut as exc:
            log.warning("investigation timed out: %s", exc, extra={"investigation_id": session_id})
            return self._abnormal(session_id, scope, config, "timed_out", str(exc))
        except Exception as exc:  # recorded as `failed`, never silently dropped
            log.exception("investigation failed", extra={"investigation_id": session_id})
            return self._abnormal(session_id, scope, config, "failed", f"{type(exc).__name__}: {str(exc)[:300]}")
        finally:
            self.env.cache.drop(thread_id)

    resume = run

    def _abnormal(self, session_id: str, scope: Scope, config: dict, status: str, error: str) -> str:
        values = dict(self.graph.get_state(config).values or {})
        state: InvestigationState = {**values, "session_id": session_id, "tenant_id": scope.tenant_id,
                                     "env": scope.env, "status": status, "error": error}
        state["gate"] = None if status == "timed_out" else values.get("gate")
        if state.get("gate") and state["gate"].get("decision") == "accept":
            state["gate"] = {**state["gate"], "proposed_actions": []}   # no actions from a broken run
        try:
            self._finalize(scope, state)
        except Exception:  # stays `running`; the next worker start resumes it
            log.exception("could not record abnormal end", extra={"investigation_id": session_id})
            return "running"
        return status

    def _finalize(self, scope: Scope, state: InvestigationState) -> None:
        repo = self.repo(scope)
        persist_outcome(repo, state, now_ms=self.env.deps.clock())
        notify_channel(repo, state, now_ms=self.env.deps.clock())


# ============================================================================ worker
class Worker:
    """Polls for queued sessions, claims them atomically and runs them on `max_workers` daemon threads."""

    def __init__(self, settings: Settings, *, max_workers: int = 2,
                 deps_factory: Callable[[Settings], Dependencies] = default_dependencies,
                 orchestrator: Orchestrator | None = None) -> None:
        self.settings = settings
        self.max_workers = max_workers
        self._deps_factory = deps_factory
        self.orchestrator = orchestrator
        self._pool = None
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._recovered = False

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._stop.clear()
        self._threads = [threading.Thread(target=self._loop, name="orchestrator-poll", daemon=True)]
        self._threads += [threading.Thread(target=self._work, name=f"orchestrator-run-{i}", daemon=True)
                          for i in range(self.max_workers)]
        for th in self._threads:
            th.start()
        log.info("orchestrator worker started (%d run threads)", self.max_workers)

    def stop(self, timeout_s: float = 10.0) -> None:
        """Stop polling, let in-flight runs finish within the timeout. A run still going after that keeps its
        checkpoint and `running` status and is resumed by the next worker start."""
        self._stop.set()
        for _ in range(self.max_workers):
            self._queue.put(None)
        for th in self._threads:
            th.join(timeout=timeout_s)
        alive = [th.name for th in self._threads if th.is_alive()]
        if alive:
            log.warning("orchestrator stopped with runs in flight: %s", ", ".join(alive))
        elif self._pool is not None:
            self._pool.close()
            self._pool = None
        log.info("orchestrator worker stopped")

    def _setup(self) -> None:
        if self.orchestrator is not None:
            return
        from app.orchestrator.checkpoint import make_saver, open_pool
        db = client.connect(self.settings.falkordb_url)
        pool = open_pool(self.settings.postgres_dsn.get_secret_value(), max_size=self.max_workers + 2)
        try:
            saver = make_saver(pool, setup=True)
            self.orchestrator = Orchestrator(falkor=db.select_graph(self.settings.graph_name), checkpointer=saver,
                                             settings=self.settings, deps=self._deps_factory(self.settings))
        except Exception:
            pool.close()
            raise
        self._pool = pool

    # ---------------------------------------------------------------- claim / recover
    def scopes(self) -> list[Scope]:
        return [Scope(tn, env) for tn in sorted(self.settings.tenants) for env in sorted(ENV_VALUES)]

    def claim_queued(self, limit: int | None = None) -> list[tuple[str, Scope]]:
        """Claim up to `limit` queued sessions (default: free run slots). Only claims this worker won."""
        limit = self._free_slots() if limit is None else limit
        claimed: list[tuple[str, Scope]] = []
        for scope in self.scopes():
            if len(claimed) >= limit:
                break
            repo = self.orchestrator.repo(scope)
            for row in repo.sessions_by_status(["queued"], limit=limit - len(claimed)):
                if repo.claim_session(row["id"], now_ms=self.orchestrator.env.deps.clock()):
                    claimed.append((row["id"], scope))
        return claimed

    def running_sessions(self) -> list[tuple[str, Scope]]:
        return [(row["id"], scope) for scope in self.scopes()
                for row in self.orchestrator.repo(scope).sessions_by_status(["running"], limit=200)]

    def _free_slots(self) -> int:
        with self._lock:
            return max(0, self.max_workers - len(self._inflight))

    def _dispatch(self, session_id: str, scope: Scope) -> None:
        with self._lock:
            if session_id in self._inflight:
                return
            self._inflight.add(session_id)
        self._queue.put((session_id, scope))

    def poll_once(self) -> list[str]:
        """One poll: on the first successful one, resume `running` sessions; then claim queued ones."""
        self._setup()
        if not self._recovered:
            for sid, scope in self.running_sessions():
                self._dispatch(sid, scope)
            self._recovered = True
        claimed = self.claim_queued()
        for sid, scope in claimed:
            self._dispatch(sid, scope)
        return [sid for sid, _ in claimed]

    # ---------------------------------------------------------------- threads
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # dependency outages must not kill the poller
                log.exception("orchestrator poll failed; retrying")
            self._stop.wait(self.settings.orchestrator_poll_s)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            session_id, scope = item
            try:
                status = self.orchestrator.run(session_id, scope)
                log.info("investigation finished: %s", status, extra={"investigation_id": session_id,
                                                                       "outcome": status})
            except Exception:
                log.exception("investigation run crashed", extra={"investigation_id": session_id})
            finally:
                with self._lock:
                    self._inflight.discard(session_id)
