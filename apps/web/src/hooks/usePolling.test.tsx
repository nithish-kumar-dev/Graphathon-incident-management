import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InvestigationOut, InvestigationStatus } from "../api/types";
import { fixtures } from "../test/mockApi";
import { isTerminalInvestigation, usePolling } from "./usePolling";

const inv = (status: InvestigationStatus): InvestigationOut =>
  ({ ...fixtures.investigation_queued, status }) as InvestigationOut;

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("isTerminalInvestigation knows the terminal states", () => {
    for (const s of ["completed", "failed", "escalated", "inconclusive", "timed_out"]) {
      expect(isTerminalInvestigation(s)).toBe(true);
    }
    for (const s of ["queued", "running", "awaiting_review"]) expect(isTerminalInvestigation(s)).toBe(false);
  });

  it("polls every interval and stops at a terminal status", async () => {
    const sequence: InvestigationStatus[] = ["queued", "running", "completed"];
    let calls = 0;
    const fn = vi.fn(async () => inv(sequence[Math.min(calls++, sequence.length - 1)]!));

    const { result } = renderHook(() =>
      usePolling(fn, {
        intervalMs: 2500,
        enabled: true,
        key: "nova.ses.01example",
        isTerminal: (i) => isTerminalInvestigation(i.status),
      }),
    );

    await advance(0);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(result.current.data?.status).toBe("queued");
    expect(result.current.polling).toBe(true);
    expect(result.current.lastUpdated).toBeInstanceOf(Date);

    await advance(2499);
    expect(fn).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(result.current.data?.status).toBe("running");

    await advance(2500);
    expect(fn).toHaveBeenCalledTimes(3);
    expect(result.current.data?.status).toBe("completed");
    expect(result.current.polling).toBe(false);

    await advance(10_000);
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("does not poll while disabled and resets on key change", async () => {
    const fn = vi.fn(async () => inv("queued"));
    const { result, rerender } = renderHook(
      ({ key, enabled }: { key: string | null; enabled: boolean }) =>
        usePolling(fn, { enabled, key, isTerminal: (i) => isTerminalInvestigation(i.status) }),
      { initialProps: { key: null as string | null, enabled: false } },
    );
    await advance(5000);
    expect(fn).not.toHaveBeenCalled();
    expect(result.current.polling).toBe(false);

    rerender({ key: "a", enabled: true });
    await advance(0);
    expect(result.current.data?.status).toBe("queued");

    rerender({ key: "b", enabled: true });
    expect(result.current.data).toBeNull();
  });

  it("pauses while the document is hidden", async () => {
    const fn = vi.fn(async () => inv("running"));
    let hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    renderHook(() => usePolling(fn, { enabled: true, key: "k", isTerminal: (i) => isTerminalInvestigation(i.status) }));
    await advance(0);
    expect(fn).toHaveBeenCalledTimes(1);

    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    await advance(10_000);
    expect(fn).toHaveBeenCalledTimes(1);

    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    await advance(0);
    expect(fn).toHaveBeenCalledTimes(2);
  });
});
