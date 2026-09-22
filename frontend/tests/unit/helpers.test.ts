// The pure helpers each section exports. Reached by import rather than by
// rendering, which is why `frontend/scripts/check-tested.mjs` asks for them by
// name and why the section-level tests beside this file did not cover them:
// rendering a section exercises a helper without ever naming it, so a helper
// that quietly returned the wrong thing would still leave the section green.
import { failureMessage } from "@/app/commands";
import { sectionPath } from "@/app/sections";
import { OFFLINE_WORDING, UNAVAILABLE_WORDING } from "@/app/transport";
import { toneOf } from "@/chrome/SeverityMark";
import { fallbackChrome } from "@/chrome/fallback";
import { ACTION_UNPLACED, refusalText } from "@/controls/RefusedControl";
import { scrollArtifact } from "@/controls/scroll";
import { shortDigest, stamp } from "@/ds/format";
import { SEV_COLOR, sevSurface, sevVar } from "@/ds/sev";
import { NODE_SEVERITY, confidenceTier, nodeTone } from "@/sections/analysis/tone";
import { caseHref } from "@/sections/directory/CaseRegister";
import { severityOf } from "@/sections/run/RouteGraph";
import { clock } from "@/sections/upload/SourcePack";
import { sameId } from "@/wire/v1";
import type { KeyboardEvent } from "react";

describe("severity is shape and hue, never hue alone", () => {
  test("every severity carries a class, and the four node states map onto them", () => {
    expect(toneOf("CRITICAL")).toBe("crit");
    expect(toneOf("IDLE")).toBe("idle");
    // The bundle's four, each read through a severity shape (DESIGN.md).
    expect(Object.keys(NODE_SEVERITY)).toEqual(["COMPLETE", "RUNNABLE", "RESTRICTED", "BLOCKED"]);
    expect(nodeTone("BLOCKED")).toBe("crit");
    expect(nodeTone("COMPLETE")).toBe("ok");
  });

  test("an unknown severity token falls back to idle rather than to nothing", () => {
    expect(sevVar("critical")).toBe(SEV_COLOR.critical);
    expect(sevVar("not-a-severity")).toBe("var(--caos-idle)");
  });

  test("a tinted surface mixes the severity colour and keeps it as the text colour", () => {
    const surface = sevSurface("warning", { border: 40, wash: 12 });
    expect(surface.color).toBe(SEV_COLOR.warning);
    expect(surface.borderColor).toContain("40%");
    expect(surface.background).toContain("12%");
  });

  test("a RUNNABLE node is only RUNNING while it is actually running", () => {
    expect(severityOf({ state: "RUNNABLE" }, true)).toBe("RUNNING");
    expect(severityOf({ state: "RUNNABLE" }, false)).toBe("IDLE");
    expect(severityOf({ state: "BLOCKED" }, false)).toBe("CRITICAL");
  });

  test("a confidence tier is the number's band, at its boundaries", () => {
    expect(confidenceTier(85).word).toBe("HIGH");
    expect(confidenceTier(84).word).toBe("MEDIUM");
    expect(confidenceTier(60).word).toBe("MEDIUM");
    expect(confidenceTier(59).word).toBe("LOW");
  });
});

describe("the wire contract and the states around it", () => {
  test("offline and unavailable are one sentence each, and never the same one", () => {
    expect(OFFLINE_WORDING).not.toBe(UNAVAILABLE_WORDING);
    expect(OFFLINE_WORDING).not.toMatch(/error|exception|stack/i);
  });

  test("a refusal reads as its code and what clears it", () => {
    expect(refusalText({ code: "SOURCE_ALREADY_WITHDRAWN", clears: "it is re-admitted" })).toBe(
      "SOURCE_ALREADY_WITHDRAWN — clears when it is re-admitted",
    );
  });

  test("fallback chrome carries the state and invents no subject, action or role", () => {
    const offline = fallbackChrome({ kind: "offline" });
    expect(offline.verdict.conclusion).toBe("Offline");
    expect(offline.verdict.severity).toBe("CRITICAL");
    expect(offline.ribbon.actions).toEqual([]);
    expect(offline.ribbon.execution).toBe("—");
    expect(offline.brief.change).toBe("Nothing observed.");

    const refused = fallbackChrome({
      kind: "error",
      refusal: { code: "WIRE_SHAPE_INVALID", clears: "the document is the declared v1 shape" },
    });
    expect(refused.ribbon.chips[0]?.label).toBe("WIRE_SHAPE_INVALID");
    expect(refused.brief.action).toContain("the document is the declared v1 shape");
  });

  test("the fallback brief ends its clause once, however the refusal punctuates it", () => {
    const brief = (clears: string) =>
      fallbackChrome({ kind: "error", refusal: { code: "STORE_UNAVAILABLE", clears } }).brief
        .action;
    expect(brief("the store answers again.")).toBe("Clears when the store answers again.");
    expect(brief("the store answers again")).toBe("Clears when the store answers again.");
    expect(brief("the store answers again. ")).toBe("Clears when the store answers again.");
    expect(brief("the store answers again?")).toBe("Clears when the store answers again?");
  });

  test("the client's own refusals read as a clause after 'clears when'", () => {
    // `classify`'s legacy key check was retired with the dual wire path
    // (slice 4.1j); every enabled section's document is validated by
    // `classifyV1`, exercised end to end in transport.test.ts. What is
    // pinned here is only the shape every such refusal's own clause takes.
    const refusals = [
      { code: "RESPONSE_INVALID", clears: "the server answers with a typed refusal" },
      { code: "WIRE_SHAPE_INVALID", clears: "the document is the declared v1 shape" },
      {
        code: "OBSERVED_EMPTY_UNTIMED",
        clears: "an observed-empty response carries the time it was observed",
      },
    ];
    for (const refusal of refusals) {
      expect(refusal.clears).toMatch(/^[a-z]/);
      expect(refusal.clears).not.toMatch(/\.$/);
    }
  });

  test("an action nothing performs is refused with a reason that is true today", () => {
    expect(ACTION_UNPLACED.code).toBe("ACTION_UNPLACED");
    expect(ACTION_UNPLACED.clears).not.toMatch(/Phase \d|REBUILD_PLAN|backend phase/);
    // Task 12.1 served the last v1 command route, so "the API serves a route
    // that performs it" and "only the run document and its event stream" are
    // both false now. What leaves a control unplaced is a section whose own
    // read judges no such action, and `chrome.actions` is where that
    // judgement arrives.
    expect(ACTION_UNPLACED.clears).toContain("chrome.actions");
    expect(ACTION_UNPLACED.clears).not.toMatch(/serves only|event stream|serves a route/);
  });
});

