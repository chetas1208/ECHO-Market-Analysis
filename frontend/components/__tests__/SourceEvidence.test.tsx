import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceEvidence, type SourceEvidenceItem } from "../SourceEvidence";

// Test fixtures only.
const mk = (over: Partial<SourceEvidenceItem> = {}): SourceEvidenceItem => ({
  provider: "gdelt",
  source_name: "Example Wire",
  source_group: "examplewire",
  source_url: "https://example.com/a",
  headline: "Tanker traffic halts",
  published_at: "2026-09-16T09:00:00Z",
  retrieved_at: "2026-09-16T09:05:30Z",
  is_independent: true,
  syndicated_from: null,
  reliability: 0.8,
  ...over,
});

describe("SourceEvidence", () => {
  it("shows summary, independent vs syndicated tags, reliability label and UTC times", () => {
    render(
      <SourceEvidence
        sources={[
          mk(),
          mk({
            source_name: "Repub Daily",
            source_group: "repub",
            is_independent: false,
            syndicated_from: "reuters",
            reliability: 0.5,
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("source-summary")).toHaveTextContent("2 sources · 1 independent");
    expect(screen.getByText("independent")).toBeInTheDocument();
    expect(screen.getByText("syndicated of reuters")).toBeInTheDocument();
    expect(screen.getAllByText(/reliability \(provider-supplied\)/)).toHaveLength(2);
    expect(screen.getByText("0.80")).toBeInTheDocument();
    expect(screen.getByText("0.50")).toBeInTheDocument();
    expect(screen.getAllByText(/published 2026-09-16 09:00 UTC/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("examplewire").length).toBe(1);
  });

  it("shows a REPLAY chip only for the replay provider", () => {
    render(<SourceEvidence sources={[mk({ provider: "replay" }), mk({ provider: "gdelt" })]} />);
    expect(screen.getAllByText("REPLAY")).toHaveLength(1);
    expect(screen.getByText("gdelt")).toBeInTheDocument();
  });

  it("renders http(s) URLs as safe links", () => {
    render(<SourceEvidence sources={[mk()]} />);
    const link = screen.getByRole("link", { name: "Tanker traffic halts" });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("rel")).toContain("noreferrer");
  });

  it("renders javascript:/data: URLs as plain text without href", () => {
    const { container } = render(
      <SourceEvidence
        sources={[
          mk({ source_url: "javascript:alert(1)" }),
          mk({ source_url: "data:text/html,<b>x</b>", headline: "Other" }),
        ]}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("[href]")).toBeNull();
    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
  });

  it("renders empty, loading and error states", () => {
    const { rerender } = render(<SourceEvidence sources={[]} />);
    expect(screen.getByText("No source evidence recorded")).toBeInTheDocument();

    rerender(<SourceEvidence sources={[]} loading />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("No source evidence recorded")).toBeNull();

    rerender(<SourceEvidence sources={[]} error={{ message: "boom", code: "internal_error" }} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("boom")).toBeInTheDocument();
    expect(screen.queryByText("No source evidence recorded")).toBeNull();
  });

  it("uses total for the count when provided", () => {
    render(<SourceEvidence sources={[mk()]} total={4} />);
    expect(screen.getByTestId("source-summary")).toHaveTextContent("4 sources · 1 independent");
  });

  it("renders untrusted text as text, never as HTML", () => {
    const xss = "<img src=x onerror=alert(1)>";
    const { container } = render(
      <SourceEvidence
        sources={[mk({ source_name: xss, headline: xss, source_group: xss, source_url: null })]}
      />,
    );
    expect(screen.getAllByText(xss).length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector("img")).toBeNull();
  });
});
