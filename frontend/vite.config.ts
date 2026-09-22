import { readFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Connect, type Plugin, type ProxyOptions } from "vite";

// Explicit demo dev and preview serve fixtures at the v1 wire's routes, for the
// six enabled sections only (brief 4.1, decision 9). Ordinary dev proxies to
// the real local API, and production carries none of this.
// `?fixture=<state>` selects
// fixtures/states/<section>.<state>.json, or drives a transport state.
const FIXTURES = fileURLToPath(new URL("./fixtures/", import.meta.url));
// The repository root's env files, read only for `CAOS_DEV_*` names (brief 4.5, decision 9).
const REPO_ROOT = fileURLToPath(new URL("../", import.meta.url));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ROLES = new Set(["READER", "ANALYST", "ADMIN"]);

/** A header the browser may not assert through the dev proxy. */
function isClientIdentity(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.startsWith("x-caos-") ||
    lower.startsWith("x-forwarded-") ||
    lower === "forwarded" ||
    lower.includes("_")
  );
}

/**
 * The real API proxy. Development trusts a role header, so the proxy -- never
 * the browser -- says who is asking: every client identity or forwarding
 * header is removed, then the local actor from `CAOS_DEV_USER` and
 * `CAOS_DEV_ROLE` (default ANALYST) is set. Without `CAOS_DEV_USER` nothing is
 * set and the API answers 401. A malformed value stops the server, and the
 * message never repeats it. Production serves no proxy and trusts no header.
 */
export function devProxy(env: Record<string, string | undefined>): Record<string, ProxyOptions> {
  const user = env.CAOS_DEV_USER || null;
  const role = env.CAOS_DEV_ROLE || "ANALYST";
  if (user !== null && !UUID.test(user)) throw new Error("CAOS_DEV_USER must be a UUID");
  if (!ROLES.has(role)) throw new Error("CAOS_DEV_ROLE must be READER, ANALYST or ADMIN");
  return {
    "/api": {
      target: "http://127.0.0.1:8000",
      xfwd: false,
      configure(proxy) {
        proxy.on("proxyReq", (proxyReq) => {
          for (const name of proxyReq.getHeaderNames()) {
            if (isClientIdentity(name)) proxyReq.removeHeader(name);
          }
          if (user === null) return;
          proxyReq.setHeader("x-caos-user", user);
          proxyReq.setHeader("x-caos-role", role);
        });
      },
    },
  };
}

/** The enabled section a v1 path names, or null. A disabled section is not served. */
function sectionOf(pathname: string): string | null {
  if (pathname === "/api/v1/directory") return "directory";
  // Book is the portfolio: no case in its path.
  if (pathname === "/api/v1/book") return "book";
  return (
    /^\/api\/v1\/cases\/[^/]+\/(upload|run|analysis|model|report|committee)$/.exec(pathname)?.[1] ??
    null
  );
}

// The frame a run's stream has advanced to; the next fetch of /run reads it.
let runFrame = 0;
// Whether the `stale` stream has announced a newer analytical identity; the
// next fetch of /analysis answers for a different run.
let staleAdvanced = false;

/** The `stale` fixture's newer answer: another displayed run, other figures. */
function advancedAnalysis(raw: string): string {
  const doc = JSON.parse(raw);
  const next = "00000000-0000-4000-8000-0000000000b2";
  doc.body.displayed_run_id = next;
  doc.body.latest_run_id = next;
  if (doc.body.handoffs[0]) doc.body.handoffs[0].confidence_score = 12;
  return JSON.stringify(doc);
}

async function readJson(path: string): Promise<string | null> {
  try {
    return await readFile(`${FIXTURES}${path}`, "utf8");
  } catch {
    return null;
  }
}

function send(res: ServerResponse, status: number, body: string): void {
  res.statusCode = status;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("cache-control", "no-store");
  res.end(body);
}

async function serveSection(section: string, fixture: string | null, res: ServerResponse) {
  if (fixture === "offline") {
    res.socket?.destroy();
    return;
  }
  if (fixture === "unavailable") return send(res, 404, "{}");
  if (fixture === "error") {
    return send(
      res,
      503,
      JSON.stringify({ code: "STORE_UNAVAILABLE", clears: "the store answers again" }),
    );
  }
  let path =
    section === "report"
      ? "report-v1.json"
      : section === "committee"
        ? "committee-v1.json"
        : `${section}.json`;
  if (fixture && !STREAM_FIXTURES.has(fixture)) path = `states/${section}.${fixture}.json`;
  else if (section === "run" && runFrame > 0) path = `run/frames/${runFrame}.json`;
  const body = await readJson(path);
  if (body === null) return send(res, 404, "{}");
  send(res, 200, section === "analysis" && staleAdvanced ? advancedAnalysis(body) : body);
}

/** Fixtures that drive the event stream, not a document state of their own. */
const STREAM_FIXTURES = new Set(["stale", "drop"]);

type Marker = [number, number];
const MARKER = /^(0|[1-9][0-9]{0,15})\.(0|[1-9][0-9]{0,15})$/;

/** A resume marker, or null when it is missing or malformed (brief 4.4, decision 3). */
function markerOf(value: string | string[] | undefined): Marker | null {
  const match = typeof value === "string" ? MARKER.exec(value) : null;
  return match ? [Number(match[1]), Number(match[2])] : null;
}

