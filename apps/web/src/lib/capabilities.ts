/**
 * What the backend can actually do today. The UI reads these flags instead of assuming, so a control is
 * enabled only when the matching API exists. Flip a flag only when the endpoint ships.
 */
export const CAPABILITIES = {
  /** POST of an APPROVE / REJECT / REQUEST_REVISION / ESCALATE decision. No review route exists yet (Phase 5). */
  reviewDecisions: false,
  /** Execution or simulation of an approved action. The orchestrator's executor is a no-op placeholder. */
  actionExecution: false,
  /** SSE / WebSocket stream of orchestrator events. Only polling of GET /api/investigations/{id} exists. */
  eventStream: false,
  /** GET list of investigations for an incident. Only a browser-local remembered id exists. */
  listInvestigations: false,
} as const;

export const PREVIEW_ONLY_MESSAGE = "Preview only — approval execution is not available in this phase.";
