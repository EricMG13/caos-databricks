// The browser half of the cross-language contract (brief 4.1, decisions 7 and
// 8): the DSL shapes in `@/wire/v1` normalise to exactly the committed backend
// schema, and the validators they produce refuse what the models refuse.
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { VisibleSnapshotContext, useVisibleSnapshot } from "@/app/snapshot";
import {
  EVENT_NAMES,
  V1_COMMAND_SHAPES,
  V1_SHAPES,
  WireIdentityError,
  WireShapeError,
  parse,
  parseAnalysisDocument,
  parseModelDocument,
  parseReportDocument,
  parseCommitteeDocument,
  parseCaseCreated,
  parseDirectoryDocument,
  parseGateApproved,
  parseGatePreviewDocument,
  parsePageDocument,
  parseQualificationRead,
  parseRefusalBody,
  parseRunCreated,
  parseRunInputPinned,
  parseRunSectionDocument,
  parseRunWork,
  parseSourcesAdmitted,
  parseUploadDocument,
  requireIdentity,
  requirePageIdentity,
} from "@/wire/v1";

const V1_DIR = resolve(process.cwd(), "src/wire/v1");
const CASE = "3f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const OTHER_CASE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const RUN = "7e6d5c4b-3a29-4817-a6f5-e4d3c2b1a098";
const OTHER_RUN = "11111111-2222-4333-8444-555555555555";
const AT = "2026-09-14T10:00:00.123456Z";
const SHA = "a".repeat(64);
const SOURCE = "216ec234-c70c-4a5f-8ae6-f4a0262bbe84";

test("Report and Committee bind case/run/revision and exact receipt identity", () => {
  const body = {
    case_id: CASE,
    displayed_run_id: RUN,
    revision_id: SOURCE,
    payload_sha256: SHA,
    case_title: "Issuer",
    artifacts: [],
    narrative: [[{ text: "<script>plain text</script>", figure: null }]],
  };
  const expected = { caseId: CASE, runId: RUN, revisionId: SOURCE };
  const report = parseReportDocument(envelope(body, { case_id: CASE, title: "Issuer" }));
  expect(report.body.narrative).toEqual(body.narrative);
  const filed = {
    ...body,
    state: "filed",
    signed_by: [CASE],
    frozen_by: RUN,
    filed_by: SOURCE,
    receipt: {
      case_id: CASE,
      run_id: RUN,
      revision_id: SOURCE,
      payload_sha256: SHA,
      signed_by: CASE,
      frozen_by: RUN,
      filed_by: SOURCE,
      renderer_sha256: SHA,
      filed_event_sha256: SHA,
    },
  };
  const committee = parseCommitteeDocument(envelope(filed, { case_id: CASE, title: "Issuer" }));
  for (const doc of [report, committee]) {
    expect(() => requireIdentity(doc, expected)).not.toThrow();
    for (const changed of [
      { caseId: OTHER_CASE },
      { runId: OTHER_RUN },
      { revisionId: OTHER_RUN },
    ]) {
      expect(() => requireIdentity(doc, { ...expected, ...changed })).toThrow(WireIdentityError);
    }
  }
  const wrong = parseCommitteeDocument(
    envelope(
      { ...filed, receipt: { ...filed.receipt, revision_id: OTHER_RUN } },
      { case_id: CASE, title: "Issuer" },
    ),
  );
  expect(() => requireIdentity(wrong, expected)).toThrow(WireIdentityError);
  for (const invalid of [
    { ...filed, state: "frozen", filed_by: null },
    { ...filed, state: "frozen", receipt: null },
    { ...filed, receipt: null },
    { ...filed, filed_by: null },
    { ...filed, receipt: { ...filed.receipt, frozen_by: OTHER_RUN } },
    { ...filed, receipt: { ...filed.receipt, filed_by: OTHER_RUN } },
    { ...filed, receipt: { ...filed.receipt, signed_by: OTHER_RUN } },
  ]) {
    expect(() =>
      requireIdentity(
        parseCommitteeDocument(envelope(invalid, { case_id: CASE, title: "Issuer" })),
        expected,
      ),
    ).toThrow(WireIdentityError);
  }
  expect(() =>
    parseReportDocument(envelope({ ...body, html: "unsafe" }, { case_id: CASE, title: "Issuer" })),
  ).toThrow(WireShapeError);
  expect(() =>
    parse(V1_SHAPES.NarrativeFigure, {
      route_node_id: "CP-0",
      citation_index: -1,
      document_sha256: SHA,
      page: 1,
      matched_text: "figure",
    }),
  ).toThrow(WireShapeError);
});

