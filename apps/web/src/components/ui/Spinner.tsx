import { cx } from "./cx";

export interface SpinnerProps {
  /** Accessible label; announced politely. */
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

export function Spinner({ label = "Loading…", size = "md", className }: SpinnerProps) {
  return (
    <span role="status" aria-live="polite" className={cx("inline-flex items-center gap-2 text-sm text-slate-600", className)}>
      <span
        aria-hidden="true"
        className={cx(
          "inline-block animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 motion-reduce:animate-none",
          size === "sm" ? "h-3 w-3" : "h-4 w-4",
        )}
      />
      <span className={size === "sm" ? "sr-only" : undefined}>{label}</span>
    </span>
  );
}
