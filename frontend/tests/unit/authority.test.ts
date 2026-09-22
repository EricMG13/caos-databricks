import { readFileSync } from "node:fs";
import {
  INITIAL,
  REFETCHES,
  accepts,
  analyticalIdentity,
  bind,
  displayedRunIdOf,
  issue,
  navigate,
  refetches,
  release,
  ticket,
  withWithdrawals,
  withdrawalsOf,
} from "@/app/authority";
import {
  parseAnalysisDocument,
  parseModelDocument,
  parseReportDocument,
  parseRunSectionDocument,
} from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

describe("the authority machine", () => {
  test("test_route_replay_discards_late_response_for_left_case", () => {
    const left = navigate(INITIAL, "CASE-2026-CVNA01");
    const sentForLeft = ticket(left);
    const current = navigate(left, "CASE-2026-HTZ02");
    // The response for the case the user left arrives after they moved on.
    expect(accepts(current, sentForLeft)).toBe(false);
    expect(accepts(current, ticket(current))).toBe(true);
    // A back navigation is a new seq: the earlier ticket is still late.
    const back = navigate(current, "CASE-2026-CVNA01");
    expect(accepts(back, sentForLeft)).toBe(false);
  });

  test("a later request for the same case supersedes an earlier one", () => {
    const first = issue(navigate(INITIAL, "CASE-2026-CVNA01"));
    const sentFirst = ticket(first);
    const second = issue(first);
    // The first response arrives after the second was issued: late, discarded.
    expect(accepts(second, sentFirst)).toBe(false);
    expect(accepts(second, ticket(second))).toBe(true);
  });

  test("a response for the same case under an earlier seq is late", () => {
    const first = navigate(INITIAL, "CASE-2026-CVNA01");
    const again = navigate(first, "CASE-2026-CVNA01");
    expect(accepts(again, ticket(first))).toBe(false);
  });

  test("test_book_binds_one_snapshot_per_compared_case", () => {
    const left = bind(INITIAL, "CASE-2026-CVNA01", "snp_cvna_q2_2026");
    expect(left.refusal).toBeNull();
    const right = bind(left.authority, "CASE-2026-CHTR03", "snp_chtr_q2_2026");
    expect(right.refusal).toBeNull();
    // A late response carrying a different snapshot for either case is refused.
    const lateLeft = bind(right.authority, "CASE-2026-CVNA01", "snp_cvna_q1_2026");
    expect(lateLeft.refusal?.code).toBe("SNAPSHOT_MISMATCH");
    expect(lateLeft.authority.bound["CASE-2026-CVNA01"]).toBe("snp_cvna_q2_2026");
    const lateRight = bind(right.authority, "CASE-2026-CHTR03", "snp_chtr_q1_2026");
    expect(lateRight.refusal?.code).toBe("SNAPSHOT_MISMATCH");
    // The same snapshot again is not a second identity.
    expect(bind(right.authority, "CASE-2026-CVNA01", "snp_cvna_q2_2026").refusal).toBeNull();
  });

  test("a binding moves only through an explicit release", () => {
    const held = bind(INITIAL, "CASE-2026-CVNA01", "snp_cvna_q2_2026").authority;
    const moved = bind(release(held, "CASE-2026-CVNA01"), "CASE-2026-CVNA01", "snp_cvna_q3_2026");
    expect(moved.refusal).toBeNull();
    expect(moved.authority.bound["CASE-2026-CVNA01"]).toBe("snp_cvna_q3_2026");
  });
});

