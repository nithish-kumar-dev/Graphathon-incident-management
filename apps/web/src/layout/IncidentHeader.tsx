import { useId, useState } from "react";
import { MODES, type DemoUser, type IncidentDetail, type Mode } from "../api/types";
import { can, usersWith } from "../auth/permissions";
import { ArrowLink, Badge, ErrorBanner, MetaLine, SeverityBadge, Spinner, StatusBadge, cx, type BadgeTone } from "../components/ui";
import { useInvestigationSession } from "../features/investigation/InvestigationSession";
import { isActivePhase, primaryActionFor, type Situation } from "../features/investigation/model";
import { RelativeTime, StatusPill } from "../features/investigation/ui";
import { shortId } from "../lib/time";

const MODE_LABELS: Record<Mode, string> = {
  recommendation_only: "Recommendation only",
  simulation: "Simulation",
};

/** The one difference that matters to a user: whether the run can be approved and acted on at all. */
const MODE_HINTS: Record<Mode, string> = {
  recommendation_only: "Ends at a written recommendation. Nothing can be approved or run from it.",
  simulation: "Pauses for your approval, then runs the approved action as a simulation. No real system changes.",
};

const SITUATION_TONE: Record<Situation["key"], BadgeTone> = {
  no_investigation: "neutral",
  resolved: "success",
  queued: "info",
  running: "info",
  awaiting_approval: "warning",
  completed: "success",
  failed: "danger",
  escalated: "warning",
  inconclusive: "neutral",
};

function primaryService(incident: IncidentDetail): string {
  const s = incident.affected_services[0];
  if (s) return s.name ?? shortId(s.id);
  const id = incident.affected_service_ids[0];
  return id ? shortId(id) : "none recorded";
}

export interface IncidentHeaderProps {
  user: DemoUser;
  /** Called by "View Investigation": jump to and focus the agent monitor. */
  onViewInvestigation: () => void;
}

