import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CodeBlock } from "./CodeBlock";
import { breakSegments } from "./wrap";

describe("id wrapping", () => {
  it("splits after . : / _ - and joins back to the input", () => {
    expect(breakSegments("nova.ev.101.deploy")).toEqual(["nova.", "ev.", "101.", "deploy"]);
    expect(breakSegments("checkout:http_5xx_rate")).toEqual(["checkout:", "http_", "5xx_", "rate"]);
    expect(breakSegments("synthetic://deploys/payment/v2.4")).toEqual(["synthetic://", "deploys/", "payment/", "v2.", "4"]);
    expect(breakSegments("a-b")).toEqual(["a-", "b"]);
    expect(breakSegments("plain")).toEqual(["plain"]);
    expect(breakSegments("")).toEqual([]);
  });

  it("inline CodeBlock inserts <wbr> after each '.' and keeps the text intact", () => {
    render(<CodeBlock inline value="nova.ev.101.deploy" />);
    const code = screen.getByText("nova.ev.101.deploy");
    expect(code.tagName).toBe("CODE");
    expect(code.textContent).toBe("nova.ev.101.deploy");
    expect(code.querySelectorAll("wbr")).toHaveLength(3);
    expect(code.innerHTML.replace(/ style="[^"]*"/g, "")).toBe("nova.<wbr>ev.<wbr>101.<wbr>deploy");
    // Wraps at the <wbr> points, never mid-word.
    expect(code.className).not.toMatch(/break-all/);
  });

  it("does not add <wbr> to a value without break points", () => {
    render(<CodeBlock inline value="efa9151799087f32" />);
    expect(screen.getByText("efa9151799087f32").querySelector("wbr")).toBeNull();
  });
});
