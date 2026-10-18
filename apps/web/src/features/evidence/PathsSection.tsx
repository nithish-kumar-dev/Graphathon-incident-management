import type { DecisionRef, ExplanationPath, PathHop, RunbookRef } from "../../api/types";
import { Card, CodeBlock, EmptyState } from "../../components/ui";
import { HypothesisNote, NodeLabel, RelArrow, UtcTime } from "../overview/format";

const SUBHEAD = "kicker mt-4 mb-1.5";

/** One stored edge, exactly as returned: [from_label] from_id —REL→ [to_label] to_id. */
export function HopLine({ hop }: { hop: PathHop }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
      <NodeLabel>{hop.from_label}</NodeLabel>
      <CodeBlock inline value={hop.from_id} />
      <RelArrow rel={hop.rel} />
      <NodeLabel>{hop.to_label}</NodeLabel>
      <CodeBlock inline value={hop.to_id} />
    </span>
  );
}

function DecisionItem({ decision, targetId }: { decision: DecisionRef; targetId: string }) {
  const docs = decision.documented_in ?? [];
  return (
    <li className="rounded-md border border-line bg-surface p-2.5">
      <HopLine hop={{ from_label: "Decision", from_id: decision.id, rel: "GOVERNS", to_label: "Service", to_id: targetId }} />
      <p className="mt-1 text-sm">
        <span className="font-medium">{decision.title}</span>{" "}
        <span className="text-xs text-faint">status {decision.status}</span>
      </p>
      <p className="text-sm text-muted">
        Required approver role:{" "}
        {decision.required_approver_role ? (
          <CodeBlock inline value={decision.required_approver_role} />
        ) : (
          <span className="text-faint">not recorded</span>
        )}
      </p>
      {docs.length > 0 ? (
        <ul aria-label={`Documents for ${decision.id}`} className="mt-1 flex flex-col gap-1">
          {docs.map((doc) => (
            <li key={doc.id} className="text-sm">
              <HopLine
                hop={{ from_label: "Decision", from_id: decision.id, rel: "DOCUMENTED_IN", to_label: "Document", to_id: doc.id }}
              />
              <div className="mt-0.5 pl-1 text-xs text-muted">
                {doc.title ?? "Untitled document"}
                {doc.uri ? (
                  <>
                    {" "}
                    · <CodeBlock inline value={doc.uri} />
                  </>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-faint">No documents recorded.</p>
      )}
    </li>
  );
}

function RunbookItem({ runbook, targetId }: { runbook: RunbookRef; targetId: string }) {
  const actions = runbook.allowed_action_types ?? [];
  return (
    <li className="rounded-md border border-line bg-surface p-2.5">
      <HopLine hop={{ from_label: "Runbook", from_id: runbook.id, rel: "APPLIES_TO", to_label: "Service", to_id: targetId }} />
      <p className="mt-1 text-sm">
        <span className="font-medium">{runbook.title}</span>{" "}
        <span className="text-xs text-faint">version {runbook.version}</span>
        {runbook.uri ? (
          <>
            {" "}
            · <CodeBlock inline value={runbook.uri} />
          </>
        ) : null}
      </p>
      <p className="text-sm text-muted">
        Allowed action types:{" "}
        {actions.length > 0
          ? actions.map((a, i) => (
              <span key={a}>
                {i > 0 ? ", " : null}
                <CodeBlock inline value={a} />
              </span>
            ))
          : <span className="text-faint">none</span>}
      </p>
    </li>
  );
}

function PathItem({ path, index }: { path: ExplanationPath; index: number }) {
  const n = index + 1;
  return (
    <li className="rounded-md border border-dashed border-warn-line bg-warn-tint p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-bold text-ink">
          Path {n} · <span className="font-normal text-muted">{path.kind}</span>
        </h4>
        <HypothesisNote />
      </div>
      <p className="mt-2 text-sm text-ink">{path.summary}</p>
      <p className="mt-1 text-xs text-muted">
        Target service <CodeBlock inline value={path.target_service_id} /> · deployment{" "}
        <CodeBlock inline value={path.deployment.id} /> {path.deployment.version}, deployed{" "}
        <UtcTime iso={path.deployment.deployed_at} /> · approval policy <CodeBlock inline value={path.approval_policy} />
      </p>

      <h5 className={SUBHEAD}>Hops, in stored edge direction</h5>
      {path.hops.length === 0 ? (
        <p className="text-sm text-muted">No hops recorded.</p>
      ) : (
        <ol aria-label={`Hops of path ${n}`} className="flex list-decimal flex-col gap-1.5 pl-6 text-sm">
          {path.hops.map((hop, i) => (
            <li key={`${i}-${hop.from_id}-${hop.rel}-${hop.to_id}`} data-testid="hop">
              <HopLine hop={hop} />
            </li>
          ))}
        </ol>
      )}

      <h5 className={SUBHEAD}>Evidence on this path</h5>
      {path.evidence.length === 0 ? (
        <p className="text-sm text-muted">No evidence recorded.</p>
      ) : (
        <ul aria-label={`Evidence on path ${n}`} className="flex flex-col gap-1 text-sm">
          {path.evidence.map((e) => (
            <li key={e.id}>
              <CodeBlock inline value={e.id} /> <span className="text-xs text-faint">source</span>{" "}
              <CodeBlock inline value={e.source_ref} />
            </li>
          ))}
        </ul>
      )}

      <h5 className={SUBHEAD}>Governing decisions</h5>
      {path.governing_decisions.length === 0 ? (
        <p className="text-sm font-medium text-bad">No active decision governs the target service — escalate.</p>
      ) : (
        <ul aria-label={`Governing decisions of path ${n}`} className="flex flex-col gap-2">
          {path.governing_decisions.map((d) => (
            <DecisionItem key={d.id} decision={d} targetId={path.target_service_id} />
          ))}
        </ul>
      )}

      <h5 className={SUBHEAD}>Runbooks</h5>
      {path.runbooks.length === 0 ? (
        <p className="text-sm text-muted">No runbook applies to the target service.</p>
      ) : (
        <ul aria-label={`Runbooks of path ${n}`} className="flex flex-col gap-2">
          {path.runbooks.map((r) => (
            <RunbookItem key={r.id} runbook={r} targetId={path.target_service_id} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function PathsSection({ paths }: { paths: ExplanationPath[] }) {
  return (
    <Card
      title="Explanation paths"
      subtitle="Real graph edges, shown exactly as stored. Each path is a correlation supporting a hypothesis, not proof."
    >
      {paths.length === 0 ? (
        <EmptyState title="No evidence-backed path found — inconclusive">
          The graph holds no path linking this incident to a deployment.
        </EmptyState>
      ) : (
        <ol aria-label="Explanation paths" className="flex flex-col gap-3">
          {paths.map((p, i) => (
            <PathItem key={`${p.deployment.id}-${p.target_service_id}-${i}`} path={p} index={i} />
          ))}
        </ol>
      )}
    </Card>
  );
}
