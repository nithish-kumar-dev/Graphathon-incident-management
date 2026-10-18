import type {
  BranchName,
  BranchStatus,
  ClaimType,
  ExplanationPath,
  FindingOut,
  IncidentDetail,
  IncidentMemories,
  IncidentSummary,
  InvestigationOut,
  MemoryOut,
  ProposedActionOut,
  RetrievalBundle,
  AgentEventOut,
} from "../../api/types";
import { formatDuration, relativeTime, shortId } from "../../lib/time";
import type { TabId } from "../types";

// ------------------------------------------------------------------ phase

/** Where the backend says the investigation is. `none` = no run is known for this incident. */
export type Phase =
  | "none"
  | "queued"
  | "running"
  | "awaiting_review"
  | "completed"
  | "escalated"
  | "inconclusive"
  | "failed";

export function phaseOf(inv: InvestigationOut | null): Phase {
  if (!inv) return "none";
  return inv.status === "timed_out" ? "failed" : inv.status;
}

export function isActivePhase(phase: Phase): boolean {
  return phase === "queued" || phase === "running" || phase === "awaiting_review";
}

export type PrimaryActionKind = "start" | "resume" | "view";

/**
 * The one button the header leads with, chosen from real backend state.
 * - none: start (POST creates a run).
 * - queued/running/awaiting_review: resume (POST returns the existing active run and re-attaches polling).
 * - finished: view (no backend call; the run is already loaded).
 */
export function primaryActionFor(phase: Phase): { kind: PrimaryActionKind; label: string } {
  if (phase === "none") return { kind: "start", label: "Start Investigation" };
  if (isActivePhase(phase)) return { kind: "resume", label: "Resume Investigation" };
  return { kind: "view", label: "View Investigation" };
}

// ------------------------------------------------------------------ stages

export type StageId = "detected" | "context" | "analyzing" | "recommending" | "review" | "execution";
export type StageStatus = "pending" | "running" | "completed" | "failed" | "waiting" | "skipped" | "unavailable";

export interface Stage {
  id: StageId;
  label: string;
  status: StageStatus;
  /** Plain-language explanation; for waiting stages it says what is awaited. */
  caption: string;
}

export const STAGE_LABELS: Record<StageId, string> = {
  detected: "Detected",
  context: "Gathering Context",
  analyzing: "Analyzing",
  recommending: "Recommending",
  review: "Human Review",
  execution: "Execution & Learning",
};

export const STAGE_STATUS_LABELS: Record<StageStatus, string> = {
  pending: "Not started",
  running: "In progress",
  completed: "Complete",
  failed: "Failed",
  waiting: "Waiting for human",
  skipped: "Skipped",
  unavailable: "Not available yet",
};

const STAGE_ORDER: StageId[] = ["detected", "context", "analyzing", "recommending", "review", "execution"];

interface BranchTally {
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  /** pending / running / not recorded: the backend has not reported a final state. */
  open: number;
  allPending: boolean;
}

export const BRANCH_LABELS: Record<BranchName, string> = {
  graph_context: "Graph & Knowledge Retrieval",
  memory_context: "Historical Memory Retrieval",
  telemetry_context: "Live Telemetry Retrieval",
};

function branchStatus(inv: InvestigationOut, name: BranchName): BranchStatus {
  return inv.branches?.[name]?.status ?? "not_recorded";
}

function tally(inv: InvestigationOut): BranchTally {
  const names = Object.keys(BRANCH_LABELS) as BranchName[];
  const t: BranchTally = { total: 0, completed: 0, failed: 0, skipped: 0, open: 0, allPending: true };
  for (const n of names) {
    const s = branchStatus(inv, n);
    t.total += 1;
    if (s === "completed") t.completed += 1;
    else if (s === "failed") t.failed += 1;
    else if (s === "skipped") t.skipped += 1;
    else t.open += 1;
    if (s !== "pending" && s !== "not_recorded") t.allPending = false;
  }
  return t;
}

