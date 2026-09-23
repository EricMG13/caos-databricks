import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import {
  UNAVAILABLE_WORDING,
  bodyOf,
  fetchQualification,
  fetchSection,
  qualificationUrl,
  retryAfterOf,
  sectionUrl,
} from "@/app/transport";
import { ENABLED_SECTIONS, isEnabledSection } from "@/app/sections";
import { Workspace } from "@/app/Workspace";
import { Rail } from "@/chrome/Rail";
import { composeChrome, markDisabled } from "@/chrome/compose";
import { SECTIONS } from "@/wire";
import {
  parseCommitteeDocument,
  parseModelDocument,
  parseReportDocument,
  parseUploadDocument,
} from "@/wire/v1";

const CASE = "3f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const OTHER_CASE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const RUN = "7e6d5c4b-3a29-4817-a6f5-e4d3c2b1a098";
const AT = "2026-09-14T10:00:00.123456Z";
const REVISION = "4f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const DISABLED = SECTIONS.filter((section) => !isEnabledSection(section));
const QUALIFICATION = "a".repeat(64);

/** A v1 Upload document for `CASE`, served under `role`. */
function v1Upload(role: { global_role: string; standing: string | null }, caseId = CASE) {
  return {
    chrome: { subject: { case_id: caseId, title: "Acme" }, served_role: role, actions: [] },
    body: { case_id: caseId, sources: [], set_versions: [] },
    observed_at: AT,
    observed_empty: false,
    status: "complete",
    notes: [],
  };
}

