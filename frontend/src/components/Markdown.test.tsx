import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

describe("Markdown (renders untrusted model output)", () => {
  it("renders headings, lists and emphasis", () => {
    const { container } = render(<Markdown>{"# Plan\n\n- **Day 1** Tokyo\n- Day 2 Kyoto"}</Markdown>);
    expect(container.querySelector("h1")?.textContent).toBe("Plan");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("Day 1");
  });

  it("never turns raw HTML into elements (no script, iframe, img or handlers)", () => {
    const hostile = [
      "Hello <script>window.__xss = 1</script>",
      '<img src=x onerror="window.__xss = 2">',
      '<iframe src="https://evil.example"></iframe>',
      '<a href="x" onclick="window.__xss = 3">click</a>',
      '<div style="position:fixed;inset:0">overlay</div>',
    ].join("\n\n");
    const { container } = render(<Markdown>{hostile}</Markdown>);

    expect(container.querySelector("script, iframe, img, div[style]")).toBeNull();
    expect(container.querySelector("[onerror], [onclick]")).toBeNull();
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
  });

  it("drops javascript: links but keeps their text", () => {
    const { container } = render(<Markdown>{"[click me](javascript:alert(1))"}</Markdown>);
    const anchor = container.querySelector("a");
    expect(anchor?.textContent).toBe("click me");
    expect(anchor?.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
  });

  it("opens ordinary links in a new tab without leaking the opener", () => {
    const { container } = render(<Markdown>{"[Source](https://example.com/hotels)"}</Markdown>);
    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("https://example.com/hotels");
    expect(anchor?.getAttribute("target")).toBe("_blank");
    expect(anchor?.getAttribute("rel")).toContain("noopener");
    expect(anchor?.getAttribute("rel")).toContain("noreferrer");
  });

  it("wraps tables so wide itineraries scroll instead of breaking the layout", () => {
    const table = "| Day | Plan |\n|---|---|\n| 1 | Arrive |";
    const { container } = render(<Markdown>{table}</Markdown>);
    expect(container.querySelector(".table-wrap > table")).not.toBeNull();
    expect(container.querySelectorAll("td")).toHaveLength(2);
  });
});
