import { useId, useState } from "react";
import { MODES, type DemoUser, type Mode } from "../api/types";
import { can, usersWith } from "../auth/permissions";
import { ErrorBanner, InvestigationStatusBadge, Spinner } from "../components/ui";
import type { IncidentInvestigationState } from "../hooks/useIncidentInvestigation";

const MODE_LABELS: Record<Mode, string> = {
  recommendation_only: "Recommendation only",
  simulation: "Simulation",
};

export interface InvestigateControlsProps {
  user: DemoUser;
  state: IncidentInvestigationState;
}

export function InvestigateControls({ user, state }: InvestigateControlsProps) {
  const [mode, setMode] = useState<Mode>("recommendation_only");
  const selectId = useId();
  const helpId = useId();
  const allowed = can(user, "investigation:create");
  const reason = allowed
    ? undefined
    : `${user} cannot start investigations (needs investigation:create). Switch the demo identity to ${usersWith("investigation:create").join(" or ")}.`;
  const inv = state.investigation;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-0.5">
          <label htmlFor={selectId} className="text-xs font-medium text-slate-700">
            Mode
          </label>
          <select
            id={selectId}
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
            disabled={!allowed || state.starting}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:bg-slate-100 disabled:text-slate-500"
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </div>
        {/* Wrapper carries the tooltip: disabled buttons do not get hover events in every browser. */}
        <span title={reason} className="inline-flex">
          <button
            type="button"
            className="btn-primary"
            disabled={!allowed || state.starting}
            aria-describedby={reason ? helpId : undefined}
            onClick={() => void state.start(mode)}
          >
            {state.starting ? "Starting…" : "Investigate"}
          </button>
        </span>
        <div className="flex min-h-8 flex-wrap items-center gap-2 text-sm" aria-live="polite">
          {inv ? (
            <>
              <span className="text-slate-700">Investigation</span>
              <code className="font-mono text-xs text-slate-700">{inv.id}</code>
              <InvestigationStatusBadge status={inv.status} />
              <span className="text-xs text-slate-600">{MODE_LABELS[inv.mode]}</span>
              {state.polling ? <Spinner size="sm" label="Polling investigation status" /> : null}
              {state.lastUpdated ? (
                <span className="text-xs text-slate-500">updated {state.lastUpdated.toLocaleTimeString()}</span>
              ) : null}
              {state.created === false ? (
                <span className="text-xs text-slate-600">(existing active investigation resumed)</span>
              ) : null}
            </>
          ) : state.investigationId && !state.pollError ? (
            <Spinner size="sm" label="Loading investigation" />
          ) : (
            <span className="text-slate-600">No investigation started for this incident.</span>
          )}
        </div>
      </div>

      {reason ? (
        <p id={helpId} className="text-xs text-slate-600">
          {reason}
        </p>
      ) : null}

      {inv?.status === "queued" ? (
        <p className="text-xs text-slate-700">
          Queued. The orchestrator that advances investigations arrives in a later phase, so this may stay queued.
        </p>
      ) : null}

      <ErrorBanner error={state.startError} title="Could not start the investigation" />
      <ErrorBanner
        error={state.pollError}
        title="Could not refresh the investigation"
        actions={
          <button type="button" className="btn-secondary" onClick={state.forget}>
            Forget this investigation
          </button>
        }
      />
    </div>
  );
}