export function actionTitle(actionType: string): string {
  const known: Record<string, string> = { rollback_deployment_simulated: "Simulated deployment rollback" };
  if (known[actionType]) return known[actionType]!;
  const text = actionType.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Why the run is in this state, from `error`, for the failure caption. */
function errorText(inv: InvestigationOut): string {
  return inv.error ? inv.error : "The run ended without a recorded reason.";
}

export function deriveStages(incident: IncidentSummary, inv: InvestigationOut | null): Stage[] {
  const phase = phaseOf(inv);
  const alertWord = incident.alert_count === 1 ? "alert" : "alerts";
  const detected: Stage = {
    id: "detected",
    label: STAGE_LABELS.detected,
    status: "completed",
    caption: `${incident.alert_count} ${alertWord} recorded ${relativeTime(incident.started_at)}.`,
  };
  const s = (id: StageId, status: StageStatus, caption: string): Stage => ({ id, label: STAGE_LABELS[id], status, caption });
  const execution = s(
    "execution",
    "pending",
    "Runs only after a person approves a proposed action in a simulation run. The execution is simulated; nothing real changes.",
  );
  const nothingToExecute = s("execution", "skipped", "Nothing to execute.");

  if (!inv) {
    return [
      detected,
      s("context", "pending", "No investigation started. Start one to see agents retrieve evidence."),
      s("analyzing", "pending", "Waits for context gathering."),
      s("recommending", "pending", "Waits for analysis."),
      s("review", "pending", "A human reviews any proposed action."),
      execution,
    ];
  }

  const t = tally(inv);
  const proposals = inv.proposed_actions ?? [];
  const first = proposals[0];
  const action = first ? actionTitle(first.action_type).toLowerCase() : "action";

  if (phase === "queued") {
    return [
      detected,
      s("context", "pending", "Queued: waiting for the orchestrator worker to claim this run."),
      s("analyzing", "pending", "Waits for context gathering."),
      s("recommending", "pending", "Waits for analysis."),
      s("review", "pending", "A human reviews any proposed action."),
      execution,
    ];
  }

  if (phase === "running") {
    const gathered = t.open === 0;
    const context = gathered
      ? s("context", "completed", `${t.completed} of ${t.total - t.skipped} retrieval branches finished.`)
      : s(
          "context",
          "running",
          t.allPending
            ? "Coordinator is scoping the incident and dispatching retrieval branches."
            : `${t.completed + t.failed} of ${t.total - t.skipped} retrieval branches have reported.`,
        );
    return [
      detected,
      context,
      s(
        "analyzing",
        gathered ? "running" : "pending",
        gathered
          ? "Investigator is correlating the retrieved evidence."
          : "Starts when the retrieval branches have reported.",
      ),
      s("recommending", "pending", "Waits for analysis."),
      s("review", "pending", "A human reviews any proposed action."),
      execution,
    ];
  }

  if (phase === "failed") {
    const noBranch = t.completed + t.failed === 0;
    const failedAtContext = noBranch || t.completed === 0;
    return [
      detected,
      failedAtContext
        ? s("context", "failed", errorText(inv))
        : s("context", "completed", `${t.completed} of ${t.total - t.skipped} retrieval branches finished.`),
      failedAtContext
        ? s("analyzing", "skipped", "Not reached.")
        : s("analyzing", "failed", errorText(inv)),
      s("recommending", "skipped", "Not reached."),
      s("review", "skipped", "Nothing to review."),
      nothingToExecute,
    ];
  }

  const contextOk = t.completed > 0;
  const context = contextOk
    ? s("context", "completed", `${t.completed} of ${t.total - t.skipped} retrieval branches finished.`)
    : s("context", "failed", "No retrieval branch completed, so there was nothing to analyze.");

  if (phase === "inconclusive") {
    return [
      detected,
      context,
      contextOk
        ? s("analyzing", "failed", "Inconclusive: no evidence-backed explanation was found.")
        : s("analyzing", "skipped", "Not run."),
      s("recommending", "skipped", "No evidence-backed recommendation."),
      s("review", "skipped", "Nothing to review."),
      nothingToExecute,
    ];
  }

  const analyzing = s("analyzing", "completed", inv.investigator ? `Investigator: ${inv.investigator}.` : "Analysis finished.");
  const hasOutput = proposals.length > 0 || inv.findings.length > 0;

  const decided = first ? decidedStages(first, s) : null;

  if (phase === "escalated" && decided) {
    return [
      detected,
      context,
      analyzing,
      s("recommending", "completed", `Proposed: ${actionTitle(first!.action_type)}.`),
      decided.review,
      decided.execution,
    ];
  }

  if (phase === "escalated") {
    return [
      detected,
      context,
      analyzing,
      s("recommending", "skipped", "The safety gate found no safe, policy-backed recommendation."),
      s("review", "waiting", "Escalated: waiting for a human to decide how to proceed. The agent proposed nothing to execute."),
      nothingToExecute,
    ];
  }

  if (phase === "awaiting_review") {
    return [
      detected,
      context,
      analyzing,
      s("recommending", "completed", first ? `Proposed: ${actionTitle(first.action_type)}.` : "Recommendation prepared."),
      s("review", "waiting", `Waiting for an authorized engineer to review the proposed ${action}.`),
      execution,
    ];
  }

  // completed
  return [
    detected,
    context,
    analyzing,
    hasOutput
      ? s("recommending", "completed", first ? `Proposed: ${actionTitle(first.action_type)}.` : "Findings recorded.")
      : s("recommending", "skipped", "No findings or proposals were recorded."),
    decided
      ? decided.review
      : inv.mode === "recommendation_only"
        ? s("review", "skipped", "Not required: this was a recommendation-only run. Start a simulation run to get an approvable proposal.")
        : s("review", "skipped", "Nothing was proposed for review."),
    decided ? decided.execution : nothingToExecute,
  ];
}

/** Review and execution stages once a person has decided on the first proposed action. */
function decidedStages(
  action: ProposedActionOut,
  s: (id: StageId, status: StageStatus, caption: string) => Stage,
): { review: Stage; execution: Stage } | null {
  const last = (action.reviews ?? []).at(-1);
  const who = last?.approver_handle ?? last?.approver_id ?? "a reviewer";
  switch (action.status) {
    case "executed_simulated": {
      const failedRun = action.execution?.result === "failed";
      const ticket = action.execution?.ticket ? ` (${action.execution.ticket})` : "";
      return {
        review: s("review", "completed", `Approved by ${who}.`),
        execution: failedRun
          ? s("execution", "failed", `The simulated execution failed${ticket}. Nothing real was changed.`)
          : s("execution", "completed", `Simulated execution succeeded${ticket}. Nothing real was changed. Verify the outcome to add it to memory.`),
      };
    }
    case "approved":
      return {
        review: s("review", "completed", `Approved by ${who}.`),
        execution: s("execution", "waiting", "Approved, but the simulated execution has not completed."),
      };
    case "rejected":
      return {
        review: s("review", "completed", `Rejected by ${who}.`),
        execution: s("execution", "skipped", "Nothing was executed."),
      };
    case "revision_requested":
      return {
        review: s("review", "completed", `${who} asked for a revision.`),
        execution: s("execution", "skipped", "Nothing was executed. Start a new investigation for a revised proposal."),
      };
    case "escalated":
      return {
        review: s("review", "waiting", `${who} escalated this to another person.`),
        execution: s("execution", "skipped", "Nothing was executed."),
      };
    default:
      return null;
  }
}

// ---------------------------------------------------------------- paced display

/** Minimum time a paced stage frame stays on screen before the next real change is revealed. */
export const STAGE_PACE_MS = 3000;

/**
 * A stage list's *progress* only: ids and statuses, ignoring captions. Captions carry live counts and
 * relative times that change on every poll without the run having moved, so pacing keys off this.
 */
export function stagesProgressSignature(stages: readonly Stage[]): string {
  return stages.map((s) => `${s.id}:${s.status}`).join("|");
}

/** How far through a stage a status is. Only used to prove a paced frame never leads the real one. */
const STATUS_RANK: Record<StageStatus, number> = {
  unavailable: 0,
  pending: 0,
  running: 1,
  waiting: 2,
  completed: 3,
  failed: 3,
  skipped: 3,
};

/**
 * One step of a paced display: `shown` moved exactly one stage closer to `real`.
 *
 * Every stage in the result is taken verbatim either from `real` (the backend's current truth) or
 * from `shown` (a frame that was itself real at an earlier moment) — no status is ever synthesised
 * — and a stage is only ever held back when its displayed status ranks strictly *behind* the real
 * one. So for every stage the displayed status is at or behind the backend's, never ahead of it.
 * Each call makes at least one more stage match `real`, so repeated calls converge on the truth.
 */
export function advanceStages(shown: readonly Stage[], real: readonly Stage[]): Stage[] {
  const previous = new Map(shown.map((s) => [s.id, s]));
  let revealed = false;
  return real.map((r) => {
    const prev = previous.get(r.id);
    // Nothing older, or nothing behind to hold on to: show what the backend currently reports.
    if (!prev || prev.status === r.status || STATUS_RANK[prev.status] >= STATUS_RANK[r.status]) return r;
    if (revealed) return prev;
    revealed = true;
    return r;
  });
}

export function currentStage(stages: readonly Stage[]): StageId | null {
  const active = stages.find((x) => x.status === "running" || x.status === "waiting" || x.status === "failed");
  if (active) return active.id;
  const done = [...stages].reverse().find((x) => x.status === "completed");
  return done?.id ?? null;
}

/** One line for the incident navigator: where this incident's investigation is right now. */
export interface StageSummary {
  phase: Phase;
  stage: StageId | null;
  status: StageStatus | null;
}

export function summarizeStage(incident: IncidentSummary, inv: InvestigationOut | null): StageSummary {
  const phase = phaseOf(inv);
  if (phase === "none") return { phase, stage: null, status: null };
  const stages = deriveStages(incident, inv);
  const id = currentStage(stages);
  return { phase, stage: id, status: stages.find((x) => x.id === id)?.status ?? null };
}

// ------------------------------------------------------------------ situation + headline

export interface Situation {
  key: "no_investigation" | "resolved" | "running" | "awaiting_approval" | "completed" | "failed" | "escalated" | "inconclusive" | "queued";
  label: string;
  description: string;
}

export function deriveSituation(incident: IncidentSummary, inv: InvestigationOut | null): Situation {
  const phase = phaseOf(inv);
  if (phase === "none") {
    if (incident.status === "resolved")
      return { key: "resolved", label: "Resolved incident", description: "No investigation run is recorded in this browser. Stored graph evidence is shown as history." };
    return {
      key: "no_investigation",
      label: "No investigation started",
      description: "What you see below is stored graph evidence, not the result of an agent run.",
    };
  }
  const map: Record<Exclude<Phase, "none">, Situation> = {
    queued: { key: "queued", label: "Queued", description: "The run is recorded and waiting for the orchestrator." },
    running: { key: "running", label: "Investigation running", description: "Results are from run " + shortId(inv!.id) + " as the backend reports them." },
    awaiting_review: { key: "awaiting_approval", label: "Awaiting approval", description: "The run finished and proposed an action. Nothing has been executed." },
    completed: { key: "completed", label: "Investigation completed", description: "Context was retrieved by run " + shortId(inv!.id) + "." },
    escalated: { key: "escalated", label: "Escalated to a human", description: "The incident was handed to a person, by the safety gate or by a reviewer." },
    inconclusive: { key: "inconclusive", label: "Inconclusive", description: "The run found no evidence-backed explanation." },
    failed: { key: "failed", label: "Investigation failed", description: "The run stopped before it finished; partial output is not a conclusion." },
  };
  return map[phase];
}

export function deriveHeadline(incident: IncidentSummary, inv: InvestigationOut | null, stages: readonly Stage[]): string {
  const phase = phaseOf(inv);
  const get = (id: StageId) => stages.find((x) => x.id === id)!;
  switch (phase) {
    case "none":
      return incident.status === "resolved"
        ? "This incident is resolved. Start an investigation to re-examine it, or review the stored evidence."
        : "No investigation started. Start an investigation to see agents retrieve evidence and analyze possible causes.";
    case "queued":
      return "Investigation requested. Waiting for the orchestrator to pick it up.";
    case "running":
      return get("analyzing").status === "running"
        ? "Investigator is correlating retrieved evidence to form a hypothesis."
        : get("context").caption;
    case "awaiting_review":
      return `Investigation complete. ${get("review").caption}`;
    case "completed": {
      const review = get("review");
      const exec = get("execution");
      if (review.status === "completed") return `Investigation complete. ${review.caption} ${exec.caption}`;
      return "Investigation complete. Findings are below; no action was proposed for execution.";
    }
    case "escalated":
      return "Investigation escalated. The agent could not support a safe automated recommendation, so a human must decide.";
    case "inconclusive":
      return "Investigation inconclusive. The agents found no evidence-backed explanation.";
    case "failed":
      return `Investigation failed. ${inv?.error ?? "The run stopped before it finished."}`;
  }
}

// ------------------------------------------------------------------ agents

export type AgentId = "coordinator" | "graph_context" | "memory_context" | "telemetry_context" | "investigator" | "safety_gate";
export type AgentStatus = "pending" | "running" | "completed" | "failed" | "skipped" | "not_recorded";

export interface Discovery {
  text: string;
  tone: "neutral" | "positive" | "warning" | "danger";
}

export interface AgentLink {
  label: string;
  tab: TabId;
}

export interface AgentCardModel {
  id: AgentId;
  name: string;
  /** Plain description of the role, including what kind of component it is. */
  subtitle: string;
  status: AgentStatus;
  /** Present-tense description of what it is doing or did. */
  activity: string;
  nextStep: string | null;
  startedAt: string | null;
  duration: string | null;
  timingNote: string;
  resultCount: number | null;
  resultLabel: string;
  discoveries: Discovery[];
  links: AgentLink[];
  /** Technical details for engineers (expandable). */
  details: Array<{ label: string; value: string }>;
}

const TIMING_NOTE = "Not recorded: runs from before step events were stored have no per-branch times.";

function mapBranchStatus(s: BranchStatus): AgentStatus {
  return s;
}

export const CLAIM_LABELS: Record<ClaimType, string> = {
  observed: "Observed",
  correlated: "Correlated",
  hypothesis: "Hypothesis",
  confirmed: "Confirmed",
};

function trunc(text: string, n = 160): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

function graphDiscoveries(bundle: RetrievalBundle | null): { items: Discovery[]; count: number | null } {
  if (!bundle) return { items: [], count: null };
  const gc = bundle.graph_context;
  const items: Discovery[] = [];
  const seen = new Set<string>();
  const add = (text: string, tone: Discovery["tone"] = "neutral") => {
    if (!seen.has(text)) {
      seen.add(text);
      items.push({ text, tone });
    }
  };
  for (const path of gc.explanation_paths) {
    for (const hop of path.hops) {
      if (hop.rel === "DEPENDS_ON") add(`${shortId(hop.from_id)} depends on ${shortId(hop.to_id)}.`);
    }
    add(`Recent deployment ${path.deployment.version} on ${shortId(path.target_service_id)} (${relativeTime(path.deployment.deployed_at)}).`);
    for (const d of path.governing_decisions) {
      add(`Policy: ${d.title}${d.required_approver_role ? ` — requires ${d.required_approver_role}` : ""}.`);
    }
    for (const r of path.runbooks) add(`Runbook found: ${r.title}.`);
  }
  const chunks = bundle.knowledge_context.items.length;
  if (chunks > 0) add(`${chunks} company document excerpt${chunks === 1 ? "" : "s"} matched this incident.`);
  const count = gc.evidence.length + gc.explanation_paths.length + chunks;
  return { items, count };
}

function memoryDiscoveries(bundle: RetrievalBundle | null): { items: Discovery[]; count: number | null } {
  if (!bundle) return { items: [], count: null };
  const mc = bundle.memory_context;
  const items: Discovery[] = mc.items.map((m) => ({
    text: `${m.about_incident_key ?? "Earlier incident"}: ${trunc(m.summary)}${m.precedent === "warns_against" ? " (did not work: do not repeat)" : ""}`,
    tone: m.precedent === "warns_against" ? "warning" : m.precedent === "supports" ? "positive" : "neutral",
  }));
  const ex = Object.entries(mc.excluded ?? {}).filter(([, n]) => n > 0);
  if (ex.length > 0) items.push({ text: `Excluded from evidence: ${ex.map(([k, n]) => `${n} ${k}`).join(", ")}.`, tone: "neutral" });
  return { items, count: mc.items.length };
}

function telemetryDiscoveries(inv: InvestigationOut): { items: Discovery[]; count: number } {
  const cited = inv.evidence_refs.filter((e) => e.source_ref.includes("/telemetry/"));
  return {
    items: cited.slice(0, 4).map((e) => ({ text: e.excerpt ? trunc(e.excerpt) : e.id, tone: "neutral" as const })),
    count: cited.length,
  };
}

const GATE_TEXT: Record<string, string> = {
  accept: "Accepted the investigator's output.",
  revise: "Asked the investigator to revise its output.",
  recommendation_only: "Allowed a recommendation only; no executable action.",
  escalate: "Escalated to a human: no safe recommendation.",
  inconclusive: "Marked the run inconclusive.",
};

export interface AgentInputs {
  incident: IncidentDetail;
  investigation: InvestigationOut | null;
  bundle: RetrievalBundle | null;
}

export function deriveAgents({ investigation: inv, bundle }: AgentInputs): AgentCardModel[] {
  if (!inv) return [];
  const phase = phaseOf(inv);
  const t = tally(inv);
  const base = { startedAt: null, duration: null, timingNote: TIMING_NOTE, nextStep: null, links: [] as AgentLink[] };
  const ran = !(phase === "queued");

  // ---- coordinator
  const dispatched = (Object.keys(BRANCH_LABELS) as BranchName[]).filter((n) => branchStatus(inv, n) !== "skipped");
  const skipped = (Object.keys(BRANCH_LABELS) as BranchName[]).filter((n) => branchStatus(inv, n) === "skipped");
  const reached = !t.allPending;
  let coordStatus: AgentStatus;
  if (phase === "queued") coordStatus = "pending";
  else if (reached) coordStatus = "completed";
  else if (phase === "running") coordStatus = "running";
  else coordStatus = phase === "failed" ? "failed" : "completed";
  const coordinator: AgentCardModel = {
    ...base,
    id: "coordinator",
    name: "Coordinator",
    subtitle: "Orchestrator step that scopes the incident and fans out retrieval branches",
    status: coordStatus,
    activity:
      coordStatus === "pending"
        ? "Waiting for the worker to claim this run."
        : coordStatus === "running"
          ? "Scoping the incident and choosing which retrieval branches to run."
          : coordStatus === "failed"
            ? errorText(inv)
            : `Started the investigation and dispatched ${dispatched.length} retrieval branch${dispatched.length === 1 ? "" : "es"}.`,
    startedAt: ran ? inv.started_at : null,
    duration: formatDuration(inv.started_at, inv.ended_at),
    timingNote: "Start is when the run was requested. Duration is the whole run, not just the coordinator.",
    resultCount: reached ? dispatched.length : null,
    resultLabel: "branches dispatched",
    discoveries: [
      ...(reached ? dispatched.map((n) => ({ text: `Dispatched: ${BRANCH_LABELS[n]}.`, tone: "neutral" as const })) : []),
      ...skipped.map((n) => ({
        text: `Skipped: ${BRANCH_LABELS[n]}${inv.branches?.[n]?.detail ? ` (${inv.branches[n]!.detail})` : ""}.`,
        tone: "neutral" as const,
      })),
    ],
    details: [
      { label: "Run id", value: inv.id },
      { label: "Thread", value: inv.thread_id },
      { label: "Mode", value: inv.mode },
      { label: "Requested by", value: inv.requested_by ?? "not recorded" },
    ],
  };

  // ---- retrieval branches
  const branchCard = (
    name: BranchName,
    subtitle: string,
    activityRunning: string,
    disc: { items: Discovery[]; count: number | null },
    resultLabel: string,
    links: AgentLink[],
  ): AgentCardModel => {
    const entry = inv.branches?.[name];
    const status = mapBranchStatus(phase === "queued" ? "pending" : branchStatus(inv, name));
    const detail = entry?.detail ?? null;
    return {
      ...base,
      id: name,
      name: BRANCH_LABELS[name],
      subtitle,
      status,
      activity:
        status === "completed"
          ? detail ?? "Finished."
          : status === "running"
            ? activityRunning
            : status === "failed"
              ? detail ?? "Failed without a recorded reason."
              : status === "skipped"
                ? detail ?? "Skipped."
                : status === "pending"
                  ? "Waiting for the coordinator."
                  : "The backend did not record a state for this branch.",
      startedAt: entry?.started_at ?? null,
      duration: formatDuration(entry?.started_at, entry?.ended_at),
      timingNote: "From the orchestrator's own step events.",
      resultCount: status === "completed" ? disc.count : null,
      resultLabel,
      discoveries: status === "completed" ? disc.items : [],
      links: status === "completed" ? links : [],
      details: [
        { label: "Branch key", value: name },
        { label: "Backend status", value: status },
        { label: "Backend detail", value: detail ?? "none" },
        ...(status === "completed" && name !== "telemetry_context"
          ? [{ label: "Discoveries from", value: "the incident's retrieval snapshot (same retrieval code the branch runs)" }]
          : []),
      ],
    };
  };

  const graph = branchCard(
    "graph_context",
    "Retrieval branch: graph traversal plus keyword/vector search over company documents",
    "Traversing dependencies, deployments, ownership and policy around the affected services.",
    graphDiscoveries(bundle),
    "items found",
    [{ label: "View graph evidence", tab: "evidence" }],
  );
  const memory = branchCard(
    "memory_context",
    "Retrieval branch: verified memories of earlier incidents",
    "Looking for verified memories of similar earlier incidents.",
    memoryDiscoveries(bundle),
    "verified memories",
    [{ label: "View similar incidents", tab: "knowledge" }],
  );
  const tel = telemetryDiscoveries(inv);
  const telemetry = branchCard(
    "telemetry_context",
    "Retrieval branch: live metrics around the incident window",
    "Reading metrics and observations from the incident window.",
    tel,
    "cited observations",
    [{ label: "View evidence", tab: "evidence" }],
  );

  // ---- investigator
  const open = t.open > 0;
  let invStatus: AgentStatus;
  if (phase === "queued") invStatus = "pending";
  else if (phase === "running") invStatus = open ? "pending" : "running";
  else if (phase === "failed") invStatus = t.completed === 0 ? "skipped" : "failed";
  else if (t.completed === 0) invStatus = "skipped";
  else invStatus = "completed";
  const claims = inv.findings;
  const investigator: AgentCardModel = {
    ...base,
    id: "investigator",
    name: "Investigator",
    subtitle: inv.investigator ? `Reasoning step (${inv.investigator}) that reads the completed branches` : "Reasoning step that reads the completed branches",
    status: invStatus,
    activity:
      invStatus === "pending"
        ? "Waits for the retrieval branches to report."
        : invStatus === "running"
          ? "Comparing deployment changes and metrics with the reported failures."
          : invStatus === "skipped"
            ? "Not run: no retrieval branch completed."
            : invStatus === "failed"
              ? errorText(inv)
              : inv.summary ?? "Finished without a written summary.",
    nextStep: invStatus === "running" ? "Correlate the retrieved evidence, then hand the result to the safety gate." : null,
    resultCount: invStatus === "completed" ? claims.length : null,
    resultLabel: "findings",
    discoveries:
      invStatus === "completed"
        ? claims.slice(0, 3).map((f) => ({
            text: `${CLAIM_LABELS[f.claim_type]}: ${trunc(f.statement, 200)}`,
            tone: f.claim_type === "confirmed" ? ("positive" as const) : ("neutral" as const),
          }))
        : [],
    links: invStatus === "completed" && claims.length > 0 ? [{ label: "See what we found", tab: "live" }] : [],
    details: [
      { label: "Implementation", value: inv.investigator ?? "not recorded" },
      { label: "Revisions after gate feedback", value: String(inv.revision_count ?? 0) },
      { label: "Overall uncertainty", value: inv.overall_uncertainty ?? "none recorded" },
    ],
  };

  // ---- safety gate
  const gate = inv.gate;
  const violations = gate?.violations ?? [];
  const gateCard: AgentCardModel = {
    ...base,
    id: "safety_gate",
    name: "Evidence Safety Gate",
    subtitle: "Automated check (not an AI agent): verifies claims and actions against stored evidence",
    status: gate ? "completed" : phase === "none" || phase === "queued" || phase === "running" ? "pending" : "not_recorded",
    activity: gate
      ? (GATE_TEXT[gate.decision] ?? gate.decision)
      : phase === "running" || phase === "queued"
        ? "Runs after the investigator."
        : "No gate result was recorded for this run.",
    resultCount: gate ? violations.length : null,
    resultLabel: "violations",
    discoveries: violations.map((v) => ({ text: `${v.code}: ${trunc(v.detail)}`, tone: "danger" as const })),
    details: [{ label: "Decision", value: gate?.decision ?? "none" }],
  };

  return [coordinator, graph, memory, telemetry, investigator, gateCard];
}

// ------------------------------------------------------------------ findings

export interface EvidenceCard {
  id: string;
  title: string;
  text: string;
  sourceRef: string;
  observedAt: string | null;
  kind: string;
}

export interface RecommendedAction {
  key: string;
  title: string;
  targetService: string;
  deployment: string | null;
  risk: string | null;
  runbook: string | null;
  requiredApprovals: string[];
  policy: string | null;
  /** True when produced by an investigation run; false when only derived from graph paths. */
  fromRun: boolean;
  proposal: ProposedActionOut | null;
  path: ExplanationPath | null;
  rationale: string | null;
}

export interface FindingsModel {
  /** "run" = from an investigation, "graph" = stored correlation only, "none". */
  origin: "run" | "graph" | "none";
  cause: { text: string; claim: ClaimType | "stored_correlation"; confidence: number | null; uncertainty: string | null } | null;
  evidence: EvidenceCard[];
  byClaim: Record<ClaimType, FindingOut[]>;
  contradicted: FindingOut[];
  warnings: string[];
  primaryAction: RecommendedAction | null;
  alternatives: RecommendedAction[];
}

export const EVIDENCE_KIND_LABELS: Record<string, string> = {
  deploy_event: "Recent deployment",
  metric: "Metric",
  log: "Log",
  alert: "Alert",
  ticket: "Ticket",
  doc: "Document",
};

function approvalRoles(path: ExplanationPath | null): string[] {
  if (!path || path.approval_policy === "no_active_policy_escalate") return [];
  return [...new Set(path.governing_decisions.map((d) => d.required_approver_role).filter((r): r is string => Boolean(r)))];
}

function policyText(path: ExplanationPath | null): string | null {
  if (!path) return null;
  if (path.approval_policy === "no_active_policy_escalate") return "No active policy: escalate to a human.";
  const d = path.governing_decisions[0];
  return d ? d.title : "Policy in force, no governing decision recorded.";
}

export function pathForTarget(paths: readonly ExplanationPath[], target: string, deploymentId: string | null): ExplanationPath | null {
  return paths.find((p) => p.target_service_id === target && p.deployment.id === deploymentId) ?? paths.find((p) => p.target_service_id === target) ?? null;
}

function toEvidenceCards(refs: ReadonlyArray<{ id: string; kind: string; source_ref: string; observed_at?: string | null; excerpt?: string | null }>): EvidenceCard[] {
  const seen = new Set<string>();
  const out: EvidenceCard[] = [];
  for (const e of refs) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    out.push({
      id: e.id,
      title: EVIDENCE_KIND_LABELS[e.kind] ?? e.kind,
      text: e.excerpt ?? "No excerpt recorded.",
      sourceRef: e.source_ref,
      observedAt: e.observed_at ?? null,
      kind: e.kind,
    });
  }
  return out;
}