test("Model is closed and binds the displayed run independently of latest", () => {
  const document = {
    chrome: {
      subject: { case_id: CASE, title: "Issuer" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body: {
      case_id: CASE,
      latest_run_id: OTHER_RUN,
      displayed_run_id: RUN,
      subject: null,
      displayed_run_status: "COMPLETE",
      blocked_by: null,
      forecast: null,
      unavailable_reason: "NO_ACCEPTED_FORECAST",
    },
    observed_at: AT,
    observed_empty: true,
    status: "partial",
    notes: [],
  };
  const parsed = parseModelDocument(document);
  expect(() => requireIdentity(parsed, { caseId: CASE, runId: RUN })).not.toThrow();
  expect(() => requireIdentity(parsed, { caseId: CASE, runId: OTHER_RUN })).toThrow(
    WireIdentityError,
  );
  expect(() => requireIdentity(parsed, { caseId: OTHER_CASE, runId: RUN })).toThrow(
    WireIdentityError,
  );
  expect(() => parseModelDocument({ ...document, arbitrary: "payload" })).toThrow(WireShapeError);
  expect(() =>
    parseModelDocument({ ...document, body: { ...document.body, unavailable_reason: "fixture" } }),
  ).toThrow(WireShapeError);
  const ratio = {
    name: "metrics.interest_coverage",
    value: null,
    unavailable_reason: "ZERO_OR_NEGATIVE_DENOMINATOR",
  };
  expect(parse(V1_SHAPES.ModelValue, ratio)).toEqual(ratio);
  expect(() => parse(V1_SHAPES.ModelValue, { ...ratio, value: 6 })).toThrow(WireShapeError);
  expect(() => parse(V1_SHAPES.ModelValue, { ...ratio, value: "NaN" })).toThrow(WireShapeError);
});

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

// The subset both sides are compared on: `$ref` resolved, pydantic's
// `anyOf: [X, {type: null}]` read as nullability, title/description/default
// dropped. Any other keyword is refused so neither side can drift past it.
const KEPT = new Set([
  "type",
  "properties",
  "required",
  "enum",
  "const",
  "maxLength",
  "maxItems",
  "pattern",
  "format",
  "items",
  "additionalProperties",
  "minimum",
  "maximum",
]);
const IGNORED = new Set(["title", "description", "default"]);

function normalise(node: Json, defs: Record<string, Json>): Json {
  if (node === null || typeof node !== "object" || Array.isArray(node)) {
    throw new Error("schema node is not an object");
  }
  const ref = node["$ref"];
  if (typeof ref === "string") {
    const target = defs[ref.replace("#/$defs/", "")];
    if (target === undefined) throw new Error(`unresolved ${ref}`);
    return normalise(target, defs);
  }
  const anyOf = node["anyOf"];
  if (Array.isArray(anyOf)) {
    const others = anyOf.filter(
      (member) =>
        !(member !== null && typeof member === "object" && !Array.isArray(member)) ||
        member["type"] !== "null",
    );
    const inner = others[0];
    if (anyOf.length !== 2 || others.length !== 1 || inner === undefined) {
      throw new Error("anyOf other than nullability");
    }
    return { nullable: normalise(inner, defs) };
  }
  const out: { [key: string]: Json } = {};
  for (const [key, value] of Object.entries(node)) {
    if (IGNORED.has(key)) continue;
    if (!KEPT.has(key)) throw new Error(`keyword outside the subset: ${key}`);
    if (key === "properties") {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("properties is not an object");
      }
      const props: { [key: string]: Json } = {};
      for (const name of Object.keys(value).sort()) props[name] = normalise(value[name]!, defs);
      out[key] = props;
    } else if (key === "items") {
      out[key] = normalise(value, defs);
    } else if (key === "required" && Array.isArray(value)) {
      out[key] = [...value].sort();
    } else {
      out[key] = value;
    }
  }
  return out;
}

function committed(): Record<string, Json> {
  const parsed: { $defs: Record<string, Json> } = JSON.parse(
    readFileSync(resolve(V1_DIR, "schema.json"), "utf8"),
  );
  return parsed.$defs;
}

function envelope(body: Json, subject: Json): { [key: string]: Json } {
  return {
    chrome: {
      subject,
      served_role: { global_role: "ANALYST", standing: "READER" },
      actions: [
        { action: "START_RUN", refusal: null },
        { action: "RETRY_RUN", refusal: { code: "RUN_NOT_STOPPED", clears: "x" } },
      ],
    },
    body,
    observed_at: AT,
    observed_empty: false,
    status: "complete",
    notes: [],
  };
}

const SUBJECT = { case_id: CASE, title: "Acme" };
const RUN_SUMMARY = {
  run_id: RUN,
  status: "COMPLETE",
  created_at: AT,
  profile_id: "LITE",
  selection_id: null,
};

function directory(): { [key: string]: Json } {
  return envelope(
    {
      cases: [
        {
          case_id: CASE,
          title: "Acme",
          created_at: AT,
          standing: "WRITER",
          live_sources: 2,
          latest_run: RUN_SUMMARY,
          members: null,
          actions: [
            { action: "GRANT_STANDING", refusal: null },
            { action: "REVOKE_STANDING", refusal: null },
          ],
        },
      ],
    },
    null,
  );
}

function upload(): { [key: string]: Json } {
  return envelope(
    {
      case_id: CASE,
      sources: [
        {
          source_id: RUN,
          filename: "10-K.pdf",
          document_sha256: SHA,
          admitted_at: AT,
          withdrawn_at: null,
          extractor_identity: null,
          set_versions: [1],
        },
      ],
      set_versions: [{ version: 1, fingerprint: SHA, member_count: 1 }],
    },
    SUBJECT,
  );
}

function runSection(): { [key: string]: Json } {
  return envelope(
    {
      case_id: CASE,
      latest_run_id: RUN,
      displayed_run_id: RUN,
      runs: [RUN_SUMMARY],
      run: {
        run_id: RUN,
        status: "BLOCKED",
        created_at: AT,
        route_digest: SHA,
        build_id: null,
        source_set_version: 1,
        subject: null,
        gates: [{ gate: "SOURCE_SET", state: "RELEASED" }],
        nodes: [
          {
            route_node_id: "CP-5",
            module_id: "CP-5",
            stage: 2,
            state: "BLOCKED",
            waiting_on: [{ source: "CP-0", type: "REQUIRED" }],
            awaiting_gate: false,
            gate_verdict: null,
            gate_reason: null,
          },
        ],
        attempts: [
          { attempt_id: RUN, route_node_id: "CP-0", ordinal: 1, started_at: AT, accepted: true },
        ],
        work: { state: "STOPPED", stop_code: "PROVIDER_UNAVAILABLE", cancel_requested: false },
        blocked_by: { route_node_id: "CP-5", module_id: "CP-5", attempt_id: RUN },
        supersedes: null,
        superseded_by: null,
      },
      route_choices: [
        {
          profile_id: "LITE_CREDIT_22",
          selection_id: "LITE_EARNINGS_UPDATE",
          accepts_model_extension: false,
        },
      ],
    },
    SUBJECT,
  );
}

function analysis(): { [key: string]: Json } {
  return envelope(
    {
      case_id: CASE,
      latest_run_id: RUN,
      displayed_run_id: RUN,
      subject: {
        issuer_id: "ACME",
        issuer_name: "Acme",
        reporting_period: "FY2025",
        analysis_date: "2026-09-14",
      },
      displayed_run_status: "COMPLETE",
      blocked_by: null,
      handoffs: [
        {
          route_node_id: "CP-0",
          module_id: "CP-0",
          artifact_sha256: SHA,
          record_sha256: SHA,
          accepted_at: AT,
          qa_status: "Passed",
          committee_status: "Committee Ready",
          confidence_score: 80,
          confidence_band: "HIGH",
          limitation_flags: [],
          validation_warnings: [],
          decision_scope: "SCREENING_ONLY",
          screening_only: true,
          source_facts: [
            {
              document_sha256: SHA,
              source_id: SOURCE,
              filename: "10-K.pdf",
              page: 3,
              matched_text: "net leverage",
              rects: [{ x0: 1, y0: 2.5, x1: 3, y1: 4 }],
              withdrawn_at: null,
            },
          ],
          model_analysis: "# CP-0",
          host_calculation: "NONE",
        },
      ],
      pending: [],
    },
    SUBJECT,
  );
}

function page(): { [key: string]: Json } {
  return {
    body: {
      case_id: CASE,
      run_id: RUN,
      source_id: SOURCE,
      document_sha256: SHA,
      page: 3,
      frame: { x0: 0, y0: 0, x1: 612, y1: 792, y_axis: "down" },
      lines: [{ text: "net leverage", x0: 1, y0: 2, x1: 3, y1: 4 }],
    },
    observed_at: AT,
    status: "complete",
    notes: [],
  };
}

function refuses(parse: () => unknown, path?: string): void {
  let caught: unknown;
  try {
    parse();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(WireShapeError);
  if (caught instanceof WireShapeError) {
    expect(caught.code).toBe("WIRE_SHAPE_INVALID");
    if (path !== undefined) expect(caught.path).toBe(path);
  }
}

describe("the v1 wire contract", () => {
  test("test_parseQualificationRead_refuses_undeclared_or_unbound_fields", () => {
    const current = {
      evidence_sha256: SHA,
      state: "QUALIFIED",
      qualification_set_sha256: "b".repeat(64),
      performed_sha256: "c".repeat(64),
      build_id: "build",
      adapter_version: "adapter",
      provider: "openrouter",
      model: "model",
      reviewer: "Reviewer",
      decided_at: AT,
      expires_at: "2026-09-16T10:00:00Z",
    };
    expect(parseQualificationRead(current).state).toBe("QUALIFIED");
    refuses(() => parseQualificationRead({ ...current, extra: true }), "$");
    refuses(
      () => parseQualificationRead({ ...current, evidence_sha256: "bad" }),
      "$.evidence_sha256",
    );
  });

  test("test_v1_shapes_equal_the_committed_backend_schema", () => {
    const defs = committed();
    const all = { ...V1_SHAPES, ...V1_COMMAND_SHAPES };
    expect(Object.keys(all)).toHaveLength(
      Object.keys(V1_SHAPES).length + Object.keys(V1_COMMAND_SHAPES).length,
    );
    expect(Object.keys(all).sort()).toEqual(Object.keys(defs).sort());
    const shapes = new Map(Object.entries(all));
    for (const [name, definition] of Object.entries(defs)) {
      const shape = shapes.get(name);
      expect(shape, name).toBeDefined();
      expect(normalise(shape!.toSchema(), defs), name).toEqual(normalise(definition, defs));
    }
  });

  test("test_command_shapes_equal_the_committed_schema", () => {
    const defs = committed();
    const commands = [
      "CreateCase",
      "CaseCreated",
      "SourcesAdmitted",
      "CreateRun",
      "RunCreated",
      "PinRunInput",
      "RunInputPinned",
      "GatePreviewDocument",
      "ApproveGate",
      "GateApproved",
      "StartRun",
      "RetryRun",
      "CancelRun",
      "RunWork",
      "SignVerdict",
      "VerdictRecorded",
      // Task 12.1's seven governed writes.
      "GrantStanding",
      "StandingGranted",
      "RevokeStanding",
      "StandingRevoked",
      "WithdrawSource",
      "SourceWithdrawn",
      "NarrativeFigureRef",
      "NarrativeDraft",
      "SaveRevision",
      "RevisionSaved",
      "SignOpinion",
      "OpinionSigned",
      "FreezeDeliverable",
      "DeliverableFrozen",
      "FileDeliverable",
      "DeliverableFiled",
    ];
    expect(Object.keys(V1_COMMAND_SHAPES).sort()).toEqual([...commands].sort());
    const shapes = new Map(Object.entries(V1_COMMAND_SHAPES));
    for (const name of commands) {
      const definition = defs[name];
      expect(definition, name).toBeDefined();
      expect(normalise(shapes.get(name)!.toSchema(), defs), name).toEqual(
        normalise(definition!, defs),
      );
    }
  });

  test("test_a_receipt_is_validated_not_cast", () => {
    const work = { state: "QUEUED", stop_code: null, cancel_requested: false };
    const preview = {
      run_id: RUN,
      gate: "SOURCE_SET",
      content: '{\n  "gate": "SOURCE_SET"\n}',
      preview_sha256: SHA,
      input_fingerprint: SHA,
      observed_at: AT,
    };
    expect(parseCaseCreated({ case_id: CASE }).case_id).toBe(CASE);
    expect(parseSourcesAdmitted({ case_id: CASE, source_ids: [RUN] }).source_ids).toEqual([RUN]);
    expect(parseRunCreated({ case_id: CASE, run_id: RUN, route_digest: SHA }).run_id).toBe(RUN);
    expect(
      parseRunInputPinned({ run_id: RUN, source_set_version: 1, input_fingerprint: SHA })
        .source_set_version,
    ).toBe(1);
    expect(parseGatePreviewDocument(preview).content).toBe(preview.content);
    expect(
      parseGateApproved({
        run_id: RUN,
        gate: "RESEARCH_PLAN",
        preview_sha256: SHA,
        input_fingerprint: SHA,
      }).gate,
    ).toBe("RESEARCH_PLAN");
    expect(parseRunWork({ run_id: RUN, run_status: "RUNNING", work }).work.state).toBe("QUEUED");

    // A receipt the server did not declare is refused, not trusted.
    refuses(() => parseCaseCreated({ case_id: CASE, standing: "ADMIN" }), "$");
    refuses(() => parseCaseCreated({}), "$");
    refuses(
      () =>
        parseSourcesAdmitted({ case_id: CASE, source_ids: Array.from({ length: 51 }, () => RUN) }),
      "$.source_ids",
    );
    refuses(
      () => parseRunCreated({ case_id: CASE, run_id: RUN, route_digest: "A".repeat(64) }),
      "$.route_digest",
    );
    refuses(() => parseGatePreviewDocument({ ...preview, gate: "source-set" }), "$.gate");
    refuses(() => parseGatePreviewDocument({ ...preview, content: 7 }), "$.content");
    refuses(
      () =>
        parseRunWork({ run_id: RUN, run_status: "RUNNING", work: { ...work, state: "PAUSED" } }),
      "$.work.state",
    );
    refuses(() => parseRunWork({ run_id: RUN, run_status: "RUNNING", work: null }), "$.work");
    refuses(
      () => parseRunInputPinned({ run_id: RUN, source_set_version: 1.5, input_fingerprint: SHA }),
      "$.source_set_version",
    );
    refuses(() => parseGateApproved({ run_id: RUN, gate: "SOURCE_SET", preview_sha256: SHA }), "$");
  });

  test("the valid documents parse", () => {
    expect(parseDirectoryDocument(directory()).body.cases).toHaveLength(1);
    expect(parseUploadDocument(upload()).body.case_id).toBe(CASE);
    expect(parseRunSectionDocument(runSection()).body.run?.status).toBe("BLOCKED");
    expect(parseRunSectionDocument(runSection()).body.run?.work?.state).toBe("STOPPED");
    expect(parseRunSectionDocument(runSection()).chrome.actions).toHaveLength(2);
    expect(parseAnalysisDocument(analysis()).body.handoffs[0]?.host_calculation).toBe("NONE");
    expect(parseRefusalBody({ code: "CASE_NOT_FOUND", clears: "x" }).code).toBe("CASE_NOT_FOUND");
  });

  test("test_an_undeclared_key_at_any_depth_is_refused", () => {
    const top = directory();
    top["extra"] = 1;
    refuses(() => parseDirectoryDocument(top), "$");

    const deep = analysis();
    const fact = JSON.parse(JSON.stringify(deep));
    fact.body.handoffs[0].source_facts[0].rects[0].bbox = [0, 0, 1, 1];
    refuses(() => parseAnalysisDocument(fact), "$.body.handoffs[0].source_facts[0].rects[0]");

    const chrome = JSON.parse(JSON.stringify(runSection()));
    chrome.chrome.served_role.enables = ["approve"];
    refuses(() => parseRunSectionDocument(chrome), "$.chrome.served_role");

    const action = JSON.parse(JSON.stringify(runSection()));
    action.chrome.actions[0].enabled = true;
    refuses(() => parseRunSectionDocument(action), "$.chrome.actions[0]");
    const unknown = JSON.parse(JSON.stringify(runSection()));
    unknown.chrome.actions[0].action = "SIGN";
    refuses(() => parseRunSectionDocument(unknown), "$.chrome.actions[0].action");

    const proto = JSON.parse('{"code":"CASE_NOT_FOUND","clears":"x","__proto__":{}}');
    refuses(() => parseRefusalBody(proto), "$");
  });

  test("test_a_missing_mistyped_or_over_bound_field_is_refused", () => {
    const missing = JSON.parse(JSON.stringify(runSection()));
    delete missing.body.run.nodes[0].gate_verdict;
    refuses(() => parseRunSectionDocument(missing), "$.body.run.nodes[0]");

    const mistyped = JSON.parse(JSON.stringify(upload()));
    mistyped.body.sources[0].set_versions = ["1"];
    refuses(() => parseUploadDocument(mistyped), "$.body.sources[0].set_versions[0]");

    const float = JSON.parse(JSON.stringify(analysis()));
    float.body.handoffs[0].confidence_score = 80.5;
    refuses(() => parseAnalysisDocument(float), "$.body.handoffs[0].confidence_score");

    const long = JSON.parse(JSON.stringify(directory()));
    long.body.cases[0].title = "x".repeat(4097);
    refuses(() => parseDirectoryDocument(long), "$.body.cases[0].title");

    const many = JSON.parse(JSON.stringify(directory()));
    many.body.cases = Array.from({ length: 201 }, () => many.body.cases[0]);
    refuses(() => parseDirectoryDocument(many), "$.body.cases");

    const hash = JSON.parse(JSON.stringify(upload()));
    hash.body.sources[0].document_sha256 = "A".repeat(64);
    refuses(() => parseUploadDocument(hash), "$.body.sources[0].document_sha256");

    const naive = JSON.parse(JSON.stringify(upload()));
    naive.observed_at = "2026-09-14T10:00:00";
    refuses(() => parseUploadDocument(naive), "$.observed_at");

    const impossible = JSON.parse(JSON.stringify(upload()));
    impossible.observed_at = "2026-02-30T10:00:00Z";
    refuses(() => parseUploadDocument(impossible), "$.observed_at");

    const uuid = JSON.parse(JSON.stringify(upload()));
    uuid.body.case_id = "not-a-uuid";
    refuses(() => parseUploadDocument(uuid), "$.body.case_id");

    const status = JSON.parse(JSON.stringify(directory()));
    status.status = "degraded";
    refuses(() => parseDirectoryDocument(status), "$.status");

    const calc = JSON.parse(JSON.stringify(analysis()));
    calc.body.handoffs[0].host_calculation = "DSCR";
    refuses(() => parseAnalysisDocument(calc), "$.body.handoffs[0].host_calculation");

    const nulled = JSON.parse(JSON.stringify(analysis()));
    nulled.body.case_id = null;
    refuses(() => parseAnalysisDocument(nulled), "$.body.case_id");

    refuses(() => parseDirectoryDocument([]), "$");
    refuses(() => parseDirectoryDocument(null), "$");
  });

  test("a shape refusal carries the path and never the offending value", () => {
    const secret = JSON.parse(JSON.stringify(directory()));
    secret.body.cases[0].title = `LEAK${"x".repeat(5000)}`;
    try {
      parseDirectoryDocument(secret);
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(WireShapeError);
      expect(String(error)).not.toContain("LEAK");
      expect(JSON.stringify(error)).not.toContain("LEAK");
    }
  });

  test("test_a_document_for_another_case_or_run_is_refused", () => {
    const run = parseRunSectionDocument(runSection());
    expect(() => requireIdentity(run, { caseId: CASE, runId: RUN })).not.toThrow();
    expect(() => requireIdentity(run, { caseId: CASE.toUpperCase(), runId: RUN })).not.toThrow();

    for (const expected of [
      { caseId: OTHER_CASE, runId: RUN },
      { caseId: CASE, runId: OTHER_RUN },
      { caseId: null },
    ]) {
      let caught: unknown;
      try {
        requireIdentity(run, expected);
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(WireIdentityError);
      expect(caught instanceof WireIdentityError && caught.code).toBe("WIRE_IDENTITY_MISMATCH");
    }

    const body = JSON.parse(JSON.stringify(analysis()));
    body.body.case_id = OTHER_CASE;
    const split = parseAnalysisDocument(body);
    expect(() => requireIdentity(split, { caseId: CASE })).toThrow(WireIdentityError);

    const up = parseUploadDocument(upload());
    expect(() => requireIdentity(up, { caseId: OTHER_CASE })).toThrow(WireIdentityError);
    const dir = parseDirectoryDocument(directory());
    expect(() => requireIdentity(dir, { caseId: null })).not.toThrow();
    expect(() => requireIdentity(dir, { caseId: CASE })).toThrow(WireIdentityError);
  });

  test("test_event_names_equal_the_committed_backend_schema", () => {
    const defs = committed();
    expect(defs["EventName"]).toEqual({ type: "string", enum: [...EVENT_NAMES] });
    expect([...EVENT_NAMES]).toEqual([
      "run_progress",
      "handoff_accepted",
      "run_terminal",
      "sources_changed",
      "runs_changed",
      "filing_changed",
    ]);
  });

  test("test_a_nested_null_where_a_list_is_declared_is_refused", () => {
    // R4 (F10), restated for v1 lists. A guard: the closed DSL already refuses
    // it, and this pins that a null never reaches a render as an empty list.
    const facts = JSON.parse(JSON.stringify(analysis()));
    facts.body.handoffs[0].source_facts = null;
    refuses(() => parseAnalysisDocument(facts), "$.body.handoffs[0].source_facts");
    const rects = JSON.parse(JSON.stringify(analysis()));
    rects.body.handoffs[0].source_facts[0].rects = null;
    refuses(() => parseAnalysisDocument(rects), "$.body.handoffs[0].source_facts[0].rects");
    const nodes = JSON.parse(JSON.stringify(runSection()));
    nodes.body.run.nodes[0].waiting_on = null;
    refuses(() => parseRunSectionDocument(nodes), "$.body.run.nodes[0].waiting_on");
    const lines = JSON.parse(JSON.stringify(page()));
    lines.body.lines = null;
    refuses(() => parsePageDocument(lines), "$.body.lines");
    const notes = JSON.parse(JSON.stringify(upload()));
    notes.notes = null;
    refuses(() => parseUploadDocument(notes), "$.notes");
  });

  test("test_a_page_document_is_validated_and_bound_to_its_request", () => {
    const doc = parsePageDocument(page());
    expect(doc.body.frame.y_axis).toBe("down");
    const expected = { caseId: CASE, runId: RUN, sourceId: SOURCE, page: 3 };
    expect(() => requirePageIdentity(doc, expected)).not.toThrow();
    expect(() =>
      requirePageIdentity(doc, { ...expected, sourceId: SOURCE.toUpperCase() }),
    ).not.toThrow();
    for (const moved of [
      { caseId: OTHER_CASE },
      { runId: OTHER_RUN },
      { sourceId: OTHER_RUN },
      { page: 4 },
    ]) {
      expect(() => requirePageIdentity(doc, { ...expected, ...moved })).toThrow(WireIdentityError);
    }

    const zero = JSON.parse(JSON.stringify(page()));
    zero.body.page = 0;
    refuses(() => parsePageDocument(zero), "$.body.page");
    const axis = JSON.parse(JSON.stringify(page()));
    axis.body.frame.y_axis = "left";
    refuses(() => parsePageDocument(axis), "$.body.frame.y_axis");
    const many = JSON.parse(JSON.stringify(page()));
    many.body.lines = Array.from({ length: 2001 }, () => many.body.lines[0]);
    refuses(() => parsePageDocument(many), "$.body.lines");
    const chrome = JSON.parse(JSON.stringify(page()));
    chrome.chrome = null;
    refuses(() => parsePageDocument(chrome), "$");
    const unsourced = JSON.parse(JSON.stringify(analysis()));
    delete unsourced.body.handoffs[0].source_facts[0].source_id;
    refuses(() => parseAnalysisDocument(unsourced), "$.body.handoffs[0].source_facts[0]");
  });

  test("the visible snapshot is null without a provider and the provided one within", () => {
    expect(renderHook(() => useVisibleSnapshot()).result.current).toBeNull();
    const snapshot = {
      key: `analysis|${CASE}|${RUN}`,
      caseId: CASE,
      displayedRunId: RUN,
      document: parseAnalysisDocument(analysis()),
      withdrawals: new Map([[SOURCE, AT]]),
    };
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(VisibleSnapshotContext.Provider, { value: snapshot }, children);
    expect(renderHook(() => useVisibleSnapshot(), { wrapper }).result.current).toBe(snapshot);
  });

  test("test_a_legacy_refusal_body_is_response_invalid", () => {
    refuses(() => parseRefusalBody({ refusal: { code: "CASE_NOT_FOUND" } }), "$");
    refuses(() => parseRefusalBody({ refusal: "CASE_NOT_FOUND" }), "$");
    refuses(() => parseRefusalBody({ code: "SOMETHING_INVENTED", clears: "x" }), "$.code");
    refuses(() => parseRefusalBody({ code: "CASE_NOT_FOUND" }), "$");
  });

  test("test_no_cast_of_parsed_json_in_transport_or_wire_v1", () => {
    // `frontend/src/app/transport.ts` still carries the legacy casts; slice
    // 4.1g rewrites it over these validators and adds it to this scan.
    const files = readdirSync(V1_DIR).filter((name) => name.endsWith(".ts"));
    expect(files.length).toBeGreaterThanOrEqual(3);
    for (const name of files) {
      const code = readFileSync(resolve(V1_DIR, name), "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "");
      const casts = code.match(/\bas\s+(?!const\b)[A-Za-z_{[(]/g) ?? [];
      expect(casts, name).toEqual([]);
      expect(code, name).not.toMatch(/<\s*[A-Z]\w*\s*>\s*(JSON|value|body)/);
    }
  });
});
