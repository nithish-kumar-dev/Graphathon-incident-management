import { useEffect, type ReactNode } from "react";
import { useApi } from "../api/client";
import type { IncidentStatus } from "../api/types";
import { ErrorBanner, Spinner, Tabs, type TabItem } from "../components/ui";
import EvidenceGraphTab from "../features/graph/EvidenceGraphTab";
import HistoryTab from "../features/history/HistoryTab";
import { InvestigationSessionProvider, useInvestigationSession } from "../features/investigation/InvestigationSession";
import LiveInvestigationTab from "../features/investigation/LiveInvestigationTab";
import { ProcessTracker } from "../features/investigation/ProcessTracker";
import { summarizeStage, type StageSummary } from "../features/investigation/model";
import KnowledgeMemoryTab from "../features/knowledge/KnowledgeMemoryTab";
import { NavProvider } from "../features/NavContext";
import HumanReviewTab from "../features/review/HumanReviewTab";
import { TAB_IDS, TAB_LABELS, type TabId } from "../features/types";
import { useAsync } from "../hooks/useAsync";
import { IncidentHeader, RunBanner } from "./IncidentHeader";

const TAB_CONTENT: Record<TabId, () => ReactNode> = {
  live: () => <LiveInvestigationTab />,
  evidence: () => <EvidenceGraphTab />,
  knowledge: () => <KnowledgeMemoryTab />,
  review: () => <HumanReviewTab />,
  history: () => <HistoryTab />,
};

export interface IncidentWorkspaceProps {
  incidentId: string;
  /** Change it to refetch the incident and every tab (e.g. after a demo graph change). */
  refreshKey?: number;
  tab: TabId;
  onTabChange: (tab: TabId) => void;
  /** Reports the live stage so the incident navigator can show it without extra requests. */
  onSummaryChange?: (incidentId: string, summary: StageSummary) => void;
  /** Reports the incident's current status (e.g. open -> investigating) so the navigator badge follows it. */
  onStatusChange?: (incidentId: string, status: IncidentStatus) => void;
}

export function IncidentWorkspace({ incidentId, refreshKey = 0, tab, onTabChange, onSummaryChange, onStatusChange }: IncidentWorkspaceProps) {
  const { client, user } = useApi();
  const { data: incident, error, loading, reload } = useAsync(
    (signal) => client.getIncident(incidentId, signal),
    [client, incidentId, user, refreshKey],
  );

  if (!incident) {
    return (
      <div className="flex flex-col gap-3">
        <ErrorBanner error={error} title="Could not load incident" onRetry={reload} />
        {loading ? <Spinner label="Loading incident…" /> : null}
      </div>
    );
  }

  return (
    <InvestigationSessionProvider key={incident.id} incident={incident} incidentRefreshing={loading} reloadIncident={reload}>
      <NavProvider value={onTabChange}>
        <Workspace tab={tab} onTabChange={onTabChange} onSummaryChange={onSummaryChange} onStatusChange={onStatusChange} />
      </NavProvider>
    </InvestigationSessionProvider>
  );
}

function Workspace({
  tab,
  onTabChange,
  onSummaryChange,
  onStatusChange,
}: {
  tab: TabId;
  onTabChange: (tab: TabId) => void;
  onSummaryChange?: (incidentId: string, summary: StageSummary) => void;
  onStatusChange?: (incidentId: string, status: IncidentStatus) => void;
}) {
  const { incident, run, view, user } = useInvestigationSession();

  useEffect(() => {
    onStatusChange?.(incident.id, incident.status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incident.id, incident.status]);

  const status = run.investigation?.status ?? "none";
  const stage = view.currentStage;
  useEffect(() => {
    onSummaryChange?.(incident.id, summarizeStage(incident, run.investigation));
    // Only the phase or current stage matters for the navigator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incident.id, status, stage]);

  const viewInvestigation = () => {
    onTabChange("live");
    setTimeout(() => {
      const el = document.getElementById("agent-monitor");
      el?.scrollIntoView?.({ block: "start" });
      el?.focus();
    }, 0);
  };

  const tabs: TabItem<TabId>[] = TAB_IDS.map((id) => ({ id, label: TAB_LABELS[id], content: TAB_CONTENT[id]() }));

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <IncidentHeader user={user} onViewInvestigation={viewInvestigation} />
      <RunBanner compact={tab !== "live"} onViewWorkstream={tab !== "live" ? viewInvestigation : undefined} />
      {/* Above the tabs so progress is visible from every section. */}
      <ProcessTracker stages={view.stages} compact={tab !== "live"} />
      <Tabs label="Incident sections" tabs={tabs} selectedId={tab} onSelect={onTabChange} />
    </div>
  );
}
