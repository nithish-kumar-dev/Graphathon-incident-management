import { can, usersWith } from "../../auth/permissions";
import { ArrowLink, SectionCard, Spinner } from "../../components/ui";
import { clockUtc } from "../../lib/time";
import { useNavigateTab } from "../NavContext";
import { useInvestigationSession } from "./InvestigationSession";
import { ActivityTimeline } from "./ActivityTimeline";
import { AgentMonitor } from "./AgentMonitor";
import { AssessmentCard, FindingsPanel, NextDecisionCard } from "./FindingsPanel";

const STEPS = ["Retrieve context", "Analyze evidence", "Prepare recommendations"] as const;

/** The no-run state: nothing has been investigated, so only recorded records are shown. */
function NoRunView() {
  const { user, incident, run, view, memories } = useInvestigationSession();
  const navigate = useNavigateTab();
  const allowed = can(user, "investigation:create");
  const reason = allowed
    ? undefined
    : `${user} cannot start investigations (needs investigation:create). Switch the demo identity to ${usersWith("investigation:create").join(" or ")}.`;
  const resolved = incident.status === "resolved";
  const verified = memories?.memories.filter((m) => m.verification_status === "verified").length ?? null;
  const evidenceCount = incident.evidence.length;
  const events = view.events;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {resolved ? (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-muted px-5 py-3.5">
          <p className="min-w-0 text-sm text-ink">
            <span className="mr-3 text-[10px] font-extrabold uppercase tracking-[0.1em] text-muted">Incident resolved</span>
            {incident.resolved_at ? (
              <>
                Resolved <time dateTime={incident.resolved_at}>{clockUtc(incident.resolved_at)} UTC</time>.
              </>
            ) : (
              "This incident is marked resolved."
            )}
          </p>
          <ArrowLink onClick={() => navigate("history")}>View incident history</ArrowLink>
        </div>
      ) : null}

      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,13fr)_minmax(0,7fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard
            title="Investigation run"
            headingLevel={3}
            actions={<span className="inline-flex rounded-full bg-surface-muted px-2.5 py-1 text-[11px] font-semibold text-muted ring-1 ring-inset ring-line">Not started</span>}
          >
            <p className="text-sm text-muted">No agent run is selected for this incident. Existing evidence and response history remain available.</p>
            {resolved ? <p className="mt-1.5 text-sm text-muted">Starting a new run will investigate this already-resolved incident using available records.</p> : null}
          </SectionCard>

          <SectionCard
            title="Investigate this incident"
            headingLevel={3}
            subtitle="A new investigation can review the incident using the stored graph, company policy and prior outcomes. No agent work is underway."
          >
            <div id="agent-monitor" tabIndex={-1} className="flex flex-col gap-5 outline-none">
              <div className="rounded-lg border border-line bg-surface-sunken p-4">
                <p className="kicker mb-2">What will happen</p>
                <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-brand-deep">
                  {STEPS.map((step, i) => (
                    <li key={step} className="flex items-center gap-2">
                      {i > 0 ? (
                        <span aria-hidden="true" className="text-faint">
                          →
                        </span>
                      ) : null}
                      {step}
                    </li>
                  ))}
                </ol>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  className="btn-primary gap-2"
                  disabled={!allowed || run.starting}
                  aria-busy={run.starting || undefined}
                  title={reason}
                  onClick={() => void run.start("recommendation_only")}
                >
                  {run.starting ? (
                    <>
                      <Spinner size="sm" label="Starting investigation" />
                      <span aria-hidden="true">Starting…</span>
                    </>
                  ) : (
                    "Start investigation"
                  )}
                </button>
                <button type="button" className="btn-secondary" onClick={() => navigate("evidence")}>
                  Explore graph evidence
                </button>
              </div>
              {reason ? <p className="text-xs text-muted">{reason}</p> : null}
              <p className="text-xs text-faint">Recommendation-only mode · nothing here can change production systems</p>
            </div>
          </SectionCard>
        </div>

        <SectionCard title="Recorded incident timeline" subtitle="Response events · not agent activity" headingLevel={3} className="min-w-0 xl:self-start">
          {events.length === 0 ? (
            <p className="text-sm text-muted">No incident events are recorded.</p>
          ) : (
            <ol aria-label="Recorded incident events" className="flex flex-col border-t border-line pt-4">
              {events.map((e, i) => (
                <li key={e.id} className="relative flex gap-3 pb-4">
                  {i < events.length - 1 ? <span aria-hidden="true" className="absolute bottom-0 left-[4px] top-4 w-px bg-line" /> : null}
                  <span aria-hidden="true" className="relative z-10 mt-1.5 size-[9px] shrink-0 rounded-full bg-brand" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="text-sm font-bold text-ink">{e.label}</span>
                      <time dateTime={e.at} className="font-mono text-[11px] text-faint">
                        {clockUtc(e.at)} UTC
                      </time>
                    </div>
                    <p className="mt-0.5 text-xs text-muted [overflow-wrap:anywhere]">{e.summary}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Available before an investigation" headingLevel={3}>
        <dl className="grid grid-cols-1 gap-4 md:grid-cols-3 md:gap-0 md:divide-x md:divide-line">
          <div className="md:pr-5">
            <dt className="text-sm font-bold text-ink">Stored evidence</dt>
            <dd className="mt-1 text-xs text-muted">
              {evidenceCount} {evidenceCount === 1 ? "record" : "records"} attached to this incident
            </dd>
          </div>
          <div className="md:px-5">
            <dt className="text-sm font-bold text-ink">Company context</dt>
            <dd className="mt-1 text-xs text-muted">Policies and runbooks are retrieved when a run starts</dd>
          </div>
          <div className="md:pl-5">
            <dt className="text-sm font-bold text-ink">Verified memory</dt>
            <dd className="mt-1 text-xs text-muted">
              {verified === null ? "Not loaded" : `${verified} verified ${verified === 1 ? "memory" : "memories"} for this incident`}
            </dd>
          </div>
        </dl>
      </SectionCard>
    </div>
  );
}

/** The main view: the agent workstream beside what has been recorded, then the assessment and next decision. */
export default function LiveInvestigationTab() {
  const { view } = useInvestigationSession();
  if (view.phase === "none") return <NoRunView />;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-phase={view.phase}>
      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,13fr)_minmax(0,7fr)]">
        <AgentMonitor />
        <ActivityTimeline variant="summary" />
        <AssessmentCard />
        <NextDecisionCard />
      </div>
      <FindingsPanel />
    </div>
  );
}
