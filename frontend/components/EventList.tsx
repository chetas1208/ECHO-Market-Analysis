import type { ApiError } from "@/lib/api";
import type { EchoEvent } from "@/types/event";
import { EventCard } from "./EventCard";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";

export type EventListProps =
  | { status: "loading" }
  | { status: "error"; error: Pick<ApiError, "message" | "code" | "requestId" | "status">; onRetry?: () => void }
  | { status: "success"; events: EchoEvent[]; now?: number };

/** Renders the loading / error / empty / populated states of the events feed. */
export function EventList(props: EventListProps) {
  if (props.status === "loading") return <LoadingState />;
  if (props.status === "error") {
    return <ErrorState error={props.error} onRetry={props.onRetry} />;
  }
  if (props.events.length === 0) {
    return (
      <EmptyState title="No events yet">
        Run <code className="mono">make seed</code> to insert the mock fixture event, then refresh.
      </EmptyState>
    );
  }
  return (
    <ul className="event-list" aria-label="Events, newest first">
      {props.events.map((event) => (
        <li key={event.id}>
          <EventCard event={event} now={props.now} />
        </li>
      ))}
    </ul>
  );
}
