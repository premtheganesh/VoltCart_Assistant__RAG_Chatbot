import { describe, expect, it } from "vitest";
import { citationNumber, linkCitations } from "./citations";

describe("linkCitations", () => {
  it("links known sources", () => {
    expect(linkCitations("Fee is 10% [1].", new Set([1]))).toBe("Fee is 10% [1](#cite-1).");
  });

  it("splits grouped citations", () => {
    expect(linkCitations("Yes [1, 3]", new Set([1, 3]))).toBe("Yes [1](#cite-1)[3](#cite-3)");
  });

  it("drops numbers with no source", () => {
    expect(linkCitations("A [1][7] B [7]", new Set([1]))).toBe("A [1](#cite-1) B ");
  });

  it("keeps every number while streaming (sources not known yet)", () => {
    expect(linkCitations("A [7]", null)).toBe("A [7](#cite-7)");
  });

  it("leaves real Markdown links and non-numbers alone", () => {
    const text = "See [the guide](https://x.example) and [note] or [2](https://y)";
    expect(linkCitations(text, new Set([2]))).toBe(text);
  });
});

describe("citationNumber", () => {
  it("reads only citation links", () => {
    expect(citationNumber("#cite-12")).toBe(12);
    expect(citationNumber("https://evil.example/#cite-1")).toBeNull();
    expect(citationNumber(undefined)).toBeNull();
  });
});
