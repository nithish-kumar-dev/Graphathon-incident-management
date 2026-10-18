import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
  if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
});
