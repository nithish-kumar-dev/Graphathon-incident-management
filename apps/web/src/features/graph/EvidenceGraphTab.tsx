import { useMemo, useRef, useState } from "react";
import { Badge, EmptyState, ErrorBanner, SectionCard, Spinner } from "../../components/ui";
import EvidenceTab from "../evidence/EvidenceTab";
import { useInvestigationSession } from "../investigation/InvestigationSession";
import { GraphCanvas } from "./GraphCanvas";
import { NodeDetailsPanel } from "./NodeDetailsPanel";
import { buildGraph, expandNode, focusedVisible } from "./model";

export default function EvidenceGraphTab() {
  const { incident, bundle, bundleError, bundleLoading, memories, run, user, reloadIncident } = useInvestigationSession();
  const model = useMemo(() => buildGraph({ incident, bundle, memories }), [incident, bundle, memories]);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const rawRecords = useRef<HTMLDetailsElement>(null);

  // The default view is focused: node cards are only readable a dozen or so at a time, so the rest of
  // the neighbourhood waits behind an expand. Anything the reader expands or selects stays on screen.
  const focused = useMemo(() => focusedVisible(model, incident), [model, incident]);
  const visible = useMemo(() => {
    let v = showAll ? new Set(model.nodes.keys()) : new Set(focused);
    for (const id of expanded) if (model.nodes.has(id)) v = expandNode(model, v, id);
    if (selectedId && model.nodes.has(selectedId)) v.add(selectedId);
    return v;
  }, [model, focused, expanded, showAll, selectedId]);

  const selected = selectedId ? (model.nodes.get(selectedId) ?? null) : null;
  const expand = (id: string) => setExpanded((s) => new Set([...s, id]));
  const reset = () => {
    setExpanded(new Set());
    setSelectedId(null);
    setShowAll(false);
    setResetToken((t) => t + 1);
  };
  const select = (id: string | null) => setSelectedId(id);
  const isolated = model.edges.length === 0;

  const openSourceRecords = () => {
    const el = rawRecords.current;
    if (!el) return;
    el.open = true;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const footer = (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span>
            {visible.size} of {model.nodes.size} related node{model.nodes.size === 1 ? "" : "s"} shown
          </span>
          {model.nodes.size > focused.size ? (
            <>
              <span aria-hidden="true" className="text-line-strong">
                ·
              </span>
              <button
                type="button"
                aria-pressed={showAll}
                className="rounded font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll ? "Back to the focused view" : `Show all ${model.nodes.size}`}
              </button>
            </>
          ) : null}
        </p>
        <details className="min-w-0">
          <summary className="cursor-pointer list-none text-[13px] font-bold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
            See all relationships ({model.edges.length}) <span aria-hidden="true">→</span>
          </summary>
          <ul className="mt-2 flex flex-col gap-0.5 font-mono text-[11px] text-ink">
            {model.edges.map((e) => (
              <li key={e.id} className="[overflow-wrap:anywhere]">
                {model.nodes.get(e.from)?.label} -[{e.rel}]→ {model.nodes.get(e.to)?.label}
                {e.derived ? " (derived)" : ""}
              </li>
            ))}
          </ul>
        </details>
      </div>
      <p className="text-xs text-faint">
        {showAll
          ? "Showing every node in the loaded context. "
          : "The view centres on the incident, its affected services and the records on its explanation paths; select or double-click a node to reveal its neighbours. "}
        {!bundle ? "Retrieval context has not loaded, so dependencies and ownership may be missing. " : ""}
        {run.investigation ? "" : "This is stored graph data, not the result of an agent run."}
      </p>
    </div>
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(19rem,3fr)]">
        <SectionCard
          title="Evidence graph"
          subtitle="Focused service dependencies and source-backed incident links"
          actions={<Badge tone="info" variant="outline">{incident.key} neighborhood</Badge>}
          footer={isolated ? undefined : footer}
          className="min-w-0"
        >
          <ErrorBanner
            error={bundleError}
            title="Could not load the full retrieval context; showing what the incident record contains"
            className="mb-3"
          />
          {bundleLoading && !bundle ? <Spinner label="Loading graph context…" className="mb-3" /> : null}
          {isolated ? (
            <EmptyState title="Nothing is connected to this incident yet" />
          ) : (
            <GraphCanvas
              model={model}
              visible={visible}
              selectedId={selectedId}
              onSelect={select}
              onExpand={expand}
              onReset={reset}
              resetToken={resetToken}
            />
          )}
        </SectionCard>

        <NodeDetailsPanel
          model={model}
          node={selected}
          visible={visible}
          onExpand={expand}
          onSelect={select}
          onOpenSources={openSourceRecords}
        />
      </div>

      <SectionCard title="Interpretation" className="min-w-0">
        <div className="border-l-4 border-warn pl-4">
          <p className="text-sm text-muted">
            The graph shows how {incident.key} is connected to the services, deployments and observations recorded around it. A
            connection is a correlation: it does not prove that any of them caused the incident.
          </p>
          <p className="mt-2.5 text-sm text-muted">
            Source events and service relationships are available for inspection below; investigate metrics and competing
            explanations before remediation.
          </p>
        </div>
      </SectionCard>

      <details ref={rawRecords} className="card p-5">
        <summary className="cursor-pointer text-sm font-bold text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
          Raw technical records (tables, ids, source refs)
        </summary>
        <div className="mt-4">
          <EvidenceTab incident={incident} investigation={run.investigation} user={user} reloadIncident={reloadIncident} />
        </div>
      </details>
    </div>
  );
}
