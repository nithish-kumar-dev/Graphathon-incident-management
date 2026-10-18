import { cx } from "./cx";
import { ID_WRAP, withWordBreaks } from "./wrap";

export interface CodeBlockProps {
  /** A string is shown as-is; anything else is pretty-printed as JSON. */
  value: unknown;
  /** Render inline (<code>) instead of a block (<pre>). For ids and source refs: wraps at `.` `:` `/` `_` `-`. */
  inline?: boolean;
  className?: string;
  /** Accessible label for the block. */
  label?: string;
}

export function CodeBlock({ value, inline = false, className, label }: CodeBlockProps) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (inline) {
    return (
      <code
        aria-label={label}
        className={cx("rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-800", ID_WRAP, className)}
      >
        {withWordBreaks(text)}
      </code>
    );
  }
  return (
    <pre
      aria-label={label}
      className={cx(
        "max-h-96 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800 whitespace-pre-wrap [overflow-wrap:anywhere]",
        className,
      )}
    >
      <code>{text}</code>
    </pre>
  );
}