export function IncidentHeader({ user, onViewInvestigation }: IncidentHeaderProps) {
  const { incident, incidentRefreshing, run, view } = useInvestigationSession();
  const [mode, setMode] = useState<Mode>("recommendation_only");
  const selectId = useId();
  const helpId = useId();
  const allowed = can(user, "investigation:create");
  const reason = allowed
    ? undefined
    : `${user} cannot start investigations (needs investigation:create). Switch the demo identity to ${usersWith("investigation:create").join(" or ")}.`;
  const inv = run.investigation;
  const action = primaryActionFor(view.phase);
  const others = incident.affected_services.length > 1 ? incident.affected_services.length - 1 : 0;
  const needsPermission = action.kind !== "view";

  const onPrimary = () => {
    if (action.kind === "view") onViewInvestigation();
    else void run.start(action.kind === "resume" && inv ? inv.mode : mode);
  };

  return (
    <header className="flex flex-col gap-4" aria-label="Incident summary">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[11px]">
        <span className="font-extrabold tracking-[0.1em] text-muted">INCIDENTS</span>
        <span aria-hidden="true" className="text-faint">/</span>
        <span className="font-bold text-ink">{incident.key}</span>
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-2xl font-bold leading-tight text-ink">{incident.title}</h2>
            <SeverityBadge severity={incident.severity} />
            <StatusBadge status={incident.status} />
            <Badge tone={SITUATION_TONE[view.situation.key]} variant="outline" title={view.situation.description}>
              {view.situation.label}
            </Badge>
            {incidentRefreshing ? <Spinner size="sm" label="Refreshing incident" /> : null}
          </div>
          <MetaLine
            className="mt-2.5"
            items={[
              <>
                {primaryService(incident)}
                {others > 0 ? <span className="text-faint"> +{others} more</span> : null}
              </>,
              `${incident.alert_count} alert${incident.alert_count === 1 ? "" : "s"}`,
              <>
                Detected <RelativeTime iso={incident.started_at} />
              </>,
            ]}
          />
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label htmlFor={selectId} className="kicker">
              Mode
            </label>
            <select
              id={selectId}
              value={action.kind === "resume" && inv ? inv.mode : mode}
              onChange={(e) => setMode(e.target.value as Mode)}
              disabled={!allowed || run.starting || action.kind === "resume"}
              className="rounded-md border border-line bg-surface px-2.5 py-2 text-sm font-medium text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:bg-surface-muted disabled:text-faint"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m]}
                </option>
              ))}
            </select>
            <p className="max-w-56 text-xs leading-snug text-muted">{MODE_HINTS[action.kind === "resume" && inv ? inv.mode : mode]}</p>
          </div>
          {/* The wrapper carries the tooltip: disabled buttons do not get hover events in every browser. */}
          <span title={needsPermission ? reason : undefined} className="inline-flex">
            <button
              type="button"
              className="btn-primary gap-2"
              disabled={(needsPermission && !allowed) || run.starting}
              aria-busy={run.starting || undefined}
              aria-describedby={needsPermission && reason ? helpId : undefined}
              onClick={onPrimary}
            >
              {run.starting ? <Spinner size="sm" /> : null}
              {run.starting ? "Starting…" : action.label}
            </button>
          </span>
          {action.kind === "view" ? (
            <span title={reason} className="inline-flex">
              <button type="button" className="btn-secondary" disabled={!allowed || run.starting} onClick={() => void run.start(mode)}>
                Re-investigate
              </button>
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line pt-3.5">
        <p className="kicker">Current run</p>
        {inv ? (
          <>
            <span className="text-[13px] font-bold text-ink">{shortId(inv.id)}</span>
            <Badge tone="neutral" variant="outline">
              {MODE_LABELS[inv.mode]}
            </Badge>
            <span className="text-xs text-muted">{view.situation.label}</span>
            {run.polling ? <Spinner size="sm" label="Polling investigation status" /> : null}
            {run.lastUpdated ? (
              <span className="text-xs text-faint">updated {run.lastUpdated.toLocaleTimeString()}</span>
            ) : null}
            {run.created === false ? (
              <span className="text-xs text-muted">existing active investigation resumed</span>
            ) : null}
          </>
        ) : run.investigationId && !run.pollError ? (
          <Spinner size="sm" label="Loading investigation" />
        ) : (
          <span className="text-[13px] font-semibold text-muted">None started</span>
        )}
      </div>

      {reason && needsPermission ? (
        <p id={helpId} className="text-xs text-muted">
          {reason}
        </p>
      ) : null}
      <ErrorBanner error={run.startError} title="Could not start the investigation" />
      <ErrorBanner
        error={run.pollError}
        title="Could not refresh the investigation"
        actions={
          <button type="button" className="btn-secondary" onClick={run.forget}>
            Forget this investigation
          </button>
        }
      />
    </header>
  );
}

/**
 * The headline strip under the incident header: what the run is doing right now.
 * `compact` is used on tabs other than the investigation one, where the detail lives in the tab itself.
 */
export function RunBanner({ compact = false, onViewWorkstream }: { compact?: boolean; onViewWorkstream?: () => void }) {
  const { run, view } = useInvestigationSession();
  const inv = run.investigation;
  const stage = view.stages.find((s) => s.id === view.currentStage);
  const active = inv ? isActivePhase(view.phase) : false;
  const awaiting = view.situation.key === "awaiting_approval";
  const accent = awaiting ? "bg-warn" : active ? "bg-brand" : "bg-line-strong";
  const kicker = awaiting ? "Review stage" : active ? "Now running" : "Run status";
  const kickerTone = awaiting ? "text-warn" : active ? "text-brand" : "text-muted";

  if (compact) {
    return (
      <div className="card flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3" role="status" aria-live="polite">
        <p className="min-w-0 flex-1 text-sm font-semibold text-ink">{view.headline}</p>
        {onViewWorkstream ? <ArrowLink onClick={onViewWorkstream}>View workstream</ArrowLink> : null}
      </div>
    );
  }

  return (
    <div className="card relative overflow-hidden p-5 pl-6" role="status" aria-live="polite">
      <span aria-hidden="true" className={cx("absolute inset-y-0 left-0 w-[5px]", accent)} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={cx("kicker", kickerTone)}>{kicker}</p>
          <p className="mt-2 text-lg font-bold leading-snug text-ink">{view.headline}</p>
        </div>
        {inv && stage ? <StatusPill status={stage.status} /> : null}
      </div>
    </div>
  );
}
