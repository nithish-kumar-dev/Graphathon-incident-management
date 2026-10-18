import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApi, type ApiError } from "../../api/client";
import type { DemoUser, IncidentDetail, IncidentMemories, RetrievalBundle } from "../../api/types";
import { useAsync } from "../../hooks/useAsync";
import { useIncidentInvestigation, type IncidentInvestigationState } from "../../hooks/useIncidentInvestigation";
import { buildInvestigationView, type InvestigationView } from "./model";

/**
 * One shared, live picture of an incident for every tab. It composes the existing polling hook with
 * the timeline, retrieval snapshot and memories, and refreshes the slower reads when the run's
 * status or branch states change (the backend has no event stream). Nothing here invents data: each
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

/** Changes whenever the run moves (status or any branch state), not on every poll. */
export function progressSignature(run: IncidentInvestigationState): string {
  const inv = run.investigation;
  if (!inv) return "none";
  const branches = Object.entries(inv.branches ?? {})
    .map(([k, v]) => `${k}:${v?.status ?? ""}`)
    .join(",");
  return `${inv.id}|${inv.status}|${branches}`;
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

  const status = run.investigation?.status ?? "none";
  useReloadOnChange(progressSignature(run), timeline.reload);
  useReloadOnChange(`${run.investigation?.id ?? ""}|${status}`, () => {
    retrieval.reload();
    memories.reload();
    reloadIncident();
  });

  const events = timeline.data?.events;
  const view = useMemo(
    () =>
      buildInvestigationView({
        incident,
        investigation: run.investigation,
        bundle: retrieval.data,
        memories: memories.data,
        timeline: events ?? [],
      }),
    [incident, run.investigation, retrieval.data, memories.data, events],
  );

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
    timelineError: timeline.error,
    timelineLoading: timeline.loading,
    view,
    now,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
