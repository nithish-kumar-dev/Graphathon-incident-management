import { Fragment, type ReactNode } from "react";
import type { ApiError } from "../../api/client";
import type { DependencyOut, ServiceContext } from "../../api/types";
import { Badge, Card, CodeBlock, EmptyState, ErrorBanner, Spinner } from "../../components/ui";
import { RelArrow, UtcTime } from "../overview/format";

export interface ServiceContextResult {
  id: string;
  data: ServiceContext | null;
  error: ApiError | null;
}

const SUBHEAD = "mt-4 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500";

function None({ children }: { children: ReactNode }) {
  return <p className="text-sm text-slate-600">{children}</p>;
}

/** Service ids along DEPENDS_ON in stored direction, joined by the relationship arrow. */
function DependencyPath({ path }: { path: string[] }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {path.map((id, i) => (
        <Fragment key={`${i}-${id}`}>
          {i > 0 ? <RelArrow rel="DEPENDS_ON" /> : null}
          <CodeBlock inline value={id} />
        </Fragment>
      ))}
    </span>
  );
}

function DependencyList({ items, label }: { items: DependencyOut[]; label: string }) {
  if (items.length === 0) return <None>None within the requested depth.</None>;
  return (
    <ul aria-label={label} className="flex flex-col gap-1.5 text-sm">
      {items.map((d) => (
        <li key={`${d.service.id}-${d.path.join(">")}`}>
          <span className="font-medium">{d.service.name ?? d.service.id}</span>{" "}
          <span className="text-xs text-slate-500">
            depth {d.depth}
            {d.service.tier ? ` · ${d.service.tier}` : ""}
          </span>
          <div className="mt-0.5">
            <DependencyPath path={d.path} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function ContextBody({ ctx }: { ctx: ServiceContext }) {
  return (
    <>
      <h5 className={SUBHEAD}>Owners</h5>
      {ctx.owners.length === 0 ? (
        <None>No owning team recorded.</None>
      ) : (
        <ul aria-label={`Owners of ${ctx.service.id}`} className="flex flex-col gap-2 text-sm">
          {ctx.owners.map((team) => (
            <li key={team.id}>
              <span className="font-medium">{team.name}</span> <CodeBlock inline value={team.id} />
              {team.members.length > 0 ? (
                <ul aria-label={`Members of ${team.id}`} className="mt-1 flex flex-col gap-0.5 pl-4">
                  {team.members.map((m) => (
                    <li key={m.id} className="flex flex-wrap items-center gap-1">
                      <CodeBlock inline value={m.handle} />
                      {(m.roles ?? []).map((r) => (
                        <Badge key={r} tone="neutral" variant="outline">
                          {r}
                        </Badge>
                      ))}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="pl-4 text-xs text-slate-500">No members recorded.</p>
              )}
            </li>
          ))}
        </ul>
      )}

      <h5 className={SUBHEAD}>Dependencies (this service DEPENDS_ON)</h5>
      <DependencyList items={ctx.dependencies} label={`Dependencies of ${ctx.service.id}`} />

      <h5 className={SUBHEAD}>Dependents (DEPENDS_ON this service)</h5>
      <DependencyList items={ctx.dependents} label={`Dependents of ${ctx.service.id}`} />

      <h5 className={SUBHEAD}>Active decisions</h5>
      {ctx.active_decisions.length === 0 ? (
        <None>No active decision governs this service.</None>
      ) : (
        <ul aria-label={`Active decisions for ${ctx.service.id}`} className="flex flex-col gap-2 text-sm">
          {ctx.active_decisions.map((d) => (
            <li key={d.id} className="rounded-md border border-slate-200 p-2">
              <span className="font-medium">{d.title}</span> <CodeBlock inline value={d.id} />{" "}
              <span className="text-xs text-slate-500">status {d.status}</span>
              <p className="mt-1 text-slate-700">{d.statement}</p>
              <p className="mt-1 text-xs text-slate-600">
                Effective <UtcTime iso={d.effective_from} />
                {d.effective_to ? (
                  <>
                    {" "}
                    to <UtcTime iso={d.effective_to} />
                  </>
                ) : null}{" "}
                · approver role{" "}
                {d.required_approver_role ? <CodeBlock inline value={d.required_approver_role} /> : "not recorded"}
              </p>
              {d.documented_in.length > 0 ? (
                <ul aria-label={`Documents for ${d.id}`} className="mt-1 text-xs text-slate-600">
                  {d.documented_in.map((doc) => (
                    <li key={doc.id}>
                      Documented in <CodeBlock inline value={doc.id} /> {doc.title ?? ""}
                      {doc.uri ? (
                        <>
                          {" "}
                          · <CodeBlock inline value={doc.uri} />
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {d.supersedes.length > 0 ? (
                <p className="mt-1 text-xs text-slate-600">
                  Supersedes{" "}
                  {d.supersedes.map((s, i) => (
                    <span key={s}>
                      {i > 0 ? ", " : null}
                      <CodeBlock inline value={s} />
                    </span>
                  ))}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <h5 className={SUBHEAD}>Runbooks</h5>
      {ctx.runbooks.length === 0 ? (
        <None>No runbook applies to this service.</None>
      ) : (
        <ul aria-label={`Runbooks for ${ctx.service.id}`} className="flex flex-col gap-1 text-sm">
          {ctx.runbooks.map((r) => (
            <li key={r.id}>
              <span className="font-medium">{r.title}</span> <CodeBlock inline value={r.id} />{" "}
              <span className="text-xs text-slate-500">version {r.version}</span>
              {r.uri ? (
                <>
                  {" "}
                  · <CodeBlock inline value={r.uri} />
                </>
              ) : null}
              {(r.allowed_action_types ?? []).length > 0 ? (
                <div className="text-xs text-slate-600">
                  Allowed:{" "}
                  {(r.allowed_action_types ?? []).map((a, i) => (
                    <span key={a}>
                      {i > 0 ? ", " : null}
                      <CodeBlock inline value={a} />
                    </span>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <h5 className={SUBHEAD}>Recent deployments</h5>
      {ctx.recent_deployments.length === 0 ? (
        <None>No recent deployments in the lookback window.</None>
      ) : (
        <ul aria-label={`Recent deployments of ${ctx.service.id}`} className="flex flex-col gap-1 text-sm">
          {ctx.recent_deployments.map((dep) => (
            <li key={dep.id}>
              <CodeBlock inline value={dep.id} /> <span className="font-medium">{dep.version}</span>{" "}
              <span className="text-xs text-slate-600">
                <UtcTime iso={dep.deployed_at} />
                {dep.status ? ` · ${dep.status}` : ""}
              </span>
              {dep.source_ref ? (
                <>
                  {" "}
                  · <CodeBlock inline value={dep.source_ref} />
                </>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export interface ServiceContextSectionProps {
  serviceIds: string[];
  /** True when the ids come from explanation paths; false when falling back to the first affected service. */
  fromPaths: boolean;
  results: ServiceContextResult[] | null;
  loading: boolean;
  /** Error that failed the whole batch (rare: each service normally reports its own error). */
  error: ApiError | null;
  reload: () => void;
}

export function ServiceContextSection({ serviceIds, fromPaths, results, loading, error, reload }: ServiceContextSectionProps) {
  return (
    <Card
      title="Target service context"
      subtitle={
        fromPaths
          ? "Owners, dependencies, decisions, runbooks and deployments for each path's target service (depth 2)."
          : "No explanation path, so this shows the first affected service (depth 2)."
      }
      actions={loading && results ? <Spinner size="sm" label="Refreshing service context" /> : null}
    >
      {serviceIds.length === 0 ? (
        <EmptyState title="No service to show">This incident has no explanation path and no affected service.</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <ErrorBanner error={error} title="Could not load service context" onRetry={reload} />
          {!results && loading ? <Spinner label="Loading service context…" /> : null}
          {results?.map((r) => (
            <section key={r.id} aria-label={`Service context for ${r.id}`} className="min-w-0">
              <h4 className="text-sm font-semibold text-slate-900">
                {r.data?.service.name ?? "Service"} <CodeBlock inline value={r.id} />
                {r.data?.service.tier ? <span className="text-xs font-normal text-slate-500"> ({r.data.service.tier})</span> : null}
              </h4>
              {r.error ? (
                <ErrorBanner error={r.error} title={`Could not load context for ${r.id}`} onRetry={reload} className="mt-2" />
              ) : r.data ? (
                <ContextBody ctx={r.data} />
              ) : null}
            </section>
          ))}
        </div>
      )}
    </Card>
  );
}
