/**
 * What the backend can actually do today. The UI reads these flags instead of assuming, so a control is
 * enabled only when the matching API exists.
 */
export const CAPABILITIES = {
  /** POST /api/actions/{id}/review (APPROVE / REJECT / REQUEST_REVISION / ESCALATE). */
  reviewDecisions: true,
  /** Approving a simulation-mode action runs it in SIMULATION only. Nothing real is ever changed. */
  actionExecution: true,
  /** Orchestrator step events, read by polling GET /api/investigations/{id}/events (there is no SSE/WebSocket). */
  eventStream: true,
  /** GET /api/incidents/{id}/investigations. */
  listInvestigations: true,
} as const;
