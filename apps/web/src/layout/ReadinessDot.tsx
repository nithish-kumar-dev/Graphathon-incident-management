import { useApi } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { cx } from "../components/ui";

/** Small status dot for GET /readyz (FalkorDB + Postgres reachability). Click to re-check. */
export function ReadinessDot() {
  const { client } = useApi();
  const { data, error, loading, reload } = useAsync((signal) => client.getReadiness(signal), [client]);

  let tone = "bg-shell-faint";
  let text = "Checking…";
  let title = "Checking backend readiness";
  if (error) {
    tone = "bg-bad";
    text = "Unreachable";
    title = `Backend unreachable (${error.code})`;
  } else if (data) {
    const down = data.body ? Object.entries(data.body.checks).filter(([, ok]) => !ok).map(([k]) => k) : [];
    tone = data.ready ? "bg-live" : "bg-bad";
    text = data.ready ? "Connected" : "Not ready";
    title = data.ready ? "Backend ready" : `Backend not ready${down.length ? `: ${down.join(", ")} down` : ` (HTTP ${data.httpStatus})`}`;
  }

  return (
    <button
      type="button"
      onClick={reload}
      title={`${title}. Click to re-check.`}
      className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs text-shell-text hover:bg-shell-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-line"
    >
      <span aria-hidden="true" className={cx("inline-block h-2 w-2 rounded-full", tone, loading && "animate-pulse")} />
      <span>{text}</span>
      <span className="sr-only"> — {title}</span>
    </button>
  );
}
