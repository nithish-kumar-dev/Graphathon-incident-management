import type {
  DecisionOut,
  DecisionRef,
  EvidenceRef,
  IncidentDetail,
  IncidentMemories,
  RetrievalBundle,
  RunbookRef,
  ServiceRef,
  TeamOut,
} from "../../api/types";
import { shortId } from "../../lib/time";

export type NodeKind = "incident" | "service" | "deployment" | "evidence" | "decision" | "runbook" | "document" | "memory" | "team";

export interface KindMeta {
  label: string;
  glyph: string;
  /** Node accent (left bar, legend dot, edge-of-kind cues). */
  accent: string;
  /** Soft background for chips and legend dots. */
  tint: string;
  /** Ring/border that matches the tint. */
  line: string;
  trust: string;
}

/** Palette tokens, written as hex because SVG attributes cannot read Tailwind utilities. */
export const KIND_META: Record<NodeKind, KindMeta> = {
  incident: { label: "Incident", glyph: "I", accent: "#175C83", tint: "#EAF3F8", line: "#BBDAEA", trust: "Recorded incident" },
  service: { label: "Service", glyph: "S", accent: "#19734E", tint: "#ECF7F1", line: "#C4E3D3", trust: "Recorded in the company graph" },
  deployment: { label: "Deployment", glyph: "D", accent: "#5B5A96", tint: "#EFEFF8", line: "#D5D4EA", trust: "Recorded deployment" },
  evidence: { label: "Evidence", glyph: "E", accent: "#A3312A", tint: "#FDECEB", line: "#F0CDC9", trust: "Recorded observation" },
  decision: { label: "Policy", glyph: "P", accent: "#A45A25", tint: "#FFF5E8", line: "#EFDAC9", trust: "Official company policy" },
  runbook: { label: "Runbook", glyph: "R", accent: "#8C4A1F", tint: "#FFF1E6", line: "#F2D9C4", trust: "Official runbook" },
  document: { label: "Document", glyph: "▤", accent: "#7A6A1F", tint: "#FBF6E3", line: "#E7DEBB", trust: "Company document" },
  memory: { label: "Memory", glyph: "M", accent: "#617180", tint: "#F2F5F7", line: "#D7DEE3", trust: "Agent memory, verified" },
  team: { label: "Team", glyph: "T", accent: "#2C596C", tint: "#EAF3F8", line: "#BBDAEA", trust: "Recorded ownership" },
};

/** Ink, muted and line tokens for SVG fills/strokes inside the canvas. */
export const CANVAS_COLORS = {
  ink: "#1B2935",
  muted: "#617180",
  faint: "#8A96A2",
  line: "#DEE5E9",
  lineStrong: "#C8D3DA",
  surface: "#FFFFFF",
  sunken: "#FBFCFD",
  brand: "#175C83",
  brandLine: "#BBDAEA",
  brandTint: "#EAF3F8",
} as const;

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  subtitle: string | null;
  /** Shown instead of KIND_META.trust when the node is not what its kind implies (e.g. another incident). */
  trust: string;
  /** Plain-language reason this node is in the graph. */
  why: string;
  details: Array<{ label: string; value: string }>;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  /** Exact relationship type stored in FalkorDB. */
  rel: string;
  /** True when the UI inferred the edge instead of reading it from a response (drawn dashed). */
  derived: boolean;
}

export interface GraphModel {
  nodes: Map<string, GraphNode>;
  edges: GraphEdge[];
  rootId: string;
}

