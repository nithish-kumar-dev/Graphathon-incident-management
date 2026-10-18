/** Pure time helpers. `now` is injectable so tests and live ticking share one code path. */

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

/** "just now", "4 min ago", "3 h ago", "2 d ago"; "in the future" for clock skew. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  const t = parseTime(iso);
  if (t === null) return "unknown time";
  const s = Math.round((now - t) / 1000);
  if (s < -60) return "in the future";
  if (s < 10) return "just now";
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

/** "42 s", "3 min 5 s", "2 h 10 min". Null when either end is missing or the range is negative. */
export function formatDuration(fromIso: string | null | undefined, toIso: string | null | undefined): string | null {
  const a = parseTime(fromIso);
  const b = parseTime(toIso);
  if (a === null || b === null || b < a) return null;
  const s = Math.round((b - a) / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** HH:MM:SS in UTC, for timeline rows. */
export function clockUtc(iso: string | null | undefined): string {
  const t = parseTime(iso);
  return t === null ? "--:--:--" : new Date(t).toISOString().slice(11, 19);
}

/** Last dotted segment of a graph id: "nova.svc.checkout" -> "checkout". */
export function shortId(id: string): string {
  return id.split(".").pop() ?? id;
}
