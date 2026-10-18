import { useEffect, useRef, useState } from "react";
import { ApiError, isAbortError, toApiError } from "../api/client";
import { TERMINAL_INVESTIGATION_STATUSES, type InvestigationStatus } from "../api/types";

export function isTerminalInvestigation(status: InvestigationStatus | string | null | undefined): boolean {
  return status != null && (TERMINAL_INVESTIGATION_STATUSES as readonly string[]).includes(status);
}

export interface PollingOptions<T> {
  /** Delay between the end of one request and the start of the next. Default 2500. */
  intervalMs?: number;
  /** Polling runs only while true. */
  enabled: boolean;
  /** Stop once this returns true for the latest value. */
  isTerminal: (value: T) => boolean;
  /** Identity of what is being polled (e.g. investigation id + user). Changing it aborts and restarts with fresh state. */
  key: string | null;
}

export interface PollingState<T> {
  data: T | null;
  error: ApiError | null;
  /** True while the loop is active (not terminal, not stopped by an error, enabled). Stays true while paused for a hidden tab. */
  polling: boolean;
  lastUpdated: Date | null;
}

/** Client errors that will not fix themselves; polling stops on these. Network and 5xx errors keep retrying. */
function isFatal(err: ApiError): boolean {
  return err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429;
}

/**
 * Poll `fn` every `intervalMs` until `isTerminal(data)`. Requests never overlap (setTimeout chain).
 * Pauses while `document.hidden` and fetches immediately when the page becomes visible again.
 * Aborts the in-flight request on key change, disable and unmount; results from an old key are dropped.
 */
export function usePolling<T>(fn: (signal: AbortSignal) => Promise<T>, options: PollingOptions<T>): PollingState<T> {
  const { intervalMs = 2500, enabled, key } = options;
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const isTerminalRef = useRef(options.isTerminal);
  isTerminalRef.current = options.isTerminal;

  const [state, setState] = useState<Omit<PollingState<T>, "polling"> & { active: boolean; key: string | null }>({
    data: null,
    error: null,
    lastUpdated: null,
    active: false,
    key: null,
  });

  useEffect(() => {
    // Fresh state for every key; never carry data across keys.
    setState((s) =>
      s.key === key ? { ...s, active: enabled && key !== null } : { data: null, error: null, lastUpdated: null, active: enabled && key !== null, key },
    );
    if (!enabled || key === null) return;

    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let inFlight = false;

    const clearTimer = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    };
    const stop = () => {
      stopped = true;
      clearTimer();
      setState((s) => (s.key === key ? { ...s, active: false } : s));
    };
    const schedule = () => {
      clearTimer();
      if (stopped || isHidden()) return;
      timer = setTimeout(tick, intervalMs);
    };

    async function tick() {
      timer = null;
      if (stopped || inFlight) return;
      if (isHidden()) return; // resumed by visibilitychange
      inFlight = true;
      const c = new AbortController();
      controller = c;
      try {
        const data = await fnRef.current(c.signal);
        if (stopped || c.signal.aborted) return;
        setState((s) => (s.key === key ? { ...s, data, error: null, lastUpdated: new Date() } : s));
        if (isTerminalRef.current(data)) {
          stop();
          return;
        }
      } catch (err) {
        if (stopped || c.signal.aborted || isAbortError(err)) return;
        const apiErr = toApiError(err);
        setState((s) => (s.key === key ? { ...s, error: apiErr } : s));
        if (isFatal(apiErr)) {
          stop();
          return;
        }
      } finally {
        inFlight = false;
        if (controller === c) controller = null;
      }
      schedule();
    }

    const onVisibility = () => {
      if (stopped) return;
      if (isHidden()) clearTimer();
      else if (!inFlight && timer === null) void tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    void tick();

    return () => {
      stopped = true;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [key, enabled, intervalMs]);

  const current = state.key === key;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    lastUpdated: current ? state.lastUpdated : null,
    polling: current && state.active && enabled && key !== null,
  };
}

function isHidden(): boolean {
  return typeof document !== "undefined" && document.hidden;
}
