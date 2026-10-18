import { useEffect, useRef, useState } from "react";
import { useApi, type ApiError } from "../../api/client";
import type { AgentEventOut, AgentEventStatus, InvestigationStatus, InvestigationSummary } from "../../api/types";
import {
  ArrowLink,
  EmptyState,
  ErrorBanner,
  FactRow,
  MetaLine,
  SectionCard,
  Spinner,
  cx,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { clockUtc, formatDuration } from "../../lib/time";
import ActivityTab from "../activity/ActivityTab";
import { UtcTime } from "../activity/ui";
import { ActivityTimeline } from "../investigation/ActivityTimeline";
import { useInvestigationSession } from "../investigation/InvestigationSession";
import type { ActivityEvent } from "../investigation/model";
import { LazyDetails, RelativeTime, StatusPill, type VisualStatus } from "../investigation/ui";

const MODE_LABELS: Record<string, string> = {
  recommendation_only: "Recommendation only",
  simulation: "Simulation",
};

/** Orchestrator step names, so a run event reads as a sentence rather than a key. */
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

const STEP_STATUS_TEXT: Record<AgentEventStatus, string> = {
  started: "started",
  completed: "finished",
  failed: "failed",
  skipped: "was skipped",
  waiting: "is waiting for a person",
};

function stepStatusPill(status: AgentEventStatus): VisualStatus {
  return status === "started" ? "running" : status;
}

/**
 * The runs table scrolls inside a `relative overflow-x-auto` wrapper. `relative` is load-bearing:
 * `.sr-only` is `position: absolute`, and an absolutely positioned descendant of a *non-positioned*
 * scroll container is not clipped by it — it lands at its static position in the page's scroll area.
 * Hidden text in the table's right-hand columns would then widen the document at 390px even though
 * the table itself is clipped, so the table carries no sr-only text; buttons use aria-label instead.
 */
function pillFor(status: InvestigationStatus): "completed" | "failed" | "running" | "waiting" {
  if (status === "completed") return "completed";
  if (status === "failed" || status === "timed_out") return "failed";
  if (status === "queued" || status === "running") return "running";
  return "waiting";
}

/** Two record sets, never conflated: agent execution events and incident response events. */
type RecordSet = "runs" | "events";

const RECORD_LABELS: Record<RecordSet, string> = { runs: "Run timeline", events: "Incident events" };

function SegmentedControl({ value, onChange }: { value: RecordSet; onChange: (v: RecordSet) => void }) {
  return (
    <div
      role="group"
      aria-label="Which record set to emphasise"
      className="inline-flex shrink-0 rounded-full border border-line bg-surface p-1"
    >
      {(Object.keys(RECORD_LABELS) as RecordSet[]).map((id) => {
        const selected = value === id;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(id)}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
              selected ? "bg-brand text-white" : "text-muted hover:text-ink",
            )}
          >
            {selected ? (
              <span aria-hidden="true" className="text-[11px]">
                ✓
              </span>
            ) : null}
            {RECORD_LABELS[id]}
          </button>
        );
      })}
    </div>
  );
}

