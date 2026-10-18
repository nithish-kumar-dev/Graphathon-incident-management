import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";
import favicon from "../public/favicon.svg?raw";

describe("index.html", () => {
  it("references the inline SVG favicon in public/", () => {
    const doc = new DOMParser().parseFromString(indexHtml, "text/html");
    const icon = doc.querySelector('link[rel="icon"]');
    expect(icon).not.toBeNull();
    expect(icon?.getAttribute("href")).toBe("/favicon.svg");
    expect(icon?.getAttribute("type")).toBe("image/svg+xml");
    expect(favicon).toMatch(/^<svg[\s>]/);
  });
});