export function buildGraph(args: {
  incident: IncidentDetail;
  bundle: RetrievalBundle | null;
  memories: IncidentMemories | null;
}): GraphModel {
  const { incident, bundle, memories } = args;
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, GraphEdge>();
  const serviceNames = new Map<string, ServiceRef>();

  // Lookups so a node first reached by id alone (explanation hop, evidence reference) still gets its real name.
  const evidenceById = new Map<string, EvidenceRef>();
  [...incident.evidence, ...(bundle?.graph_context?.evidence ?? [])].forEach((e) => evidenceById.set(e.id, e));
  const deploymentById = new Map<string, { version: string; status?: string | null; serviceId: string | null }>();
  incident.explanation_paths.forEach((p) => deploymentById.set(p.deployment.id, { version: p.deployment.version, status: p.deployment.status, serviceId: p.target_service_id }));
  (bundle?.graph_context?.recent_deployments ?? []).forEach((d) => deploymentById.set(d.id, { version: d.version, status: d.status, serviceId: d.service_id }));
  const evidenceTitle = (e: EvidenceRef | undefined, id: string) => {
    let text = e?.excerpt?.replace(/\s+/g, " ").trim();
    // A trailing "at <timestamp>" repeats observed_at, which the subtitle already shows; dropping it
    // lets the title spend its width on the part that varies between kinds of reading.
    if (text && e?.observed_at) text = text.replace(/\s+at \d{4}-\d\d-\d\dT[\d:.]+Z?$/, "") || text;
    return text || shortId(id);
  };
  /** "metric · 10-17 13:15Z": the kind plus the observation time, which is what tells sibling samples apart. */
  const evidenceSubtitle = (e: EvidenceRef | undefined): string | null => {
    if (!e) return null;
    const t = e.observed_at && /^\d{4}-(\d\d-\d\d)T(\d\d:\d\d)/.exec(e.observed_at);
    return t ? `${e.kind} · ${t[1]} ${t[2]}Z` : e.kind;
  };
  const deploymentTitle = (id: string) => {
    const d = deploymentById.get(id);
    if (!d) return shortId(id);
    const svc = d.serviceId ? (serviceNames.get(d.serviceId)?.name ?? shortId(d.serviceId)) : null;
    return svc ? `${svc} ${d.version}` : d.version;
  };

  const noteService = (s: ServiceRef) => serviceNames.set(s.id, { ...serviceNames.get(s.id), ...s });
  incident.affected_services.forEach(noteService);
  const gc = bundle?.graph_context;
  if (gc) for (const deps of Object.values(gc.dependencies)) for (const d of deps) noteService(d.service);

  const addNode = (n: Omit<GraphNode, "details" | "trust"> & { trust?: string; details?: GraphNode["details"] }) => {
    const existing = nodes.get(n.id);
    if (existing) {
      if (n.details) existing.details = [...existing.details, ...n.details.filter((d) => !existing.details.some((e) => e.label === d.label && e.value === d.value))];
      return existing;
    }
    const node: GraphNode = { ...n, trust: n.trust ?? KIND_META[n.kind].trust, details: n.details ?? [] };
    nodes.set(n.id, node);
    return node;
  };
  const addEdge = (from: string, rel: string, to: string, derived = false) => {
    const id = `${from}|${rel}|${to}`;
    if (!edges.has(id)) edges.set(id, { id, from, to, rel, derived });
  };
  const service = (id: string, why: string) => {
    const ref = serviceNames.get(id);
    addNode({ id, kind: "service", label: ref?.name ?? shortId(id), subtitle: ref?.tier ?? null, why, details: [{ label: "Id", value: id }, ...(ref?.tier ? [{ label: "Tier", value: ref.tier }] : [])] });
  };
  const evidenceNode = (e: EvidenceRef, why: string) =>
    addNode({
      id: e.id,
      kind: "evidence",
      label: evidenceTitle(e, e.id),
      subtitle: evidenceSubtitle(e),
      why,
      details: [{ label: "Id", value: e.id }, { label: "Kind", value: e.kind }, { label: "Source", value: e.source_ref }, ...(e.excerpt ? [{ label: "Excerpt", value: e.excerpt }] : []), ...(e.observed_at ? [{ label: "Observed", value: e.observed_at }] : [])],
    });
  const decisionNode = (d: DecisionRef | DecisionOut, why: string) => {
    addNode({
      id: d.id,
      kind: "decision",
      label: d.title,
      subtitle: d.status,
      why,
      details: [
        { label: "Status", value: d.status },
        ...(d.required_approver_role ? [{ label: "Required approver", value: d.required_approver_role }] : []),
        ...("statement" in d ? [{ label: "Statement", value: d.statement }] : []),
      ],
    });
    for (const doc of d.documented_in ?? []) {
      addNode({ id: doc.id, kind: "document", label: doc.title ?? shortId(doc.id), subtitle: doc.doc_type ?? null, why: `Documents policy "${d.title}".`, details: [{ label: "Id", value: doc.id }, ...(doc.uri ? [{ label: "URI", value: doc.uri }] : [])] });
      addEdge(d.id, "DOCUMENTED_IN", doc.id);
    }
  };
  const runbookNode = (r: RunbookRef, why: string) =>
    addNode({
      id: r.id,
      kind: "runbook",
      label: r.title,
      subtitle: `v${r.version}`,
      why,
      details: [{ label: "Version", value: r.version }, ...(r.uri ? [{ label: "URI", value: r.uri }] : []), ...(r.allowed_action_types?.length ? [{ label: "Allowed actions", value: r.allowed_action_types.join(", ") }] : [])],
    });
  const teamNode = (t: TeamOut, why: string) =>
    addNode({ id: t.id, kind: "team", label: t.name, subtitle: `${t.members.length} member${t.members.length === 1 ? "" : "s"}`, why, details: t.members.map((m) => ({ label: "Member", value: `${m.handle}${m.roles?.length ? ` (${m.roles.join(", ")})` : ""}` })) });

  // ---- the incident itself
  addNode({
    id: incident.id,
    kind: "incident",
    label: incident.key,
    subtitle: incident.status,
    why: "The incident being investigated.",
    details: [{ label: "Title", value: incident.title }, { label: "Severity", value: incident.severity }, { label: "Started", value: incident.started_at }],
  });
  for (const s of incident.affected_services) {
    service(s.id, `Affected by ${incident.key}.`);
    addEdge(incident.id, "AFFECTS", s.id);
  }
  for (const e of incident.evidence) {
    evidenceNode(e, `Attached to ${incident.key}.`);
    addEdge(incident.id, "HAS_EVIDENCE", e.id);
    for (const sid of e.observed_on_service_ids) {
      service(sid, `Where "${evidenceTitle(e, e.id)}" was observed.`);
      addEdge(e.id, "OBSERVED_ON", sid);
    }
    for (const did of e.refers_to_deployment_ids) {
      addNode({ id: did, kind: "deployment", label: deploymentTitle(did), subtitle: deploymentById.get(did)?.status ?? null, why: `Referenced by evidence "${evidenceTitle(e, e.id)}".`, details: [{ label: "Id", value: did }] });
      addEdge(e.id, "REFERS_TO", did);
    }
  }

  // ---- explanation paths (every hop is a real stored edge)
  for (const p of incident.explanation_paths) {
    for (const h of p.hops) {
      for (const [id, label] of [[h.from_id, h.from_label], [h.to_id, h.to_label]] as const) {
        if (nodes.has(id)) continue;
        if (label === "Service") service(id, "On the stored explanation path.");
        else if (label === "Deployment") addNode({ id, kind: "deployment", label: deploymentTitle(id), subtitle: deploymentById.get(id)?.status ?? null, why: "On the stored explanation path.", details: [{ label: "Id", value: id }] });
        else if (label === "Evidence") addNode({ id, kind: "evidence", label: evidenceTitle(evidenceById.get(id), id), subtitle: evidenceSubtitle(evidenceById.get(id)), why: "On the stored explanation path.", details: [{ label: "Id", value: id }] });
      }
      addEdge(h.from_id, h.rel, h.to_id);
    }
    addNode({
      id: p.deployment.id,
      kind: "deployment",
      label: deploymentTitle(p.deployment.id),
      subtitle: p.deployment.status ?? null,
      why: "A recent deployment correlated with the incident (a hypothesis, not a confirmed cause).",
      details: [{ label: "Id", value: p.deployment.id }, { label: "Version", value: p.deployment.version }, { label: "Deployed", value: p.deployment.deployed_at }, { label: "Correlation", value: p.summary }],
    });
    addEdge(p.deployment.id, "DEPLOYED_TO", p.target_service_id);
    p.governing_decisions.forEach((d) => {
      decisionNode(d, `Governs ${shortId(p.target_service_id)} rollbacks.`);
      addEdge(d.id, "GOVERNS", p.target_service_id);
    });
    p.runbooks.forEach((r) => {
      runbookNode(r, `Applies to ${shortId(p.target_service_id)}.`);
      addEdge(r.id, "APPLIES_TO", p.target_service_id);
    });
  }

  // ---- full retrieval context (dependencies, owners, policy, runbooks, documents, memories)
  if (gc && bundle) {
    for (const [sid, list] of Object.entries(gc.dependencies)) {
      for (const d of list) {
        service(d.service.id, `Reached through DEPENDS_ON from ${shortId(sid)}.`);
        if (d.path[0]) service(d.path[0], `Start of a DEPENDS_ON chain for ${shortId(sid)}.`);
        d.path.slice(1).forEach((to, i) => {
          service(to, `Reached through DEPENDS_ON from ${shortId(sid)}.`);
          addEdge(d.path[i]!, "DEPENDS_ON", to);
        });
      }
    }
    for (const [sid, teams] of Object.entries(gc.ownership)) {
      service(sid, "Owned service.");
      teams.forEach((t) => {
        teamNode(t, `Owns ${shortId(sid)}.`);
        addEdge(t.id, "OWNS", sid);
      });
    }
    for (const [sid, list] of Object.entries(gc.decisions)) {
      for (const d of list) {
        service(sid, "Governed service.");
        decisionNode(d, `Active policy for ${shortId(sid)}.`);
        addEdge(d.id, "GOVERNS", sid);
      }
    }
    for (const [sid, list] of Object.entries(gc.runbooks)) {
      for (const r of list) {
        service(sid, "Service with a runbook.");
        runbookNode(r, `Runbook for ${shortId(sid)}.`);
        addEdge(r.id, "APPLIES_TO", sid);
      }
    }
    for (const d of gc.recent_deployments) {
      addNode({ id: d.id, kind: "deployment", label: deploymentTitle(d.id), subtitle: d.status ?? null, why: "A recent deployment to an affected or related service.", details: [{ label: "Id", value: d.id }, { label: "Version", value: d.version }, { label: "Deployed", value: d.deployed_at }] });
      service(d.service_id, "Deployed to.");
      addEdge(d.id, "DEPLOYED_TO", d.service_id);
    }
    // Knowledge: the graph_links strings are "Document <id> -[REL]-> <Label> <id>" read from the graph.
    for (const chunk of bundle.knowledge_context.items) {
      addNode({
        id: chunk.document_id,
        kind: "document",
        label: chunk.document_title,
        subtitle: chunk.document_classification,
        why: "A company document matched this incident (retrieval, not a confirmed cause).",
        details: [{ label: "Id", value: chunk.document_id }, { label: "Classification", value: chunk.document_classification }],
      });
      for (const link of chunk.graph_links) {
        const m = /^Document (\S+) -\[([A-Z_]+)\]-> (\w+) (\S+)$/.exec(link);
        if (!m) continue;
        const [, from, rel, label, to] = m as unknown as [string, string, string, string, string];
        if (label === "Service") service(to, "Linked from a matched document.");
        if (label === "Incident" && !nodes.has(to)) {
          addNode({ id: to, kind: "incident", label: shortId(to), subtitle: null, trust: "Recorded incident (not the current one)", why: "Linked from a matched document.", details: [{ label: "Id", value: to }] });
        }
        if (nodes.has(to)) addEdge(from, rel, to);
      }
    }
  }

  // ---- memories (from retrieval, or from the memories endpoint when retrieval is unavailable)
  const memoryRows: Array<{ id: string; summary: string; aboutId: string | null; aboutKey: string | null; shared: string[]; precedent: string; outcome: string }> = [
    ...(bundle?.memory_context.items ?? []).map((m) => ({ id: m.id, summary: m.summary, aboutId: m.about_incident_id, aboutKey: m.about_incident_key, shared: m.shared_service_ids, precedent: m.precedent, outcome: m.outcome })),
    ...(memories?.memories ?? []).filter((m) => m.verification_status === "verified").map((m) => ({ id: m.id, summary: m.summary, aboutId: m.about_incident_id, aboutKey: m.about_incident_key, shared: m.shared_service_ids, precedent: m.precedent, outcome: m.outcome })),
  ];
  for (const m of memoryRows) {
    addNode({
      id: m.id,
      kind: "memory",
      label: m.aboutKey ? `Memory of ${m.aboutKey}` : m.summary.replace(/\s+/g, " ").trim() || shortId(m.id),
      subtitle: m.outcome,
      why: m.precedent === "warns_against" ? "A verified memory of an action that did not work." : "A verified memory of a similar earlier incident.",
      details: [{ label: "Id", value: m.id }, { label: "Summary", value: m.summary }, { label: "Outcome", value: m.outcome }, { label: "Precedent", value: m.precedent }],
    });
    if (!m.aboutId) continue;
    if (!nodes.has(m.aboutId)) {
      addNode({ id: m.aboutId, kind: "incident", label: m.aboutKey ?? shortId(m.aboutId), subtitle: "earlier incident", trust: "Recorded incident (not the current one)", why: "An earlier incident a memory is about.", details: [{ label: "Id", value: m.aboutId }] });
    }
    addEdge(m.id, "ABOUT", m.aboutId);
    if (m.aboutId !== incident.id) {
      for (const sid of m.shared) {
        if (!nodes.has(sid)) continue;
        // The earlier incident's AFFECTS edge to a shared service is implied by `shared_service_ids`; it was not read directly.
        addEdge(m.aboutId, "AFFECTS", sid, true);
      }
    }
  }

  return { nodes, edges: [...edges.values()].filter((e) => nodes.has(e.from) && nodes.has(e.to)), rootId: incident.id };
}

