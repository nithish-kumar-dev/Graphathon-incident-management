import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApi, type ApiError } from "../../api/client";
import type { AgentEventOut, DemoUser, IncidentDetail, IncidentMemories, RetrievalBundle } from "../../api/types";
import { useAsync } from "../../hooks/useAsync";
import { useIncidentInvestigation, type IncidentInvestigationState } from "../../hooks/useIncidentInvestigation";
import {
  STAGE_PACE_MS,
  advanceStages,
  buildInvestigationView,
  currentStage as currentStageOf,
  stagesProgressSignature,
  type InvestigationView,
  type Phase,
  type Stage,
} from "./model";

/**
 * One shared, live picture of an incident for every tab. It composes the existing polling hook with
 * the timeline, retrieval snapshot and memories, and refreshes the slower reads when the run's
 * status, branch states or action states change, and polls the run's step events while it is active
 * (the backend has no event stream, only polling). Nothing here invents data: each
 * field is either what an endpoint returned or null.
 */
export interface InvestigationSession {
  user: DemoUser;
  incident: IncidentDetail;
  incidentRefreshing: boolean;
  reloadIncident: () => void;
  run: IncidentInvestigationState;
  bundle: RetrievalBundle | null;
  bundleError: ApiError | null;
  bundleLoading: boolean;
  memories: IncidentMemories | null;
  memoriesError: ApiError | null;
  reloadMemories: () => void;
  /** Orchestrator step events for the current run; empty until the first fetch lands. */
  runEvents: readonly AgentEventOut[];
  /** Refetch the run, its timeline, events and memories (e.g. after a review decision). */
  reloadAll: () => Promise<void>;
  timelineError: ApiError | null;
  timelineLoading: boolean;
  view: InvestigationView;
  /** Ticks so relative times ("4 min ago") stay current without refetching. */
  now: number;
}

const SessionContext = createContext<InvestigationSession | null>(null);

export function useInvestigationSession(): InvestigationSession {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useInvestigationSession must be used inside <InvestigationSessionProvider>");
  return value;
}

