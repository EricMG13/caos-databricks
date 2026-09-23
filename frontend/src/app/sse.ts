// The case event tail (brief 4.4, decisions 1-4). Name-only: the client reads
// the event's name and refetches the sections it names; it never reads a
// payload. The browser resumes after its Last-Event-ID on its own; every open,
// the first included, refetches the visible documents (finding FE-9), and a
// reconnect the server refuses is retried with backoff until the document read
// says the case is gone (finding FE-3).
import { EVENT_NAMES, type EventName } from "@/wire/v1";

export interface Tail {
  close(): void;
}

/** What to do after a refused reconnect. The document read decides: a case
    that answers 404 or unavailable has nothing left to stream, and anything
    else is a refusal the tail waits out. `retryAfterSeconds` is the server's
    own `Retry-After` where the refusal carried one. */
export interface TailDecision {
  stop: boolean;
  retryAfterSeconds: number | null;
}

export interface TailHandlers {
  onEvent(name: EventName): void;
  /** The stream is open: every open refetches, because events between the
      document read and the stream's head are not replayed. */
  onOpen(): void;
  /** The server refused the stream; answered with whether to stop and when to
      try again. */
  onRefused(): Promise<TailDecision>;
  /** Whether events are reaching this view. False from a refusal until the
      tail is open again, so the reader is told the view is no longer live. */
  onLive(live: boolean): void;
}

/** The first wait after a refused reconnect, doubling to the ceiling. */
export const FIRST_RETRY_MS = 1_000;
export const MAX_RETRY_MS = 60_000;

export function eventsUrl(caseId: string, runId: string | null, fixture: string | null): string {
  const params = new URLSearchParams();
  if (runId) params.set("run", runId);
  if (fixture) params.set("fixture", fixture);
  const search = params.toString();
  return `/api/v1/cases/${encodeURIComponent(caseId)}/events${search ? `?${search}` : ""}`;
}

/** The wait before the next attempt: 1 s doubling to 60 s, or the server's
    `Retry-After` where that is longer. The backoff is the floor, so a
    `Retry-After: 0` -- legal, and what a proxy may send mid-restart -- cannot
    turn a refusal into a reconnect loop as fast as the network allows (DF-8).
    Both are held to the ceiling, so a hostile or mistaken header cannot park
    the tail for a day. */
export function retryDelayMs(attempt: number, retryAfterSeconds: number | null): number {
  const backoff = FIRST_RETRY_MS * 2 ** attempt;
  const asked =
    retryAfterSeconds !== null && retryAfterSeconds >= 0 ? retryAfterSeconds * 1_000 : 0;
  return Math.min(Math.max(backoff, asked), MAX_RETRY_MS);
}

export function openTail(url: string, handlers: TailHandlers): Tail {
  if (typeof EventSource === "undefined") return { close() {} };
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let done = false;

  const connect = () => {
    const current = new EventSource(url);
    source = current;
    for (const name of EVENT_NAMES) {
      current.addEventListener(name, () => handlers.onEvent(name));
    }
    current.addEventListener("open", () => {
      attempt = 0;
      handlers.onLive(true);
      handlers.onOpen();
    });
    // A dropped connection leaves the source CONNECTING and the browser retries;
    // a refused one (a non-200 answer) leaves it CLOSED, and it never retries.
    // That is the browser's last word, not this workspace's: the tail reopens
    // itself until the document read says there is nothing to reopen for.
    // Either way nothing reaches the view from here until the next open, so it
    // stops being marked live now; that open refetches and marks it again
    // (MAX-14).
    current.addEventListener("error", () => {
      handlers.onLive(false);
      if (current.readyState !== EventSource.CLOSED) return;
      current.close();
      void handlers.onRefused().then((decision) => {
        if (done || decision.stop) return;
        const wait = retryDelayMs(attempt, decision.retryAfterSeconds);
        attempt += 1;
        timer = setTimeout(() => {
          timer = null;
          if (!done) connect();
        }, wait);
      });
    });
  };

  connect();
  return {
    close() {
      done = true;
      if (timer !== null) clearTimeout(timer);
      source?.close();
    },
  };
}
