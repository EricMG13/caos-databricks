// The case event tail (brief 4.4, decisions 1-4): one case-scoped stream,
// listening for exactly the closed v1 names, name-only.
import { EVENT_NAMES } from "@/wire/v1";
import { eventsUrl, openTail } from "@/app/sse";

class FakeSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static last: FakeSource | null = null;
  readonly listeners = new Map<string, (event: Event) => void>();
  readyState = FakeSource.CONNECTING;
  closed = false;
  constructor(readonly url: string) {
    FakeSource.last = this;
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

function withFake(run: () => void) {
  const held = globalThis.EventSource;
  globalThis.EventSource = FakeSource as unknown as typeof EventSource;
  try {
    run();
  } finally {
    globalThis.EventSource = held;
  }
}

const handlers = () => ({ onEvent: vi.fn(), onReconnect: vi.fn(), onRefused: vi.fn() });

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
      const tail = openTail("/api/v1/cases/c-1/events", handlers());
      expect(() => tail.close()).not.toThrow();
    } finally {
      globalThis.EventSource = held;
    }
  });

  test("it listens for exactly the committed names and nothing retired", () => {
    withFake(() => {
      const h = handlers();
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

  test("the first open is the connection; every later open is a reconnect", () => {
    withFake(() => {
      const h = handlers();
      openTail("/x", h);
      const source = FakeSource.last!;
      source.fire("open");
      expect(h.onReconnect).not.toHaveBeenCalled();
      source.fire("error");
      source.fire("open");
      source.fire("open");
      expect(h.onReconnect).toHaveBeenCalledTimes(2);
    });
  });

  test("an error that leaves the source closed is a refused reconnect", () => {
    withFake(() => {
      const h = handlers();
      openTail("/x", h);
      const source = FakeSource.last!;
      source.readyState = FakeSource.CONNECTING;
      source.fire("error");
      expect(h.onRefused).not.toHaveBeenCalled();
      source.readyState = FakeSource.CLOSED;
      source.fire("error");
      expect(h.onRefused).toHaveBeenCalledOnce();
      expect(source.closed).toBe(true);
    });
  });
});