export function useNow(intervalMs = 20_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** True when the viewer has asked for reduced motion. Re-reads the query if the preference changes. */
export function usePrefersReducedMotion(): boolean {
  const query = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null);
  const [reduced, setReduced] = useState(() => query()?.matches ?? false);
  useEffect(() => {
    const mq = query();
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    onChange();
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return reduced;
}

/**
 * The stage tracker, paced so a live run is watchable instead of snapping from "not started" to
 * "complete" in one poll.
 *
 * It only ever *delays* the real data. Every frame it returns comes out of `advanceStages`, which
 * copies each stage verbatim from the current real list or from the previously displayed frame
 * (itself real at an earlier moment), so no stage can be displayed further along than the backend
 * has reported. Pacing is skipped entirely for:
 *   - the first frame seen for a run, so a run that finished long ago is shown at once, never replayed;
 *   - any run never observed in `queued`/`running` here, i.e. anything that was not progressing live;
 *   - a `failed` run, which converges immediately rather than leaving a stale stage on screen;
 *   - a different run id (restart), and for viewers who prefer reduced motion.
 * Caption-only churn (counts, relative times) is adopted immediately and does not restart the clock.
 */
export function usePacedStages(real: Stage[], runId: string | null, phase: Phase, paced: boolean): Stage[] {
  const [shown, setShown] = useState<Stage[]>(real);
  const shownRef = useRef<Stage[]>(real);
  const lastFrameAt = useRef<number>(Date.now());
  const seenRunId = useRef<string | null>(runId);
  const sawLiveRun = useRef(false);

  useEffect(() => {
    const show = (next: Stage[], restartClock: boolean) => {
      shownRef.current = next;
      if (restartClock) lastFrameAt.current = Date.now();
      setShown(next);
    };

    const wasLive = sawLiveRun.current;
    if (phase === "queued" || phase === "running") sawLiveRun.current = true;

    // A different run (or no run) has nothing in common with what is on screen: show it as it is.
    if (seenRunId.current !== runId) {
      seenRunId.current = runId;
      show(real, true);
      return;
    }
    if (!paced || !wasLive || phase === "none" || phase === "failed") {
      show(real, true);
      return;
    }
    if (stagesProgressSignature(real) === stagesProgressSignature(shownRef.current)) {
      // Same progress, fresher captions. Adopt without restarting the dwell timer.
      show(real, false);
      return;
    }
    const wait = Math.max(0, STAGE_PACE_MS - (Date.now() - lastFrameAt.current));
    const id = setTimeout(() => show(advanceStages(shownRef.current, real), true), wait);
    return () => clearTimeout(id);
  }, [real, runId, phase, paced, shown]);

  return shown;
}

/** Changes whenever the run moves (status or any branch state), not on every poll. */
export function progressSignature(run: IncidentInvestigationState): string {
  const inv = run.investigation;
  if (!inv) return "none";
  const branches = Object.entries(inv.branches ?? {})
    .map(([k, v]) => `${k}:${v?.status ?? ""}:${v?.ended_at ?? ""}`)
    .join(",");
  const actions = (inv.proposed_actions ?? []).map((a) => `${a.id}:${a.status}`).join(",");
  return `${inv.id}|${inv.status}|${branches}|${actions}`;
}

function useReloadOnChange(signature: string, reload: () => void): void {
  const previous = useRef(signature);
  useEffect(() => {
    if (previous.current === signature) return;
    previous.current = signature;
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);
}

export interface InvestigationSessionProviderProps {
  incident: IncidentDetail;
  incidentRefreshing: boolean;
  reloadIncident: () => void;
  children: ReactNode;
}

/** Mount with `key={incident.id}` so state never leaks between incidents. */
export function InvestigationSessionProvider({ incident, incidentRefreshing, reloadIncident, children }: InvestigationSessionProviderProps) {
  const { client, user } = useApi();
  const run = useIncidentInvestigation(incident.id);
  const now = useNow();

  const timeline = useAsync((signal) => client.getTimeline(incident.id, signal), [client, incident.id, user]);
  const retrieval = useAsync((signal) => client.getRetrieval(incident.id, signal), [client, incident.id, user]);
  const memories = useAsync((signal) => client.getMemories(incident.id, { includeUnverified: false }, signal), [client, incident.id, user]);

  const investigationId = run.investigation?.id ?? null;
  const stepEvents = useAsync(
    (signal) => (investigationId ? client.getInvestigationEvents(investigationId, signal) : Promise.resolve(null)),
    [client, investigationId, user],
  );

  const status = run.investigation?.status ?? "none";
  const active = status === "queued" || status === "running";
  // Step events (intake, investigator, safety gate...) can happen while the run's status stays "running",
  // so refetch them on a short interval until the run leaves the active states.
  const reloadEvents = stepEvents.reload;
  useEffect(() => {
    if (!active) return;
    const id = setInterval(reloadEvents, 2500);
    return () => clearInterval(id);
  }, [active, reloadEvents]);
  useReloadOnChange(progressSignature(run), () => {
    timeline.reload();
    reloadEvents();
  });
  useReloadOnChange(`${run.investigation?.id ?? ""}|${status}`, () => {
    retrieval.reload();
    memories.reload();
    reloadIncident();
  });

  const events = timeline.data?.events;
  const realView = useMemo(
    () =>
      buildInvestigationView({
        incident,
        investigation: run.investigation,
        bundle: retrieval.data,
        memories: memories.data,
        timeline: events ?? [],
        runEvents: stepEvents.data?.events ?? null,
      }),
    [incident, run.investigation, retrieval.data, memories.data, events, stepEvents.data],
  );

  // Only the stage tracker is paced; every other field stays exactly what the backend reported.
  const reducedMotion = usePrefersReducedMotion();
  const pacedStages = usePacedStages(realView.stages, run.investigation?.id ?? null, realView.phase, !reducedMotion);
  const view = useMemo<InvestigationView>(
    () => (pacedStages === realView.stages ? realView : { ...realView, stages: pacedStages, currentStage: currentStageOf(pacedStages) }),
    [realView, pacedStages],
  );

  const refreshRun = run.refresh;
  const reloadMemories = memories.reload;
  const reloadTimeline = timeline.reload;
  const reloadAll = async () => {
    await refreshRun();
    reloadTimeline();
    reloadEvents();
    reloadMemories();
    reloadIncident();
  };

  const value: InvestigationSession = {
    user,
    incident,
    incidentRefreshing,
    reloadIncident,
    run,
    bundle: retrieval.data,
    bundleError: retrieval.error,
    bundleLoading: retrieval.loading,
    memories: memories.data,
    memoriesError: memories.error,
    reloadMemories,
    runEvents: stepEvents.data?.events ?? [],
    reloadAll,
    timelineError: timeline.error,
    timelineLoading: timeline.loading,
    view,
    now,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