describe("navigation", () => {
  test("a section path is the slug with its trailing slash", () => {
    expect(sectionPath("directory")).toBe("/directory/");
    expect(sectionPath("committee")).toBe("/committee/");
  });
});

describe("the helpers a section reads its own rows with", () => {
  test("a case opens in Analysis, with its id escaped", () => {
    expect(caseHref("CASE/2026")).toBe("/analysis/?case=CASE%2F2026");
  });

  test("a digest is elided in the middle, and a short one is left alone", () => {
    expect(shortDigest("0b582ff0aaaaaaaaaaaaaaaa30df")).toBe("0b582ff0…30df");
    expect(shortDigest("0b582ff0")).toBe("0b582ff0");
    // Sixteen is the threshold: the short form is thirteen characters, so
    // eliding anything shorter hides characters and saves nothing.
    expect(shortDigest("0123456789abcdef")).toBe("0123456789abcdef");
    expect(shortDigest("0123456789abcdef0")).toBe("01234567…def0");
  });

  test("a missing digest reads as the caller's word for it, never as the elision", () => {
    expect(shortDigest(null)).toBe("—");
    expect(shortDigest(null, "not pinned")).toBe("not pinned");
  });

  test("a stamp keeps the date and the minute and drops the seconds; the clock part alone is marked UTC", () => {
    expect(stamp("2026-09-09T14:30:00Z")).toBe("2026-09-09 14:30Z");
    expect(stamp("2026-09-09T14:30:00.123456Z")).toBe("2026-09-09 14:30Z");
    expect(clock("2026-09-09T14:30:00Z")).toBe("14:30Z");
  });

  test("two ids are the same ignoring case, and two absent ids are the same", () => {
    expect(sameId("ABC", "abc")).toBe(true);
    expect(sameId(null, undefined)).toBe(true);
    expect(sameId("abc", null)).toBe(false);
    expect(sameId("abc", "abd")).toBe(false);
  });

  test("an arrow key pans a wide artifact and any other key is left to the browser", () => {
    const event = (key: string) => {
      const scrollBy = vi.fn();
      const preventDefault = vi.fn();
      const fired = { key, preventDefault, currentTarget: { scrollBy } };
      scrollArtifact(fired as unknown as KeyboardEvent<HTMLPreElement>);
      return { scrollBy, preventDefault };
    };
    expect(event("ArrowRight").scrollBy).toHaveBeenCalledWith({ left: 40 });
    expect(event("ArrowLeft").scrollBy).toHaveBeenCalledWith({ left: -40 });
    const other = event("ArrowDown");
    expect(other.scrollBy).not.toHaveBeenCalled();
    expect(other.preventDefault).not.toHaveBeenCalled();
  });
});

describe("why a command did not succeed", () => {
  test("every outcome reads the same way whichever control ran the command", () => {
    expect(
      failureMessage({
        kind: "refused",
        refusal: { code: "RUN_NOT_RUNNING", clears: "the run is running again" },
      }),
    ).toBe("RUN_NOT_RUNNING — clears when the run is running again");
    expect(failureMessage({ kind: "error", code: "RESPONSE_INVALID" })).toBe("RESPONSE_INVALID");
    // Offline is the page-level sentence, never engine text.
    expect(failureMessage({ kind: "offline" })).toBe(OFFLINE_WORDING);
  });

  test("a successful command has no failure to describe", () => {
    expect(() =>
      failureMessage({ kind: "ok", status: 201, receipt: {}, replayed: false }),
    ).toThrow();
  });
});
