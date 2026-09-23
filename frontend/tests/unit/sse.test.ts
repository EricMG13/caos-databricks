// The case event tail (brief 4.4, decisions 1-4): one case-scoped stream,
// listening for exactly the closed v1 names, name-only. Findings FE-3 and
// FE-9: a refused reconnect is retried with backoff until the document read
// says the case is gone, and every open refetches, the first included.
import { EVENT_NAMES } from "@/wire/v1";
import { FIRST_RETRY_MS, MAX_RETRY_MS, eventsUrl, openTail, retryDelayMs } from "@/app/sse";

class FakeSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static all: FakeSource[] = [];
  static get last(): FakeSource | null {
    return FakeSource.all.at(-1) ?? null;
  }
  readonly listeners = new Map<string, (event: Event) => void>();
  readyState = FakeSource.CONNECTING;
  closed = false;
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  addEventListener(name: string, handler: (event: Event) => void) {
    this.listeners.set(name, handler);
  }
  close() {
    this.closed = true;
    this.readyState = FakeSource.CLOSED;
  }
  fire(name: string) {
    this.listeners.get(name)?.(new Event(name));
  }
}

async function withFake(run: () => void | Promise<void>) {
  const held = globalThis.EventSource;
  FakeSource.all = [];
  globalThis.EventSource = FakeSource as unknown as typeof EventSource;
  try {
    await run();
  } finally {
    globalThis.EventSource = held;
  }
}

const KEEP = { stop: false, retryAfterSeconds: null };

const handlers = (refused: () => Promise<{ stop: boolean; retryAfterSeconds: number | null }>) => ({
  onEvent: vi.fn(),
  onOpen: vi.fn(),
  onLive: vi.fn(),
  onRefused: vi.fn(refused),
});

