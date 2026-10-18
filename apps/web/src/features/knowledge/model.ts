import type { EvidenceRef, IncidentMemories, MemoryOut, Precedent, RetrievalBundle, ScoredChunk, ScoredMemory } from "../../api/types";

export interface MemoryCardModel {
  id: string;
  incidentKey: string | null;
  incidentId: string | null;
  /** What happened, as recorded in the memory. */
  summary: string;
  outcome: "successful" | "failed" | "unknown";
  precedent: Precedent;
  verification: { status: string; method: string | null; by: string[] };
  /** Ids of the recorded actions this memory was derived from. */
  actionIds: string[];
  evidence: EvidenceRef[];
  applicability: string;
  matchedBy: string[];
  score: number | null;
  /** Why retrieval returned this memory. */
  why: string[];
  /** Text similarity alone can never support or warn. */
  textOnly: boolean;
  /** A failed outcome is shown as a warning, never as a success. */
  warning: boolean;
  impact: string;
  source: "retrieval" | "stored";
}

function impactOf(precedent: Precedent, textOnly: boolean, actionName: string | null): string {
  const action = actionName ? `the proposed ${actionName.toLowerCase()}` : "an action";
  if (textOnly) return "Only the text is similar, so this memory does not change the recommendation.";
  if (precedent === "supports") return `Supports ${action}: a verified earlier success.`;
  if (precedent === "warns_against") return `Warns against repeating ${action}: it failed before.`;
  return "No effect on the recommendation.";
}

function fromScored(m: ScoredMemory, actionName: string | null): MemoryCardModel {
  const textOnly = m.applicability === "text_similarity_only";
  return {
    id: m.id,
    incidentKey: m.about_incident_key,
    incidentId: m.about_incident_id,
    summary: m.summary,
    outcome: m.outcome,
    precedent: textOnly ? "none" : m.precedent,
    verification: { status: m.verification_status, method: m.validation_method, by: m.validated_by },
    actionIds: m.derived_from_action_ids,
    evidence: m.grounded_in,
    applicability: m.applicability.replace(/_/g, " "),
    matchedBy: m.matched_by,
    score: m.score,
    why: m.rationale,
    textOnly,
    warning: m.outcome === "failed" || m.precedent === "warns_against",
    impact: impactOf(m.precedent, textOnly, actionName),
    source: "retrieval",
  };
}

function fromStored(m: MemoryOut, actionName: string | null): MemoryCardModel {
  return {
    id: m.id,
    incidentKey: m.about_incident_key,
    incidentId: m.about_incident_id,
    summary: m.summary,
    outcome: m.outcome,
    precedent: m.precedent,
    verification: { status: m.verification_status, method: m.validation_method ?? null, by: m.validated_by.map((r) => r.handle) },
    actionIds: m.derived_from_action_ids,
    evidence: m.grounded_in,
    applicability: m.relation.replace(/_/g, " "),
    matchedBy: [],
    score: null,
    why: [`Recorded against ${m.about_incident_key ?? m.about_incident_id} (${m.relation.replace(/_/g, " ")}).`],
    textOnly: false,
    warning: m.outcome === "failed" || m.precedent === "warns_against",
    impact: impactOf(m.precedent, false, actionName),
    source: "stored",
  };
}

/**
 * Cards for historical memory. The ranked retrieval is preferred (it carries scores and reasons);
 * stored memories fill in when retrieval is unavailable. Drafts and other unverified memories are
 * never returned, even if an endpoint sends one.
 */
export function memoryCards(bundle: RetrievalBundle | null, memories: IncidentMemories | null, actionName: string | null): MemoryCardModel[] {
  if (bundle) return bundle.memory_context.items.filter((m) => m.verification_status === "verified").map((m) => fromScored(m, actionName));
  return (memories?.memories ?? []).filter((m) => m.verification_status === "verified").map((m) => fromStored(m, actionName));
}

export type KnowledgeProvenance = "official_policy" | "company_document" | "text_match";

export const PROVENANCE_LABELS: Record<KnowledgeProvenance, string> = {
  official_policy: "Official policy document",
  company_document: "Company document linked in the graph",
  text_match: "Company document matched by text only",
};

export interface KnowledgeCardModel {
  id: string;
  title: string;
  classification: string;
  sourceRef: string;
  excerpt: string;
  provenance: KnowledgeProvenance;
  matchedBy: string[];
  score: number;
  why: string[];
  scoreParts: Array<{ name: string; value: number }>;
}

