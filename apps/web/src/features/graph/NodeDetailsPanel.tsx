import { ArrowLink, Badge, Kicker, type BadgeTone } from "../../components/ui";
import { KIND_META, hiddenNeighborCount, type GraphEdge, type GraphModel, type GraphNode } from "./model";

const TONES: Record<string, BadgeTone> = {
  incident: "info",
  service: "success",
  deployment: "accent",
  evidence: "danger",
  decision: "warning",
  runbook: "warning",
  document: "neutral",
  memory: "neutral",
  team: "info",
};

const HEADING = "text-sm font-bold text-ink";

/** Detail labels that carry a pointer back to a synthetic source record. */
const SOURCE_LABELS = new Set(["Source", "URI"]);

export interface NodeDetailsPanelProps {
  model: GraphModel;
  node: GraphNode | null;
  visible: ReadonlySet<string>;
  onExpand: (id: string) => void;
  onSelect: (id: string) => void;
  /** Opens the raw source records below the graph. */
  onOpenSources?: () => void;
}

export function NodeDetailsPanel({ model, node, visible, onExpand, onSelect, onOpenSources }: NodeDetailsPanelProps) {
  if (!node) {
    return (
      <aside aria-label="Selected entity" className="card flex min-w-0 flex-col gap-2 border-dashed bg-surface-muted p-5">
        <Kicker>Selected entity</Kicker>
        <p className="text-base font-bold text-ink">Nothing selected</p>
        <p className="text-sm text-muted">
          Select a node to see what it is, why it appears and how it connects. Double-click a node, or use Expand, to reveal its
          neighbours.
        </p>
      </aside>
    );
  }
  const meta = KIND_META[node.kind];
  const outgoing = model.edges.filter((e) => e.from === node.id);
  const incoming = model.edges.filter((e) => e.to === node.id);
  const relationships = [...outgoing, ...incoming];
  const hidden = hiddenNeighborCount(model, visible, node.id);
  const label = (id: string) => model.nodes.get(id)?.label ?? id;
  const idDetail = node.details.find((d) => d.label === "Id")?.value ?? node.id;
  const sources = node.details.filter((d) => SOURCE_LABELS.has(d.label));
  const facts = node.details.filter((d) => d.label !== "Id" && !SOURCE_LABELS.has(d.label));

  const relRow = (e: GraphEdge) => {
    const other = e.from === node.id ? e.to : e.from;
    return (
      <li key={e.id}>
        <button
          type="button"
          className="flex w-full flex-col gap-0.5 rounded-md border border-line bg-surface-sunken px-3 py-2 text-left hover:border-brand-line hover:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
          onClick={() => onSelect(other)}
        >
          <span className="text-[13px] font-bold text-ink [overflow-wrap:anywhere]">{label(e.from)}</span>
          <span className="text-[11px] font-semibold text-brand [overflow-wrap:anywhere]">
            {e.rel} <span aria-hidden="true">→</span> {label(e.to)}
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            {e.derived ? (
              <Badge tone="warning" variant="dashed" title="Inferred by the UI, not read from the graph">
                derived
              </Badge>
            ) : null}
            {!visible.has(other) ? <span className="text-[11px] text-faint">Hidden in this view</span> : null}
          </span>
        </button>
      </li>
    );
  };

  return (
    <aside aria-label="Selected entity" className="card flex min-w-0 flex-col gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Kicker>Selected entity</Kicker>
        <Badge tone={TONES[node.kind] ?? "neutral"}>{meta.label}</Badge>
      </div>
      <div className="min-w-0">
        <h3 className="text-xl font-bold leading-tight text-ink [overflow-wrap:anywhere]">{node.label}</h3>
        <p className="mt-1 font-mono text-[13px] text-muted [overflow-wrap:anywhere]">{idDetail}</p>
      </div>

      <div className="border-t border-line pt-4">
        <h4 className={HEADING}>Why it appears</h4>
        <p className="mt-1.5 text-sm text-muted">{node.why}</p>
      </div>

      <div>
        <h4 className={HEADING}>Direct relationships</h4>
        {relationships.length === 0 ? (
          <p className="mt-1.5 text-sm text-muted">No relationships in the loaded data.</p>
        ) : (
          <ul aria-label={`Relationships of ${node.label}`} className="mt-2 flex flex-col gap-2">
            {relationships.map(relRow)}
          </ul>
        )}
        {hidden > 0 ? (
          <button type="button" className="btn-secondary mt-2.5 !py-1.5 text-xs" onClick={() => onExpand(node.id)}>
            Expand {hidden} hidden neighbour{hidden === 1 ? "" : "s"}
          </button>
        ) : null}
      </div>

      <div>
        <h4 className={HEADING}>Assessment</h4>
        <div className="mt-2 rounded-md border border-warn-line bg-warn-tint p-3">
          <p className="text-[13px] font-bold text-warn">Related, not confirmed</p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            {node.trust}. A dependency, a deployment time or an attached observation does not establish causality.
          </p>
        </div>
      </div>

      {facts.length > 0 ? (
        <div>
          <h4 className={HEADING}>Recorded fields</h4>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            {facts.map((d, i) => (
              <div key={`${d.label}${i}`} className="contents">
                <dt className="font-semibold text-muted">{d.label}</dt>
                <dd className="font-mono text-ink [overflow-wrap:anywhere]">{d.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {sources.length > 0 ? (
        <div>
          <h4 className={HEADING}>Sources</h4>
          <ul className="mt-1.5 flex flex-col gap-1">
            {sources.map((d, i) => (
              <li key={`${d.label}${i}`} className="font-mono text-[11px] text-brand [overflow-wrap:anywhere]">
                {d.value}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {onOpenSources ? (
        <ArrowLink className="self-start" onClick={onOpenSources}>
          Open source records
        </ArrowLink>
      ) : null}
    </aside>
  );
}