describe("what a name refetches and what a view is", () => {
  const analysis = parseAnalysisDocument(load("../../fixtures/analysis.json"));
  const run = parseRunSectionDocument(load("../../fixtures/run/frames/1.json"));
  const model = parseModelDocument({
    chrome: {
      subject: { case_id: "00000000-0000-4000-8000-000000000001", title: "Issuer" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body: {
      case_id: "00000000-0000-4000-8000-000000000001",
      latest_run_id: "00000000-0000-4000-8000-0000000000a1",
      displayed_run_id: "00000000-0000-4000-8000-0000000000a1",
      subject: null,
      displayed_run_status: "COMPLETE",
      blocked_by: null,
      forecast: null,
      unavailable_reason: "NO_ACCEPTED_FORECAST",
    },
    observed_at: "2026-09-14T10:00:00Z",
    observed_empty: false,
    status: "complete",
    notes: [],
  });
  const report = parseReportDocument({
    chrome: {
      subject: { case_id: "00000000-0000-4000-8000-000000000001", title: "Issuer" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body: {
      case_id: "00000000-0000-4000-8000-000000000001",
      displayed_run_id: "00000000-0000-4000-8000-0000000000a1",
      revision_id: "00000000-0000-4000-8000-0000000000b2",
      payload_sha256: "a".repeat(64),
      case_title: "Issuer",
      artifacts: [],
      narrative: [],
    },
    observed_at: "2026-09-14T10:00:00Z",
    observed_empty: false,
    status: "complete",
    notes: [],
  });

  test("each event name refetches exactly the sections decision 2 names", () => {
    expect(REFETCHES).toEqual({
      run_progress: ["run"],
      handoff_accepted: ["run", "analysis", "model"],
      run_terminal: ["run", "analysis", "model"],
      sources_changed: ["upload", "run", "analysis", "model", "report", "committee"],
      runs_changed: ["run", "analysis", "model"],
      filing_changed: ["report", "committee"],
    });
    expect(refetches("run_progress", "analysis")).toBe(false);
    expect(refetches("sources_changed", "upload")).toBe(true);
    expect(refetches("runs_changed", "directory")).toBe(false);
    expect(refetches("filing_changed", "committee")).toBe(true);
  });

  test("analytical identity is the run, or the run and its sorted records", () => {
    expect(analyticalIdentity("run", run)).toBe(run.body.run!.run_id);
    const records = analysis.body.handoffs.map((h) => h.record_sha256);
    const reordered = {
      ...analysis,
      body: { ...analysis.body, handoffs: [...analysis.body.handoffs].reverse() },
    };
    expect(analyticalIdentity("analysis", reordered)).toBe(
      analyticalIdentity("analysis", analysis),
    );
    expect(analyticalIdentity("analysis", analysis)).toBe(
      `${analysis.body.displayed_run_id}|${[...records].sort().join(",")}`,
    );
    expect(analyticalIdentity("directory", analysis)).toBeNull();
    expect(analyticalIdentity("upload", analysis)).toBeNull();
    expect(displayedRunIdOf("run", run)).toBe(run.body.run!.run_id);
    expect(displayedRunIdOf("analysis", analysis)).toBe(analysis.body.displayed_run_id);
    expect(displayedRunIdOf("model", model)).toBe(model.body.displayed_run_id);
    expect(displayedRunIdOf("report", report)).toBe(report.body.displayed_run_id);
    expect(analyticalIdentity("model", model)).toBe(
      `${model.body.displayed_run_id}|NO_ACCEPTED_FORECAST`,
    );
    expect(analyticalIdentity("report", report)).toBe(
      `${report.body.revision_id}|${report.body.payload_sha256}`,
    );
  });

  test("withdrawals overlay a document without touching its figures", () => {
    const fact = analysis.body.handoffs[0]!.source_facts[0]!;
    const latest = {
      ...analysis,
      body: {
        ...analysis.body,
        handoffs: analysis.body.handoffs.map((h, i) =>
          i === 0
            ? {
                ...h,
                confidence_score: 1,
                source_facts: h.source_facts.map((f) => ({
                  ...f,
                  withdrawn_at: "2026-09-10T00:00:00Z",
                })),
              }
            : h,
        ),
      },
    };
    const withdrawals = withdrawalsOf(latest);
    expect(withdrawals.get(fact.source_id)).toBe("2026-09-10T00:00:00Z");
    const shown = withWithdrawals(analysis, withdrawals);
    expect(shown.body.handoffs[0]!.source_facts[0]!.withdrawn_at).toBe("2026-09-10T00:00:00Z");
    expect(shown.body.handoffs[0]!.confidence_score).toBe(
      analysis.body.handoffs[0]!.confidence_score,
    );
    expect(withWithdrawals(run, withdrawals)).toBe(run);
  });
});