export default function HistoryTab() {
  const { client, user } = useApi();
  const { incident, run, reloadIncident, runEvents, view } = useInvestigationSession();
  const inv = run.investigation;

  const runs = useAsync((signal) => client.listInvestigations(incident.id, 20, signal), [client, incident.id, user]);
  // Refetch the list when the current run starts or changes state, not on every poll.
  const marker = `${inv?.id ?? ""}|${inv?.status ?? ""}`;
  const previous = useRef(marker);
  const reloadRuns = runs.reload;
  useEffect(() => {
    if (previous.current === marker) return;
    previous.current = marker;
    reloadRuns();
  }, [marker, reloadRuns]);

  const items = runs.data?.items ?? [];
  const [record, setRecord] = useState<RecordSet>("runs");
  const [picked, setPicked] = useState<string | null>(null);

  const currentId = inv?.id ?? null;
  // A pick is dropped once the list no longer contains it (e.g. after switching incident or a refetch).
  const pickedValid = picked && (picked === currentId || items.some((r) => r.id === picked)) ? picked : null;
  const selectedId = pickedValid ?? currentId ?? items[0]?.id ?? null;
  const isCurrent = selectedId !== null && selectedId === currentId;
  const selectedRun: InvestigationSummary | null =
    items.find((r) => r.id === selectedId) ?? (inv && inv.id === selectedId ? inv : null);

  // The session polls the current run's step events; any other run is read once, on selection.
  const otherEvents = useAsync(
    (signal) =>
      selectedId && !isCurrent ? client.getInvestigationEvents(selectedId, signal) : Promise.resolve(null),
    [client, selectedId, isCurrent, user],
  );
  const events: readonly AgentEventOut[] = isCurrent ? runEvents : (otherEvents.data?.events ?? []);
  const eventsLoading = !isCurrent && otherEvents.loading;

  // Agent execution events and incident response events are separate records. Run events carry a "run:" id prefix.
  const incidentEvents = view.events.filter((e) => !e.id.startsWith("run:"));

  const runTimeline = (
    <RunTimelineCard
      selected={selectedRun}
      isCurrent={isCurrent}
      events={events}
      loading={eventsLoading}
      error={otherEvents.error}
      synthetic={incident.data_classification === "synthetic"}
      headline={isCurrent ? view.headline : null}
      reviewNote={isCurrent ? reviewNoteFor(view) : null}
      prominent={record === "runs"}
    />
  );
  const incidentHistory = <IncidentEventsCard events={incidentEvents} prominent={record === "events"} />;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-xl font-bold leading-tight text-ink">History &amp; audit trail</h3>
          <p className="mt-1.5 text-sm text-muted">
            Incident events and agent execution are recorded separately. Select a run to inspect its work.
          </p>
        </div>
        <SegmentedControl value={record} onChange={setRecord} />
      </div>

      <SectionCard
        title="Investigation runs"
        subtitle="Every investigation run recorded for this incident, newest first."
        className="min-w-0"
      >
        {runs.error ? <ErrorBanner error={runs.error} title="Could not load investigation runs" onRetry={runs.reload} /> : null}
        {!runs.data && !runs.error ? <Spinner size="sm" label="Loading investigation runs" /> : null}
        {runs.data && items.length === 0 ? <EmptyState title="No investigation has been run for this incident" /> : null}
        {items.length > 0 ? (
          <div className="relative overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">Investigation runs</caption>
              <thead>
                <tr className="text-left text-muted">
                  <th className="kicker py-1.5 pr-3">Run</th>
                  <th className="kicker py-1.5 pr-3">Status</th>
                  <th className="kicker py-1.5 pr-3">Mode</th>
                  <th className="kicker py-1.5 pr-3">Started</th>
                  <th className="kicker py-1.5 pr-3">Duration</th>
                  <th className="kicker py-1.5 pr-3">Requested by</th>
                  <th className="kicker py-1.5">Inspect</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr
                    key={r.id}
                    className={cx("border-t border-line align-top", r.id === selectedId && "bg-brand-tint")}
                  >
                    <td className="py-2 pr-3 font-mono text-xs text-ink [overflow-wrap:anywhere]">
                      {r.id}
                      {r.id === currentId ? (
                        <span className="ml-1 rounded-full bg-brand-tint px-1.5 font-sans text-[10px] font-semibold text-brand ring-1 ring-inset ring-brand-line">
                          current
                        </span>
                      ) : null}
                      {r.summary ? <p className="mt-0.5 max-w-prose font-sans text-xs text-muted">{r.summary}</p> : null}
                    </td>
                    <td className="py-2 pr-3">
                      <StatusPill status={pillFor(r.status)} />
                      <span className="ml-1 text-xs text-muted">{r.status}</span>
                    </td>
                    <td className="py-2 pr-3 text-ink">{r.mode}</td>
                    <td className="py-2 pr-3 text-ink">
                      <RelativeTime iso={r.started_at} />
                    </td>
                    <td className="py-2 pr-3 text-ink">{formatDuration(r.started_at, r.ended_at) ?? "in progress"}</td>
                    <td className="py-2 pr-3 text-ink">{r.requested_by ?? "unknown"}</td>
                    <td className="py-2 whitespace-nowrap">
                      {r.id === selectedId ? (
                        <span className="text-xs font-bold text-brand">Selected</span>
                      ) : (
                        <button
                          type="button"
                          className="text-xs font-bold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
                          aria-label={`Inspect run ${r.id}`}
                          onClick={() => setPicked(r.id)}
                        >
                          Inspect
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </SectionCard>

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,62fr)_minmax(0,38fr)]">
        {record === "runs" ? (
          <>
            {runTimeline}
            <div className="flex min-w-0 flex-col gap-4">
              <RunSnapshotCard isCurrent={isCurrent} selected={selectedRun} view={view} />
              {incidentHistory}
            </div>
          </>
        ) : (
          <>
            {incidentHistory}
            <div className="flex min-w-0 flex-col gap-4">
              <RunSnapshotCard isCurrent={isCurrent} selected={selectedRun} view={view} />
              {runTimeline}
            </div>
          </>
        )}
      </div>

      <div id="incident-activity-timeline">
        <ActivityTimeline />
      </div>

      <LazyDetails summary="Raw technical records (agent activity, gate output, JSON)" className="card p-5">
        <ActivityTab incident={incident} investigation={inv} user={user} reloadIncident={reloadIncident} />
      </LazyDetails>
    </div>
  );
}

/** Whether a human decision is on record for the current run, for the run-timeline footer strip. */
function reviewNoteFor(view: ReturnType<typeof useInvestigationSession>["view"]): string {
  const proposal = view.findings.primaryAction?.proposal ?? null;
  const reviews = proposal?.reviews ?? [];
  const last = reviews.at(-1);
  if (!last) return "No review decision recorded yet.";
  const who = last.approver_handle ?? last.approver_id;
  return `Review decision ${last.decision.toLowerCase().replace(/_/g, " ")} by ${who}.`;
}

/** Agent execution events of the selected run: what the orchestrator recorded, step by step. */
function RunTimelineCard({
  selected,
  isCurrent,
  events,
  loading,
  error,
  synthetic,
  headline,
  reviewNote,
  prominent,
}: {
  selected: InvestigationSummary | null;
  isCurrent: boolean;
  events: readonly AgentEventOut[];
  loading: boolean;
  error: ApiError | null;
  synthetic: boolean;
  headline: string | null;
  reviewNote: string | null;
  prominent: boolean;
}) {
  const shown = prominent ? events : events.slice(-4);
  return (
    <SectionCard
      className="min-w-0"
      kicker={prominent ? "Selected investigation run" : "Agent execution"}
      title={
        selected ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-base [overflow-wrap:anywhere]">{selected.id}</span>
            <StatusPill status={pillFor(selected.status)} />
          </span>
        ) : (
          "No run selected"
        )
      }
      footer={
        prominent && selected && isCurrent ? (
          <p className="rounded-md bg-brand-tint px-3 py-2 text-[13px] text-brand">
            Current run: {headline ?? selected.status.replace(/_/g, " ")} {reviewNote}
          </p>
        ) : null
      }
    >
      {selected ? (
        <>
          <MetaLine
            className="-mt-2 mb-3"
            items={[
              <>
                Started at <UtcTime value={selected.started_at} />
              </>,
              MODE_LABELS[selected.mode] ?? selected.mode,
              synthetic ? "Synthetic example" : null,
            ].filter(Boolean)}
          />
          <ErrorBanner error={error} title="Could not load this run's execution events" />
          {loading && events.length === 0 ? <Spinner size="sm" label="Loading agent execution events" /> : null}
          {!loading && events.length === 0 ? (
            <EmptyState title="No agent execution events recorded for this run" />
          ) : null}
          {shown.length > 0 ? (
            <>
              {!prominent && events.length > shown.length ? (
                <p className="mb-2 text-xs text-muted">
                  Showing the last {shown.length} of {events.length} execution events.
                </p>
              ) : null}
              <ol className="flex flex-col" aria-label="Agent execution events">
                {shown.map((e) => {
                  const step = STEP_LABELS[e.kind] ?? e.kind.replace(/_/g, " ");
                  return (
                    <li key={e.id} className="flex min-w-0 gap-3 border-l border-line pb-3.5 pl-3.5 last:pb-0">
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                          <span className="text-sm font-bold text-ink">
                            {step} {STEP_STATUS_TEXT[e.status]}
                          </span>
                          <span className="font-mono text-xs text-muted">{clockUtc(e.at)} UTC</span>
                        </span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-2">
                          <StatusPill status={stepStatusPill(e.status)} />
                          <span className="min-w-0 text-sm text-muted [overflow-wrap:anywhere]">
                            {e.detail ?? "No detail recorded."}
                          </span>
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </>
          ) : null}
        </>
      ) : (
        <EmptyState title="No investigation run to inspect">
          Start an investigation, or pick a run from the table above.
        </EmptyState>
      )}
    </SectionCard>
  );
}

/** Where the current run stands: its activity and what each retrieval branch returned. */
function RunSnapshotCard({
  isCurrent,
  selected,
  view,
}: {
  isCurrent: boolean;
  selected: InvestigationSummary | null;
  view: ReturnType<typeof useInvestigationSession>["view"];
}) {
  const stage = view.stages.find((s) => s.id === view.currentStage) ?? null;
  const agents = view.agents.filter((a) => a.id !== "investigator" && a.id !== "safety_gate");

  return (
    <SectionCard className="min-w-0" kicker="Run snapshot" title={isCurrent && stage ? stage.label : "Current run"}>
      {!isCurrent ? (
        <p className="text-sm text-muted">
          {selected
            ? "This snapshot describes the run the workspace is following, not the run selected above."
            : "No run is being followed in this workspace."}
        </p>
      ) : null}
      {isCurrent && stage ? <p className="-mt-2 mb-3 text-sm text-muted">{stage.caption}</p> : null}
      {agents.length > 0 ? (
        <dl className="divide-y divide-line border-y border-line">
          {agents.map((a) => (
            <FactRow key={a.id} term={a.name}>
              {a.resultCount !== null ? (
                `${a.resultCount} ${a.resultLabel}`
              ) : (
                <span className="font-normal text-muted">{a.status.replace(/_/g, " ")}</span>
              )}
            </FactRow>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted">Retrieval branches report here once a run starts.</p>
      )}
    </SectionCard>
  );
}

/** Incident response events: alerts, on-call actions and incident state changes. Not agent execution. */
function IncidentEventsCard({ events, prominent }: { events: readonly ActivityEvent[]; prominent: boolean }) {
  const shown = prominent ? events : events.slice(-4);
  return (
    <SectionCard
      className="min-w-0"
      kicker="Separate record"
      title="Incident event history"
      subtitle="Alerts, on-call actions and incident state changes are not agent execution events."
      footer={<ArrowLink href="#incident-activity-timeline">Open incident timeline</ArrowLink>}
    >
      {events.length === 0 ? (
        <EmptyState title="No incident events recorded yet" />
      ) : (
        <>
          {!prominent && events.length > shown.length ? (
            <p className="mb-2 text-xs text-muted">
              Showing the last {shown.length} of {events.length} incident events.
            </p>
          ) : null}
          <ol className="flex flex-col divide-y divide-line" aria-label="Incident events">
            {shown.map((e) => (
              <li key={e.id} className="flex min-w-0 gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="w-14 shrink-0 font-mono text-xs text-muted">{clockUtc(e.at)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-bold text-ink [overflow-wrap:anywhere]">{e.summary}</span>
                  <span className="block text-xs text-muted">{e.label}</span>
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </SectionCard>
  );
}
