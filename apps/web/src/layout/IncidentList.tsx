import { useEffect, useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { IncidentSummary } from "../api/types";
import { EmptyState, ErrorBanner, SeverityBadge, Spinner, StatusBadge, cx } from "../components/ui";
import { STAGE_LABELS, STAGE_STATUS_LABELS, summarizeStage, type StageSummary } from "../features/investigation/model";
import { useAsync } from "../hooks/useAsync";
import { readStorage, STORAGE_KEYS } from "../lib/storage";
import { shortId } from "../lib/time";

export interface IncidentListProps {
  selectedId: string | null;
  onSelect: (incidentId: string) => void;
  /** Live stage summaries reported by the open incident workspace. */
  liveSummaries?: Readonly<Record<string, StageSummary>>;
}

type Scope = "active" | "resolved";

export function stageText(summary: StageSummary | undefined): string {
  if (!summary) return "Checking investigation…";
  if (summary.phase === "none" || !summary.stage) return "Not investigated";
  const status = summary.status ? STAGE_STATUS_LABELS[summary.status] : "";
  return `${STAGE_LABELS[summary.stage]} · ${status}`;
}

/** One request per incident that this browser has a remembered run for. Others are "Not investigated". */
function useRememberedSummaries(items: readonly IncidentSummary[] | undefined) {
  const { client } = useApi();
  const [summaries, setSummaries] = useState<Record<string, StageSummary>>({});
  useEffect(() => {
    if (!items) return;
    const ctl = new AbortController();
    const none: StageSummary = { phase: "none", stage: null, status: null };
    for (const inc of items) {
      const runId = readStorage(STORAGE_KEYS.investigationFor(inc.id));
      if (!runId) {
        setSummaries((s) => (s[inc.id] ? s : { ...s, [inc.id]: none }));
        continue;
      }
      client
        .getInvestigation(runId, ctl.signal)
        .then((inv) => setSummaries((s) => ({ ...s, [inc.id]: summarizeStage(inc, inv) })))
        .catch(() => setSummaries((s) => ({ ...s, [inc.id]: none })));
    }
    return () => ctl.abort();
  }, [client, items]);
  return summaries;
}

export function IncidentList({ selectedId, onSelect, liveSummaries }: IncidentListProps) {
  const { client, user } = useApi();
  const { data, error, loading, reload } = useAsync(
    (signal) => client.listIncidents({ limit: 50 }, signal),
    [client, user],
  );
  const [scope, setScope] = useState<Scope>("active");
  const remembered = useRememberedSummaries(data?.items);

  const { active, resolved } = useMemo(() => {
    const items = data?.items ?? [];
    return {
      active: items.filter((i) => i.status !== "resolved"),
      resolved: items.filter((i) => i.status === "resolved"),
    };
  }, [data]);
  const shown = scope === "active" ? active : resolved;

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

      <div role="group" aria-label="Incident scope" className="grid grid-cols-2 gap-1 rounded-lg bg-slate-200 p-1 text-sm">
        {(
          [
            ["active", "Active", active.length],
            ["resolved", "Resolved", resolved.length],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            aria-pressed={scope === id}
            onClick={() => setScope(id)}
            className={cx(
              "rounded-md px-2 py-1 font-medium focus-visible:outline-2 focus-visible:outline-sky-600",
              scope === id ? "bg-white text-slate-900 shadow-sm" : "text-slate-700 hover:bg-slate-100",
            )}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      <ErrorBanner error={error} title="Could not load incidents" onRetry={reload} />
      {loading && !data ? <Spinner label="Loading incidents…" /> : null}
      {data && data.items.length === 0 ? (
        <EmptyState title="No incidents">Ingest a synthetic alert to open one.</EmptyState>
      ) : null}
      {data && data.items.length > 0 && shown.length === 0 ? (
        <EmptyState title={scope === "active" ? "No active incidents" : "No resolved incidents"} />
      ) : null}

      {shown.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Incident list">
          {shown.map((inc) => (
            <li key={inc.id}>
              <IncidentRow
                incident={inc}
                selected={inc.id === selectedId}
                onSelect={onSelect}
                summary={liveSummaries?.[inc.id] ?? remembered[inc.id]}
              />
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
  summary,
}: {
  incident: IncidentSummary;
  selected: boolean;
  onSelect: (id: string) => void;
  summary: StageSummary | undefined;
}) {
  const service = incident.affected_service_ids[0];
  return (
    <button
      type="button"
      onClick={() => onSelect(incident.id)}
      aria-current={selected ? "true" : undefined}
      className={cx(
        "w-full rounded-lg border p-3 text-left shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600",
        selected ? "border-sky-600 bg-sky-50 ring-1 ring-sky-600" : "border-[#DDE5EF] bg-white hover:border-slate-400",
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
          Service: <span className="font-mono">{service ? shortId(service) : "none"}</span>
        </span>
        <span>
          {incident.alert_count} alert{incident.alert_count === 1 ? "" : "s"}
        </span>
      </div>
      <p className="mt-1 text-xs font-medium text-slate-700">{stageText(summary)}</p>
    </button>
  );
}
