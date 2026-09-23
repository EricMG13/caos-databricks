// What a reader who cannot see the screen is told after a command, and where
// their focus is left (round 4, DF-6, DF-7 and DF-9).
//
// DF-6: six controls passed an empty success sentence, so creating a case,
// admitting sources, withdrawing a source, granting and revoking standing and
// saving a revision succeeded without a word in the live region; and a
// sentence equal to the last one said was not said again. DF-7: a confirmed
// withdrawal or revocation is answered by a re-read that takes the pressed
// control away, and focus fell to <body>; so did a rail link from the
// unavailable page. DF-9: the demo fixtures offered none of the confirmed acts,
// so the a11y matrix never measured one available or armed.
//
// Every section is mounted whole, on the demo's `acts` fixtures -- the same
// documents the a11y matrix now scans -- under the section's own live region.
import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "@/app/App";
import { CommandOutcome } from "@/sections/run/controls";
import { DirectorySection } from "@/sections/directory/DirectorySection";
import { ReportSection } from "@/sections/report/ReportSection";
import { UploadSection } from "@/sections/upload/UploadSection";
import { Announcer, useAnnouncer } from "@/states/Announcer";
import {
  parseDirectoryDocument,
  parseReportDocument,
  parseRunSectionDocument,
  parseUploadDocument,
  type DirectoryDocument,
  type UploadDocument,
} from "@/wire/v1";
import { STATE_ROUTES, armedRoute, sectionRoute } from "../../scripts/fixture-routes.mjs";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const directory = () => parseDirectoryDocument(load("../../fixtures/states/directory.acts.json"));
const upload = () => parseUploadDocument(load("../../fixtures/states/upload.acts.json"));
const report = () => parseReportDocument(load("../../fixtures/states/report.acts.json"));
const run = () => parseRunSectionDocument(load("../../fixtures/states/run.acts.json"));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Answers every request in turn with the next of `answers`. */
function answering(...answers: Response[]) {
  const spy = vi.fn();
  for (const answer of answers) spy.mockResolvedValueOnce(answer);
  vi.stubGlobal("fetch", spy);
  return spy;
}

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

async function settled() {
  for (let i = 0; i < 4; i += 1) await settle();
}

const said = (container: HTMLElement) => container.querySelector("[data-announcer]")!;

afterEach(() => vi.unstubAllGlobals());

const CASE = "ff1fbf5a-e56f-4f84-a983-2f5a507675f0";
const WRITER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function inDirectory(document: DirectoryDocument) {
  return render(
    <MemoryRouter>
      <Announcer>
        <DirectorySection document={document} tab={null} />
      </Announcer>
    </MemoryRouter>,
  );
}

function inUpload(document: UploadDocument) {
  return render(
    <MemoryRouter>
      <Announcer>
        <UploadSection document={document} tab={null} />
      </Announcer>
    </MemoryRouter>,
  );
}

