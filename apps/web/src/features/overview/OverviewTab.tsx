import type { ReactNode } from "react";
import type {
  AlertOut,
  DecisionRef,
  EvidenceRef,
  ExplanationPath,
  FindingOut,
  IncidentDetail,
  InvestigationOut,
  InvestigationStatus,
  ProposedActionOut,
  RunbookRef,
} from "../../api/types";
import { rolesFor } from "../../auth/permissions";
import {
  Badge,
  Card,
  ClaimTypeBadge,
  CodeBlock,
  EmptyState,
  GateDecisionBadge,
  GateViolationList,
  InvestigatorBadge,
  ProposalStatusBadge,
  SeverityBadge,
  StatusBadge,
  cx,
  type BadgeTone,
} from "../../components/ui";
import { formatConfidence, pathForProposal, shortHash } from "../proposals";
import type { TabProps } from "../types";
import { HypothesisNote, TD, TD_ID, TD_REF, TH, TableScroll, UtcTime } from "./format";

export default function OverviewTab({ incident, investigation, user }: TabProps) {
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <IncidentFacts incident={incident} />
      <InvestigationPanel investigation={investigation} />
      <SuspectedCause incident={incident} investigation={investigation} />
      <ProposedActions
        paths={incident.explanation_paths}
        proposals={investigation?.proposed_actions ?? []}
        userRoles={rolesFor(user)}
        user={user}
      />
    </div>
  );
}

// ------------------------------------------------------------------ facts
function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{term}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{children}</dd>
    </div>
  );
}

