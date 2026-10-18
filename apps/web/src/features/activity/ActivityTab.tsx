import { useApi } from "../../api/client";
import {
  BRANCH_NAMES,
  type BranchName,
  type BranchState,
  type InvestigationOut,
  type RetrievalBundle,
  type RetrievalStepName,
  type StepStatus,
  type TimelineEventOut,
} from "../../api/types";
import {
  Badge,
  BranchStatusBadge,
  Card,
  EmptyState,
  ErrorBanner,
  GateDecisionBadge,
  GateViolationList,
  InvestigationStatusBadge,
  InvestigatorBadge,
  Spinner,
  cx,
  type BadgeTone,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import type { TabProps } from "../types";
import { Code, CodeList, Field, Fields, UtcTime } from "./ui";

const MODE_LABELS: Record<string, string> = {
  recommendation_only: "Recommendation only",
  simulation: "Simulation",
};

export default function ActivityTab({ incident, investigation, user }: TabProps) {
  const { client } = useApi();
  const retrieval = useAsync((signal) => client.getRetrieval(incident.id, signal), [client, incident.id, user]);
  const timeline = useAsync((signal) => client.getTimeline(incident.id, signal), [client, incident.id, user]);

  return (
    <div className="flex flex-col gap-4">
      <InvestigationCard investigation={investigation} />
      <BranchesCard investigation={investigation} />
      <Card
        title="Retrieval steps"
        subtitle="How the investigator's context was gathered: graph (required), then keyword and optional vector search."
      >
        <ErrorBanner error={retrieval.error} title="Could not load retrieval steps" onRetry={retrieval.reload} />
        {retrieval.loading && !retrieval.data ? <Spinner label="Loading retrieval steps…" /> : null}
        {retrieval.data ? <RetrievalSteps bundle={retrieval.data} /> : null}
      </Card>
      <Card title="Handoff timeline" subtitle="Auditable events for this incident, oldest first. Times are UTC.">
        <ErrorBanner error={timeline.error} title="Could not load timeline" onRetry={timeline.reload} />
        {timeline.loading && !timeline.data ? <Spinner label="Loading timeline…" /> : null}
        {timeline.data ? <Timeline events={timeline.data.events} /> : null}
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ investigation

function InvestigationCard({ investigation }: { investigation: InvestigationOut | null }) {
  if (!investigation) {
    return (
      <Card title="Investigation">
        <EmptyState title="No investigation started">
          Start one with <span className="font-medium">Investigate</span> above (needs investigation:create).
        </EmptyState>
      </Card>
    );
  }
  const inv = investigation;
  const warnings = inv.integrity_warnings ?? [];
  return (
    <Card title="Investigation" actions={<InvestigationStatusBadge status={inv.status} />}>
      <Fields>
        <Field label="Id">
          <Code>{inv.id}</Code>
        </Field>
        <Field label="Status">{inv.status.replace(/_/g, " ")}</Field>
        <Field label="Mode">{MODE_LABELS[inv.mode] ?? inv.mode}</Field>
        <Field label="Thread">
          <Code>{inv.thread_id}</Code>
        </Field>
        <Field label="Requested by">{inv.requested_by ?? <span className="text-faint">not recorded</span>}</Field>
        <Field label="Started">
          <UtcTime value={inv.started_at} />
        </Field>
        <Field label="Ended">
          {inv.ended_at ? <UtcTime value={inv.ended_at} /> : <span className="text-faint">not ended</span>}
        </Field>
        <Field label="Investigator">
          {inv.investigator ? <InvestigatorBadge investigator={inv.investigator} /> : <span className="text-faint">not recorded</span>}
        </Field>
        <Field label="Gate decision">
          {inv.gate ? (
            <div className="flex flex-col gap-1.5">
              <span>
                <GateDecisionBadge decision={inv.gate.decision} />
              </span>
              {inv.gate.violations.length > 0 ? (
                <GateViolationList violations={inv.gate.violations} label="Gate violations (activity)" />
              ) : null}
            </div>
          ) : (
            <span className="text-faint">not recorded</span>
          )}
        </Field>
        <Field label="Revisions">{inv.revision_count ?? 0}</Field>
        {inv.error ? (
          <Field label="Error">
            <span className="font-semibold text-bad">{inv.error}</span>
          </Field>
        ) : null}
        <Field label="Integrity warnings">
          {warnings.length === 0 ? (
            <span className="text-faint">none</span>
          ) : (
            <ul className="list-disc space-y-0.5 pl-5 text-warn">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </Field>
      </Fields>
    </Card>
  );
}

// ------------------------------------------------------------------ branches

const BRANCH_LABELS: Record<BranchName, { title: string; help: string }> = {
  graph_context: { title: "Graph context", help: "Dependencies, deployments, ownership and policy from the graph." },
  memory_context: { title: "Memory context", help: "Verified memories and knowledge chunks." },
  telemetry_context: { title: "Telemetry context", help: "Metrics and logs around the incident window." },
};

function BranchesCard({ investigation }: { investigation: InvestigationOut | null }) {
  return (
    <Card title="Coordinator branches" subtitle="The coordinator fans out to three context branches.">
      {!investigation ? (
        <p className="text-sm text-muted">Branch states appear once an investigation is started.</p>
      ) : (
        <>
          {investigation.status === "queued" ? (
            <p className="mb-3 rounded-md border border-line-strong bg-surface-muted p-2 text-sm text-muted">
              Queued: the orchestrator (Phase 4) has not picked this investigation up yet, so every branch is still
              pending.
            </p>
          ) : null}
          <ul className="grid grid-cols-1 gap-2 md:grid-cols-3" aria-label="Branch states">
            {BRANCH_NAMES.map((name) => (
              <BranchItem key={name} name={name} state={investigation.branches?.[name]} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function BranchItem({ name, state }: { name: BranchName; state: BranchState | undefined }) {
  const status = state?.status ?? "not_recorded";
  const failed = status === "failed";
  const skipped = status === "skipped";
  const label = BRANCH_LABELS[name];
  return (
    <li
      className={cx(
        "min-w-0 rounded-md border p-3 text-sm",
        failed && "border-bad-line border-l-4 bg-bad-tint",
        skipped && "border-dashed border-line-strong bg-surface-muted",
        !failed && !skipped && "border-line bg-surface",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">{label.title}</span>
        <BranchStatusBadge status={status} />
      </div>
      <p className="mt-0.5">
        <Code>{name}</Code>
      </p>
      <p className="mt-1 text-xs text-muted">{label.help}</p>
      {failed ? <p className="mt-2 font-semibold text-bad">✕ Branch failed</p> : null}
      {skipped ? <p className="mt-2 font-semibold text-muted">⤼ Branch skipped</p> : null}
      {!state ? <p className="mt-2 text-xs text-muted">Not present in the investigation response.</p> : null}
      {state?.detail ? (
        <p className={cx("mt-1 break-words", failed ? "text-bad" : "text-ink")}>
          <span className="font-medium">Detail: </span>
          {state.detail}
        </p>
      ) : null}
    </li>
  );
}

// ------------------------------------------------------------------ retrieval

const STEP_ORDER: RetrievalStepName[] = ["graph", "keyword", "vector"];

const STEP_TONE: Record<StepStatus["status"], { tone: BadgeTone; variant: "soft" | "solid" | "outline" }> = {
  completed: { tone: "success", variant: "soft" },
  failed: { tone: "danger", variant: "solid" },
  skipped: { tone: "neutral", variant: "outline" },
};

function stepFallback(name: RetrievalStepName, step: StepStatus): string | null {
  if (step.status === "completed") return null;
  if (name === "vector") return "Fallback: graph + keyword only (no vector similarity in scores).";
  if (name === "keyword") return "Fallback: keyword search unavailable; graph context is still returned.";
  return "Graph context is required; results without it are incomplete.";
}

// The scroll wrapper is `relative` so the sr-only caption (position: absolute) is clipped by the
// scroller instead of landing in the page's scroll area at its static position.
function RetrievalSteps({ bundle }: { bundle: RetrievalBundle }) {
  const present = STEP_ORDER.filter((n) => bundle.steps?.[n]);
  const extracted = bundle.extracted;
  return (
    <div className="flex flex-col gap-4">
      {present.length === 0 ? (
        <EmptyState title="No retrieval steps reported" />
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="sr-only">Retrieval steps</caption>
            <thead className="border-b border-line text-xs uppercase text-muted">
              <tr>
                <th scope="col" className="py-2 pr-3">
                  Step
                </th>
                <th scope="col" className="py-2 pr-3">
                  Status
                </th>
                <th scope="col" className="py-2 pr-3">
                  Candidates
                </th>
                <th scope="col" className="py-2">
                  Detail
                </th>
              </tr>
            </thead>
            <tbody>
              {STEP_ORDER.map((name) => {
                const step = bundle.steps?.[name];
                const tone = step ? STEP_TONE[step.status] ?? STEP_TONE.skipped : null;
                const fallback = step ? stepFallback(name, step) : null;
                return (
                  <tr
                    key={name}
                    className={cx(
                      "border-b border-line align-top",
                      step?.status === "failed" && "bg-bad-tint",
                    )}
                  >
                    <th scope="row" className="py-2 pr-3 font-medium text-ink">
                      {name}
                    </th>
                    <td className="py-2 pr-3">
                      {step && tone ? (
                        <Badge tone={tone.tone} variant={tone.variant}>
                          {step.status}
                        </Badge>
                      ) : (
                        <Badge variant="dashed">not reported</Badge>
                      )}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{step?.candidates ?? "—"}</td>
                    <td className="py-2 break-words">
                      {step?.detail ? <span>{step.detail}</span> : <span className="text-faint">—</span>}
                      {fallback ? <p className="mt-1 text-xs font-medium text-warn">{fallback}</p> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Fields>
        <Field label="Extracted services">
          <CodeList items={extracted?.service_ids} />
        </Field>
        <Field label="Error terms">
          {extracted?.error_terms?.length ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Extracted error terms">
              {extracted.error_terms.map((t) => (
                <li key={t}>
                  <Badge tone="info">{t}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-faint">none</span>
          )}
        </Field>
        <Field label="Embedding model">
          {bundle.embedding_model ? <Code>{bundle.embedding_model}</Code> : <span className="text-faint">none</span>}
        </Field>
        <Field label="As of">
          <UtcTime value={bundle.as_of} />
        </Field>
      </Fields>
    </div>
  );
}

// ------------------------------------------------------------------ timeline

const HIGHLIGHT: Record<string, BadgeTone> = {
  alert_fired: "danger",
  incident_opened: "warning",
  status_change: "info",
  investigation_requested: "accent",
  approval: "success",
};

function highlightTone(type: string): BadgeTone | null {
  if (HIGHLIGHT[type]) return HIGHLIGHT[type];
  if (type.startsWith("approval")) return "success";
  return null;
}

const BORDER: Record<BadgeTone, string> = {
  neutral: "border-l-line-strong",
  info: "border-l-brand",
  success: "border-l-good",
  warning: "border-l-warn",
  danger: "border-l-bad",
  accent: "border-l-brand-deep",
};

function Timeline({ events }: { events: TimelineEventOut[] }) {
  if (events.length === 0) return <EmptyState title="No timeline events yet" />;
  // Server orders by time; sort again (stable) so the list is always chronological.
  const ordered = events
    .map((e, i) => ({ e, i }))
    .sort((a, b) => Date.parse(a.e.at) - Date.parse(b.e.at) || a.i - b.i)
    .map(({ e }) => e);
  return (
    <ol className="flex flex-col gap-2" aria-label="Timeline events">
      {ordered.map((ev) => {
        const tone = highlightTone(ev.type);
        return (
          <li
            key={ev.id}
            className={cx(
              "min-w-0 rounded-md border border-line border-l-4 p-2 text-sm",
              tone ? cx(BORDER[tone], "bg-surface") : "border-l-line bg-surface-muted",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted">
                <UtcTime value={ev.at} />
              </span>
              <Badge tone={tone ?? "neutral"} variant={tone ? "soft" : "outline"}>
                {ev.type}
              </Badge>
              <span className="text-muted">
                by <span className="font-medium">{ev.actor ?? "unknown actor"}</span>
              </span>
            </div>
            <p className="mt-1 break-words text-ink">{ev.summary ?? <span className="text-faint">no summary</span>}</p>
            {ev.ref_id ? (
              <p className="mt-1 text-xs text-muted">
                ref: <Code>{ev.ref_id}</Code>
              </p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