// ------------------------------------------------------------------ visibility

export function neighbors(model: GraphModel, id: string): string[] {
  const out = new Set<string>();
  for (const e of model.edges) {
    if (e.from === id) out.add(e.to);
    else if (e.to === id) out.add(e.from);
  }
  return [...out];
}

/**
 * How many node cards the focused default view aims for. Node cards are drawn large enough to read
 * their type, name and role, so the canvas can only hold a handful before text stops being legible.
 */
export const FOCUS_BUDGET = 10;

/** Kinds that explain an incident first, used to rank the one-hop neighbours that fill the budget. */
const FOCUS_PRIORITY: NodeKind[] = ["service", "deployment", "evidence", "decision", "runbook", "incident", "team", "document", "memory"];

/**
 * The focused default view: the incident, every node on a stored explanation path, and its affected
 * services — all of them, however many there are — then the most relevant remaining one-hop
 * neighbours until the budget is used up. Everything else stays one expand away.
 */
export function focusedVisible(model: GraphModel, incident: IncidentDetail, budget = FOCUS_BUDGET): Set<string> {
  const has = (id: string) => model.nodes.has(id);
  const core: string[] = [model.rootId];
  for (const p of incident.explanation_paths) {
    for (const h of p.hops) core.push(h.from_id, h.to_id);
    core.push(p.deployment.id);
  }
  for (const s of incident.affected_services) core.push(s.id);
  const visible = new Set(core.filter(has));

  const rest = neighbors(model, model.rootId)
    .filter((id) => has(id) && !visible.has(id))
    .sort((a, b) => {
      const na = model.nodes.get(a)!;
      const nb = model.nodes.get(b)!;
      return FOCUS_PRIORITY.indexOf(na.kind) - FOCUS_PRIORITY.indexOf(nb.kind) || na.label.localeCompare(nb.label);
    });
  for (const id of rest) {
    if (visible.size >= budget) break;
    visible.add(id);
  }
  return visible;
}

