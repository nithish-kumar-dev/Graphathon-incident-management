import type { DemoUser, IncidentDetail, InvestigationOut } from "../api/types";

/** Props every workspace tab receives. */
export interface TabProps {
  incident: IncidentDetail;
  investigation: InvestigationOut | null; // latest polled value, or null if none started
  user: DemoUser;
  reloadIncident: () => void; // refetch IncidentDetail
}

export const TAB_IDS = ["live", "evidence", "knowledge", "review", "history"] as const;
export type TabId = (typeof TAB_IDS)[number];

export const TAB_LABELS: Record<TabId, string> = {
  live: "Live Investigation",
  evidence: "Evidence Graph",
  knowledge: "Knowledge & Memory",
  review: "Human Review",
  history: "History",
};

/** Hash tab names from earlier versions of the UI, kept so old links still resolve. */
export const LEGACY_TABS: Record<string, TabId> = {
  overview: "live",
  activity: "history",
  memory: "knowledge",
};

export function isTabId(value: unknown): value is TabId {
  return typeof value === "string" && (TAB_IDS as readonly string[]).includes(value);
}