describe("every command says when it succeeded (DF-6)", () => {
  test("test_creating_a_case_is_announced", async () => {
    const doc = directory();
    const created = "33333333-3333-4333-8333-333333333333";
    answering(jsonResponse({ case_id: created }, 201), jsonResponse(doc));
    const { container } = inDirectory(doc);
    fireEvent.change(screen.getByLabelText("New case title"), { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Create case" }));
    await settled();
    expect(said(container)).toHaveTextContent(`Case ${created} created.`);
    // The note keeps its own name, and now says it as a status.
    const note = container.querySelector("[data-new-case-success]")!;
    expect(note).toHaveTextContent(`Case ${created} created.`);
    expect(note).toHaveAttribute("role", "status");
  });

  test("test_granting_standing_is_announced", async () => {
    const doc = directory();
    const caseId = doc.body.cases[0]!.case_id;
    const newcomer = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    answering(
      jsonResponse({ case_id: caseId, user_id: newcomer, standing: "READER" }, 201),
      jsonResponse(doc),
    );
    const { container } = inDirectory(doc);
    const panel = container.querySelector<HTMLElement>(`[data-access="${caseId}"]`)!;
    fireEvent.change(within(panel).getByLabelText("Member id"), { target: { value: newcomer } });
    fireEvent.click(within(panel).getByRole("button", { name: "Grant standing" }));
    await settled();
    expect(said(container)).toHaveTextContent("Standing granted. Reading the register back.");
  });

  test("test_admitting_sources_is_announced", async () => {
    const doc = upload();
    answering(
      jsonResponse({ case_id: CASE, source_ids: ["22222222-2222-4222-8222-222222222222"] }, 201),
      jsonResponse(doc),
    );
    const { container } = inUpload(doc);
    fireEvent.change(screen.getByLabelText("Documents to admit"), {
      target: { files: [new File(["x"], "a.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    await settled();
    expect(said(container)).toHaveTextContent("1 source(s) admitted.");
    expect(container.querySelector("[data-admit-sources-success]")).toHaveAttribute(
      "role",
      "status",
    );
  });

  test("test_saving_a_revision_is_announced", async () => {
    const doc = report();
    const revision = "00000000-0000-4000-8000-0000000000c4";
    answering(
      jsonResponse(
        {
          case_id: doc.body.case_id,
          run_id: doc.body.displayed_run_id,
          revision_id: revision,
          payload_sha256: "b".repeat(64),
        },
        201,
      ),
    );
    const { container } = render(
      <MemoryRouter>
        <Announcer>
          <ReportSection document={doc} tab={null} />
        </Announcer>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Narrative draft"), {
      target: { value: "Coverage improved." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settled();
    expect(said(container)).toHaveTextContent(`Revision ${revision} saved.`);
    expect(container.querySelector("[data-revision-saved]")).toHaveTextContent(revision);
  });

  test("an equal sentence said again is announced again", () => {
    function Say({ sentence }: { sentence: string }) {
      const say = useAnnouncer();
      return (
        <button type="button" onClick={() => say(sentence)}>
          say
        </button>
      );
    }
    const { container } = render(
      <Announcer>
        <Say sentence="Subject pinned. Reading it back." />
      </Announcer>,
    );
    const button = screen.getByRole("button", { name: "say" });
    fireEvent.click(button);
    const first = said(container).firstChild;
    expect(said(container)).toHaveTextContent("Subject pinned. Reading it back.");
    fireEvent.click(button);
    // A region that does not change is not announced: the words are the same,
    // the node is not.
    expect(said(container).firstChild).not.toBe(first);
    expect(said(container)).toHaveTextContent("Subject pinned. Reading it back.");
  });

  test("test_a_second_success_of_the_same_command_is_announced_again", () => {
    const ok = () => ({ kind: "ok" as const, status: 200, receipt: {}, replayed: false });
    const sentence = "Subject pinned. Reading it back.";
    const { container, rerender } = render(
      <Announcer>
        <CommandOutcome result={null} success={sentence} />
      </Announcer>,
    );
    const changes: MutationRecord[] = [];
    const watch = new MutationObserver((batch) => changes.push(...batch));
    watch.observe(said(container), { childList: true, characterData: true, subtree: true });
    rerender(
      <Announcer>
        <CommandOutcome result={ok()} success={sentence} />
      </Announcer>,
    );
    changes.push(...watch.takeRecords());
    const afterFirst = changes.length;
    expect(afterFirst).toBeGreaterThan(0);
    // The second press clears the answer while it is in flight, then succeeds.
    rerender(
      <Announcer>
        <CommandOutcome result={null} success={sentence} />
      </Announcer>,
    );
    rerender(
      <Announcer>
        <CommandOutcome result={ok()} success={sentence} />
      </Announcer>,
    );
    changes.push(...watch.takeRecords());
    expect(changes.length).toBeGreaterThan(afterFirst);
    watch.disconnect();
  });
});

describe("focus after a confirmed act takes its own control away (DF-7)", () => {
  test("test_a_confirmed_withdrawal_leaves_focus_on_the_source_pack_heading", async () => {
    const doc = upload();
    const alive = doc.body.sources.find((source) => source.withdrawn_at === null)!;
    const refreshed: UploadDocument = {
      ...doc,
      body: {
        ...doc.body,
        sources: doc.body.sources.map((row) =>
          row.source_id === alive.source_id
            ? { ...row, withdrawn_at: "2026-09-17T09:00:00Z" }
            : row,
        ),
      },
    };
    answering(
      jsonResponse({ case_id: doc.body.case_id, source_id: alive.source_id }),
      jsonResponse(refreshed),
    );
    const { container } = inUpload(doc);
    const row = () =>
      container.querySelector<HTMLElement>(
        `table.reg[data-source-pack] tr[data-source="${alive.source_id}"]`,
      )!;
    fireEvent.click(row().querySelector("[data-confirm-open]")!);
    fireEvent.click(row().querySelector("[data-confirm-yes]")!);
    // The opener has focus back while the command is out (FE-7).
    expect(document.activeElement).toBe(row().querySelector("[data-confirm-open]"));
    await settled();
    // The re-read pack offers this row nothing more.
    expect(row().querySelector("button")).toBeNull();
    const heading = screen.getByRole("heading", { name: "Source pack" });
    expect(document.activeElement).toBe(heading);
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(said(container)).toHaveTextContent(
      `${alive.filename} withdrawn. Reading the pack back.`,
    );
  });

  test("test_a_confirmed_revocation_leaves_focus_on_the_cases_access_heading", async () => {
    const doc = directory();
    const first = doc.body.cases[0]!;
    const without: DirectoryDocument = {
      ...doc,
      body: {
        cases: [
          {
            ...first,
            members: first.members!.filter((member) => member.user_id !== WRITER),
          },
          ...doc.body.cases.slice(1),
        ],
      },
    };
    answering(jsonResponse({ case_id: first.case_id, user_id: WRITER }), jsonResponse(without));
    const { container } = inDirectory(doc);
    const panel = container.querySelector<HTMLElement>(`[data-access="${first.case_id}"]`)!;
    fireEvent.click(within(panel).getByRole("button", { name: `Revoke ${WRITER}` }));
    fireEvent.click(within(panel).getByRole("button", { name: "Confirm Revoke standing" }));
    await settled();
    expect(panel.querySelector(`[data-member="${WRITER}"]`)).toBeNull();
    const heading = within(panel).getByRole("heading", { name: first.title });
    expect(document.activeElement).toBe(heading);
    expect(said(container)).toHaveTextContent("Standing revoked. Reading the register back.");
  });

  test("a control that leaves while focus is elsewhere takes nothing with it", async () => {
    const doc = upload();
    const alive = doc.body.sources.find((source) => source.withdrawn_at === null)!;
    answering(
      jsonResponse({ case_id: doc.body.case_id, source_id: alive.source_id }),
      jsonResponse({
        ...doc,
        body: {
          ...doc.body,
          sources: doc.body.sources.map((row) =>
            row.source_id === alive.source_id
              ? { ...row, withdrawn_at: "2026-09-17T09:00:00Z" }
              : row,
          ),
        },
      }),
    );
    const { container } = inUpload(doc);
    const row = container.querySelector<HTMLElement>(`tr[data-source="${alive.source_id}"]`)!;
    fireEvent.click(row.querySelector("[data-confirm-open]")!);
    fireEvent.click(row.querySelector("[data-confirm-yes]")!);
    // The reader moves on before the answer arrives.
    const elsewhere = screen.getByLabelText("Documents to admit");
    elsewhere.focus();
    await settled();
    expect(document.activeElement).toBe(elsewhere);
  });

  test("test_a_rail_link_from_the_unavailable_page_moves_focus_to_the_section_heading", async () => {
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    vi.stubGlobal(
      "EventSource",
      class {
        addEventListener() {}
        close() {}
      },
    );
    window.history.pushState({}, "", "/nothing/");
    try {
      render(<App />);
      const link = screen.getByRole("link", { name: /Directory/ });
      link.focus();
      fireEvent.click(link);
      await settle();
      expect(window.location.pathname).toBe("/directory/");
      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading).toHaveTextContent("DIRECTORY");
      expect(document.activeElement).toBe(heading);
    } finally {
      window.history.pushState({}, "", "/");
    }
  });
});

describe("the a11y matrix measures every confirmed act available (DF-9)", () => {
  test("test_the_acts_fixtures_offer_every_confirmed_act_unrefused", () => {
    const offered = (actions: readonly { action: string; refusal: unknown }[]) =>
      actions.filter((entry) => entry.refusal === null).map((entry) => entry.action);
    expect(offered(report().chrome.actions)).toEqual(
      expect.arrayContaining(["SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE"]),
    );
    expect(offered(upload().chrome.actions)).toContain("WITHDRAW_SOURCE");
    expect(offered(run().chrome.actions)).toContain("CANCEL_RUN");
    const administered = directory().body.cases[0]!;
    expect(offered(administered.actions)).toContain("REVOKE_STANDING");
    expect(administered.members?.length).toBeGreaterThan(1);
    // The workspace's own reading of each: rendered, the control is live.
    const { container } = render(
      <MemoryRouter>
        <ReportSection document={report()} tab={null} />
      </MemoryRouter>,
    );
    for (const act of ["SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE"]) {
      const control = container.querySelector(`[data-action="${act}"][data-confirm-open]`)!;
      expect(control).not.toHaveAttribute("aria-disabled");
    }
  });

  test("test_the_matrix_routes_every_acts_fixture_and_an_armed_step", () => {
    for (const section of ["directory", "upload", "run", "report"]) {
      expect(STATE_ROUTES).toContain(sectionRoute(section, "acts"));
    }
    const armed = armedRoute("report", "SIGN_OPINION");
    expect(STATE_ROUTES).toContain(armed);
    expect(new URL(armed, "http://localhost").searchParams.get("arm")).toBe("SIGN_OPINION");
    expect(new URL(armed, "http://localhost").searchParams.get("fixture")).toBe("acts");
  });
});