export function expandNode(model: GraphModel, visible: ReadonlySet<string>, id: string): Set<string> {
  return new Set([...visible, id, ...neighbors(model, id)]);
}

export function hiddenNeighborCount(model: GraphModel, visible: ReadonlySet<string>, id: string): number {
  return neighbors(model, id).filter((n) => !visible.has(n)).length;
}

/** Hop distance from the incident to every visible node it can reach. */
export function hopDistances(model: GraphModel, visible: ReadonlySet<string>): Map<string, number> {
  const dist = new Map<string, number>();
  if (!model.nodes.has(model.rootId) || !visible.has(model.rootId)) return dist;
  dist.set(model.rootId, 0);
  const queue = [model.rootId];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    for (const e of model.edges) {
      const other = e.from === cur ? e.to : e.to === cur ? e.from : null;
      if (other && visible.has(other) && !dist.has(other)) {
        dist.set(other, dist.get(cur)! + 1);
        queue.push(other);
      }
    }
  }
  return dist;
}

/** How many hops from the incident the current view actually reaches (0 when nothing is connected). */
export function maxHops(model: GraphModel, visible: ReadonlySet<string>): number {
  const values = [...hopDistances(model, visible).values()];
  return values.length === 0 ? 0 : Math.max(...values);
}

// ------------------------------------------------------------------ layout

