/** localStorage wrappers that never throw (private mode, blocked storage, quota). */
export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the app keeps working without persistence */
  }
}

export const STORAGE_KEYS = {
  demoUser: "graphathon.demoUser",
  investigationFor: (incidentId: string) => `graphathon.investigation.${incidentId}`,
} as const;
