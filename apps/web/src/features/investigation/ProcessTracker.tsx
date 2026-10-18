import { cx } from "../../components/ui";
import type { Stage } from "./model";
import { StatusPill, VISUAL } from "./ui";

export interface ProcessTrackerProps {
  stages: readonly Stage[];
  /** Compact = a single dense row, used under the header on tabs other than the investigation one. */
  compact?: boolean;
}

/** Stage tracker. Every state comes from `deriveStages`; nothing here advances on a timer. */
export function ProcessTracker({ stages, compact = false }: ProcessTrackerProps) {
  if (compact) {
    return (
      <nav aria-label="Investigation progress" className="card px-4 py-2.5">
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          {stages.map((stage, i) => {
            const v = VISUAL[stage.status];
            const active = stage.status === "running" || stage.status === "waiting" || stage.status === "failed";
            return (
              <li
                key={stage.id}
                data-stage={stage.id}
                data-status={stage.status}
                aria-current={active ? "step" : undefined}
                title={stage.caption}
                className="flex items-center gap-2"
              >
                {i > 0 ? <span aria-hidden="true" className="mr-1 h-px w-4 bg-line" /> : null}
                <span
                  aria-hidden="true"
                  className={cx(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 text-[10px] font-bold",
                    v.dot,
                    v.pulse ? "animate-pulse motion-reduce:animate-none" : "",
                  )}
                >
                  {v.glyph}
                </span>
                <span className={cx("text-xs", active ? "font-bold text-ink" : "font-medium text-muted")}>
                  <span className="sr-only">Step {i + 1}: </span>
                  {stage.label}
                  <span className="sr-only"> — {v.label}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </nav>
    );
  }

  return (
    <nav aria-label="Investigation progress" className="card px-5 py-4">
      <ol className="grid grid-cols-1 gap-x-2 gap-y-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {stages.map((stage, i) => {
          const v = VISUAL[stage.status];
          const active = stage.status === "running" || stage.status === "waiting" || stage.status === "failed";
          return (
            <li
              key={stage.id}
              data-stage={stage.id}
              data-status={stage.status}
              aria-current={active ? "step" : undefined}
              title={stage.caption}
              className="relative flex min-w-0 flex-col gap-2"
            >
              <div className="flex items-center gap-2.5">
                <span
                  aria-hidden="true"
                  className={cx(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold",
                    v.dot,
                    v.pulse ? "animate-pulse motion-reduce:animate-none" : "",
                  )}
                >
                  {v.glyph}
                </span>
                <span className={cx("min-w-0 text-sm leading-tight", active ? "font-bold text-ink" : "font-semibold text-ink")}>
                  <span className="sr-only">Step {i + 1}: </span>
                  {stage.label}
                </span>
                {/* Connector to the next step; hidden on the last column of each row. */}
                <span aria-hidden="true" className="ml-auto hidden h-px flex-1 bg-line 2xl:block" />
              </div>
              <div className="pl-[34px]">
                <StatusPill status={stage.status} />
                <p className="mt-1.5 text-xs leading-snug text-muted">{stage.caption}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
