import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Kicker, cx } from "../../components/ui";
import {
  CANVAS_COLORS,
  KIND_META,
  NODE_H,
  NODE_W,
  hiddenNeighborCount,
  layout,
  maxHops,
  placeEdgeLabels,
  type GraphModel,
  type NodeKind,
  type Rect,
} from "./model";

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 2.5;
const C = CANVAS_COLORS;

interface View {
  x: number;
  y: number;
  k: number;
}
const HOME: View = { x: 0, y: 0, k: 1 };

/** Where the line from `from` to `to` leaves/enters a node's rectangle, so arrows stop at the border. */
function edgePoint(from: { x: number; y: number }, to: { x: number; y: number }, pad = 0) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (dx === 0 && dy === 0) return from;
  const t = Math.min(dx === 0 ? Infinity : (NODE_W / 2 + pad) / Math.abs(dx), dy === 0 ? Infinity : (NODE_H / 2 + pad) / Math.abs(dy));
  return { x: from.x + dx * t, y: from.y + dy * t };
}

function trunc(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

export interface GraphCanvasProps {
  model: GraphModel;
  visible: ReadonlySet<string>;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onExpand: (id: string) => void;
  onReset: () => void;
  /** Bump to recentre the view (e.g. after a reset). */
  resetToken?: number;
}

export function GraphCanvas({ model, visible, selectedId, onSelect, onExpand, onReset, resetToken = 0 }: GraphCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [view, setView] = useState<View>(HOME);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const positions = useMemo(() => layout(model, visible), [model, visible]);
  const hops = useMemo(() => maxHops(model, visible), [model, visible]);

  useEffect(() => setView(HOME), [resetToken]);

  const zoomBy = useCallback((factor: number) => setView((v) => ({ ...v, k: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * factor)) })), []);

  // React registers wheel listeners as passive, so preventDefault (stop the page scrolling) needs a native one.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

  const nodes = [...visible].map((id) => model.nodes.get(id)).filter((n): n is NonNullable<typeof n> => !!n && positions.has(n.id));
  const edges = model.edges.filter((e) => visible.has(e.from) && visible.has(e.to) && positions.has(e.from) && positions.has(e.to));

  const edgeText = (e: (typeof edges)[number]) => `${e.rel}${e.derived ? " (derived)" : ""}`;

  // Labels claim a free slot along their edge; whatever cannot fit stays unlabelled rather than
  // printing over a card or another name. The footer's relationship list stays complete either way.
  const labels = useMemo(() => {
    const occupied: Rect[] = nodes.map((n) => {
      const p = positions.get(n.id)!;
      return { x: p.x - NODE_W / 2 - 6, y: p.y - NODE_H / 2 - 6, w: NODE_W + 12, h: NODE_H + 12 };
    });
    const inputs = edges.map((e) => {
      const a = positions.get(e.from)!;
      const b = positions.get(e.to)!;
      return {
        id: e.id,
        text: edgeText(e),
        a: edgePoint(a, b),
        b: edgePoint(b, a, 5),
        priority: selectedId === e.from || selectedId === e.to ? 1 : 0,
      };
    });
    return placeEdgeLabels(inputs, occupied);
    // `nodes` and `edges` are derived from exactly these, and are rebuilt on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, visible, positions, selectedId]);

  // Frame every laid-out node, so a wide ring is never cropped by a fixed viewBox.
  const box = useMemo(() => {
    const pts = [...positions.values()];
    if (pts.length === 0) return { x: 0, y: 0, w: 1000, h: 640 };
    const pad = 48;
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const minX = Math.min(...xs) - NODE_W / 2 - pad;
    const maxX = Math.max(...xs) + NODE_W / 2 + pad;
    const minY = Math.min(...ys) - NODE_H / 2 - pad;
    const maxY = Math.max(...ys) + NODE_H / 2 + pad;
    const w = Math.max(maxX - minX, 620);
    const h = Math.max(maxY - minY, 400);
    // Keep the content centred when one axis is padded up to its minimum.
    return { x: (minX + maxX) / 2 - w / 2, y: (minY + maxY) / 2 - h / 2, w, h };
  }, [positions]);
  const cx0 = box.x + box.w / 2;
  const cy0 = box.y + box.h / 2;

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest("[data-node]")) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    const el = svgRef.current;
    if (!d || !el) return;
    const rect = el.getBoundingClientRect();
    const scale = rect.width > 0 ? box.w / rect.width : 1;
    setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x) * scale, y: d.vy + (e.clientY - d.y) * scale }));
  };
  const endDrag = () => {
    drag.current = null;
  };

  const selected = selectedId ? model.nodes.get(selectedId) : null;
  const canExpand = selected ? hiddenNeighborCount(model, visible, selected.id) > 0 : false;
  const kinds = useMemo(() => [...new Set(nodes.map((n) => n.kind))], [nodes]);
  const hasDerived = edges.some((e) => e.derived);
  const zoomPct = Math.round(view.k * 100);

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface-sunken">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-1 pt-3 sm:px-4">
        <Kicker>
          Incident neighborhood · {hops} hop{hops === 1 ? "" : "s"}
        </Kicker>
        <div className="flex items-center gap-1 rounded-full border border-line bg-surface px-1 py-0.5" role="group" aria-label="Zoom">
          <button
            type="button"
            className="rounded-full px-2 py-0.5 text-sm font-bold text-ink hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand"
            aria-label="Zoom out"
            onClick={() => zoomBy(1 / 1.2)}
          >
            −
          </button>
          <span className="min-w-[3.25rem] text-center text-xs font-semibold tabular-nums text-ink" role="status">
            {zoomPct}%
          </span>
          <button
            type="button"
            className="rounded-full px-2 py-0.5 text-sm font-bold text-ink hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand"
            aria-label="Zoom in"
            onClick={() => zoomBy(1.2)}
          >
            +
          </button>
        </div>
      </div>

      <div className="relative min-w-0">
        <svg
          ref={svgRef}
          viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
          style={{ aspectRatio: `${Math.round(box.w)} / ${Math.round(box.h)}` }}
          className="block max-h-[31rem] min-h-[17rem] w-full cursor-grab touch-none active:cursor-grabbing"
          role="group"
          aria-label="Incident knowledge graph. Drag to pan, scroll or use the zoom buttons to zoom. Select a node for details."
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onClick={(e) => {
            if (!(e.target as Element).closest("[data-node]")) onSelect(null);
          }}
        >
          <defs>
            <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={C.faint} />
            </marker>
            <marker id="graph-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill={C.brand} />
            </marker>
          </defs>
          <g transform={`translate(${view.x} ${view.y}) translate(${cx0} ${cy0}) scale(${view.k}) translate(${-cx0} ${-cy0})`}>
            <g aria-hidden="true">
              {edges.map((e) => {
                const a = positions.get(e.from)!;
                const b = positions.get(e.to)!;
                const p1 = edgePoint(a, b);
                const p2 = edgePoint(b, a, 5);
                const touchesSelection = selectedId === e.from || selectedId === e.to;
                const label = labels.get(e.id);
                return (
                  <g key={e.id} data-edge={e.rel} data-derived={e.derived || undefined}>
                    <line
                      x1={p1.x}
                      y1={p1.y}
                      x2={p2.x}
                      y2={p2.y}
                      stroke={touchesSelection ? C.brand : C.lineStrong}
                      strokeWidth={touchesSelection ? 2.25 : 1.4}
                      strokeLinecap="round"
                      strokeDasharray={e.derived ? "6 4" : undefined}
                      markerEnd={touchesSelection ? "url(#graph-arrow-active)" : "url(#graph-arrow)"}
                      opacity={selectedId && !touchesSelection ? 0.4 : 1}
                    />
                    {label ? (
                      <text
                        x={label.x}
                        y={label.y + 4}
                        textAnchor="middle"
                        fontSize="10"
                        fontWeight="700"
                        letterSpacing="0.4"
                        fill={touchesSelection ? C.brand : C.muted}
                        stroke={C.sunken}
                        strokeWidth="4"
                        paintOrder="stroke"
                        opacity={selectedId && !touchesSelection ? 0.5 : 1}
                      >
                        {edgeText(e)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
            {nodes.map((n) => {
              const p = positions.get(n.id)!;
              const meta = KIND_META[n.kind];
              const isSel = n.id === selectedId;
              const hidden = hiddenNeighborCount(model, visible, n.id);
              const role = n.subtitle ?? meta.label;
              return (
                <g
                  key={n.id}
                  data-node={n.id}
                  data-kind={n.kind}
                  transform={`translate(${p.x - NODE_W / 2} ${p.y - NODE_H / 2})`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSel}
                  aria-label={`${meta.label}: ${n.label}, ${role}${hidden > 0 ? `, ${hidden} more connected items hidden` : ""}`}
                  className="cursor-pointer outline-none focus-visible:[&>rect:first-of-type]:stroke-[3] focus-visible:[&>rect:first-of-type]:stroke-[#175C83]"
                  onClick={() => onSelect(n.id)}
                  onDoubleClick={() => onExpand(n.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(n.id);
                    }
                  }}
                >
                  <title>{`${meta.label}: ${n.label}${n.subtitle ? ` (${n.subtitle})` : ""}`}</title>
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx="8"
                    fill={C.surface}
                    stroke={isSel ? C.brand : C.line}
                    strokeWidth={isSel ? 2 : 1}
                    strokeDasharray={n.id !== model.rootId && n.kind === "incident" ? "5 4" : undefined}
                  />
                  <rect x="0" y="0" width="5" height={NODE_H} rx="2" fill={meta.accent} />
                  <text x="19" y="21" fontSize="10" fontWeight="700" letterSpacing="0.6" fill={C.muted}>
                    {meta.label.toUpperCase()}
                  </text>
                  <text x="19" y="44" fontSize="15" fontWeight="700" fill={C.ink}>
                    {trunc(n.label, 20)}
                  </text>
                  <text x="19" y="62" fontSize="11" fill={C.muted}>
                    {trunc(role, 28)}
                  </text>
                  {hidden > 0 ? (
                    <g>
                      <rect x={NODE_W - 42} y="9" width="33" height="17" rx="8.5" fill={C.brandTint} stroke={C.brandLine} strokeWidth="1" />
                      <text x={NODE_W - 25.5} y="21" textAnchor="middle" fontSize="10" fontWeight="700" fill={C.brand}>
                        +{hidden}
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>

        {canExpand && selected ? (
          <div className="absolute bottom-2 left-2 right-2 flex flex-wrap items-center gap-2">
            <button type="button" className="btn-secondary !py-1.5 text-xs" onClick={() => onExpand(selected.id)}>
              Expand {trunc(selected.label, 24)}
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line px-3 py-2.5 sm:px-4">
        <GraphLegend kinds={kinds} derived={hasDerived} />
        <button
          type="button"
          className="shrink-0 rounded text-xs font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
          onClick={onReset}
        >
          Reset view <span aria-hidden="true">↻</span>
        </button>
      </div>
    </div>
  );
}

export function GraphLegend({ kinds, derived = false, className }: { kinds: readonly NodeKind[]; derived?: boolean; className?: string }) {
  return (
    <ul aria-label="Graph legend" className={cx("flex min-w-0 flex-wrap items-center gap-x-3.5 gap-y-1.5 text-[11px] text-muted", className)}>
      {kinds.map((k) => (
        <li key={k} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: KIND_META[k].accent }}
          />
          {KIND_META[k].label}
        </li>
      ))}
      {derived ? (
        <li className="inline-flex items-center gap-1.5">
          <svg aria-hidden="true" width="22" height="6" className="shrink-0">
            <line x1="0" y1="3" x2="22" y2="3" stroke={C.lineStrong} strokeWidth="1.5" strokeDasharray="5 3" />
          </svg>
          Derived link (inferred, not read from the graph)
        </li>
      ) : null}
    </ul>
  );
}
