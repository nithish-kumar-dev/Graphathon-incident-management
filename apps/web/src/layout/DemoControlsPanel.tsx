import { useState } from "react";
import { toApiError, useApi, type ApiError } from "../api/client";
import type { ApprovalPolicyState, DemoControls, DemoToggle } from "../api/types";
import { can } from "../auth/permissions";
import { Badge, Card, CodeBlock, ErrorBanner, type BadgeTone } from "../components/ui";
import { useAsync } from "../hooks/useAsync";

export interface DemoControlsPanelProps {
  incidentId: string | null;
  /** Bumped by the parent after every change; refetches this panel. */
  refreshKey: number;
  /** Called after a successful change so the incident workspace can refetch everything. */
  onChanged: () => void;
}

const POLICY: Record<ApprovalPolicyState, { tone: BadgeTone; label: string }> = {
  policy_in_force: { tone: "success", label: "policy in force" },
  no_active_policy_escalate: { tone: "warning", label: "no active policy: escalate" },
  no_rollback_path: { tone: "neutral", label: "no rollback path" },
};

/**
 * Demo-only. Shown only when the server reports `enabled: true`; any error (including 404 from a build without the
 * endpoint) hides it, so it never appears in a normal deployment.
 */
export function DemoControlsPanel({ incidentId, refreshKey, onChanged }: DemoControlsPanelProps) {
  const { client, user } = useApi();
  const state = useAsync(
    (signal) => client.getDemoControls(incidentId ?? undefined, signal),
    [client, incidentId, user, refreshKey],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const controls: DemoControls | null = state.data;
  if (!controls?.enabled) return null;

  const allowed = can(user, "demo:control");
  const run = async (action: () => Promise<DemoControls>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };
  const allPresent = controls.toggles.every((t) => t.present);

  return (
    <Card
      title="Demo controls"
      subtitle="Synthetic data only. Flip a graph edge and watch the recommendation change; no database edits needed."
      headingLevel={2}
      className="border-violet-300 bg-violet-50/40"
      actions={
        <button
          type="button"
          className="btn-secondary"
          disabled={!allowed || busy || allPresent}
          onClick={() => run(() => client.resetDemoControls(incidentId ?? undefined))}
        >
          Restore both
        </button>
      }
    >
      {!allowed ? (
        <p className="mb-2 text-sm text-slate-700">{user} cannot change demo controls. Switch to demo-responder or payments-lead.</p>
      ) : null}
      <ErrorBanner error={error} title="Could not change the demo graph" className="mb-2" />
      <ul aria-label="Demo toggles" className="flex flex-col gap-3">
        {controls.toggles.map((t) => (
          <ToggleRow
            key={t.id}
            toggle={t}
            disabled={!allowed || busy}
            onToggle={() => run(() => client.setDemoToggle(t.id, !t.present, incidentId ?? undefined))}
          />
        ))}
      </ul>
      {controls.effect ? (
        <div aria-live="polite" className="mt-3 rounded-md border border-slate-200 bg-white p-3 text-sm">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="font-semibold">Recommendation now</span>
            <Badge tone={POLICY[controls.effect.approval_policy].tone} variant="soft">
              {POLICY[controls.effect.approval_policy].label}
            </Badge>
            <Badge tone="neutral" variant="outline">
              rollback paths: {controls.effect.rollback_paths}
            </Badge>
          </div>
          <p className="break-words text-slate-800">{controls.effect.summary}</p>
        </div>
      ) : null}
    </Card>
  );
}

function ToggleRow({ toggle, disabled, onToggle }: { toggle: DemoToggle; disabled: boolean; onToggle: () => void }) {
  return (
    <li className="flex min-w-0 flex-wrap items-start justify-between gap-2">
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
          {toggle.label}
          <Badge tone={toggle.present ? "success" : "danger"} variant="soft">
            {toggle.present ? "link present" : "link removed"}
          </Badge>
        </p>
        <CodeBlock inline value={toggle.edge} />
        <p className="mt-0.5 text-xs text-slate-600">{toggle.description}</p>
      </div>
      <button
        type="button"
        className="btn-secondary shrink-0"
        disabled={disabled}
        aria-label={`${toggle.present ? "Remove" : "Restore"} link: ${toggle.label}`}
        onClick={onToggle}
      >
        {toggle.present ? "Remove link" : "Restore link"}
      </button>
    </li>
  );
}