export function deriveActions(incident: IncidentDetail, inv: InvestigationOut | null): RecommendedAction[] {
  const paths = incident.explanation_paths ?? [];
  const proposals = inv?.proposed_actions ?? [];
  if (proposals.length > 0) {
    return proposals.map((p) => {
      const path = pathForTarget(paths, p.target_service_id, p.deployment_id);
      const runbook = path?.runbooks.find((r) => r.id === p.runbook_id);
      return {
        key: p.id,
        title: actionTitle(p.action_type),
        targetService: p.target_service_id,
        deployment: p.deployment_id,
        risk: p.risk,
        runbook: runbook ? `${runbook.title} (v${runbook.version})` : p.runbook_id,
        requiredApprovals: p.required_approver_role ? [p.required_approver_role] : approvalRoles(path),
        policy: policyText(path),
        fromRun: true,
        proposal: p,
        path,
        rationale: p.rationale,
      };
    });
  }
  const out: RecommendedAction[] = [];
  paths.forEach((path, i) => {
    for (const rb of path.runbooks) {
      for (const type of rb.allowed_action_types ?? []) {
        out.push({
          key: `${i}:${rb.id}:${type}`,
          title: actionTitle(type),
          targetService: path.target_service_id,
          deployment: path.deployment.id,
          risk: null,
          runbook: `${rb.title} (v${rb.version})`,
          requiredApprovals: approvalRoles(path),
          policy: policyText(path),
          fromRun: false,
          proposal: null,
          path,
          rationale: null,
        });
      }
    }
  });
  return out;
}

