/**
 * TypeScript mirror of the API contracts.
 *
 * Sources:
 *  - apps/api/app/api/models.py   (Pydantic v2 request/response models)
 *  - apps/api/app/rag/retrieval.py (RetrievalBundle and friends)
 *  - apps/api/app/tools/graph_tools.py (DeploymentHit)
 *
 * Datetimes arrive as ISO-8601 strings. Optional Pydantic fields with a default are still always
 * serialised by the server, but are typed optional here where the server could omit them.
 * Enums are string-literal unions, each backed by a `const` array so code can iterate over them.
 */

/** ISO-8601 datetime string, e.g. "2026-10-17T14:05:00Z". */
export type IsoDateTime = string;

// ------------------------------------------------------------------ enums
export const DEMO_USERS = ["demo-viewer", "demo-responder", "payments-lead"] as const;
export type DemoUser = (typeof DEMO_USERS)[number];

export const SEVERITIES = ["sev1", "sev2", "sev3", "sev4"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const INCIDENT_STATUSES = ["open", "investigating", "mitigated", "resolved"] as const;
export type IncidentStatus = (typeof INCIDENT_STATUSES)[number];

export const ALERT_SEVERITIES = ["critical", "warning", "info"] as const;
export type AlertSeverity = (typeof ALERT_SEVERITIES)[number];

export const MODES = ["recommendation_only", "simulation"] as const;
export type Mode = (typeof MODES)[number];

export const INVESTIGATION_STATUSES = [
  "queued",
  "running",
  "awaiting_review",
  "completed",
  "failed",
  "escalated",
  "inconclusive",
  "timed_out",
] as const;
export type InvestigationStatus = (typeof INVESTIGATION_STATUSES)[number];

export const TERMINAL_INVESTIGATION_STATUSES = [
  "completed",
  "failed",
  "escalated",
  "inconclusive",
  "timed_out",
] as const satisfies readonly InvestigationStatus[];
export type TerminalInvestigationStatus = (typeof TERMINAL_INVESTIGATION_STATUSES)[number];

export const BRANCH_NAMES = ["graph_context", "memory_context", "telemetry_context"] as const;
export type BranchName = (typeof BRANCH_NAMES)[number];

export const BRANCH_STATUSES = ["pending", "running", "completed", "failed", "skipped", "not_recorded"] as const;
export type BranchStatus = (typeof BRANCH_STATUSES)[number];

export const CLAIM_TYPES = ["observed", "correlated", "hypothesis", "confirmed"] as const;
export type ClaimType = (typeof CLAIM_TYPES)[number];

/** Verdict of the safety gate that checks the investigator's output before it is stored. */
export const GATE_DECISIONS = ["accept", "revise", "recommendation_only", "escalate", "inconclusive"] as const;
export type GateDecision = (typeof GATE_DECISIONS)[number];

export const ACTION_RISKS = ["low", "medium", "high"] as const;
export type ActionRisk = (typeof ACTION_RISKS)[number];

export type DataClassification = "synthetic";

export type MemoryType = "episodic" | "procedural";
export type VerificationStatus = "draft" | "verified" | "rejected" | "superseded";
export type MemoryOutcome = "successful" | "failed" | "unknown";
export type Precedent = "supports" | "warns_against" | "none";
export type MemoryRelation = "same_incident" | "shared_service";
export type ValidationMethod = "human" | "ground_truth";
export type ApprovalPolicy = "policy_in_force" | "no_active_policy_escalate";
export type AlertIngestOutcome = "created_incident" | "attached_to_incident" | "deduplicated" | "replayed";

// ------------------------------------------------------------- shared refs
export interface ServiceRef {
  id: string;
  name?: string | null;
  tier?: string | null;
}

export interface EvidenceRef {
  id: string;
  kind: string;
  source_ref: string;
  observed_at?: IsoDateTime | null;
  excerpt?: string | null;
}

export interface ResponderRef {
  id: string;
  handle: string;
  roles?: string[];
}

export interface DocumentRef {
  id: string;
  title?: string | null;
  uri?: string | null;
  doc_type?: string | null;
}

/** One real edge in the graph, in its stored direction. */
export interface PathHop {
  from_label: string;
  from_id: string;
  rel: string;
  to_label: string;
  to_id: string;
}

// ------------------------------------------------------------------ alerts
export interface AlertIn {
  fingerprint: string;
  service_id: string;
  severity: AlertSeverity;
  /** Must carry a timezone. */
  fired_at: IsoDateTime;
  summary: string;
  source_ref: string;
}

export interface AlertIngestResult {
  outcome: AlertIngestOutcome;
  alert_id: string;
  incident_id: string | null;
  incident_key: string | null;
  dedup_count: number;
  dedup_window_seconds: number;
}

export interface AlertOut {
  id: string;
  fingerprint: string;
  severity: string;
  fired_at: IsoDateTime;
  last_fired_at?: IsoDateTime | null;
  dedup_count?: number;
  summary?: string | null;
  source_ref?: string | null;
}

// --------------------------------------------------------------- incidents
export interface IncidentSummary {
  id: string;
  key: string;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  started_at: IsoDateTime;
  resolved_at?: IsoDateTime | null;
  affected_service_ids: string[];
  alert_count: number;
  data_classification?: DataClassification;
}

export interface IncidentList {
  items: IncidentSummary[];
  limit: number;
  offset: number;
}

export interface EvidenceOut extends EvidenceRef {
  observed_on_service_ids: string[];
  refers_to_deployment_ids: string[];
}

export interface DeploymentRef {
  id: string;
  version: string;
  deployed_at: IsoDateTime;
  status?: string | null;
  source_ref?: string | null;
}

export interface DecisionRef {
  id: string;
  title: string;
  status: string;
  required_approver_role?: string | null;
  documented_in?: DocumentRef[];
}

export interface RunbookRef {
  id: string;
  title: string;
  version: string;
  uri?: string | null;
  allowed_action_types?: string[];
}

/** Graph-derived correlation. It is evidence for a hypothesis, never a confirmed cause. */
export interface ExplanationPath {
  kind: "rollback_candidate";
  claim_type: "correlated";
  summary: string;
  hops: PathHop[];
  target_service_id: string;
  deployment: DeploymentRef;
  evidence: EvidenceRef[];
  governing_decisions: DecisionRef[];
  runbooks: RunbookRef[];
  approval_policy: ApprovalPolicy;
}

export interface IncidentDetail extends IncidentSummary {
  affected_services: ServiceRef[];
  alerts: AlertOut[];
  evidence: EvidenceOut[];
  explanation_paths: ExplanationPath[];
  as_of: IsoDateTime;
}

/** PATCH body. Provide status and/or severity. The response is an IncidentSummary. */
export interface IncidentUpdate {
  status?: IncidentStatus;
  severity?: Severity;
}

export interface TimelineEventOut {
  id: string;
  at: IsoDateTime;
  type: string;
  actor?: string | null;
  summary?: string | null;
  ref_id?: string | null;
}

export interface IncidentTimeline {
  incident_id: string;
  events: TimelineEventOut[];
}

export interface MemoryOut {
  id: string;
  memory_type: MemoryType;
  verification_status: VerificationStatus;
  outcome: MemoryOutcome;
  /** supports = verified success; warns_against = verified failure; none = not verified. */
  precedent: Precedent;
  summary: string;
  about_incident_id: string;
  about_incident_key: string | null;
  relation: MemoryRelation;
  shared_service_ids: string[];
  grounded_in: EvidenceRef[];
  validated_by: ResponderRef[];
  derived_from_action_ids: string[];
  provenance_refs: string[];
  validated_at?: IsoDateTime | null;
  validation_method?: ValidationMethod | null;
  model_version?: string | null;
}

export interface IncidentMemories {
  incident_id: string;
  include_unverified: boolean;
  memories: MemoryOut[];
}

// ---------------------------------------------------------------- services
export interface TeamOut {
  id: string;
  name: string;
  members: ResponderRef[];
}

export interface DependencyOut {
  service: ServiceRef;
  depth: number;
  /** Service ids along DEPENDS_ON, in stored edge direction. */
  path: string[];
  rel?: "DEPENDS_ON";
}

export interface DecisionOut {
  id: string;
  title: string;
  statement: string;
  status: string;
  effective_from: IsoDateTime;
  effective_to?: IsoDateTime | null;
  required_approver_role?: string | null;
  documented_in: DocumentRef[];
  supersedes: string[];
}

export interface ServiceContext {
  service: ServiceRef;
  owners: TeamOut[];
  dependencies: DependencyOut[];
  dependents: DependencyOut[];
  active_decisions: DecisionOut[];
  runbooks: RunbookRef[];
  recent_deployments: DeploymentRef[];
  depth: number;
  as_of: IsoDateTime;
  data_classification?: DataClassification;
}

// ---------------------------------------------------------- investigations
export interface InvestigationIn {
  incident_id: string;
  mode?: Mode;
}

export interface BranchState {
  status: BranchStatus;
  detail?: string | null;
  started_at?: IsoDateTime | null;
  ended_at?: IsoDateTime | null;
}

export interface FindingOut {
  claim_type: ClaimType;
  statement: string;
  /** Supporting evidence. */
  evidence: EvidenceRef[];
  /** Evidence that argues against the statement (Phase 4; absent in older responses). */
  contradicting_evidence?: EvidenceRef[];
  /** 0..1, or null when the investigator gave none. */
  confidence?: number | null;
  uncertainty?: string | null;
  integrity_warnings?: string[];
}

export interface GateViolation {
  code: string;
  /** Where in the investigator output the problem is, e.g. "proposed_actions[0]". */
  target: string;
  detail: string;
}

export interface GateOut {
  decision: GateDecision;
  violations: GateViolation[];
}

/**
 * A proposed (never executed) action produced by an investigation run. `spec` is the exact argument
 * object and `spec_hash` its SHA-256 hex digest; approval binds to that hash.
 */
export interface ProposedActionOut {
  id: string;
  proposal_id: string;
  version: number;
  action_type: string;
  /** "proposed" | "pending_review" | ... (kept open: Phase 5 adds review states). */
  status: string;
  mode: Mode;
  target_service_id: string;
  deployment_id: string | null;
  runbook_id: string;
  risk: ActionRisk;
  rationale: string;
  spec: Record<string, unknown>;
  spec_hash: string;
  evidence: EvidenceRef[];
  integrity_warnings?: string[];
  /** Role the active policy requires to approve this action, or null when no policy applies. */
  required_approver_role?: string | null;
  approval_policy_id?: string | null;
  reviews?: ReviewOut[];
  /** Set only after a simulated execution. */
  execution?: ExecutionOut | null;
}

export const REVIEW_DECISIONS = ["APPROVE", "REJECT", "REQUEST_REVISION", "ESCALATE"] as const;
export type ReviewDecision = (typeof REVIEW_DECISIONS)[number];

export interface ReviewIn {
  decision: ReviewDecision;
  comment?: string | null;
}

export interface ReviewOut {
  id: string;
  decision: ReviewDecision;
  approver_id: string;
  approver_handle?: string | null;
  decided_at: IsoDateTime;
  expires_at?: IsoDateTime | null;
  comment?: string | null;
  spec_hash: string;
  action_version: number;
  policy_decision_id?: string | null;
}

/** Outcome of a SIMULATED execution. Nothing real was changed. */
export interface ExecutionOut {
  simulated: true;
  result: "succeeded" | "failed";
  ticket?: string | null;
  executed_at: IsoDateTime;
  note?: string | null;
}

export interface ReviewResult {
  action: ProposedActionOut;
  review: ReviewOut;
  investigation_status: InvestigationStatus;
  /** Draft memory written after a simulated execution; hidden from retrieval until a human validates it. */
  memory_id?: string | null;
  message: string;
}

export interface MemoryReviewOut {
  id: string;
  verification_status: string;
  outcome: string;
}

export interface InvestigationSummary {
  id: string;
  mode: Mode;
  status: InvestigationStatus;
  requested_by?: string | null;
  started_at: IsoDateTime;
  ended_at?: IsoDateTime | null;
  revision_count?: number;
  investigator?: string | null;
  summary?: string | null;
  error?: string | null;
}

export interface InvestigationList {
  incident_id: string;
  items: InvestigationSummary[];
}

export type AgentEventStatus = "started" | "completed" | "failed" | "skipped" | "waiting";

/** One orchestrator step transition. Dedupe by id. */
export interface AgentEventOut {
  id: string;
  kind: string;
  status: AgentEventStatus;
  at: IsoDateTime;
  revision?: number;
  detail?: string | null;
}

export interface InvestigationEvents {
  investigation_id: string;
  status: InvestigationStatus;
  events: AgentEventOut[];
}

export interface InvestigationOut {
  id: string;
  thread_id: string;
  incident_id: string | null;
  incident_key: string | null;
  mode: Mode;
  status: InvestigationStatus;
  requested_by?: string | null;
  started_at: IsoDateTime;
  ended_at?: IsoDateTime | null;
  revision_count?: number;
  branches: Partial<Record<BranchName, BranchState>>;
  findings: FindingOut[];
  evidence_refs: EvidenceRef[];
  integrity_warnings?: string[];
  data_classification?: DataClassification;
  // Phase 4 run output. Optional so responses from before Phase 4 still parse.
  summary?: string | null;
  /** e.g. "stub-v1", "ollama:qwen2.5:7b", "stub-fallback(ollama timeout)". */
  investigator?: string | null;
  overall_uncertainty?: string | null;
  /** Set when status is "failed". */
  error?: string | null;
  gate?: GateOut | null;
  proposed_actions?: ProposedActionOut[];
}

// --------------------------------------------------------------- retrieval
export type RetrievalStepName = "graph" | "keyword" | "vector";
export type MatchedBy = RetrievalStepName;

export interface StepStatus {
  status: "completed" | "skipped" | "failed";
  detail?: string | null;
  candidates?: number;
}

export interface ScoreComponent {
  name: string;
  value: number;
}

export interface Extracted {
  service_ids: string[];
  service_names: string[];
  error_terms: string[];
  query_text: string;
}

export type MemoryApplicability = "same_incident" | "shared_service" | "dependency_related" | "text_similarity_only";

export interface ScoredMemory {
  id: string;
  summary: string;
  memory_type: string;
  outcome: MemoryOutcome;
  verification_status: "verified";
  validation_method: string | null;
  about_incident_id: string | null;
  about_incident_key: string | null;
  applicability: MemoryApplicability;
  precedent: Precedent;
  shared_service_ids: string[];
  grounded_in: EvidenceRef[];
  /** Responder ids (plain strings here, unlike MemoryOut.validated_by). */
  validated_by: string[];
  derived_from_action_ids: string[];
  matched_by: MatchedBy[];
  score: number;
  components: ScoreComponent[];
  rationale: string[];
}

export interface ScoredChunk {
  id: string;
  /** Knowledge chunks are context, never a claim. */
  claim_type: "context";
  document_id: string;
  document_title: string;
  document_classification: string;
  ordinal: number;
  source_ref: string;
  text_excerpt: string;
  graph_links: string[];
  matched_by: MatchedBy[];
  score: number;
  components: ScoreComponent[];
  rationale: string[];
}

/** From graph_tools.py: a DeploymentRef plus the service it was deployed to. */
export interface DeploymentHit extends DeploymentRef {
  service_id: string;
}

export interface GraphContext {
  incident: IncidentSummary;
  alerts: AlertOut[];
  evidence: EvidenceOut[];
  explanation_paths: ExplanationPath[];
  /** Keyed by service id. */
  dependencies: Record<string, DependencyOut[]>;
  ownership: Record<string, TeamOut[]>;
  decisions: Record<string, DecisionOut[]>;
  runbooks: Record<string, RunbookRef[]>;
  recent_deployments: DeploymentHit[];
}

export interface MemoryContext {
  items: ScoredMemory[];
  /** Reason -> count of candidates excluded, e.g. {"draft": 1}. */
  excluded: Record<string, number>;
}

export interface KnowledgeContext {
  items: ScoredChunk[];
  excluded: Record<string, number>;
}

export interface RetrievalBundle {
  incident_id: string;
  as_of: IsoDateTime;
  extracted: Extracted;
  graph_context: GraphContext;
  memory_context: MemoryContext;
  knowledge_context: KnowledgeContext;
  steps: Partial<Record<RetrievalStepName, StepStatus>>;
  embedding_model?: string | null;
  data_classification?: DataClassification;
}

// ------------------------------------------------------------------ health
export interface ReadinessBody {
  status: "ready" | "unavailable";
  checks: Record<string, boolean>;
}

// ------------------------------------------------------------------ errors
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: unknown;
  };
}

// ------------------------------------------------------------------ demo controls (Phase 6)
export interface DemoToggle {
  id: string;
  label: string;
  description: string;
  /** The graph relationship the toggle adds or removes, with real ids. */
  edge: string;
  present: boolean;
}

export type ApprovalPolicyState = "policy_in_force" | "no_active_policy_escalate" | "no_rollback_path";

export interface RecommendationEffect {
  incident_id: string;
  rollback_paths: number;
  target_service_ids: string[];
  deployment_ids: string[];
  approval_policy: ApprovalPolicyState;
  summary: string;
}

export interface DemoControls {
  /** False unless the deployment turned demo controls on; then there are no toggles. */
  enabled: boolean;
  toggles: DemoToggle[];
  effect: RecommendationEffect | null;
}
