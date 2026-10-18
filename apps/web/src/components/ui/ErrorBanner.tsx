import type { ReactNode } from "react";
import type { ApiError } from "../../api/client";
import { cx } from "./cx";

export interface ErrorBannerProps {
  error: ApiError | null | undefined;
  /** Short context, e.g. "Could not load incident". */
  title?: string;
  /** Renders a Retry button. */
  onRetry?: () => void;
  /** Extra actions (e.g. a Dismiss button). */
  actions?: ReactNode;
  className?: string;
}

/** Shows the server's error code, message and request_id (quote the id when reading API logs). */
export function ErrorBanner({ error, title, onRetry, actions, className }: ErrorBannerProps) {
  if (!error) return null;
  return (
    <div role="alert" className={cx("rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900", className)}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          {title ? <p className="font-semibold">{title}</p> : null}
          <p className="break-words">
            <code className="mr-2 rounded bg-red-100 px-1 font-mono text-xs">{error.code}</code>
            {error.status ? <span className="mr-2 text-xs text-red-800">HTTP {error.status}</span> : null}
            {error.message}
          </p>
          {error.requestId ? (
            <p className="mt-1 text-xs text-red-800">
              request_id: <code className="font-mono break-all">{error.requestId}</code>
            </p>
          ) : null}
        </div>
        {onRetry || actions ? (
          <div className="flex shrink-0 gap-2">
            {onRetry ? (
              <button type="button" onClick={onRetry} className="btn-secondary">
                Retry
              </button>
            ) : null}
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  );
}