function v1Model(runId = RUN) {
  return {
    chrome: {
      subject: { case_id: CASE, title: "Acme" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body: {
      case_id: CASE,
      latest_run_id: runId,
      displayed_run_id: runId,
      subject: null,
      displayed_run_status: "COMPLETE",
      blocked_by: null,
      forecast: null,
      unavailable_reason: "NO_ACCEPTED_FORECAST",
    },
    observed_at: AT,
    observed_empty: false,
    status: "complete",
    notes: [],
  };
}

function v1Report({
  caseId = CASE,
  runId = RUN,
  revisionId = REVISION,
}: { caseId?: string; runId?: string; revisionId?: string } = {}) {
  return {
    chrome: {
      subject: { case_id: caseId, title: "Acme" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body: {
      case_id: caseId,
      displayed_run_id: runId,
      revision_id: revisionId,
      payload_sha256: "a".repeat(64),
      case_title: "Acme",
      artifacts: [],
      narrative: [],
      revisions: [],
    },
    observed_at: AT,
    observed_empty: false,
    status: "complete",
    notes: [],
  };
}

function v1Committee({
  caseId = CASE,
  runId = RUN,
  revisionId = REVISION,
  receiptRevisionId = revisionId,
}: { caseId?: string; runId?: string; revisionId?: string; receiptRevisionId?: string } = {}) {
  const report = v1Report({ caseId, runId, revisionId });
  return {
    ...report,
    body: {
      ...report.body,
      state: "filed",
      signed_by: [CASE],
      frozen_by: RUN,
      filed_by: REVISION,
      receipt: {
        case_id: caseId,
        run_id: runId,
        revision_id: receiptRevisionId,
        payload_sha256: "a".repeat(64),
        signed_by: CASE,
        frozen_by: RUN,
        filed_by: REVISION,
        renderer_sha256: "b".repeat(64),
        filed_event_sha256: "c".repeat(64),
      },
    },
  };
}

describe("the transport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  test("a request that never reached the server is offline, with no engine text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await fetchSection("analysis", { case: CASE })).toEqual({ kind: "offline" });
  });

  test("a body that is not JSON reads as null, so a refusal is typed from nothing", async () => {
    expect(await bodyOf(new Response("<html>", { status: 502 }))).toBeNull();
    expect(await bodyOf(new Response('{"code":"X"}', { status: 409 }))).toEqual({ code: "X" });
  });

  // FE-3: the event tail waits the server's own Retry-After where the refusal
  // carried one. An HTTP-date form names a moment against a clock this
  // workspace does not trust, so it reads as absent.
  test("test_a_refusals_retry_after_is_carried_in_seconds_or_not_at_all", async () => {
    expect(retryAfterOf(new Response("{}", { status: 503 }))).toBeNull();
    expect(
      retryAfterOf(new Response("{}", { status: 503, headers: { "Retry-After": "30" } })),
    ).toBe(30);
    expect(
      retryAfterOf(
        new Response("{}", {
          status: 503,
          headers: { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" },
        }),
      ),
    ).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "STREAM_LIMIT_REACHED", clears: "a slot frees" }), {
          status: 503,
          headers: { "Retry-After": "12" },
        }),
      ),
    );
    expect(await fetchSection("analysis", { case: CASE })).toEqual({
      kind: "error",
      refusal: { code: "STREAM_LIMIT_REACHED", clears: "a slot frees" },
      retryAfterSeconds: 12,
    });
  });

  test("an observed 404 is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 404 })));
    expect(await fetchSection("analysis", { case: CASE })).toEqual({ kind: "unavailable" });
    expect(UNAVAILABLE_WORDING).toBe("Unavailable or not permitted.");
  });

  test("qualification reads bind the returned state to the requested evidence", async () => {
    const body = {
      evidence_sha256: QUALIFICATION,
      state: "RESTRICTED",
      qualification_set_sha256: null,
      performed_sha256: null,
      build_id: null,
      adapter_version: null,
      provider: null,
      model: null,
      reviewer: null,
      decided_at: null,
      expires_at: null,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));

    expect(qualificationUrl(QUALIFICATION)).toBe(`/api/v1/qualification/${QUALIFICATION}`);
    expect(await fetchQualification(QUALIFICATION)).toEqual({ kind: "ready", document: body });

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ ...body, evidence_sha256: "b".repeat(64) })),
        ),
    );
    expect(await fetchQualification(QUALIFICATION)).toEqual({
      kind: "error",
      refusal: {
        code: "WIRE_IDENTITY_MISMATCH",
        clears: "the qualification result is bound to the requested evidence",
      },
    });
  });

  test("any other non-2xx is a typed refusal, never exception text", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("Traceback (most recent call last)", { status: 500 }))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ code: "STORE_UNAVAILABLE", clears: "The store answers." }),
            { status: 503 },
          ),
        ),
    );
    const opaque = await fetchSection("run", { case: CASE });
    expect(opaque).toEqual({
      kind: "error",
      refusal: { code: "RESPONSE_INVALID", clears: expect.any(String) },
    });
    expect(JSON.stringify(opaque)).not.toContain("Traceback");
    expect(await fetchSection("run", { case: CASE })).toEqual({
      kind: "error",
      refusal: { code: "STORE_UNAVAILABLE", clears: "The store answers." },
    });
  });

  test("test_a_legacy_refusal_body_is_response_invalid", async () => {
    const bodies = [
      { refusal: "STORE_UNAVAILABLE" },
      { refusal: { code: "STORE_UNAVAILABLE", clears: "x" } },
      { code: "SOMETHING_INVENTED", clears: "x" },
      { code: "STORE_UNAVAILABLE", clears: "x", extra: 1 },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(bodies.shift()), { status: 503 })),
    );
    for (let i = 0; i < 4; i += 1) {
      expect(await fetchSection("directory", {})).toEqual({
        kind: "error",
        refusal: { code: "RESPONSE_INVALID", clears: expect.any(String) },
      });
    }
  });

  test("test_a_report_without_a_revision_is_requested_for_the_runs_head_or_first_save", () => {
    // The filing chain's front door: nothing else sets `?revision`, so a
    // Report that needed one to load could never produce the first.
    vi.stubEnv("MODE", "production");
    expect(sectionUrl("report", { case: CASE, run: RUN })).toBe(
      `/api/v1/cases/${CASE}/report?run=${RUN}`,
    );
    expect(sectionUrl("report", { case: CASE })).toBeNull();
    vi.unstubAllEnvs();
  });

  test("test_section_urls_are_versioned_case_scoped_and_carry_no_fixture_outside_demo", () => {
    vi.stubEnv("MODE", "production");
    expect(sectionUrl("directory", { fixture: "reader" })).toBe("/api/v1/directory");
    expect(sectionUrl("upload", { case: CASE, run: RUN, fixture: "partial" })).toBe(
      `/api/v1/cases/${CASE}/upload`,
    );
    expect(sectionUrl("run", { case: CASE, run: RUN })).toBe(
      `/api/v1/cases/${CASE}/run?run=${RUN}`,
    );
    expect(sectionUrl("analysis", { case: CASE })).toBe(`/api/v1/cases/${CASE}/analysis`);
    expect(sectionUrl("model", { case: "a/b?c", run: RUN })).toBe(
      `/api/v1/cases/a%2Fb%3Fc/model?run=${RUN}`,
    );
    expect(sectionUrl("model", { case: CASE })).toBe(`/api/v1/cases/${CASE}/model`);
    for (const section of ["report", "committee"] as const) {
      expect(sectionUrl(section, { case: "a/b?c", run: RUN, revision: REVISION })).toBe(
        `/api/v1/cases/a%2Fb%3Fc/${section}?run=${RUN}&revision=${REVISION}`,
      );
    }
    expect(sectionUrl("run", { case: "a/b?c" })).toBe("/api/v1/cases/a%2Fb%3Fc/run");
    expect(sectionUrl("committee", { case: CASE, run: RUN })).toBeNull();
    // A caseless case section, or a disabled section, has no URL at all.
    for (const section of ["upload", "run", "analysis", "model", "report", "committee"] as const) {
      expect(sectionUrl(section, { run: RUN })).toBeNull();
    }
    for (const section of DISABLED) expect(sectionUrl(section, { case: CASE })).toBeNull();

    vi.stubEnv("MODE", "demo");
    expect(sectionUrl("run", { case: CASE, run: RUN, fixture: "gate" })).toBe(
      `/api/v1/cases/${CASE}/run?run=${RUN}&fixture=gate`,
    );
    expect(sectionUrl("directory", { fixture: "observed-empty" })).toBe(
      "/api/v1/directory?fixture=observed-empty",
    );
    for (const section of DISABLED) {
      expect(sectionUrl(section, { case: CASE, fixture: "reader" })).toBeNull();
    }
  });

  test("a caseless case section is unavailable and sends no request", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    for (const section of ["upload", "run", "analysis", "model"] as const) {
      expect(await fetchSection(section, {})).toEqual({ kind: "unavailable" });
    }
    for (const section of DISABLED) {
      expect(await fetchSection(section, { case: CASE })).toEqual({ kind: "unavailable" });
    }
    expect(spy).not.toHaveBeenCalled();
  });

  test("test_disabled_sections_render_unavailable_without_a_request", async () => {
    expect([...ENABLED_SECTIONS]).toEqual([
      "directory",
      "upload",
      "run",
      "analysis",
      "book",
      "model",
      "report",
      "committee",
    ]);
    expect(DISABLED).toEqual(["admin"]);
    const spy = vi.fn();
    const tail = vi.fn();
    vi.stubGlobal("fetch", spy);
    vi.stubGlobal("EventSource", tail);
    vi.stubEnv("MODE", "demo");
    for (const section of DISABLED) {
      const { container, unmount } = render(
        createElement(
          MemoryRouter,
          { initialEntries: [`/${section}/?case=${CASE}&fixture=reader`] },
          createElement(Workspace, { section }),
        ),
      );
      expect(
        await within(container).findByText(UNAVAILABLE_WORDING, {
          selector: "[data-surface-state='unavailable'] *",
        }),
      ).toBeInTheDocument();
      const nav = within(container).getByRole("navigation", { name: "Workspace" });
      for (const off of DISABLED) {
        const link = within(nav).getByRole("link", { name: new RegExp(off, "i") });
        expect(link, off).toHaveTextContent(/unavailable/i);
      }
      unmount();
    }
    expect(spy).not.toHaveBeenCalled();
    expect(tail).not.toHaveBeenCalled();
  });

  test("a supplied Model run is parser-bound to the displayed run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(v1Model(OTHER_CASE)))),
    );
    expect(await fetchSection("model", { case: CASE, run: RUN })).toEqual({
      kind: "error",
      refusal: { code: "WIRE_IDENTITY_MISMATCH", clears: expect.any(String) },
    });
    expect(parseModelDocument(v1Model()).body.displayed_run_id).toBe(RUN);
  });

  test("Report requires the case and run and binds the revision it names", async () => {
    const mismatches = [
      v1Report({ caseId: OTHER_CASE }),
      v1Report({ runId: OTHER_CASE }),
      v1Report({ revisionId: OTHER_CASE }),
    ];
    const spy = vi.fn(async () => new Response(JSON.stringify(mismatches.shift())));
    vi.stubGlobal("fetch", spy);
    // A Report with no revision named is requested -- the run's head, or its
    // first save -- so only a missing case or run sends nothing.
    for (const query of [
      { case: CASE, revision: REVISION },
      { run: RUN, revision: REVISION },
    ]) {
      expect(await fetchSection("report", query)).toEqual({ kind: "unavailable" });
    }
    expect(spy).not.toHaveBeenCalled();
    for (let index = 0; index < 3; index += 1) {
      expect(await fetchSection("report", { case: CASE, run: RUN, revision: REVISION })).toEqual({
        kind: "error",
        refusal: { code: "WIRE_IDENTITY_MISMATCH", clears: expect.any(String) },
      });
    }
    expect(parseReportDocument(v1Report()).body.revision_id).toBe(REVISION);
  });

  test("Committee requires and binds exact case/run/revision including its receipt", async () => {
    const mismatches = [
      v1Committee({ caseId: OTHER_CASE }),
      v1Committee({ runId: OTHER_CASE }),
      v1Committee({ revisionId: OTHER_CASE }),
      v1Committee({ receiptRevisionId: OTHER_CASE }),
    ];
    const spy = vi.fn(async () => new Response(JSON.stringify(mismatches.shift())));
    vi.stubGlobal("fetch", spy);
    for (const query of [
      { case: CASE, run: RUN },
      { case: CASE, revision: REVISION },
      { run: RUN, revision: REVISION },
    ]) {
      expect(await fetchSection("committee", query)).toEqual({ kind: "unavailable" });
    }
    expect(spy).not.toHaveBeenCalled();
    for (let index = 0; index < 4; index += 1) {
      expect(await fetchSection("committee", { case: CASE, run: RUN, revision: REVISION })).toEqual(
        {
          kind: "error",
          refusal: { code: "WIRE_IDENTITY_MISMATCH", clears: expect.any(String) },
        },
      );
    }
    expect(parseCommitteeDocument(v1Committee()).body.receipt?.revision_id).toBe(REVISION);
  });

  test("the rail preserves an exact Report or Committee selection for every section", () => {
    render(
      createElement(
        MemoryRouter,
        null,
        createElement(Rail, {
          section: "committee",
          entries: null,
          local: null,
          servedRole: null,
          searchFor: () => `?case=${CASE}&run=${RUN}&revision=${REVISION}`,
        }),
      ),
    );
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toContain(`case=${CASE}&run=${RUN}&revision=${REVISION}`);
    }
  });

  test("test_served_role_is_displayed_and_enables_nothing", () => {
    const reader = parseUploadDocument(v1Upload({ global_role: "READER", standing: "READER" }));
    const admin = parseUploadDocument(v1Upload({ global_role: "ADMIN", standing: "APPROVER" }));
    const asReader = composeChrome("upload", reader);
    const asAdmin = composeChrome("upload", admin);
    // The served role is the only thing that differs, and no action is offered.
    expect({ ...asAdmin, served_role: null }).toEqual({ ...asReader, served_role: null });
    expect(asAdmin.ribbon.actions).toEqual([]);
    expect(asAdmin.served_role).toEqual({ role: "ADMIN", standing: "APPROVER" });
    expect(asAdmin.subject).toEqual({ case_id: CASE, issuer: "Acme" });

    render(
      createElement(
        MemoryRouter,
        null,
        createElement(Rail, {
          section: "upload",
          entries: asAdmin.rail,
          local: null,
          servedRole: asAdmin.served_role,
          searchFor: () => "",
        }),
      ),
    );
    const role = screen.getByText(/ADMIN · APPROVER/).closest("[data-served-role]");
    expect(role).not.toBeNull();
    expect(role!.querySelector("button, a, select, input")).toBeNull();

    // A directory served with no case standing still shows its role, and nothing more.
    const none = composeChrome(
      "upload",
      parseUploadDocument(v1Upload({ global_role: "ANALYST", standing: null })),
    );
    expect(none.served_role).toEqual({ role: "ANALYST", standing: null });
    expect(none.ribbon.actions).toEqual([]);
  });

  test("a composed chrome serves every enabled section on the rail, and no other", () => {
    const chrome = composeChrome(
      "upload",
      parseUploadDocument(v1Upload({ global_role: "READER", standing: "READER" })),
    );
    const served = chrome.rail.filter((entry) => entry.state === "Served").map((e) => e.section);
    expect(served).toEqual([...ENABLED_SECTIONS]);
    expect(chrome.rail.map((entry) => entry.section).sort()).toEqual([...SECTIONS].sort());
    for (const entry of chrome.rail) expect(entry.count).toBeNull();
  });

  test("the rail marks every disabled section unavailable", () => {
    const entries = markDisabled([{ section: "run", count: 2, state: "RUNNING" }]);
    expect(entries.find((entry) => entry.section === "run")).toEqual({
      section: "run",
      count: 2,
      state: "RUNNING",
    });
    for (const section of DISABLED) {
      expect(entries.find((entry) => entry.section === section)).toEqual({
        section,
        count: null,
        state: "Unavailable",
      });
    }
  });

  test("test_no_cast_of_parsed_json_in_transport_or_wire_v1", () => {
    const code = readFileSync(resolve(process.cwd(), "src/app/transport.ts"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "")
      .replace(/^import\s[^;]*;/gm, "");
    expect(code.length).toBeGreaterThan(500);
    expect(code.match(/\bas\s+(?!const\b)[A-Za-z_{[(]/g) ?? []).toEqual([]);
    expect(code).not.toMatch(/<\s*[A-Z]\w*\s*>\s*(JSON|value|body)/);
  });

  // Every enabled section reads the v1 wire unconditionally since slice
  // 4.1j; there is no marker left to mock, so this is `fetchSection` on the
  // one path it now has, not a variant of it.
  test("a v1 document is validated whole and bound to the requested case", async () => {
    const served = [
      v1Upload({ global_role: "ANALYST", standing: "WRITER" }),
      { ...v1Upload({ global_role: "ANALYST", standing: "WRITER" }), widget: 1 },
      v1Upload({ global_role: "ANALYST", standing: "WRITER" }, OTHER_CASE),
      { ...v1Upload({ global_role: "ANALYST", standing: "WRITER" }), observed_empty: true },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(served.shift()))),
    );
    expect(await fetchSection("upload", { case: CASE })).toMatchObject({
      kind: "ready",
      document: { body: { case_id: CASE } },
    });
    expect(await fetchSection("upload", { case: CASE })).toEqual({
      kind: "error",
      refusal: { code: "WIRE_SHAPE_INVALID", clears: expect.any(String) },
    });
    expect(await fetchSection("upload", { case: CASE })).toEqual({
      kind: "error",
      refusal: { code: "WIRE_IDENTITY_MISMATCH", clears: expect.any(String) },
    });
    expect(await fetchSection("upload", { case: CASE })).toMatchObject({
      kind: "observed-empty",
      observed_at: AT,
    });
  });

  test("test_no_dual_wire_marker_remains", () => {
    // Task 4.1 is not accepted while `keysMatch` or a legacy marker exists
    // (brief 4.1, Waves). Slice 4.1j retired both: `wire/keys.ts`, the
    // per-section `sections/<s>/wire.ts` markers and the legacy branch in
    // `transport.ts` this file used to exercise.
    const sources = [
      "src/app/transport.ts",
      "src/app/Workspace.tsx",
      "src/app/views.tsx",
      "src/wire/index.ts",
    ].map((path) => readFileSync(resolve(process.cwd(), path), "utf8"));
    for (const code of sources) {
      expect(code).not.toMatch(/keysMatch|WIRE_KEYS_MISMATCH|isLegacyDocument/);
      expect(code).not.toMatch(/sections\/[a-z]+\/wire["']/);
    }
    expect(existsSync(resolve(process.cwd(), "src/wire/keys.ts"))).toBe(false);
    for (const section of ["directory", "upload", "run", "analysis"]) {
      expect(existsSync(resolve(process.cwd(), `src/sections/${section}/wire.ts`))).toBe(false);
      expect(existsSync(resolve(process.cwd(), `src/wire/${section}.ts`))).toBe(false);
    }
  });
});