export function deriveFindings(
  incident: IncidentDetail,
  inv: InvestigationOut | null,
  memories: IncidentMemories | null,
): FindingsModel {
  const byClaim: Record<ClaimType, FindingOut[]> = { confirmed: [], observed: [], correlated: [], hypothesis: [] };
  const actions = deriveActions(incident, inv);
  const paths = incident.explanation_paths ?? [];
  const hasRunOutput = !!inv && (inv.findings.length > 0 || !!inv.summary);

  if (inv && hasRunOutput) {
    for (const f of inv.findings) byClaim[f.claim_type].push(f);
    const lead = inv.findings.find((f) => (f.contradicting_evidence ?? []).length === 0) ?? inv.findings[0];
    const refs = inv.findings.flatMap((f) => f.evidence);
    const evidence = toEvidenceCards(refs.length > 0 ? refs : inv.evidence_refs);
    const similar = memories?.memories.find((m) => m.verification_status === "verified" && m.precedent === "supports");
    if (similar) {
      evidence.push({
        id: similar.id,
        title: "Related historical incident",
        text: similar.summary,
        sourceRef: similar.about_incident_key ?? similar.about_incident_id,
        observedAt: similar.validated_at ?? null,
        kind: "memory",
      });
    }
    return {
      origin: "run",
      cause: {
        text: inv.summary ?? lead?.statement ?? "The run finished without a written cause.",
        claim: lead?.claim_type ?? "hypothesis",
        confidence: lead?.confidence ?? null,
        uncertainty: lead?.uncertainty ?? inv.overall_uncertainty ?? null,
      },
      evidence,
      byClaim,
      contradicted: inv.findings.filter((f) => (f.contradicting_evidence ?? []).length > 0),
      warnings: inv.integrity_warnings ?? [],
      primaryAction: actions[0] ?? null,
      alternatives: actions.slice(1),
    };
  }

  const path = paths[0];
  if (!inv && path) {
    return {
      origin: "graph",
      cause: { text: path.summary, claim: "stored_correlation", confidence: null, uncertainty: "A stored graph correlation. No agent has examined it." },
      evidence: toEvidenceCards(path.evidence),
      byClaim,
      contradicted: [],
      warnings: [],
      primaryAction: actions[0] ?? null,
      alternatives: actions.slice(1),
    };
  }

  return {
    origin: "none",
    cause: null,
    evidence: [],
    byClaim,
    contradicted: [],
    warnings: inv?.integrity_warnings ?? [],
    primaryAction: actions[0] ?? null,
    alternatives: actions.slice(1),
  };
}