export interface Positioned {
  x: number;
  y: number;
}

/** Node card size in canvas units (white rounded rectangles, as in the design). */
export const NODE_W = 200;
export const NODE_H = 76;

export const GRAPH_W = 1000;
export const GRAPH_H = 640;

const KIND_ORDER: NodeKind[] = ["service", "deployment", "evidence", "decision", "runbook", "document", "memory", "team", "incident"];

/** Roughly the shape of the canvas the layout is drawn into, used to pick the tidiest orientation. */
const PANEL_ASPECT = 1.6;
/** Whole-layout rotations tried, so a ring of two does not always land left/right of the incident. */
const ORIENTATIONS = [0, Math.PI / 4, Math.PI / 2, (3 * Math.PI) / 4];

function boundsOf(pos: Map<string, Positioned>): { w: number; h: number } {
  const xs = [...pos.values()].map((p) => p.x);
  const ys = [...pos.values()].map((p) => p.y);
  if (xs.length === 0) return { w: NODE_W, h: NODE_H };
  return { w: Math.max(...xs) - Math.min(...xs) + NODE_W, h: Math.max(...ys) - Math.min(...ys) + NODE_H };
}

/**
 * Radial layout: the incident in the middle, each ring one hop further out, cards pushed apart until
 * none touch. Several orientations are laid out and the one that fills the canvas best wins, so a
 * small graph does not stretch into a thin horizontal band. Deterministic for a given visible set.
 */
