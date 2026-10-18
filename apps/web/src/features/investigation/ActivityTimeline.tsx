import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLink, EmptyState, ErrorBanner, SectionCard, Spinner, cx } from "../../components/ui";
import { clockUtc } from "../../lib/time";
import { useNavigateTab } from "../NavContext";
import type { TabId } from "../types";
import { useInvestigationSession } from "./InvestigationSession";
import { isActivePhase, type ActivityEvent } from "./model";

/** Events shown while following: all of them. While paused: only the ones present when paused. */
export function visibleEvents(events: readonly ActivityEvent[], frozenIds: ReadonlySet<string> | null): ActivityEvent[] {
  return frozenIds ? events.filter((e) => frozenIds.has(e.id)) : [...events];
}

const TONE_GLYPH: Record<ActivityEvent["tone"], string> = { neutral: "•", info: "i", success: "✓", warning: "!", danger: "✕" };
const TONE_DOT: Record<ActivityEvent["tone"], string> = {
  neutral: "border-line-strong bg-surface text-muted",
  info: "border-brand bg-brand-tint text-brand",
  success: "border-good bg-good-tint text-good",
  warning: "border-warn bg-warn-tint text-warn",
  danger: "border-bad bg-bad-tint text-bad",
};

const SUMMARY_LIMIT = 5;

export interface ActivityTimelineProps {
  /** "summary": the compact card on the Investigation tab (newest first, "View all"). "full": the whole log. */
  variant?: "summary" | "full";
}

export function ActivityTimeline({ variant = "full" }: ActivityTimelineProps = {}) {
  const { view, run, timelineError, timelineLoading } = useInvestigationSession();
  const navigate = useNavigateTab();
  const [frozen, setFrozen] = useState<Set<string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const summary = variant === "summary";

  const all = useMemo(() => visibleEvents(view.events, frozen), [view.events, frozen]);
  const shown = useMemo(() => (summary ? all.slice(-SUMMARY_LIMIT).reverse() : all), [all, summary]);
  const pending = frozen ? view.events.filter((e) => !frozen.has(e.id)).length : 0;
  const live = isActivePhase(view.phase) && view.phase !== "awaiting_review";

  useEffect(() => {
    if (frozen || summary) return;
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length, frozen, summary]);

  const toggle = () => setFrozen((f) => (f ? null : new Set(view.events.map((e) => e.id))));

  return (
    <SectionCard
      headingLevel={3}
      className="min-w-0"
      title={summary ? "Activity" : "Activity timeline"}
      subtitle={summary ? "Latest recorded events in this run" : "Events recorded by the backend. Hover a time for the exact UTC instant."}
      actions={
        <>
          <button type="button" className="btn-secondary" onClick={toggle} aria-pressed={frozen !== null}>
            {frozen ? `Resume auto-follow${pending > 0 ? ` (${pending} new)` : ""}` : "Pause auto-follow"}
          </button>
          {summary ? <ArrowLink onClick={() => navigate("history")}>View all</ArrowLink> : null}
        </>
      }
      footer={
        <p className="text-[11px] text-faint">
          Recorded events · UTC. {frozen ? "Auto-follow is paused." : "New events appear automatically."} The backend records start and outcome events only, so there are no per-agent steps here.
        </p>
      }
    >
      <ErrorBanner error={timelineError} title="Could not load the timeline" />

      {shown.length === 0 ? (
        timelineLoading ? (
          <Spinner label="Loading timeline…" />
        ) : (
          <EmptyState title="No events recorded yet" />
        )
      ) : (
        <ol
          ref={listRef}
          aria-label="Recorded events"
          className={cx("flex flex-col border-t border-line pt-4", summary ? "" : "max-h-[26rem] overflow-y-auto pr-1")}
        >
          {shown.map((e, i) => (
            <li key={e.id} className="relative">
              {i < shown.length - 1 ? <span aria-hidden="true" className="absolute bottom-0 left-[13px] top-7 w-px bg-line" /> : null}
              <button
                type="button"
                data-event-type={e.type}
                aria-expanded={selectedId === e.id}
                onClick={() => setSelectedId(selectedId === e.id ? null : e.id)}
                className={cx(
                  "flex w-full gap-3 rounded-md px-1 pb-4 text-left focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand",
                  selectedId === e.id ? "bg-brand-tint" : "hover:bg-surface-muted",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cx("relative z-10 mt-0.5 flex size-[26px] shrink-0 items-center justify-center rounded-full border text-[11px] font-bold", TONE_DOT[e.tone])}
                >
                  {TONE_GLYPH[e.tone]}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="text-sm font-bold text-ink">{e.label}</span>
                    <time dateTime={e.at} title={new Date(e.at).toISOString()} className="font-mono text-[11px] text-faint">
                      {clockUtc(e.at)} UTC
                    </time>
                  </span>
                  <span className="mt-0.5 block text-xs text-muted [overflow-wrap:anywhere]">{e.summary}</span>
                </span>
              </button>
              {selectedId === e.id ? <EventDetail event={e} onOpen={navigate} /> : null}
            </li>
          ))}
        </ol>
      )}

      {live ? (
        <p className="mt-2 flex items-start gap-2 rounded-md bg-brand-tint px-3 py-2 text-sm text-brand" role="status">
          <span aria-hidden="true" className="animate-pulse motion-reduce:animate-none">
            ●
          </span>
          <span>
            <span className="font-semibold">Now</span> (current run state, not a recorded event): {view.headline}
            {run.lastUpdated ? <span className="text-xs"> · checked {run.lastUpdated.toLocaleTimeString()}</span> : null}
          </span>
        </p>
      ) : null}
    </SectionCard>
  );
}

function EventDetail({ event, onOpen }: { event: ActivityEvent; onOpen: (tab: TabId) => void }) {
  return (
    <div className="mx-2 mb-2 mt-1 rounded-md border border-line bg-surface-muted p-2" aria-label={`Details of ${event.label}`}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="font-medium text-muted">Time</dt>
        <dd className="font-mono">{event.at}</dd>
        {event.details.map((d) => (
          <div key={`${d.label}:${d.value}`} className="contents">
            <dt className="font-medium text-muted">{d.label}</dt>
            <dd className="font-mono text-ink [overflow-wrap:anywhere]">{d.value}</dd>
          </div>
        ))}
      </dl>
      {event.link ? (
        <button type="button" className="btn-secondary mt-2" onClick={() => onOpen(event.link!.tab)}>
          {event.link.label}
        </button>
      ) : null}
    </div>
  );
}
