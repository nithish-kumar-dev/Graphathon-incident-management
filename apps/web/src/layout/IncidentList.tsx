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
    <section aria-labelledby="incident-list-heading" className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-2">
        <h2 id="incident-list-heading" className="text-[17px] font-bold text-ink">
          Incidents
        </h2>
        <div className="flex items-center gap-2">
          {loading && data ? <Spinner size="sm" label="Refreshing incidents" /> : null}
          <button
            type="button"
            onClick={reload}
            disabled={loading}
            className="rounded-md px-2 py-1 text-xs font-semibold text-brand hover:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:text-faint"
          >
            Refresh
          </button>
        </div>
      </div>

      <div role="group" aria-label="Incident scope" className="flex flex-wrap gap-2 text-xs">
        {(
          [
            ["active", "ACTIVE", active.length],
            ["resolved", "RESOLVED", resolved.length],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            aria-pressed={scope === id}
            onClick={() => setScope(id)}
            className={cx(
              "rounded-full border px-3.5 py-1.5 font-semibold tracking-wide focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
              scope === id
                ? "border-brand bg-brand-tint text-brand"
                : "border-line bg-surface text-muted hover:border-line-strong hover:text-ink",
            )}
          >
            {count} {label}
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

      <div className="mt-2 border-t border-line pt-4">
        <p className="kicker">Workspace</p>
        <p className="mt-2 text-xs font-semibold text-ink">NovaCommerce</p>
        <p className="text-[11px] text-muted">Synthetic incident data</p>
        <p className="mt-2 text-[11px] text-faint">No production actions</p>
      </div>
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
        "relative w-full overflow-hidden rounded-lg border p-3.5 pl-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
        selected ? "border-brand bg-brand-tint" : "border-line bg-surface hover:border-line-strong",
      )}
    >
      {selected ? <span aria-hidden="true" className="absolute inset-y-2.5 left-0 w-[3px] rounded-full bg-brand" /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-bold text-ink">{incident.key}</span>
        <SeverityBadge severity={incident.severity} />
        <StatusBadge status={incident.status} />
      </div>
      <p className="mt-2 text-[13px] font-semibold leading-snug text-ink">{incident.title}</p>
      <p className="mt-2 text-[11px] text-muted">
        <span>{service ? shortId(service) : "no service"}</span>
        <span aria-hidden="true"> · </span>
        <span>
          {incident.alert_count} alert{incident.alert_count === 1 ? "" : "s"}
        </span>
      </p>
      <p className="mt-1 text-[11px] font-semibold text-brand">{stageText(summary)}</p>
    </button>
  );
}
