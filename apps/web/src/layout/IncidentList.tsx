import { useApi } from "../api/client";
import type { IncidentSummary } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { EmptyState, ErrorBanner, SeverityBadge, Spinner, StatusBadge, cx } from "../components/ui";

export interface IncidentListProps {
  selectedId: string | null;
  onSelect: (incidentId: string) => void;
}

export function IncidentList({ selectedId, onSelect }: IncidentListProps) {
  const { client, user } = useApi();
  const { data, error, loading, reload } = useAsync(
    (signal) => client.listIncidents({ limit: 50 }, signal),
    [client, user],
  );

  return (
    <section aria-labelledby="incident-list-heading" className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id="incident-list-heading" className="text-lg font-semibold text-slate-900">
          Incidents
        </h2>
        <div className="flex items-center gap-2">
          {loading && data ? <Spinner size="sm" label="Refreshing incidents" /> : null}
          <button type="button" onClick={reload} className="btn-secondary" disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      <ErrorBanner error={error} title="Could not load incidents" onRetry={reload} />
      {loading && !data ? <Spinner label="Loading incidents…" /> : null}
      {data && data.items.length === 0 ? (
        <EmptyState title="No incidents">Ingest a synthetic alert to open one.</EmptyState>
      ) : null}

      {data && data.items.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Incident list">
          {data.items.map((inc) => (
            <li key={inc.id}>
              <IncidentRow incident={inc} selected={inc.id === selectedId} onSelect={onSelect} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function IncidentRow({
  incident,
  selected,
  onSelect,
}: {
  incident: IncidentSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(incident.id)}
      aria-current={selected ? "true" : undefined}
      className={cx(
        "w-full rounded-lg border p-3 text-left shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600",
        selected ? "border-sky-600 bg-sky-50 ring-1 ring-sky-600" : "border-slate-200 bg-white hover:border-slate-400",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-slate-900">{incident.key}</span>
        <SeverityBadge severity={incident.severity} />
        <StatusBadge status={incident.status} />
      </div>
      <p className="mt-1 text-sm text-slate-800">{incident.title}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
        <span>
          Services:{" "}
          <span className="font-mono">{incident.affected_service_ids.join(", ") || "none"}</span>
        </span>
        <span>
          {incident.alert_count} alert{incident.alert_count === 1 ? "" : "s"}
        </span>
      </div>
    </button>
  );
}
