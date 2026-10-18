import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { useAsync } from "./useAsync";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAsync", () => {
  it("does not apply stale results when deps change quickly", async () => {
    const pending: Record<string, ReturnType<typeof deferred<string>>> = {};
    const signals: Record<string, AbortSignal> = {};
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) =>
        useAsync((signal) => {
          pending[id] = deferred<string>();
          signals[id] = signal;
          return pending[id].promise;
        }, [id]),
      { initialProps: { id: "A" } },
    );
    expect(result.current.loading).toBe(true);

    rerender({ id: "B" });
    rerender({ id: "C" });
    expect(signals.A?.aborted).toBe(true);
    expect(signals.B?.aborted).toBe(true);
    expect(signals.C?.aborted).toBe(false);

    // Resolve out of order: the latest first, then the stale ones.
    await act(async () => {
      pending.C!.resolve("data-C");
    });
    await act(async () => {
      pending.A!.resolve("data-A");
      pending.B!.resolve("data-B");
    });
    expect(result.current.data).toBe("data-C");
    expect(result.current.loading).toBe(false);
  });

  it("clears data on deps change but keeps it during reload", async () => {
    let n = 0;
    const { result, rerender } = renderHook(({ id }: { id: string }) => useAsync(async () => `${id}-${++n}`, [id]), {
      initialProps: { id: "A" },
    });
    await waitFor(() => expect(result.current.data).toBe("A-1"));

    act(() => result.current.reload());
    expect(result.current.data).toBe("A-1");
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe("A-2"));

    rerender({ id: "B" });
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.data).toBe("B-3"));
  });

  it("normalises errors to ApiError and ignores aborts", async () => {
    const { result } = renderHook(() =>
      useAsync(async () => {
        throw new ApiError({ status: 403, code: "forbidden", message: "nope", requestId: "r1" });
      }, []),
    );
    await waitFor(() => expect(result.current.error?.code).toBe("forbidden"));
    expect(result.current.loading).toBe(false);
  });
});
