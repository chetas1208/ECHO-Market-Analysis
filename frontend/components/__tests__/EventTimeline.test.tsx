import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EventTimeline, type TimelineSource } from "../EventTimeline";

const OCC = "2026-09-16T09:00:00Z";

function src(over: Partial<TimelineSource> & { source_name: string }): TimelineSource {
  return { retrieved_at: "2026-09-16T12:00:00Z", headline: null, published_at: null, ...over };
}

function items() {
  return within(screen.getByRole("list", { name: "Event timeline" })).getAllByRole("listitem");
}

/** Row accessor: text content by index (throws if the row is missing). */
function rows() {
  const els = items();
  const at = (i: number): string => {
    const el = els[i];
    if (!el) throw new Error(`no row ${i}`);
    return el.textContent ?? "";
  };
  return { length: els.length, kinds: els.map((e) => e.getAttribute("data-kind")), at };
}

describe("EventTimeline", () => {
  it("orders occurred, sources ascending by published_at, then last updated", () => {
    render(
      <EventTimeline
        occurredAt={OCC}
        revisions={3}
        sources={[
          src({ source_name: "Late Wire", headline: "Third", published_at: "2026-09-16T11:45:00Z" }),
          src({ source_name: "Early Wire", headline: "First", published_at: "2026-09-16T09:20:00Z" }),
          src({ source_name: "Mid Wire", headline: "Second", published_at: "2026-09-16T10:05:00Z" }),
        ]}
      />,
    );
    const li = rows();
    expect(li.kinds).toEqual([
      "occurred",
      "source",
      "source",
      "source",
      "updated",
    ]);
    expect(li.at(0)).toContain("09:00");
    expect(li.at(0)).toContain("Event occurred");
    expect(li.at(1)).toContain("Early Wire");
    expect(li.at(1)).toContain("First");
    expect(li.at(1)).toContain("09:20");
    expect(li.at(2)).toContain("Mid Wire");
    expect(li.at(2)).toContain("10:05");
    expect(li.at(3)).toContain("Late Wire");
    expect(li.at(3)).toContain("11:45");
    expect(li.at(4)).toContain("Last updated (revision 3)");
    expect(li.at(4)).toContain("12:00");
  });

  it("places a source with missing published_at by retrieved_at and notes it", () => {
    render(
      <EventTimeline
        occurredAt={OCC}
        sources={[
          src({ source_name: "B", published_at: "2026-09-16T10:30:00Z" }),
          src({ source_name: "NoPub", retrieved_at: "2026-09-16T10:00:00Z", published_at: null }),
        ]}
      />,
    );
    const li = rows();
    expect(li.at(1)).toContain("NoPub");
    expect(li.at(1)).toContain("10:00");
    expect(li.at(1)).toMatch(/unknown publish time/);
    expect(li.at(2)).toContain("B");
    expect(li.at(2)).not.toMatch(/unknown publish time/);
  });

  it("handles an unparsable retrieved_at without throwing and sorts it last", () => {
    render(
      <EventTimeline
        occurredAt={OCC}
        sources={[
          src({ source_name: "Broken", retrieved_at: "garbage", published_at: null }),
          src({ source_name: "Good", published_at: "2026-09-16T09:10:00Z" }),
        ]}
      />,
    );
    const li = rows();
    expect(li.at(1)).toContain("Good");
    expect(li.at(2)).toContain("Broken");
    expect(li.at(2)).toContain("--:--");
  });

  it("handles empty sources", () => {
    render(<EventTimeline occurredAt={OCC} sources={[]} />);
    const li = rows();
    expect(li).toHaveLength(1);
    expect(li.at(0)).toContain("Event occurred");
  });

  it("shows last updated with revision even when there are no sources", () => {
    render(<EventTimeline occurredAt={OCC} sources={[]} revisions={1} />);
    const li = rows();
    expect(li).toHaveLength(2);
    expect(li.at(1)).toContain("Last updated (revision 1)");
  });

  it("prefixes the date when a timestamp falls on another UTC day", () => {
    render(
      <EventTimeline
        occurredAt={OCC}
        sources={[src({ source_name: "Next", published_at: "2026-09-17T01:05:00Z" })]}
      />,
    );
    expect(rows().at(1)).toContain("09-17 01:05");
  });

  it("renders untrusted headline text as text, not HTML", () => {
    const { container } = render(
      <EventTimeline
        occurredAt={OCC}
        sources={[
          src({ source_name: "X", headline: "<img src=x onerror=alert(1)>", published_at: OCC }),
        ]}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});