export function knowledgeCards(bundle: RetrievalBundle | null): KnowledgeCardModel[] {
  if (!bundle) return [];
  const official = new Set<string>();
  for (const list of Object.values(bundle.graph_context.decisions)) for (const d of list) for (const doc of d.documented_in) official.add(doc.id);
  for (const p of bundle.graph_context.explanation_paths) for (const d of p.governing_decisions) for (const doc of d.documented_in ?? []) official.add(doc.id);
  return bundle.knowledge_context.items.map((c: ScoredChunk) => ({
    id: c.id,
    title: c.document_title,
    classification: c.document_classification,
    sourceRef: c.source_ref,
    excerpt: c.text_excerpt,
    provenance: official.has(c.document_id) ? "official_policy" : c.graph_links.length > 0 ? "company_document" : "text_match",
    matchedBy: c.matched_by,
    score: c.score,
    why: c.rationale,
    scoreParts: c.components,
  }));
}

export interface KnowledgeEntry {
  key: string;
  /** "Policy", "Runbook" or the document classification. */
  kicker: string;
  title: string;
  typeLabel: string;
  official: boolean;
  /** Short status chip text ("Active", "Applicable", "Context"). */
  status: string;
  /** Source preview content. */
  previewId: string;
  previewText: string | null;
  statusLine: string | null;
  uri: string | null;
  provenance: KnowledgeProvenance | null;
}

/** Official policy first, then runbooks, then matched documents. Only real bundle data is used. */
export function knowledgeEntries(bundle: RetrievalBundle | null): KnowledgeEntry[] {
  if (!bundle) return [];
  const decisions = new Map<string, NonNullable<typeof bundle>["graph_context"]["decisions"][string][number]>();
  const runbooks = new Map<string, NonNullable<typeof bundle>["graph_context"]["runbooks"][string][number]>();
  for (const list of Object.values(bundle.graph_context.decisions)) for (const d of list) decisions.set(d.id, d);
  for (const list of Object.values(bundle.graph_context.runbooks)) for (const r of list) runbooks.set(r.id, r);
  const out: KnowledgeEntry[] = [];
  for (const d of decisions.values()) {
    const parts = [d.status.charAt(0).toUpperCase() + d.status.slice(1)];
    if (d.supersedes.length > 0) parts.push(`Supersedes ${d.supersedes.join(", ")}`);
    if (d.required_approver_role) parts.push(`Requires ${d.required_approver_role}`);
    out.push({
      key: `decision:${d.id}`,
      kicker: "Policy",
      title: d.title,
      typeLabel: d.documented_in.length > 0 ? `Documented in ${d.documented_in.map((x) => x.title ?? x.id).join(", ")}` : "Decision record",
      official: true,
      status: d.status,
      previewId: d.id,
      previewText: d.statement,
      statusLine: parts.join(" · "),
      uri: null,
      provenance: "official_policy",
    });
  }
  for (const r of runbooks.values()) {
    out.push({
      key: `runbook:${r.id}`,
      kicker: "Runbook",
      title: r.title,
      typeLabel: `Official runbook v${r.version}`,
      official: false,
      status: "Applicable",
      previewId: r.id,
      previewText: r.allowed_action_types?.length ? `Allows: ${r.allowed_action_types.join(", ")}` : null,
      statusLine: `Official runbook v${r.version}`,
      uri: r.uri ?? null,
      provenance: null,
    });
  }
  for (const c of knowledgeCards(bundle)) {
    out.push({
      key: `chunk:${c.id}`,
      kicker: c.classification,
      title: c.title,
      typeLabel: PROVENANCE_LABELS[c.provenance],
      official: false,
      status: c.provenance === "official_policy" ? "Applicable" : "Context",
      previewId: c.id,
      previewText: c.excerpt,
      statusLine: `Matched by ${c.matchedBy.join(", ") || "unknown"} · relevance ${c.score.toFixed(2)}`,
      uri: c.sourceRef,
      provenance: c.provenance,
    });
  }
  return out;
}

export interface MemoryGroup {
  key: string;
  incidentKey: string | null;
  memories: MemoryCardModel[];
}

/** Group verified memories by the incident they are about, preserving retrieval order. */
export function groupMemories(cards: MemoryCardModel[]): MemoryGroup[] {
  const groups = new Map<string, MemoryGroup>();
  for (const m of cards) {
    const key = m.incidentId ?? m.incidentKey ?? m.id;
    const g = groups.get(key) ?? { key, incidentKey: m.incidentKey, memories: [] };
    g.memories.push(m);
    groups.set(key, g);
  }
  return [...groups.values()];
}
