import type { IncidentDetail, ServiceContext } from "../../api/types";

export type SourceRefOwnerKind = "evidence" | "deployment" | "document" | "runbook";

export interface SourceRefEntry {
  ref: string;
  owners: Array<{ kind: SourceRefOwnerKind; id: string }>;
}

/**
 * Deduplicated list of every source reference the evidence tab displays (evidence source_ref,
 * deployment source_ref, document and runbook uris), each with the ids it belongs to.
 * Order: first appearance.
 */
export function collectSourceRefs(incident: IncidentDetail, contexts: ServiceContext[]): SourceRefEntry[] {
  const byRef = new Map<string, SourceRefEntry>();
  const add = (ref: string | null | undefined, kind: SourceRefOwnerKind, id: string) => {
    if (!ref) return;
    let entry = byRef.get(ref);
    if (!entry) {
      entry = { ref, owners: [] };
      byRef.set(ref, entry);
    }
    if (!entry.owners.some((o) => o.kind === kind && o.id === id)) entry.owners.push({ kind, id });
  };

  for (const p of incident.explanation_paths) {
    add(p.deployment.source_ref, "deployment", p.deployment.id);
    for (const e of p.evidence) add(e.source_ref, "evidence", e.id);
    for (const d of p.governing_decisions) for (const doc of d.documented_in ?? []) add(doc.uri, "document", doc.id);
    for (const r of p.runbooks) add(r.uri, "runbook", r.id);
  }
  for (const e of incident.evidence) add(e.source_ref, "evidence", e.id);
  for (const ctx of contexts) {
    for (const d of ctx.active_decisions) for (const doc of d.documented_in) add(doc.uri, "document", doc.id);
    for (const r of ctx.runbooks) add(r.uri, "runbook", r.id);
    for (const dep of ctx.recent_deployments) add(dep.source_ref, "deployment", dep.id);
  }
  return [...byRef.values()];
}