// ------------------------------------------------------------------ activity events

export interface ActivityEvent {
  id: string;
  at: string;
  type: string;
  label: string;
  summary: string;
  actor: string | null;
  refId: string | null;
  tone: "neutral" | "info" | "success" | "warning" | "danger";
  details: Array<{ label: string; value: string }>;
  /** Where a reviewer can look at what the event refers to. */
  link: AgentLink | null;
}

export interface RecordedTimelineEvent {
  id: string;
  at: string;
  type: string;
  actor?: string | null;
  summary?: string | null;
  ref_id?: string | null;
}

const EVENT_LABELS: Record<string, { label: string; tone: ActivityEvent["tone"] }> = {
  alert_fired: { label: "Alert received", tone: "danger" },
  incident_opened: { label: "Incident opened", tone: "warning" },
  status_change: { label: "Incident status changed", tone: "info" },
  investigation_requested: { label: "Investigation requested", tone: "info" },
  investigation_completed: { label: "Investigation completed", tone: "success" },
  investigation_awaiting_review: { label: "Awaiting human approval", tone: "warning" },
  investigation_escalated: { label: "Escalated to a human", tone: "warning" },
  investigation_inconclusive: { label: "Investigation inconclusive", tone: "neutral" },
  investigation_failed: { label: "Investigation failed", tone: "danger" },
  human_action: { label: "Human action", tone: "neutral" },
  approval: { label: "Approval recorded", tone: "success" },
  action_approved: { label: "Action approved", tone: "success" },
  action_rejected: { label: "Action rejected", tone: "danger" },
  action_revision_requested: { label: "Revision requested", tone: "warning" },
  action_escalated: { label: "Action escalated", tone: "warning" },
  action_executed_simulated: { label: "Simulated execution", tone: "success" },
  agent_step_completed: { label: "Agent step finished", tone: "neutral" },
  agent_step_failed: { label: "Agent step failed", tone: "danger" },
  agent_step_skipped: { label: "Agent step skipped", tone: "neutral" },
  agent_step_waiting: { label: "Waiting for a person", tone: "warning" },
};