export function layout(model: GraphModel, visible: ReadonlySet<string>): Map<string, Positioned> {
  let best: Map<string, Positioned> | null = null;
  let bestFit = -Infinity;
  for (const phi of ORIENTATIONS) {
    const pos = placeRings(model, visible, phi);
    separate(pos);
    const { w, h } = boundsOf(pos);
    const fit = Math.min(PANEL_ASPECT / w, 1 / h);
    if (fit > bestFit) {
      bestFit = fit;
      best = pos;
    }
  }
  return best ?? new Map();
}

function placeRings(model: GraphModel, visible: ReadonlySet<string>, phi: number): Map<string, Positioned> {
  const ids = [...visible].filter((id) => model.nodes.has(id));
  const dist = hopDistances(model, visible);
  if (!dist.has(model.rootId)) dist.set(model.rootId, 0);
  const maxKnown = Math.max(0, ...dist.values());
  const rings = new Map<number, string[]>();
  for (const id of ids) {
    const d = dist.get(id) ?? maxKnown + 1;
    rings.set(d, [...(rings.get(d) ?? []), id]);
  }
  const pos = new Map<string, Positioned>();
  const cx = GRAPH_W / 2;
  const cy = GRAPH_H / 2;
  let prevRx = 0;
  let prevRy = 0;
  for (const d of [...rings.keys()].sort((a, b) => a - b)) {
    const members = rings.get(d)!;
    if (d === 0) {
      members.forEach((id) => pos.set(id, { x: cx, y: cy }));
      continue;
    }
    members.sort((a, b) => KIND_ORDER.indexOf(model.nodes.get(a)!.kind) - KIND_ORDER.indexOf(model.nodes.get(b)!.kind) || a.localeCompare(b));
    // Grow the ring until the node cards on it stop colliding, and keep each ring outside the last one.
    const spread = members.length > 1 ? 1 / (2 * Math.sin(Math.PI / members.length)) : 0;
    const rx = Math.min(2400, Math.max(190 + (d - 1) * 140, (NODE_W + 48) * spread, prevRx + NODE_W * 0.72));
    const ry = Math.min(1600, Math.max(140 + (d - 1) * 105, (NODE_H + 40) * spread, prevRy + NODE_H + 34));
    prevRx = rx;
    prevRy = ry;
    members.forEach((id, i) => {
      const angle = (2 * Math.PI * i) / members.length - Math.PI / 2 + (d % 2 ? 0 : Math.PI / members.length) + phi;
      pos.set(id, { x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) });
    });
  }
  return pos;
}

