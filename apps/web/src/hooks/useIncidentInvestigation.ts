import { useCallback, useState } from "react";
import { ApiError, toApiError, useApi } from "../api/client";
import type { InvestigationOut, Mode } from "../api/types";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";
import { isTerminalInvestigation, usePolling } from "./usePolling";

export interface IncidentInvestigationState {
  investigationId: string | null;
  /** Latest polled value (falls back to the POST response until the first poll lands). */
  investigation: InvestigationOut | null;
  /** From the last POST: true = new investigation (201), false = existing active one returned (200). */
  created: boolean | null;
  starting: boolean;
  startError: ApiError | null;
  pollError: ApiError | null;
  polling: boolean;
  lastUpdated: Date | null;
  start: (mode: Mode) => Promise<void>;
  /** Fetch the run now (e.g. right after a review decision) instead of waiting for the next poll. */
  refresh: () => Promise<void>;
  /** Drop the remembered investigation id for this incident. */
  forget: () => void;
}

/**
 * Current investigation for one incident. The id lives in state and in localStorage per incident
 * (the run list endpoint is used by the History tab, not here). Mount with `key={incidentId}`.
 */
export function useIncidentInvestigation(incidentId: string): IncidentInvestigationState {
  const { client, user } = useApi();
  const [investigationId, setInvestigationId] = useState<string | null>(() =>
    readStorage(STORAGE_KEYS.investigationFor(incidentId)),
  );
  const [initial, setInitial] = useState<InvestigationOut | null>(null);
  const [created, setCreated] = useState<boolean | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);

  const polled = usePolling((signal) => client.getInvestigation(investigationId ?? "", signal), {
    intervalMs: 2500,
    enabled: investigationId !== null,
    isTerminal: (inv) => isTerminalInvestigation(inv.status),
    key: investigationId ? `${investigationId}|${user}|${nonce}` : null,
  });

  const start = useCallback(
    async (mode: Mode) => {
      setStarting(true);
      setStartError(null);
      try {
        const res = await client.createInvestigation({ incident_id: incidentId, mode });
        writeStorage(STORAGE_KEYS.investigationFor(incidentId), res.investigation.id);
        setInitial(res.investigation);
        setCreated(res.created);
        setInvestigationId(res.investigation.id);
        setNonce((n) => n + 1);
      } catch (err) {
        setStartError(toApiError(err));
      } finally {
        setStarting(false);
      }
    },
    [client, incidentId],
  );

  const refresh = useCallback(async () => {
    if (!investigationId) return;
    try {
      const fresh = await client.getInvestigation(investigationId);
      setInitial(fresh);
      setNonce((n) => n + 1);
    } catch {
      // The poll loop will surface a persistent failure; a missed refresh is harmless.
    }
  }, [client, investigationId]);

  const forget = useCallback(() => {
    writeStorage(STORAGE_KEYS.investigationFor(incidentId), null);
    setInvestigationId(null);
    setInitial(null);
    setCreated(null);
  }, [incidentId]);

  const candidate = polled.data ?? (initial && initial.id === investigationId ? initial : null);
  const investigation = candidate && candidate.incident_id === incidentId ? candidate : null;

  return {
    investigationId,
    investigation,
    created,
    starting,
    startError,
    pollError: polled.error,
    polling: polled.polling,
    lastUpdated: polled.lastUpdated,
    start,
    refresh,
    forget,
  };
}
