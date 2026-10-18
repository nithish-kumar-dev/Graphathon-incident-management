import { useCallback, useEffect, useState } from "react";
import { isTabId, LEGACY_TABS, type TabId } from "../features/types";

/** Route encoded in the URL hash: `#/incidents/<id>` or `#/incidents/<id>/<tab>`. */
export interface HashRoute {
  incidentId: string | null;
  tab: TabId;
}

export const DEFAULT_TAB: TabId = "live";

export function parseHash(hash: string): HashRoute {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] !== "incidents" || !parts[1]) return { incidentId: null, tab: DEFAULT_TAB };
  let incidentId: string;
  try {
    incidentId = decodeURIComponent(parts[1]);
  } catch {
    return { incidentId: null, tab: DEFAULT_TAB };
  }
  return { incidentId, tab: isTabId(parts[2]) ? parts[2] : (parts[2] ? LEGACY_TABS[parts[2]] : undefined) ?? DEFAULT_TAB };
}

export function buildHash(route: { incidentId: string | null; tab?: TabId }): string {
  if (!route.incidentId) return "#/";
  const base = `#/incidents/${encodeURIComponent(route.incidentId)}`;
  return route.tab ? `${base}/${route.tab}` : base;
}

/** Current hash route plus a navigate function. Back/forward work through `hashchange`. */
export function useHashRoute(): [HashRoute, (next: { incidentId: string | null; tab?: TabId }) => void] {
  const [route, setRoute] = useState<HashRoute>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: { incidentId: string | null; tab?: TabId }) => {
    const hash = buildHash(next);
    if (window.location.hash !== hash) window.location.hash = hash;
    // Update synchronously too; hashchange fires async and would otherwise lag one frame.
    setRoute(parseHash(hash));
  }, []);

  return [route, navigate];
}
