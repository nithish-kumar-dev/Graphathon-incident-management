import { useApi } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { cx } from "../components/ui";

/** Small status dot for GET /readyz (FalkorDB + Postgres reachability). Click to re-check. */
export function ReadinessDot() {
  const { client } = useApi();
  const { data, error, loading, reload } = useAsync((signal) => client.getReadiness(signal), [client]);

  let tone = "bg-slate-400";
  let text = "Checking backend…";
  if (error) {
    tone = "bg-red-600";
    text = `Backend unreachable (${error.code})`;
  } else if (data) {
    const down = data.body ? Object.entries(data.body.checks).filter(([, ok]) => !ok).map(([k]) => k) : [];
    tone = data.ready ? "bg-emerald-600" : "bg-red-600";
    text = data.ready ? "Backend ready" : `Backend not ready${down.length ? `: ${down.join(", ")} down` : ` (HTTP ${data.httpStatus})`}`;
  }

  return (
    <button
      type="button"
      onClick={reload}
      title={`${text}. Click to re-check.`}
      className="inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
    >
      <span aria-hidden="true" className={cx("inline-block h-2.5 w-2.5 rounded-full", tone, loading && "animate-pulse")} />
      <span>{text}</span>
    </button>
  );
}