function IncidentFacts({ incident }: { incident: IncidentDetail }) {
  return (
    <Card title="Incident facts" subtitle={<>As of <UtcTime iso={incident.as_of} /></>}>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Fact term="Status">
          <StatusBadge status={incident.status} />
        </Fact>
        <Fact term="Severity">
          <SeverityBadge severity={incident.severity} />
        </Fact>
        <Fact term="Alerts">{incident.alert_count}</Fact>
        <Fact term="Started">
          <UtcTime iso={incident.started_at} />
        </Fact>
        <Fact term="Resolved">
          {incident.resolved_at ? <UtcTime iso={incident.resolved_at} /> : <span className="text-slate-600">Not resolved</span>}
        </Fact>
        <Fact term="Affected services">
          {incident.affected_services.length > 0 ? (
            <ul className="flex flex-col gap-0.5">
              {incident.affected_services.map((s) => (
                <li key={s.id}>
                  <span className="font-medium">{s.name ?? s.id}</span> <CodeBlock inline value={s.id} />
                  {s.tier ? <span className="text-xs text-slate-500"> ({s.tier})</span> : null}
                </li>
              ))}
            </ul>
          ) : incident.affected_service_ids.length > 0 ? (
            <ul>
              {incident.affected_service_ids.map((id) => (
                <li key={id}>
                  <CodeBlock inline value={id} />
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-slate-600">None recorded</span>
          )}
        </Fact>
      </dl>

      <h4 className="mt-4 mb-2 text-sm font-semibold text-slate-900">
        Alerts ({incident.alerts.length}
        {incident.alerts.length !== incident.alert_count ? ` shown of ${incident.alert_count}` : ""})
      </h4>
      {incident.alerts.length === 0 ? (
        <EmptyState title="No alerts attached to this incident" />
      ) : (
        <AlertTable alerts={incident.alerts} />
      )}
    </Card>
  );
}

function AlertTable({ alerts }: { alerts: AlertOut[] }) {
  return (
    <TableScroll label="Alerts table">
      <table className="min-w-full border-collapse">
        <caption className="sr-only">Alerts attached to this incident</caption>
        <thead>
          <tr>
            <th scope="col" className={TH}>Fingerprint</th>
            <th scope="col" className={TH}>Severity</th>
            <th scope="col" className={TH}>Fired at</th>
            <th scope="col" className={TH}>Dedup count</th>
            <th scope="col" className={TH}>Summary</th>
            <th scope="col" className={TH}>Source ref</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id}>
              <td className={TD_ID}>
                <CodeBlock inline value={a.fingerprint} />
              </td>
              <td className={TD}>
                <Badge tone={a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : "info"}>
                  {a.severity}
                </Badge>
              </td>
              <td className={TD}>
                <UtcTime iso={a.fired_at} />
                {a.last_fired_at ? (
                  <div className="text-xs text-slate-500">
                    last <UtcTime iso={a.last_fired_at} />
                  </div>
                ) : null}
              </td>
              <td className={TD}>{a.dedup_count ?? 0}</td>
              <td className={cx(TD, "min-w-48")}>{a.summary ?? <span className="text-slate-500">—</span>}</td>
              <td className={TD_REF}>
                {a.source_ref ? <CodeBlock inline value={a.source_ref} /> : <span className="text-slate-500">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

// ---------------------------------------------------------- investigation
const STATUS_MESSAGE: Record<InvestigationStatus, { title: string; body: string; tone: string; badge: BadgeTone }> = {
  queued: {
    title: "Queued — waiting for the orchestrator",
    body: "The investigation is recorded and waiting for the orchestrator to pick it up. The agent run arrives in a later phase, so it can stay queued; the graph evidence below is available now.",
    tone: "border-slate-300 bg-slate-50",
    badge: "neutral",
  },
  running: {
    title: "Running — the agent is gathering context",
    body: "Graph, memory and telemetry branches are in progress. Findings appear here when the run finishes.",
    tone: "border-sky-300 bg-sky-50",
    badge: "info",
  },
  awaiting_review: {
    title: "Pending human approval",
    body: "The agent has proposed an action that needs a human reviewer before anything else happens. Nothing has been executed. See the Human review tab.",
    tone: "border-violet-300 bg-violet-50",
    badge: "accent",
  },
  completed: {
    title: "Completed — the run finished",
    body: "The run finished. Each finding below carries its own claim type; only findings marked Confirmed are confirmed, the rest remain hypotheses.",
    tone: "border-emerald-300 bg-emerald-50",
    badge: "success",
  },
  failed: {
    title: "Failed — the run did not finish",
    body: "The investigation stopped with an error. Its partial output is not a conclusion. Work from the graph evidence or start a new investigation.",
    tone: "border-red-300 bg-red-50",
    badge: "danger",
  },
  escalated: {
    title: "Escalated to a human",
    body: "The agent handed this incident to a human: an unsafe or invalid action was proposed and revisions ran out, or no safe, policy-backed recommendation applied. Nothing was proposed for execution.",
    tone: "border-amber-300 bg-amber-50",
    badge: "warning",
  },
  inconclusive: {
    title: "Inconclusive — no evidence-backed explanation",
    body: "The investigation found no evidence-backed explanation. Nothing below should be read as a cause.",
    tone: "border-slate-300 bg-slate-50",
    badge: "neutral",
  },
  timed_out: {
    title: "Timed out — stopped before finishing",
    body: "The investigation exceeded its time budget before finishing. Its partial output is not a conclusion.",
    tone: "border-red-300 bg-red-50",
    badge: "danger",
  },
};

function InvestigationPanel({ investigation }: { investigation: InvestigationOut | null }) {
  if (!investigation) {
    return (
      <Card title="Investigation">
        <EmptyState title="No investigation yet — use Investigate above">
          The suspected cause below comes straight from stored graph paths, without an agent run.
        </EmptyState>
      </Card>
    );
  }
  const msg = STATUS_MESSAGE[investigation.status] ?? {
    title: investigation.status,
    body: "Unknown investigation status.",
    tone: "border-slate-300 bg-slate-50",
    badge: "neutral" as const,
  };
  const warnings = investigation.integrity_warnings ?? [];
  return (
    <Card
      title="Investigation"
      actions={
        // Not InvestigationStatusBadge: the workspace header already shows that one, so this badge uses the raw status.
        <Badge tone={msg.badge} variant="outline" title={`Investigation state: ${investigation.status}`}>
          state: {investigation.status}
        </Badge>
      }
    >
      <div className={cx("rounded-md border p-3", msg.tone)} data-testid="investigation-state">
        <p className="font-semibold text-slate-900">{msg.title}</p>
        <p className="mt-1 text-sm text-slate-700">{msg.body}</p>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Fact term="Investigation">
          <CodeBlock inline value={investigation.id} />
        </Fact>
        <Fact term="Mode">
          <CodeBlock inline value={investigation.mode} />
        </Fact>
        <Fact term="Started">
          <UtcTime iso={investigation.started_at} />
        </Fact>
        <Fact term="Ended">
          {investigation.ended_at ? <UtcTime iso={investigation.ended_at} /> : <span className="text-slate-600">Not ended</span>}
        </Fact>
        {investigation.requested_by ? (
          <Fact term="Requested by">
            <CodeBlock inline value={investigation.requested_by} />
          </Fact>
        ) : null}
        {investigation.investigator ? (
          <Fact term="Investigator">
            <InvestigatorBadge investigator={investigation.investigator} />
          </Fact>
        ) : null}
        {investigation.gate ? (
          <Fact term="Gate decision">
            <GateDecisionBadge decision={investigation.gate.decision} />
          </Fact>
        ) : null}
      </dl>
      {investigation.error ? (
        <div role="alert" className="mt-3 rounded-md border-2 border-red-400 bg-red-50 p-3 text-sm text-red-900">
          <p className="font-semibold">Run error</p>
          <p className="mt-0.5 break-words">{investigation.error}</p>
        </div>
      ) : null}
      {investigation.summary ? (
        <section aria-label="Investigation summary" className="mt-3 rounded-md border border-slate-200 bg-white p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</h4>
          <p className="mt-1 text-sm text-slate-900">{investigation.summary}</p>
          {investigation.overall_uncertainty ? (
            <p className="mt-2 text-sm text-slate-700">
              <span className="font-semibold">Overall uncertainty: </span>
              {investigation.overall_uncertainty}
            </p>
          ) : null}
        </section>
      ) : investigation.overall_uncertainty ? (
        <p className="mt-3 text-sm text-slate-700">
          <span className="font-semibold">Overall uncertainty: </span>
          {investigation.overall_uncertainty}
        </p>
      ) : null}
      {investigation.gate && investigation.gate.violations.length > 0 ? (
        <div className="mt-3">
          <h4 className="mb-1 text-sm font-semibold text-slate-900">
            Gate violations ({investigation.gate.violations.length})
          </h4>
          <GateViolationList violations={investigation.gate.violations} />
        </div>
      ) : null}
      {warnings.length > 0 ? <IntegrityWarnings warnings={warnings} heading="Investigation integrity warnings" /> : null}
    </Card>
  );
}

function IntegrityWarnings({ warnings, heading }: { warnings: string[]; heading: string }) {
  return (
    <div className="mt-3 rounded-md border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-semibold">{heading}</p>
      <ul className="mt-1 list-disc pl-5">
        {warnings.map((w, i) => (
          <li key={i} className="break-words">
            {w}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------- suspected cause
function EvidenceRefList({ evidence, label }: { evidence: EvidenceRef[]; label: string }) {
  if (evidence.length === 0) return <p className="text-sm text-slate-600">No evidence ids recorded.</p>;
  return (
    <ul aria-label={label} className="flex flex-col gap-1">
      {evidence.map((e) => (
        <li key={e.id} className="text-sm">
          <CodeBlock inline value={e.id} /> <span className="text-xs text-slate-500">({e.kind})</span>{" "}
          <span className="text-xs text-slate-500">source</span> <CodeBlock inline value={e.source_ref} />
          {e.excerpt ? <p className="mt-0.5 text-xs text-slate-600">“{e.excerpt}”</p> : null}
        </li>
      ))}
    </ul>
  );
}

function PathSummary({ path, index }: { path: ExplanationPath; index: number }) {
  const d = path.deployment;
  return (
    <li className="rounded-md border border-dashed border-amber-400 bg-amber-50/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-slate-900">Explanation path {index + 1}</h4>
        <HypothesisNote />
      </div>
      <p className="mt-2 text-sm text-slate-800">{path.summary}</p>
      <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Fact term="Deployment">
          <CodeBlock inline value={d.id} /> <span className="font-medium">{d.version}</span>
          <div className="text-xs text-slate-600">
            deployed <UtcTime iso={d.deployed_at} />
            {d.status ? <> · status {d.status}</> : null}
          </div>
          {d.source_ref ? (
            <div className="text-xs text-slate-600">
              source <CodeBlock inline value={d.source_ref} />
            </div>
          ) : null}
        </Fact>
        <Fact term="Target service">
          <CodeBlock inline value={path.target_service_id} />
        </Fact>
      </dl>
      <h5 className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Supporting evidence</h5>
      <EvidenceRefList evidence={path.evidence} label={`Supporting evidence for path ${index + 1}`} />
    </li>
  );
}

function FindingItem({ finding, index }: { finding: FindingOut; index: number }) {
  const warnings = finding.integrity_warnings ?? [];
  const n = index + 1;
  const contradicting = finding.contradicting_evidence;
  return (
    <li className="min-w-0 rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <ClaimTypeBadge claimType={finding.claim_type} />
        <span className="text-xs text-slate-500">Finding {n}</span>
        {typeof finding.confidence === "number" ? (
          <Badge tone="neutral" variant="outline" title={`Investigator confidence for finding ${n}`}>
            confidence {formatConfidence(finding.confidence)}
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 text-sm text-slate-900">{finding.statement}</p>
      {finding.uncertainty ? (
        <p className="mt-1 text-sm text-slate-700">
          <span className="font-semibold">Uncertainty: </span>
          {finding.uncertainty}
        </p>
      ) : null}
      <h5 className="mt-2 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Supporting evidence</h5>
      <EvidenceRefList evidence={finding.evidence} label={`Evidence for finding ${n}`} />
      {contradicting ? (
        <>
          <h5 className="mt-2 mb-1 text-xs font-semibold uppercase tracking-wide text-red-800">Contradicting evidence</h5>
          {contradicting.length === 0 ? (
            <p className="text-sm text-slate-600">None recorded.</p>
          ) : (
            <div className="rounded-md border-l-4 border-red-400 bg-red-50/50 py-1 pl-2">
              <EvidenceRefList evidence={contradicting} label={`Contradicting evidence for finding ${n}`} />
            </div>
          )}
        </>
      ) : null}
      {warnings.length > 0 ? <IntegrityWarnings warnings={warnings} heading="Finding integrity warnings" /> : null}
    </li>
  );
}

function SuspectedCause({ incident, investigation }: { incident: IncidentDetail; investigation: InvestigationOut | null }) {
  const paths = incident.explanation_paths;
  const findings = investigation?.findings ?? [];
  return (
    <Card
      title="Suspected cause"
      subtitle="Derived only from stored graph explanation paths. A path is a correlation that supports a hypothesis; it is not proof."
    >
      {paths.length === 0 ? (
        <EmptyState title="No evidence-backed path found — inconclusive">
          The graph holds no path linking this incident to a deployment. That is a valid result, not an error.
        </EmptyState>
      ) : (
        <ol aria-label="Explanation paths" className="flex flex-col gap-3">
          {paths.map((p, i) => (
            <PathSummary key={`${p.deployment.id}-${p.target_service_id}-${i}`} path={p} index={i} />
          ))}
        </ol>
      )}
      {findings.length > 0 ? (
        <>
          <h4 className="mt-4 mb-2 text-sm font-semibold text-slate-900">Investigation findings ({findings.length})</h4>
          <ol aria-label="Investigation findings" className="flex flex-col gap-3">
            {findings.map((f, i) => (
              <FindingItem key={i} finding={f} index={i} />
            ))}
          </ol>
        </>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------- proposed actions
interface ProposedAction {
  key: string;
  actionType: string;
  path: ExplanationPath;
  runbook: RunbookRef;
}

function deriveActions(paths: ExplanationPath[]): ProposedAction[] {
  const out: ProposedAction[] = [];
  paths.forEach((path, pi) => {
    path.runbooks.forEach((runbook) => {
      (runbook.allowed_action_types ?? []).forEach((actionType) => {
        out.push({ key: `${pi}:${runbook.id}:${actionType}`, actionType, path, runbook });
      });
    });
  });
  return out;
}

function ApprovalPolicy({
  path,
  userRoles,
  user,
}: {
  path: ExplanationPath;
  userRoles: readonly string[];
  user: string;
}) {
  const governing = path.governing_decisions.filter((d): d is DecisionRef & { required_approver_role: string } =>
    Boolean(d.required_approver_role),
  );
  if (path.approval_policy === "no_active_policy_escalate") {
    return (
      <div role="note" className="rounded-md border-2 border-red-400 bg-red-50 p-2 text-sm text-red-900">
        <p className="font-semibold">No active policy — escalate</p>
        <p className="text-xs">
          No decision currently governs the target service. Escalate to the service owner instead of acting.
        </p>
      </div>
    );
  }
  if (governing.length === 0) {
    return (
      <div role="note" className="rounded-md border-2 border-red-400 bg-red-50 p-2 text-sm text-red-900">
        <p className="font-semibold">Policy in force, but no approver role recorded — escalate</p>
        <p className="text-xs">The governing decision names no approver role, so nobody can be shown as eligible.</p>
      </div>
    );
  }
  return (
    <ul aria-label="Approval requirements" className="flex flex-col gap-2">
      {governing.map((d) => {
        const role = d.required_approver_role;
        const holds = userRoles.includes(role);
        return (
          <li key={d.id} className="text-sm">
            <span className="text-slate-700">Approver role </span>
            <CodeBlock inline value={role} />
            <span className="text-slate-700"> per decision </span>
            <span className="font-medium">{d.title}</span> <CodeBlock inline value={d.id} />{" "}
            <span className="text-xs text-slate-500">({d.status})</span>
            <div className="mt-1">
              {holds ? (
                <Badge tone="success" title={`${user} holds ${role}`}>
                  You hold {role}
                </Badge>
              ) : (
                <Badge tone="neutral" variant="outline" title={`${user} does not hold ${role}`}>
                  Requires {role}
                </Badge>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function RealProposal({
  proposal: p,
  paths,
  userRoles,
  user,
}: {
  proposal: ProposedActionOut;
  paths: ExplanationPath[];
  userRoles: readonly string[];
  user: string;
}) {
  const path = pathForProposal(paths, p);
  return (
    <li className="min-w-0 rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-slate-900">
          <CodeBlock inline value={p.action_type} className="text-sm" />
        </h4>
        <Badge tone="info" variant="outline" title="Proposed by the investigation run. Not executed.">
          Proposal
        </Badge>
        <ProposalStatusBadge status={p.status} />
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Fact term="Proposal id">
          <CodeBlock inline value={p.id} />
          <div className="text-xs text-slate-600">
            of <CodeBlock inline value={p.proposal_id} /> · version {p.version}
          </div>
        </Fact>
        <Fact term="Spec hash">
          <code title={p.spec_hash} aria-label={`Spec hash ${p.spec_hash}`} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-800">
            {shortHash(p.spec_hash)}
          </code>
        </Fact>
        <Fact term="Mode · risk">
          <CodeBlock inline value={p.mode} /> · {p.risk}
        </Fact>
        <Fact term="Target service">
          <CodeBlock inline value={p.target_service_id} />
        </Fact>
        <Fact term="Deployment">
          {p.deployment_id ? <CodeBlock inline value={p.deployment_id} /> : <span className="text-slate-600">none</span>}
        </Fact>
        <Fact term="Runbook">
          <CodeBlock inline value={p.runbook_id} />
        </Fact>
      </dl>
      <h5 className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Rationale</h5>
      <p className="text-sm text-slate-800">{p.rationale}</p>
      <h5 className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</h5>
      <EvidenceRefList evidence={p.evidence} label={`Evidence for proposal ${p.id}`} />
      <h5 className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Approval policy</h5>
      {path ? (
        <ApprovalPolicy path={path} userRoles={userRoles} user={user} />
      ) : (
        <p className="text-sm text-slate-700">No explanation path matches this proposal, so no governing decision is shown.</p>
      )}
    </li>
  );
}

function ProposedActions({
  paths,
  proposals,
  userRoles,
  user,
}: {
  paths: ExplanationPath[];
  proposals: ProposedActionOut[];
  userRoles: readonly string[];
  user: string;
}) {
  const banner = (
    <p className="mb-3 rounded-md border border-sky-300 bg-sky-50 p-2 text-sm font-medium text-sky-900">
      Proposal only — execution requires human approval (Phase 5); recommendation_only mode never executes.
    </p>
  );
  if (proposals.length > 0) {
    return (
      <Card title="Proposed safe actions" subtitle="Proposed by the investigation run and checked by the safety gate. None has been executed.">
        {banner}
        <ul aria-label="Proposed actions" className="flex flex-col gap-3">
          {proposals.map((p) => (
            <RealProposal key={p.id} proposal={p} paths={paths} userRoles={userRoles} user={user} />
          ))}
        </ul>
      </Card>
    );
  }
  const actions = deriveActions(paths);
  return (
    <Card title="Proposed safe actions" subtitle="Preview from the runbooks attached to each explanation path; no run has proposed an action.">
      {banner}
      {actions.length === 0 ? (
        <EmptyState title="No proposed actions">
          {paths.length === 0
            ? "There is no evidence-backed path, so no runbook action applies."
            : "The runbooks on these paths list no allowed action types."}
        </EmptyState>
      ) : (
        <ul aria-label="Proposed actions" className="flex flex-col gap-3">
          {actions.map((a) => (
            <li key={a.key} className="rounded-md border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="text-sm font-semibold text-slate-900">
                  <CodeBlock inline value={a.actionType} className="text-sm" />
                </h4>
                <Badge tone="info" variant="outline">
                  Proposal
                </Badge>
                <Badge tone="neutral" variant="dashed" title="Derived from graph paths, not proposed by an investigation run.">
                  Preview — derived from graph paths
                </Badge>
              </div>
              <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Fact term="Target service">
                  <CodeBlock inline value={a.path.target_service_id} />
                </Fact>
                <Fact term="Deployment">
                  <CodeBlock inline value={a.path.deployment.id} /> {a.path.deployment.version}
                </Fact>
                <Fact term="Runbook">
                  <span className="font-medium">{a.runbook.title}</span> <CodeBlock inline value={a.runbook.id} />{" "}
                  <span className="text-xs text-slate-500">v{a.runbook.version}</span>
                </Fact>
              </dl>
              <h5 className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Approval policy</h5>
              <ApprovalPolicy path={a.path} userRoles={userRoles} user={user} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