/** Gap kept between two node cards, so neighbouring cards never touch. */
const NODE_GAP_X = 44;
const NODE_GAP_Y = 34;

/**
 * Pushes overlapping node cards apart along their shallowest axis until none intersect. The ring
 * radii already space a ring out, but an ellipse squeezes its top and bottom, so cards from
 * different rings can still meet. Deterministic: same input order, same result.
 */
function separate(pos: Map<string, Positioned>): void {
  const ids = [...pos.keys()];
  const minX = NODE_W + NODE_GAP_X;
  const minY = NODE_H + NODE_GAP_Y;
  for (let pass = 0; pass < 80; pass++) {
    let moved = false;
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos.get(ids[i]!)!;
        const b = pos.get(ids[j]!)!;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const overlapX = minX - Math.abs(dx);
        const overlapY = minY - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;
        moved = true;
        if (overlapX / minX <= overlapY / minY) {
          const push = ((dx >= 0 ? 1 : -1) * (overlapX + 2)) / 2;
          a.x -= push;
          b.x += push;
        } else {
          const push = ((dy >= 0 ? 1 : -1) * (overlapY + 2)) / 2;
          a.y -= push;
          b.y += push;
        }
      }
    }
    if (!moved) break;
  }
}

// ------------------------------------------------------------------ edge labels

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Box an edge label occupies. Inter at 10px bold, uppercase, plus the halo it is painted with. */
export function edgeLabelSize(text: string): { w: number; h: number } {
  return { w: text.length * 6.6 + 10, h: 15 };
}

export interface EdgeLabelInput {
  id: string;
  text: string;
  /** Edge endpoints, already clipped to the node borders. */
  a: Positioned;
  b: Positioned;
  /** Higher wins a contested spot (the selected node's edges are labelled first). */
  priority: number;
}

/** Slots a label may sit in: a fraction along the edge, and which side of it to sit on. */
const LABEL_SLOTS: Array<[number, number]> = [
  [0.5, -1],
  [0.5, 1],
  [0.38, -1],
  [0.62, -1],
  [0.38, 1],
  [0.62, 1],
  [0.28, -1],
  [0.72, 1],
];
const LABEL_OFFSET = 11;

/**
 * Places as many edge labels as fit without touching a node card or another label; an edge that has
 * nowhere to put its name goes unlabelled rather than printing over something. The text itself is
 * never abbreviated, so a label that renders is the exact stored relationship type.
 */
export function placeEdgeLabels(inputs: EdgeLabelInput[], occupied: readonly Rect[]): Map<string, Positioned> {
  const taken: Rect[] = [...occupied];
  const out = new Map<string, Positioned>();
  const ordered = [...inputs].sort((p, q) => q.priority - p.priority || p.id.localeCompare(q.id));
  for (const input of ordered) {
    const { w, h } = edgeLabelSize(input.text);
    const dx = input.b.x - input.a.x;
    const dy = input.b.y - input.a.y;
    const length = Math.hypot(dx, dy);
    // A label much longer than its edge reads as belonging to nothing; the selected node's edges get
    // more leeway, because those are the names the reader just asked for.
    if (length < w * (input.priority > 0 ? 0.45 : 0.75)) continue;
    // Perpendicular to the edge, so a label sits beside its line instead of across it.
    const px = length === 0 ? 0 : (-dy / length) * LABEL_OFFSET;
    const py = length === 0 ? -LABEL_OFFSET : (dx / length) * LABEL_OFFSET;
    for (const [t, side] of LABEL_SLOTS) {
      const x = input.a.x + dx * t + px * side;
      const y = input.a.y + dy * t + py * side;
      const box = { x: x - w / 2, y: y - h / 2, w, h };
      if (taken.some((r) => rectsOverlap(r, box))) continue;
      taken.push(box);
      out.set(input.id, { x, y });
      break;
    }
  }
  return out;
}
