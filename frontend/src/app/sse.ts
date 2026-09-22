// The case event tail (brief 4.4, decisions 1-4). Name-only: the client reads
// the event's name and refetches the sections it names; it never reads a
// payload. The browser resumes after its Last-Event-ID on its own; every open
// after the first refetches the visible documents, and a reconnect the server
// refuses (standing lost, 404) closes the tail for good.
import { EVENT_NAMES, type EventName } from "@/wire/v1";

export interface Tail {
  close(): void;
}

export interface TailHandlers {
  onEvent(name: EventName): void;
  /** The stream reopened after a drop: events may have been missed. */
  onReconnect(): void;
  /** The server refused the stream; the tail is closed. */
  onRefused(): void;
}

export function eventsUrl(caseId: string, runId: string | null, fixture: string | null): string {
  const params = new URLSearchParams();
  if (runId) params.set("run", runId);
  if (fixture) params.set("fixture", fixture);
  const search = params.toString();
  return `/api/v1/cases/${encodeURIComponent(caseId)}/events${search ? `?${search}` : ""}`;
}

export function openTail(url: string, handlers: TailHandlers): Tail {
  if (typeof EventSource === "undefined") return { close() {} };
  const source = new EventSource(url);
  for (const name of EVENT_NAMES) {
    source.addEventListener(name, () => handlers.onEvent(name));
  }
  let opened = false;
  source.addEventListener("open", () => {
    if (opened) handlers.onReconnect();
    opened = true;
  });
  // A dropped connection leaves the source CONNECTING and the browser retries;
  // a refused one (a non-200 answer) leaves it CLOSED, and it never retries.
  source.addEventListener("error", () => {
    if (source.readyState !== EventSource.CLOSED) return;
    source.close();
    handlers.onRefused();
  });
  return { close: () => source.close() };
}
