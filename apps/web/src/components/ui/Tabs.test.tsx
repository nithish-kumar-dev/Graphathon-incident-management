import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Harness() {
  const [sel, setSel] = useState("a");
  return (
    <Tabs
      label="Sections"
      selectedId={sel}
      onSelect={setSel}
      tabs={[
        { id: "a", label: "Alpha", content: <p>Alpha content</p> },
        { id: "b", label: "Beta", content: <p>Beta content</p> },
        { id: "c", label: "Gamma", content: <p>Gamma content</p> },
      ]}
    />
  );
}

describe("Tabs", () => {
  it("exposes tablist/tab/tabpanel roles", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    expect(alpha).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("tabindex", "-1");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Alpha content");
    expect(panel).toHaveAttribute("aria-labelledby", alpha.id);
  });

  it("moves with arrow keys, wraps, and supports Home/End", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("tab", { name: "Alpha" }));

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Beta content");

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveFocus();

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Gamma" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Gamma content");

    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Gamma" })).toHaveAttribute("aria-selected", "true");
  });
});
