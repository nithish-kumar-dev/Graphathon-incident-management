/**
 * Type-level check of the fixtures (captured from the live API) against src/api/types.ts.
 * `npm run typecheck` fails if a fixture does not fit its type, or carries a field the type lacks.
 * JSON imports widen string literals to `string`, so literal unions are checked at runtime below.
 */
import { describe, expect, it } from "vitest";
import error404 from "../test/fixtures/error_404.json";
import incident092 from "../test/fixtures/incident_092.json";
import incident101 from "../test/fixtures/incident_101.json";
import incidents from "../test/fixtures/incidents.json";
import investigation092 from "../test/fixtures/investigation_092.json";
import investigationQueued from "../test/fixtures/investigation_queued.json";
import investigationAwaitingReview101 from "../test/fixtures/investigation_awaiting_review_101.json";
import investigationCompleted101 from "../test/fixtures/investigation_completed_101.json";
import investigationEscalated101 from "../test/fixtures/investigation_escalated_101.json";
import investigationFailed101 from "../test/fixtures/investigation_failed_101.json";
import memories101 from "../test/fixtures/memories_101.json";
import retrieval101 from "../test/fixtures/retrieval_101.json";
import servicePayment from "../test/fixtures/service_payment.json";
import timeline101 from "../test/fixtures/timeline_101.json";
import {
  ACTION_RISKS,
  BRANCH_STATUSES,
  GATE_DECISIONS,
  CLAIM_TYPES,
  INCIDENT_STATUSES,
  INVESTIGATION_STATUSES,
  MODES,
  SEVERITIES,
  type ApiErrorBody,
  type IncidentDetail,
  type IncidentList,
  type IncidentMemories,
  type IncidentTimeline,
  type InvestigationOut,
  type RetrievalBundle,
  type ServiceContext,
} from "./types";

/** Replace every string/number/boolean literal type with its primitive, recursively. */
type Widen<T> = T extends string
  ? string
  : T extends number
    ? number
    : T extends boolean
      ? boolean
      : T extends readonly (infer U)[]
        ? Widen<U>[]
        : T extends object
          ? { [K in keyof T]: Widen<T[K]> }
          : T;

/** Union of keys present in the fixture F but absent from type T, at any depth (never when none). */
type ExtraKeys<F, T> = F extends readonly (infer FU)[]
  ? NonNullable<T> extends readonly (infer TU)[]
    ? ExtraKeys<FU, TU>
    : never
  : F extends object
    ? NonNullable<T> extends object
      ? { [K in keyof F]: K extends keyof NonNullable<T> ? ExtraKeys<F[K], NonNullable<T>[K]> : K }[keyof F]
      : never
    : never;

type NoExtra<F, T> = [ExtraKeys<F, T>] extends [never] ? true : ExtraKeys<F, T>;

// Structural fit (types, nullability, arrays, required keys).
export const typeChecks = {
  incidents: incidents satisfies Widen<IncidentList>,
  incident101: incident101 satisfies Widen<IncidentDetail>,
  incident092: incident092 satisfies Widen<IncidentDetail>,
  timeline101: timeline101 satisfies Widen<IncidentTimeline>,
  memories101: memories101 satisfies Widen<IncidentMemories>,
  servicePayment: servicePayment satisfies Widen<ServiceContext>,
  investigation092: investigation092 satisfies Widen<InvestigationOut>,
  investigationQueued: investigationQueued satisfies Widen<InvestigationOut>,
  investigationCompleted101: investigationCompleted101 satisfies Widen<InvestigationOut>,
  investigationAwaitingReview101: investigationAwaitingReview101 satisfies Widen<InvestigationOut>,
  investigationEscalated101: investigationEscalated101 satisfies Widen<InvestigationOut>,
  investigationFailed101: investigationFailed101 satisfies Widen<InvestigationOut>,
  retrieval101: retrieval101 satisfies Widen<RetrievalBundle>,
  error404: error404 satisfies Widen<ApiErrorBody>,
};

