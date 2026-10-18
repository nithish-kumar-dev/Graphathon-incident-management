import { EmptyState, SectionCard, cx } from "../../components/ui";
import { useNavigateTab } from "../NavContext";
import type { AgentCardModel, Discovery } from "./model";
import { RelativeTime, StatusPill, VISUAL } from "./ui";
import { useInvestigationSession } from "./InvestigationSession";

const TONE_MARK: Record<Discovery["tone"], { mark: string; cls: string; sr: string }> = {
  neutral: { mark: "•", cls: "text-faint", sr: "" },
  positive: { mark: "✓", cls: "text-good", sr: "Supports: " },
  warning: { mark: "!", cls: "text-warn", sr: "Warning: " },
  danger: { mark: "✕", cls: "text-bad", sr: "Problem: " },
};

const VISIBLE_DISCOVERIES = 3;

export function AgentCard({ agent, last = false }: { agent: AgentCardModel; last?: boolean }) {
  const navigate = useNavigateTab();
  const shown = agent.discoveries.slice(0, VISIBLE_DISCOVERIES);
  const hidden = agent.discoveries.slice(VISIBLE_DISCOVERIES);
  const muted = agent.status === "pending" || agent.status === "skipped" || agent.status === "not_recorded";
  const v = VISUAL[agent.status];
  const counted = agent.status === "completed" && agent.resultCount !== null;
  return (
    <li className="relative">
      {!last ? <span aria-hidden="true" className="absolute bottom-[-0.5rem] left-[1.375rem] top-12 w-px bg-line" /> : null}
      <article
        aria-label={`${agent.name} agent`}
        data-agent={agent.id}
        data-status={agent.status}
        className={cx(
          "flex min-w-0 flex-col gap-2 rounded-lg border p-3",
          agent.status === "running" ? "border-brand-line bg-brand-tint" : agent.status === "failed" ? "border-bad-line bg-bad-tint" : muted ? "border-line bg-surface-muted" : "border-line bg-surface",
        )}
      >
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className={cx(
              "relative z-10 flex size-[26px] shrink-0 items-center justify-center rounded-full border text-xs font-bold",
              v.dot,
              v.pulse ? "animate-pulse motion-reduce:animate-none" : "",
            )}
          >
            {v.glyph}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
              <h4 className="text-sm font-bold text-ink">
                {agent.name}
                <span className="sr-only"> ({v.label})</span>
              </h4>
              {counted ? (
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-good-tint px-2.5 py-1 text-[11px] font-semibold text-good ring-1 ring-inset ring-good-line">
                  <span aria-hidden="true">✓</span>
                  {agent.resultCount} {agent.resultLabel}
                </span>
              ) : (
                <StatusPill status={agent.status} agent />
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted">{agent.activity}</p>
          </div>
        </div>

        <div className="pl-[38px]">
          {agent.nextStep ? <p className="text-xs text-muted">Next: {agent.nextStep}</p> : null}

          {shown.length > 0 ? (
            <ul aria-label={`${agent.name} key discoveries`} className="mt-1 flex flex-col gap-1 text-sm text-ink">
              {shown.map((d, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden="true" className={cx("w-3 shrink-0 text-center font-bold", TONE_MARK[d.tone].cls)}>
                    {TONE_MARK[d.tone].mark}
                  </span>
                  <span>
                    <span className="sr-only">{TONE_MARK[d.tone].sr}</span>
                    {d.text}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          <details className="group mt-1 text-sm">
            <summary className="cursor-pointer text-xs font-bold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
              {hidden.length > 0 ? `Details (+${hidden.length} more discoveries)` : "Details"}
            </summary>
            <div className="mt-2 flex flex-col gap-2 border-t border-line pt-2">
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                <div className="flex gap-1">
                  <dt>Started</dt>
                  <dd>{agent.startedAt ? <RelativeTime iso={agent.startedAt} /> : "not reported"}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>Duration</dt>
                  <dd>{agent.duration ?? "not reported"}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>Results</dt>
                  <dd className="font-medium text-ink">{agent.resultCount === null ? "—" : `${agent.resultCount} ${agent.resultLabel}`}</dd>
                </div>
              </dl>
              <p className="text-xs text-muted">{agent.subtitle}</p>
              {hidden.length > 0 ? (
                <ul className="flex flex-col gap-1 text-sm text-ink">
                  {hidden.map((d, i) => (
                    <li key={i}>• {d.text}</li>
                  ))}
                </ul>
              ) : null}
              {agent.links.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {agent.links.map((l) => (
                    <button key={l.label} type="button" className="btn-secondary" onClick={() => navigate(l.tab)}>
                      {l.label}
                    </button>
                  ))}
                </div>
              ) : null}
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                {agent.details.map((d) => (
                  <div key={d.label} className="contents">
                    <dt className="font-medium text-muted">{d.label}</dt>
                    <dd className="font-mono text-ink [overflow-wrap:anywhere]">{d.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs text-faint">{agent.timingNote}</p>
            </div>
          </details>
        </div>
      </article>
    </li>
  );
}

/** Real orchestrator steps only. With no run there are no statuses to show, so no rows are rendered. */
export function AgentMonitor() {
  const { view, run } = useInvestigationSession();
  const agents = view.agents;
  const done = agents.filter((a) => a.status === "completed").length;

  return (
    <SectionCard
      headingLevel={3}
      className="min-w-0"
      title="Agent workstream"
      subtitle={agents.length > 0 ? view.headline : "The real steps of the investigation graph. Statuses come from the backend run record."}
      actions={
        agents.length > 0 ? (
          <span className="inline-flex whitespace-nowrap rounded-full bg-surface-muted px-2.5 py-1 text-[11px] font-semibold text-muted ring-1 ring-inset ring-line">
            {done} of {agents.length} steps
          </span>
        ) : null
      }
    >
      <div id="agent-monitor" tabIndex={-1} className="outline-none">
        {agents.length === 0 ? (
          <EmptyState title={run.investigationId ? "Loading agent state…" : "No agents have run for this incident"}>
            {run.investigationId
              ? "Fetching the run record from the backend."
              : "Start an investigation. A coordinator will fan out to graph, memory and telemetry retrieval, then an investigator and a safety gate will work on the results."}
          </EmptyState>
        ) : (
          <ol aria-label="Agent steps" className="flex flex-col gap-2">
            {agents.map((a, i) => (
              <AgentCard key={a.id} agent={a} last={i === agents.length - 1} />
            ))}
          </ol>
        )}
      </div>
    </SectionCard>
  );
}
