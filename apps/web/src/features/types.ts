import type { DemoUser, IncidentDetail, InvestigationOut } from "../api/types";

/** Props every workspace tab receives. */
export interface TabProps {
  incident: IncidentDetail;
  investigation: InvestigationOut | null; // latest polled value, or null if none started
  user: DemoUser;
  reloadIncident: () => void; // refetch IncidentDetail
}

export const TAB_IDS = ["overview", "evidence", "activity", "memory", "review"] as const;
export type TabId = (typeof TAB_IDS)[number];

export const TAB_LABELS: Record<TabId, string> = {
  overview: "Overview",
  evidence: "Graph evidence",
  activity: "Agent activity",
  memory: "Memory & company brain",
  review: "Human review",
};

export function isTabId(value: unknown): value is TabId {
  return typeof value === "string" && (TAB_IDS as readonly string[]).includes(value);
}
