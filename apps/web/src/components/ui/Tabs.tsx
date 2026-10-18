import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";

export interface TabItem<Id extends string = string> {
  id: Id;
  label: ReactNode;
  /** Rendered only while this tab is selected (unselected tabs are not mounted). */
  content: ReactNode;
}

export interface TabsProps<Id extends string = string> {
  tabs: ReadonlyArray<TabItem<Id>>;
  selectedId: Id;
  onSelect: (id: Id) => void;
  /** Accessible name of the tablist. */
  label: string;
  className?: string;
}

/**
 * WAI-ARIA tabs with automatic activation: Left/Right arrows move and select (wrapping),
 * Home/End jump to the first/last tab. Only the selected tab is in the Tab order.
 */
export function Tabs<Id extends string>({ tabs, selectedId, onSelect, label, className }: TabsProps<Id>) {
  const baseId = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = Math.max(
    0,
    tabs.findIndex((t) => t.id === selectedId),
  );
  const tabId = (id: string) => `${baseId}-tab-${id}`;
  const panelId = (id: string) => `${baseId}-panel-${id}`;

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    let next: number | null = null;
    if (e.key === "ArrowRight") next = (selectedIndex + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (selectedIndex - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next === null) return;
    e.preventDefault();
    const tab = tabs[next];
    if (!tab) return;
    onSelect(tab.id);
    refs.current[next]?.focus();
  }

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="flex gap-1 overflow-x-auto border-b border-slate-200"
      >
        {tabs.map((t, i) => {
          const selected = i === selectedIndex;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={tabId(t.id)}
              aria-selected={selected}
              aria-controls={panelId(t.id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(t.id)}
              className={cx(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600",
                selected
                  ? "border-sky-700 text-sky-800"
                  : "border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900",
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {tabs.map((t, i) => {
        const selected = i === selectedIndex;
        return (
          <div
            key={t.id}
            role="tabpanel"
            id={panelId(t.id)}
            aria-labelledby={tabId(t.id)}
            hidden={!selected}
            tabIndex={0}
            className="pt-4 focus-visible:outline-2 focus-visible:outline-sky-600"
          >
            {selected ? t.content : null}
          </div>
        );
      })}
    </div>
  );
}