const STEP_LABELS: Record<string, string> = {
  intake_and_deduplicate: "Intake and de-duplication",
  coordinator: "Coordinator",
  graph_context_retrieval: "Graph context retrieval",
  memory_retrieval: "Memory retrieval",
  live_evidence_retrieval: "Live evidence retrieval",
  fan_in: "Fan-in",
  investigator: "Investigator",
  evidence_safety_gate: "Evidence safety gate",
  human_review: "Human review",
};

/**
 * Orchestrator step events as timeline rows. "started" events are dropped: each step's closing event
 * already carries what happened, and showing both doubles the length of the timeline.
 */
export function runEventsToTimeline(events: readonly AgentEventOut[] | null | undefined): RecordedTimelineEvent[] {
  return (events ?? [])
    .filter((e) => e.status !== "started")
    .map((e) => {
      const step = STEP_LABELS[e.kind] ?? e.kind.replace(/_/g, " ");
      return {
        id: `run:${e.id}`,
        at: e.at,
        type: `agent_step_${e.status}`,
        actor: "orchestrator",
        summary: e.detail ? `${step}: ${e.detail}` : step,
      };
    });
}

export function describeEventType(type: string): { label: string; tone: ActivityEvent["tone"] } {
  return EVENT_LABELS[type] ?? { label: type.replace(/_/g, " "), tone: "neutral" };
}