// The v1 case stream (brief 4.4, decisions 1-3): a cursor frame, then
// name-only frames `id: {audit_seq}.{run_seq}`, delivered strictly after a
// Last-Event-ID. `drop` ends the first connection after its second frame, so
// the browser resumes with its marker.
async function serveEvents(fixture: string | null, req: IncomingMessage, res: ServerResponse) {
  const named = fixture === "stale" ? "stale" : "events";
  const raw = await readJson(`run/${named}.json`);
  let events: { id: string; event: string }[] = [];
  try {
    events = raw ? JSON.parse(raw) : [];
  } catch {
    events = [];
  }
  const resumed = markerOf(req.headers["last-event-id"]);
  const [audit, run] = resumed ?? [0, 0];
  res.statusCode = 200;
  res.setHeader("content-type", "text/event-stream");
  res.setHeader("cache-control", "no-store");
  res.flushHeaders();
  // A fresh stream starts the fixture over; a resumed one keeps its place.
  if (resumed === null) {
    runFrame = 0;
    staleAdvanced = false;
  } else if (named === "events") {
    runFrame = run;
  }
  res.write(`retry: 300\nid: ${audit}.${run}\n\n`);
  const pending = events.filter((event) => {
    const marker = markerOf(event.id);
    return marker !== null && (marker[0] > audit || marker[1] > run);
  });
  const dropAfter = fixture === "drop" && resumed === null ? 2 : Infinity;
  let index = 0;
  const tick = () => {
    const event = pending[index];
    // With nothing left the stream stays open and idle, as a real tail does.
    if (res.writableEnded || !event) return;
    if (named === "events") runFrame = markerOf(event.id)?.[1] ?? runFrame;
    else staleAdvanced = true;
    res.write(`id: ${event.id}\nevent: ${event.event}\ndata: {}\n\n`);
    index += 1;
    if (index >= dropAfter) {
      res.end();
      return;
    }
    setTimeout(tick, 250);
  };
  setTimeout(tick, 250);
  // The frame is reset when a fresh stream opens, never when it closes: the
  // refetch an event triggers races the close, and must still see the last
  // frame. The client opens its tail before its first fetch for the same reason.
  // ponytail: one process-wide frame; per-stream frames if two runs ever tail at once.
  req.on("close", () => res.end());
}

const fixtureMiddleware: Connect.NextHandleFunction = (req, res, next) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  const pathname = url.pathname;
  const isApi = pathname.startsWith("/api/");
  if (isApi && !["GET", "HEAD"].includes(req.method ?? "GET")) {
    res.setHeader("allow", "GET, HEAD");
    send(
      res,
      405,
      JSON.stringify({ code: "READ_ONLY_DEMO", clears: "a real API handles commands" }),
    );
    return;
  }
  const requested = url.searchParams.get("fixture");
  // A state name is one word: never a path.
  if (requested !== null && !/^[a-z-]+$/.test(requested)) {
    send(res, 404, "{}");
    return;
  }
  if (!isApi) {
    next();
    return;
  }
  const fixture = requested;
  const section = sectionOf(pathname);
  if (section) {
    void serveSection(section, fixture, res);
    return;
  }
  if (/^\/api\/v1\/cases\/[^/]+\/events$/.test(pathname)) {
    void serveEvents(fixture, req, res);
    return;
  }
  // An evidence page's text layer (brief 4.4, decision 7): a fixture per
  // source and page, and the private 404 for anything else.
  const layer =
    /^\/api\/v1\/cases\/[^/]+\/runs\/[^/]+\/sources\/([0-9a-f-]{36})\/pages\/([1-9][0-9]{0,2})$/.exec(
      pathname,
    );
  if (layer) {
    void readJson(`pages/v1/${layer[1]}.${layer[2]}.json`).then((body) =>
      body === null
        ? send(
            res,
            404,
            JSON.stringify({ code: "PAGE_NOT_AVAILABLE", clears: "a pinned live page" }),
          )
        : send(res, 200, body),
    );
    return;
  }
  const page = /^\/api\/pages\/([A-Za-z0-9-]+\.svg)$/.exec(pathname)?.[1];
  if (page) {
    void readJson(`pages/${page}`).then((body) => {
      if (body === null) return send(res, 404, "{}");
      res.statusCode = 200;
      res.setHeader("content-type", "image/svg+xml");
      res.end(body);
    });
    return;
  }
  send(res, 404, "{}");
};

const fixtures: Plugin = {
  name: "caos-fixtures",
  configureServer(server) {
    server.middlewares.use(fixtureMiddleware);
  },
  configurePreviewServer(server) {
    server.middlewares.use(fixtureMiddleware);
  },
};

export default defineConfig(({ command, mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === "demo" ? [fixtures] : [])],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  publicDir: false,
  server: {
    port: 5173,
    strictPort: true,
    // A build carries no proxy, so its dev identity is never read.
    proxy:
      mode === "demo" || command !== "serve"
        ? undefined
        : devProxy(loadEnv(mode, REPO_ROOT, "CAOS_DEV_")),
  },
  preview: { port: 4173, strictPort: true },
  build: { sourcemap: false, target: "es2022" },
}));
