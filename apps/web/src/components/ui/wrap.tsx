import { Fragment, type ReactNode } from "react";

/** Characters after which an id or source ref may wrap: `.` `:` `/` `_` `-`, plus `?` `&` `=` for query strings. */
const BREAK_AFTER = /[^.:/_\-?&=]*[.:/_\-?&=]*/g;

/**
 * Split an id / fingerprint / source ref into segments that each end at a natural break point,
 * e.g. "nova.ev.101.deploy" -> ["nova.", "ev.", "101.", "deploy"]. Joining the segments gives the input back.
 */
export function breakSegments(text: string): string[] {
  return text.match(BREAK_AFTER)?.filter((s) => s.length > 0) ?? [];
}

/** Explicitly inline: accessible-name algorithms put a space around non-inline children, which would split ids. */
const WBR_STYLE = { display: "inline" } as const;

/**
 * Render text with a <wbr> after each natural break point, so long ids wrap at `.`/`:`/`/`/`_`/`-`
 * instead of mid-word. The text nodes stay direct children of the parent, so text queries still match.
 */
export function withWordBreaks(text: string): ReactNode {
  const parts = breakSegments(text);
  if (parts.length <= 1) return text;
  return parts.map((part, i) => (
    <Fragment key={i}>
      {part}
      {i < parts.length - 1 ? <wbr style={WBR_STYLE} /> : null}
    </Fragment>
  ));
}

/** Tailwind classes for inline ids: break at the <wbr> points; split a too-long segment only when it overflows. */
export const ID_WRAP = "break-words";