/** Merge by id (last write wins) and sort oldest first. Re-fetching never duplicates an event. */
export function mergeTimeline(...lists: ReadonlyArray<readonly RecordedTimelineEvent[]>): RecordedTimelineEvent[] {
  const byId = new Map<string, RecordedTimelineEvent>();
  for (const list of lists) for (const e of list) byId.set(e.id, e);
  return [...byId.values()]
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (Date.parse(a.e.at) || 0) - (Date.parse(b.e.at) || 0) || a.e.id.localeCompare(b.e.id) || a.i - b.i)
    .map(({ e }) => e);
}

export function deriveEvents(
  incident: IncidentDetail,
  inv: InvestigationOut | null,
  recorded: readonly RecordedTimelineEvent[],
): ActivityEvent[] {
  return mergeTimeline(recorded).map((e) => {
    const meta = describeEventType(e.type);
    const details: ActivityEvent["details"] = [
      { label: "Event type", value: e.type },
      { label: "Recorded by", value: e.actor ?? "unknown" },
    ];
    let link: AgentLink | null = null;
    const ref = e.ref_id ?? null;
    if (ref) {
      details.push({ label: "Reference", value: ref });
      const alert = incident.alerts.find((a) => a.id === ref);
      const evidence = incident.evidence.find((x) => x.id === ref);
      if (alert) {
        details.push({ label: "Alert", value: alert.summary ?? alert.fingerprint });
        if (alert.source_ref) details.push({ label: "Source", value: alert.source_ref });
        link = { label: "View in evidence graph", tab: "evidence" };
      } else if (evidence) {
        details.push({ label: "Evidence", value: evidence.excerpt ?? evidence.id }, { label: "Source", value: evidence.source_ref });
        link = { label: "View in evidence graph", tab: "evidence" };
      } else if (inv && ref === inv.id) {
        details.push({ label: "Investigation status", value: inv.status }, { label: "Mode", value: inv.mode });
        for (const [name, b] of Object.entries(inv.branches ?? {})) {
          if (b) details.push({ label: `Branch ${name}`, value: `${b.status}${b.detail ? ` — ${b.detail}` : ""}` });
        }
        if (inv.investigator) details.push({ label: "Investigator", value: inv.investigator });
        link = { label: "View investigation", tab: "live" };
      }
    }
    return {
      id: e.id,
      at: e.at,
      type: e.type,
      label: meta.label,
      summary: e.summary ?? "No summary recorded.",
      actor: e.actor ?? null,
      refId: ref,
      tone: meta.tone,
      details,
      link,
    };
  });
}

