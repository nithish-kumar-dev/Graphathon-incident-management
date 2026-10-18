import type { ComponentType } from "react";
import { useApi } from "../api/client";
import { ErrorBanner, SeverityBadge, Spinner, StatusBadge, Tabs, type TabItem } from "../components/ui";
import ActivityTab from "../features/activity/ActivityTab";
import EvidenceTab from "../features/evidence/EvidenceTab";
import MemoryTab from "../features/memory/MemoryTab";
import OverviewTab from "../features/overview/OverviewTab";
import ReviewTab from "../features/review/ReviewTab";
import { TAB_IDS, TAB_LABELS, type TabId, type TabProps } from "../features/types";
import { useAsync } from "../hooks/useAsync";
import { useIncidentInvestigation } from "../hooks/useIncidentInvestigation";
import { InvestigateControls } from "./InvestigateControls";

const TAB_COMPONENTS: Record<TabId, ComponentType<TabProps>> = {
  overview: OverviewTab,
  evidence: EvidenceTab,
  activity: ActivityTab,
  memory: MemoryTab,
  review: ReviewTab,
};

export interface IncidentWorkspaceProps {
  incidentId: string;
  tab: TabId;
  onTabChange: (tab: TabId) => void;
}

/** Mount with `key={incidentId}` so investigation state never leaks between incidents. */
export function IncidentWorkspace({ incidentId, tab, onTabChange }: IncidentWorkspaceProps) {
  const { client, user } = useApi();
  const { data: incident, error, loading, reload } = useAsync(
    (signal) => client.getIncident(incidentId, signal),
    [client, incidentId, user],
  );
  const investigation = useIncidentInvestigation(incidentId);

  if (!incident) {
    return (
      <div className="flex flex-col gap-3">
        <ErrorBanner error={error} title="Could not load incident" onRetry={reload} />
        {loading ? <Spinner label="Loading incident…" /> : null}
      </div>
    );
  }

  const tabProps: TabProps = { incident, investigation: investigation.investigation, user, reloadIncident: reload };
  const tabs: TabItem<TabId>[] = TAB_IDS.map((id) => {
    const Component = TAB_COMPONENTS[id];
    return { id, label: TAB_LABELS[id], content: <Component {...tabProps} /> };
  });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold text-slate-700">{incident.key}</span>
          <StatusBadge status={incident.status} />
          <SeverityBadge severity={incident.severity} />
          {loading ? <Spinner size="sm" label="Refreshing incident" /> : null}
        </div>
        <h2 className="text-xl font-semibold text-slate-900">{incident.title}</h2>
        <p className="text-sm text-slate-700">
          Affected services:{" "}
          {incident.affected_services.length > 0
            ? incident.affected_services.map((s, i) => (
                <span key={s.id}>
                  {i > 0 ? ", " : null}
                  <span className="font-medium">{s.name ?? s.id}</span>{" "}
                  <code className="font-mono text-xs text-slate-500">{s.id}</code>
                  {s.tier ? <span className="text-xs text-slate-500"> ({s.tier})</span> : null}
                </span>
              ))
            : "none"}
        </p>
        <ErrorBanner error={error} title="Could not refresh incident" onRetry={reload} />
      </header>

      <InvestigateControls user={user} state={investigation} />

      <Tabs label="Incident sections" tabs={tabs} selectedId={tab} onSelect={onTabChange} />
    </div>
  );
}
