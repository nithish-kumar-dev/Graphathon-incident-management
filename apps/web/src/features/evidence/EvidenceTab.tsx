import { useMemo } from "react";
import { isAbortError, toApiError, useApi } from "../../api/client";
import type { EvidenceOut, ExplanationPath, IncidentDetail } from "../../api/types";
import { Badge, Card, CodeBlock, EmptyState, cx } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { TD, TD_ID, TD_REF, TH, TableScroll, UtcTime } from "../overview/format";
import type { TabProps } from "../types";
import { PathsSection } from "./PathsSection";
import { ServiceContextSection, type ServiceContextResult } from "./ServiceContextSection";
import { collectSourceRefs, type SourceRefEntry } from "./sourceRefs";

/** Distinct path target services, or the first affected service when there is no path. */
function contextServiceIds(incident: IncidentDetail): { ids: string[]; fromPaths: boolean } {
  const fromPaths = [...new Set(incident.explanation_paths.map((p) => p.target_service_id))];
  if (fromPaths.length > 0) return { ids: fromPaths, fromPaths: true };
  const first = incident.affected_service_ids[0] ?? incident.affected_services[0]?.id;
  return { ids: first ? [first] : [], fromPaths: false };
}

/** Evidence ids an explanation path relies on (its evidence list plus any Evidence node in its hops). */
function pathEvidenceIds(paths: ExplanationPath[]): Set<string> {
  const ids = new Set<string>();
  for (const p of paths) {
    for (const e of p.evidence) ids.add(e.id);
    for (const h of p.hops) {
      if (h.from_label === "Evidence") ids.add(h.from_id);
      if (h.to_label === "Evidence") ids.add(h.to_id);
    }
  }
  return ids;
}

export default function EvidenceTab({ incident, user }: TabProps) {
  const { client } = useApi();
  const { ids: serviceIds, fromPaths } = useMemo(() => contextServiceIds(incident), [incident]);
  const idsKey = serviceIds.join("\n");

  const contexts = useAsync(
    (signal) =>
      Promise.all(
        serviceIds.map((id) =>
          client.getServiceContext(id, { depth: 2 }, signal).then(
            (data): ServiceContextResult => ({ id, data, error: null }),
            (err: unknown): ServiceContextResult => {
              if (isAbortError(err)) throw err;
              return { id, data: null, error: toApiError(err) };
            },
          ),
        ),
      ),
    [client, incident.id, idsKey, user],
  );

  const usedIds = useMemo(() => pathEvidenceIds(incident.explanation_paths), [incident.explanation_paths]);
  const sourceRefs = useMemo(
    () => collectSourceRefs(incident, (contexts.data ?? []).flatMap((r) => (r.data ? [r.data] : []))),
    [incident, contexts.data],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PathsSection paths={incident.explanation_paths} />
      <EvidenceTable evidence={incident.evidence} usedIds={usedIds} />
      <ServiceContextSection
        serviceIds={serviceIds}
        fromPaths={fromPaths}
        results={contexts.data}
        loading={contexts.loading}
        error={contexts.error}
        reload={contexts.reload}
      />
      <SourceRefsSection entries={sourceRefs} />
    </div>
  );
}

function IdList({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <ul className="flex flex-col gap-0.5">
      {ids.map((id) => (
        <li key={id}>
          <CodeBlock inline value={id} />
        </li>
      ))}
    </ul>
  );
}

function EvidenceTable({ evidence, usedIds }: { evidence: EvidenceOut[]; usedIds: Set<string> }) {
  return (
    <Card title="Evidence" subtitle={`${evidence.length} item${evidence.length === 1 ? "" : "s"} attached to this incident.`}>
      {evidence.length === 0 ? (
        <EmptyState title="No evidence attached to this incident" />
      ) : (
        <TableScroll label="Evidence table">
          <table className="min-w-full border-collapse">
            <caption className="sr-only">Incident evidence; rows used by an explanation path are marked</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Id</th>
                <th scope="col" className={TH}>Kind</th>
                <th scope="col" className={TH}>Observed at</th>
                <th scope="col" className={TH}>Excerpt</th>
                <th scope="col" className={TH}>Source ref</th>
                <th scope="col" className={TH}>Observed on</th>
                <th scope="col" className={TH}>Refers to deployment</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((e) => {
                const used = usedIds.has(e.id);
                return (
                  <tr key={e.id} className={cx(used && "bg-amber-50/60")} data-used-in-path={used ? "true" : undefined}>
                    <th scope="row" className={cx(TD_ID, "text-left font-normal")}>
                      <CodeBlock inline value={e.id} />
                      {used ? (
                        <div className="mt-1">
                          <Badge tone="warning" variant="dashed" title="Cited by an explanation path (a correlation, not proof)">
                            used in path
                          </Badge>
                        </div>
                      ) : null}
                    </th>
                    <td className={TD}>{e.kind}</td>
                    <td className={TD}>
                      <UtcTime iso={e.observed_at} />
                    </td>
                    <td className={cx(TD, "min-w-48")}>{e.excerpt ?? <span className="text-slate-500">—</span>}</td>
                    <td className={TD_REF}>
                      <CodeBlock inline value={e.source_ref} />
                    </td>
                    <td className={TD_ID}>
                      <IdList ids={e.observed_on_service_ids} />
                    </td>
                    <td className={TD_ID}>
                      <IdList ids={e.refers_to_deployment_ids} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
      )}
    </Card>
  );
}

function SourceRefsSection({ entries }: { entries: SourceRefEntry[] }) {
  return (
    <Card
      title="Source references"
      subtitle="Every synthetic source reference on this tab, with the record it belongs to. These are identifiers, not links."
    >
      {entries.length === 0 ? (
        <EmptyState title="No source references on this tab" />
      ) : (
        <TableScroll label="Source references table">
          <table className="min-w-full border-collapse">
            <caption className="sr-only">Deduplicated source references and the ids they belong to</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Source ref</th>
                <th scope="col" className={TH}>Belongs to</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.ref}>
                  <th scope="row" className={cx(TD_REF, "text-left font-normal")}>
                    <CodeBlock inline value={entry.ref} />
                  </th>
                  <td className={TD_ID}>
                    <ul className="flex flex-col gap-0.5">
                      {entry.owners.map((o) => (
                        <li key={`${o.kind}:${o.id}`}>
                          <span className="text-xs text-slate-500">{o.kind}</span> <CodeBlock inline value={o.id} />
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </Card>
  );
}
