// The Run section's node reasons, recomputed from v1 wire fields (slice 4.1i).
import { blockedByOf, blockingOf, reasonOf, runningOf, stateWordOf } from "@/sections/run/reason";
import { severityOf } from "@/sections/run/RouteGraph";
describe("the reasons a node draws", () => {
  test("reasonOf names the gate's verdict first, then the typed edges; runningOf needs an unaccepted attempt", () => {
    const waiting = [{ source: "CP-L10", type: "ADVISORY" as const }];
    expect(
      reasonOf(
        { state: "BLOCKED", waiting_on: waiting, gate_verdict: null, awaiting_gate: false },
        "RUNNING",
      ),
    ).toBe("waits on ADVISORY CP-L10");
    expect(
      reasonOf(
        { state: "BLOCKED", waiting_on: [], gate_verdict: "NOT_READY", awaiting_gate: false },
        "RUNNING",
      ),
    ).toBe("NOT_READY");
    const node = { route_node_id: "N1", state: "RUNNABLE" as const };
    const attempt = {
      attempt_id: "a",
      route_node_id: "N1",
      ordinal: 1,
      started_at: "2026-09-14T10:00:00Z",
    };
    expect(runningOf(node, [{ ...attempt, accepted: false }], "RUNNING")).toBe(true);
    expect(runningOf(node, [{ ...attempt, accepted: true }], "RUNNING")).toBe(false);
  });

  // `node_states` is recomputed from accepted artifacts alone (invariant 10),
  // and a validated Blocked accepts nothing -- so the node whose verdict ended
  // the run comes back RUNNABLE with one unaccepted attempt, and the page drew
  // it pulsing "in the frontier" beside a Status of BLOCKED. The node states
  // are right; what was wrong was reading them without the run's own status.
  test("a node is not drawn running, nor said to be in the frontier, once the run has ended", () => {
    const node = { route_node_id: "N1", state: "RUNNABLE" as const };
    const unaccepted = [
      {
        attempt_id: "a",
        route_node_id: "N1",
        ordinal: 1,
        started_at: "2026-09-14T10:00:00Z",
        accepted: false,
      },
    ];
    for (const status of ["BLOCKED", "FAILED", "CANCELLED", "COMPLETE"] as const) {
      expect(runningOf(node, unaccepted, status)).toBe(false);
    }
    expect(runningOf(node, unaccepted, "RUNNING")).toBe(true);

    const runnable = {
      state: "RUNNABLE" as const,
      waiting_on: [{ source: "CP-0", type: "REQUIRED" as const }],
      gate_verdict: null,
      awaiting_gate: false,
    };
    expect(reasonOf(runnable, "RUNNING")).toBe("in the frontier · REQUIRED CP-0");
    expect(reasonOf(runnable, "BLOCKED")).toBe("did not run · REQUIRED CP-0");
    expect(reasonOf({ ...runnable, waiting_on: [] }, "BLOCKED")).toBe("did not run");
    // The real shape: the gate cleared CP-5, and the run ended before it ran.
    // "READY" on its own is what the page used to say beside a BLOCKED status,
    // which reads as the opposite of what happened. The verdict is kept, after
    // the fact that overrides it.
    const cleared = { ...runnable, waiting_on: [], gate_verdict: "READY" };
    expect(reasonOf(cleared, "RUNNING")).toBe("READY");
    expect(reasonOf(cleared, "BLOCKED")).toBe("did not run · READY");
    // An accepted node is still accepted: ending a run changes what is pending,
    // not what already happened.
    expect(reasonOf({ ...runnable, state: "COMPLETE" }, "BLOCKED")).toBe(
      "accepted · REQUIRED CP-0",
    );
  });

  // The wire names the node whose validated Blocked verdict ended the run
  // (`blocked_by`, §68). Its state is still RUNNABLE -- a Blocked verdict
  // accepts nothing -- so read without that field the node said "did not run",
  // the opposite of what happened. Nothing is inferred from an unaccepted
  // attempt: a node the run never reached holds one too.
  test("the node that answered Blocked is named as what ended the run, and no other node is", () => {
    const cp5 = {
      route_node_id: "N5",
      state: "RUNNABLE" as const,
      waiting_on: [],
      gate_verdict: "READY",
      awaiting_gate: false,
    };
    const blockedBy = { route_node_id: "N5", module_id: "CP-5", attempt_id: "a" };
    expect(blockingOf(cp5, blockedBy)).toBe(true);
    expect(blockingOf({ route_node_id: "N4" }, blockedBy)).toBe(false);
    expect(blockingOf(cp5, null)).toBe(false);

    expect(reasonOf(cp5, "BLOCKED", true)).toBe("answered Blocked · ended the run");
    expect(reasonOf(cp5, "BLOCKED", false)).toBe("did not run · READY");
    expect(severityOf(cp5, false, true)).toBe("CRITICAL");
    expect(severityOf(cp5, false, false)).toBe("IDLE");

    // The graph's state word says the same thing the detail does, and no
    // longer reads FRONTIER on a run that has ended.
    expect(stateWordOf(cp5, "BLOCKED", false, true)).toBe("RUNNABLE · BLOCKED THE RUN");
    expect(stateWordOf(cp5, "BLOCKED", false, false)).toBe("RUNNABLE · DID NOT RUN");
    expect(stateWordOf(cp5, "RUNNING", true, false)).toBe("RUNNABLE · RUNNING");
    expect(stateWordOf(cp5, "RUNNING", false, false)).toBe("RUNNABLE · FRONTIER");
    expect(stateWordOf({ state: "COMPLETE" }, "BLOCKED", false, false)).toBe("COMPLETE");

    // The run panel's line: the node, its verdict and the attempt on a run a
    // verdict ended; the route's own rule (§39) on one the frontier emptied;
    // nothing on a run that is not BLOCKED.
    const attempts = [
      {
        attempt_id: "a",
        route_node_id: "N5",
        ordinal: 1,
        started_at: "2026-09-14T10:00:00Z",
        accepted: false,
      },
    ];
    expect(blockedByOf({ status: "BLOCKED", blocked_by: blockedBy, attempts })).toBe(
      "CP-5 answered Blocked on attempt 1 · N5",
    );
    expect(blockedByOf({ status: "BLOCKED", blocked_by: blockedBy, attempts: [] })).toBe(
      "CP-5 answered Blocked on an unlisted attempt · N5",
    );
    expect(blockedByOf({ status: "BLOCKED", blocked_by: null, attempts: [] })).toBe(
      "no node's verdict — the frontier emptied with required work unfinished",
    );
    expect(blockedByOf({ status: "RUNNING", blocked_by: null, attempts })).toBeNull();
    expect(blockedByOf({ status: "COMPLETE", blocked_by: null, attempts })).toBeNull();
  });
});