// ------------------------------------------------------------------ memory helpers

/** True when the run's own text names this memory, i.e. the investigator cited it. */
export function citedByRun(inv: InvestigationOut | null, memory: Pick<MemoryOut, "id">): boolean {
  if (!inv) return false;
  const text = [inv.summary, inv.overall_uncertainty, ...inv.findings.flatMap((f) => [f.statement, f.uncertainty])].filter(Boolean).join("\n");
  return text.includes(memory.id);
}

// ------------------------------------------------------------------ view

export interface InvestigationView {
  phase: Phase;
  situation: Situation;
  stages: Stage[];
  currentStage: StageId | null;
  headline: string;
  agents: AgentCardModel[];
  findings: FindingsModel;
  events: ActivityEvent[];
}

export function buildInvestigationView(args: {
  incident: IncidentDetail;
  investigation: InvestigationOut | null;
  bundle: RetrievalBundle | null;
  memories: IncidentMemories | null;
  timeline: readonly RecordedTimelineEvent[];
  runEvents?: readonly AgentEventOut[] | null;
}): InvestigationView {
  const { incident, investigation, bundle, memories, timeline, runEvents } = args;
  const stages = deriveStages(incident, investigation);
  return {
    phase: phaseOf(investigation),
    situation: deriveSituation(incident, investigation),
    stages,
    currentStage: currentStage(stages),
    headline: deriveHeadline(incident, investigation, stages),
    agents: deriveAgents({ incident, investigation, bundle }),
    findings: deriveFindings(incident, investigation, memories),
    events: deriveEvents(incident, investigation, [...timeline, ...runEventsToTimeline(runEvents)]),
  };
}

export { STAGE_ORDER };