const settled = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("the case event tail", () => {
  test("the tail url is the case's v1 events path, the run optional", () => {
    expect(eventsUrl("c-1", null, null)).toBe("/api/v1/cases/c-1/events");
    expect(eventsUrl("c 1", "r-1", null)).toBe("/api/v1/cases/c%201/events?run=r-1");
    expect(eventsUrl("c-1", "r-1", "stale")).toBe("/api/v1/cases/c-1/events?run=r-1&fixture=stale");
  });

  test("openTail is a no-op where EventSource does not exist", () => {
    const held = globalThis.EventSource;
    // @ts-expect-error -- removing a global the runtime declares
    delete globalThis.EventSource;
    try {
      const tail = openTail(
        "/api/v1/cases/c-1/events",
        handlers(async () => KEEP),
      );
      expect(() => tail.close()).not.toThrow();
    } finally {
      globalThis.EventSource = held;
    }
  });

  test("it listens for exactly the committed names and nothing retired", async () => {
    await withFake(() => {
      const h = handlers(async () => KEEP);
      openTail("/x", h);
      const source = FakeSource.last!;
      const named = [...source.listeners.keys()].filter(
        (name) => !["open", "error"].includes(name),
      );
      expect(named.sort()).toEqual([...EVENT_NAMES].sort());
      for (const name of EVENT_NAMES) source.fire(name);
      expect(h.onEvent.mock.calls.map(([name]) => name)).toEqual([...EVENT_NAMES]);
      expect(source.listeners.has("authority_changed")).toBe(false);
      expect(source.listeners.has("stream_end")).toBe(false);
    });
  });

  // FE-9: the first open is a resync too. The stream carries no Last-Event-ID
  // yet, so anything that landed between the document read and the stream's
  // head is not replayed and only a read can find it.
  test("test_every_open_refetches_the_visible_documents_the_first_included", async () => {
    await withFake(() => {
      const h = handlers(async () => KEEP);
      openTail("/x", h);
      const source = FakeSource.last!;
      source.fire("open");
      expect(h.onOpen).toHaveBeenCalledTimes(1);
      expect(h.onLive).toHaveBeenLastCalledWith(true);
      source.fire("open");
      expect(h.onOpen).toHaveBeenCalledTimes(2);
    });
  });

  // FE-3: 1 s doubling to a 60 s ceiling, or the server's wait where it named
  // a longer one; neither the backoff nor a Retry-After passes the ceiling.
  test("test_the_reconnect_wait_doubles_from_a_second_to_a_minute_and_honours_retry_after", () => {
    expect(retryDelayMs(0, null)).toBe(FIRST_RETRY_MS);
    expect(retryDelayMs(1, null)).toBe(2_000);
    expect(retryDelayMs(3, null)).toBe(8_000);
    expect(retryDelayMs(20, null)).toBe(MAX_RETRY_MS);
    expect(retryDelayMs(0, 7)).toBe(7_000);
    expect(retryDelayMs(0, 86_400)).toBe(MAX_RETRY_MS);
  });

  // DF-8: `Retry-After: 0` is legal, and a proxy may send it mid-restart. It
  // was taken as a wait of nothing, so every tab reopened the stream and
  // re-read the document as fast as the network allowed. The backoff is the
  // floor under the server's wait, and it keeps doubling while refusals repeat.
  test("test_a_retry_after_shorter_than_the_backoff_waits_the_backoff", () => {
    expect(retryDelayMs(0, 0)).toBe(FIRST_RETRY_MS);
    expect(retryDelayMs(5, 0)).toBe(32_000);
    expect(retryDelayMs(3, 2)).toBe(8_000);
    expect(retryDelayMs(20, 0)).toBe(MAX_RETRY_MS);
  });

  test("test_a_tail_refused_with_retry_after_zero_waits_a_second_then_two", async () => {
    vi.useFakeTimers();
    try {
      await withFake(async () => {
        const h = handlers(async () => ({ stop: false, retryAfterSeconds: 0 }));
        openTail("/x", h);
        const refuse = async () => {
          FakeSource.last!.readyState = FakeSource.CLOSED;
          FakeSource.last!.fire("error");
          await vi.advanceTimersByTimeAsync(0);
        };
        await refuse();
        await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS - 1);
        expect(FakeSource.all).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(1);
        expect(FakeSource.all).toHaveLength(2);
        await refuse();
        await vi.advanceTimersByTimeAsync(2 * FIRST_RETRY_MS - 1);
        expect(FakeSource.all).toHaveLength(2);
        await vi.advanceTimersByTimeAsync(1);
        expect(FakeSource.all).toHaveLength(3);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("test_a_refused_reconnect_reopens_the_tail_after_the_backoff", async () => {
    vi.useFakeTimers();
    try {
      await withFake(async () => {
        const h = handlers(async () => KEEP);
        openTail("/x", h);
        expect(FakeSource.all).toHaveLength(1);
        FakeSource.last!.readyState = FakeSource.CLOSED;
        FakeSource.last!.fire("error");
        expect(h.onLive).toHaveBeenLastCalledWith(false);
        await vi.advanceTimersByTimeAsync(0);
        expect(h.onRefused).toHaveBeenCalledOnce();
        // Nothing reopens before the first second is out.
        await vi.advanceTimersByTimeAsync(FIRST_RETRY_MS - 1);
        expect(FakeSource.all).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(1);
        expect(FakeSource.all).toHaveLength(2);
        expect(FakeSource.last!.url).toBe("/x");
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("test_a_refused_reconnect_waits_the_servers_retry_after", async () => {
    vi.useFakeTimers();
    try {
      await withFake(async () => {
        const h = handlers(async () => ({ stop: false, retryAfterSeconds: 30 }));
        openTail("/x", h);
        FakeSource.last!.readyState = FakeSource.CLOSED;
        FakeSource.last!.fire("error");
        await vi.advanceTimersByTimeAsync(29_999);
        expect(FakeSource.all).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(1);
        expect(FakeSource.all).toHaveLength(2);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("test_a_case_that_is_gone_stops_the_tail_for_good", async () => {
    vi.useFakeTimers();
    try {
      await withFake(async () => {
        const h = handlers(async () => ({ stop: true, retryAfterSeconds: null }));
        openTail("/x", h);
        FakeSource.last!.readyState = FakeSource.CLOSED;
        FakeSource.last!.fire("error");
        expect(FakeSource.all[0]!.closed).toBe(true);
        await vi.advanceTimersByTimeAsync(MAX_RETRY_MS * 2);
        expect(FakeSource.all).toHaveLength(1);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("a closed tail neither reopens nor leaves a timer behind", async () => {
    vi.useFakeTimers();
    try {
      await withFake(async () => {
        const h = handlers(async () => KEEP);
        const tail = openTail("/x", h);
        FakeSource.last!.readyState = FakeSource.CLOSED;
        FakeSource.last!.fire("error");
        tail.close();
        await vi.advanceTimersByTimeAsync(MAX_RETRY_MS * 2);
        expect(FakeSource.all).toHaveLength(1);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  test("an error that leaves the source connecting is the browser's own retry", async () => {
    await withFake(async () => {
      const h = handlers(async () => KEEP);
      openTail("/x", h);
      const source = FakeSource.last!;
      source.readyState = FakeSource.CONNECTING;
      source.fire("error");
      await settled();
      expect(h.onRefused).not.toHaveBeenCalled();
      expect(source.closed).toBe(false);
      expect(FakeSource.all).toHaveLength(1);
    });
  });

  // MAX-14: a dropped connection returned before saying anything, so a view
  // receiving no events went on being marked live while the browser retried.
  test("test_a_dropped_connection_marks_the_view_not_live_until_it_reopens", async () => {
    await withFake(async () => {
      const h = handlers(async () => KEEP);
      openTail("/x", h);
      const source = FakeSource.last!;
      source.readyState = FakeSource.OPEN;
      source.fire("open");
      expect(h.onLive).toHaveBeenLastCalledWith(true);
      source.readyState = FakeSource.CONNECTING;
      source.fire("error");
      expect(h.onLive).toHaveBeenLastCalledWith(false);
      // The browser's own reconnect restores it, and that open resyncs.
      source.readyState = FakeSource.OPEN;
      source.fire("open");
      expect(h.onLive).toHaveBeenLastCalledWith(true);
      expect(h.onOpen).toHaveBeenCalledTimes(2);
      await settled();
      expect(h.onRefused).not.toHaveBeenCalled();
    });
  });
});