// No undeclared fields (models are extra="forbid" server-side, so the types must list every field).
export const noExtraKeys: true[] = [
  true satisfies NoExtra<typeof incidents, IncidentList>,
  true satisfies NoExtra<typeof incident101, IncidentDetail>,
  true satisfies NoExtra<typeof incident092, IncidentDetail>,
  true satisfies NoExtra<typeof timeline101, IncidentTimeline>,
  true satisfies NoExtra<typeof memories101, IncidentMemories>,
  true satisfies NoExtra<typeof servicePayment, ServiceContext>,
  true satisfies NoExtra<typeof investigation092, InvestigationOut>,
  true satisfies NoExtra<typeof investigationQueued, InvestigationOut>,
  true satisfies NoExtra<typeof investigationCompleted101, InvestigationOut>,
  true satisfies NoExtra<typeof investigationAwaitingReview101, InvestigationOut>,
  true satisfies NoExtra<typeof investigationEscalated101, InvestigationOut>,
  true satisfies NoExtra<typeof investigationFailed101, InvestigationOut>,
  true satisfies NoExtra<typeof retrieval101, RetrievalBundle>,
  true satisfies NoExtra<typeof error404, ApiErrorBody>,
];

// Literal-union values, checked at runtime.
describe("fixture enum values", () => {
  const oneOf = (allowed: readonly string[], value: string) => expect(allowed).toContain(value);

  it("incidents use known severities and statuses", () => {
    for (const inc of [...incidents.items, incident101, incident092, retrieval101.graph_context.incident]) {
      oneOf(SEVERITIES, inc.severity);
      oneOf(INCIDENT_STATUSES, inc.status);
    }
  });

  const phase4 = [investigationCompleted101, investigationAwaitingReview101, investigationEscalated101, investigationFailed101];

  it("investigations use known statuses, modes, branch statuses and claim types", () => {
    for (const inv of [investigation092, investigationQueued, ...phase4]) {
      oneOf(INVESTIGATION_STATUSES, inv.status);
      oneOf(MODES, inv.mode);
      for (const b of Object.values(inv.branches)) oneOf(BRANCH_STATUSES, b.status);
      for (const f of inv.findings) oneOf(CLAIM_TYPES, f.claim_type);
    }
  });

  it("phase 4 runs use known gate decisions, modes and risks, with 64-hex spec hashes", () => {
    for (const inv of phase4) {
      if (inv.gate) oneOf(GATE_DECISIONS, inv.gate.decision);
      for (const a of inv.proposed_actions) {
        oneOf(MODES, a.mode);
        oneOf(ACTION_RISKS, a.risk);
        expect(a.spec_hash).toMatch(/^[0-9a-f]{64}$/);
        expect(a.spec.action_type).toBe(a.action_type);
      }
      for (const f of inv.findings) {
        if (f.confidence !== null) expect(f.confidence).toBeGreaterThanOrEqual(0);
        for (const e of [...f.evidence, ...f.contradicting_evidence]) expect(e.id).toMatch(/^nova\.ev\./);
      }
    }
    expect(investigationFailed101.error).toBeTruthy();
    expect(investigationEscalated101.proposed_actions).toHaveLength(0);
  });

  it("explanation paths are correlations, never causes", () => {
    for (const p of [...incident101.explanation_paths, ...retrieval101.graph_context.explanation_paths]) {
      expect(p.claim_type).toBe("correlated");
    }
  });

  it("memories use known precedents and verification states", () => {
    for (const m of memories101.memories) {
      oneOf(["supports", "warns_against", "none"], m.precedent);
      oneOf(["draft", "verified", "rejected", "superseded"], m.verification_status);
    }
    for (const m of retrieval101.memory_context.items) expect(m.verification_status).toBe("verified");
    for (const c of retrieval101.knowledge_context.items) expect(c.claim_type).toBe("context");
  });
});
