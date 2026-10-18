import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { ApiError, isAbortError, toApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** Re-run the request with the same deps. Keeps the current data visible while loading. */
  reload: () => void;
}

function sameDeps(a: DependencyList | null, b: DependencyList): boolean {
  return a !== null && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
}

/**
 * Run `fn` whenever `deps` change (or `reload()` is called).
 *
 * - The previous request is aborted on deps change, reload and unmount.
 * - Each request is keyed by a counter; a result from anything but the latest request is dropped,
 *   so data for incident A can never appear after switching to incident B.
 * - When deps change, `data` resets to null (no stale data from the previous key). On `reload()`
 *   the old data stays until the new result arrives.
 * - Aborts are not errors. Other failures are normalised to ApiError.
 */
export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const requestId = useRef(0);
  const prevDeps = useRef<DependencyList | null>(null);

  useEffect(() => {
    const id = ++requestId.current;
    const keyChanged = !sameDeps(prevDeps.current, deps);
    prevDeps.current = deps;
    const controller = new AbortController();
    const isCurrent = () => id === requestId.current && !controller.signal.aborted;

    setState((s) => ({ data: keyChanged ? null : s.data, error: null, loading: true }));

    let promise: Promise<T>;
    try {
      promise = fnRef.current(controller.signal);
    } catch (err) {
      promise = Promise.reject(err);
    }
    promise.then(
      (data) => {
        if (isCurrent()) setState({ data, error: null, loading: false });
      },
      (err: unknown) => {
        if (!isCurrent() || isAbortError(err)) return;
        setState((s) => ({ data: s.data, error: toApiError(err), loading: false }));
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  const reload = useCallback(() => setReloadToken((t) => t + 1), []);
  return { ...state, reload };
}
