import { readFileSync } from "node:fs";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OFFLINE_WORDING } from "@/app/transport";
import { sentence } from "@/chrome/compose";
import { DirectorySection } from "@/sections/directory/DirectorySection";
import {
  parseDirectoryDocument,
  parseStandingGranted,
  parseStandingRevoked,
  parseUploadDocument,
  type DirectoryDocument,
} from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const fixture = parseDirectoryDocument(load("../../fixtures/directory.json"));
const empty = parseDirectoryDocument(load("../../fixtures/states/directory.observed-empty.json"));

function mount(document: DirectoryDocument) {
  return render(
    <MemoryRouter>
      <DirectorySection document={document} tab={null} />
    </MemoryRouter>,
  );
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const rowsOf = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>("table.reg[data-register] tbody tr"));

describe("Directory", () => {
  test("test_register_has_one_action_per_row_and_no_batch_state", () => {
    const { container } = mount(fixture);
    expect(container.querySelector("table.reg[data-register]")).not.toBeNull();
    const rows = rowsOf(container);
    expect(rows).toHaveLength(fixture.body.cases.length);
    for (const row of rows) {
      const links = within(row).getAllByRole("link");
      expect(links).toHaveLength(1);
      expect(links[0]).toHaveTextContent("Open case");
      expect(within(row).queryAllByRole("button")).toHaveLength(0);
    }
    // No batch state: no checkboxes, no select-all, no "n selected".
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByText(/select all|selected/i)).toBeNull();
    const first = fixture.body.cases[0]!;
    const row = container.querySelector<HTMLElement>(`tr[data-case="${first.case_id}"]`);
    expect(row).not.toBeNull();
    expect(within(row!).getByRole("link", { name: /^Open / })).toHaveAttribute(
      "href",
      `/analysis/?case=${first.case_id}`,
    );
  });

  test("test_directory_draws_no_sector_rating_or_leverage", () => {
    const { container } = mount(fixture);
    const text = container.textContent ?? "";
    // Neither the dropped columns' headers nor any of the legacy sample
    // values they used to carry (issuer sector, rating, net leverage,
    // pathway or snapshot) reach the page — the v1 CaseRow does not carry
    // them, so nothing here can fake them.
    expect(screen.queryByText("Sector")).toBeNull();
    expect(screen.queryByText("Rating")).toBeNull();
    expect(screen.queryByText("Pathway")).toBeNull();
    expect(screen.queryByText("Snapshot")).toBeNull();
    expect(text).not.toMatch(/Automotive Retail|Car Rental|Telecommunications/);
    expect(text).not.toMatch(/B3 \/ B-|B2 \/ B|Ba1 \/ BB\+/);
    // Net leverage read "5.9x"; nothing on the v1 CaseRow carries a ratio.
    expect(text).not.toMatch(/\d+\.\d+x/);
  });

  test("every case row draws its title, created time, standing, live sources and latest run", () => {
    const { container } = mount(fixture);
    const row = fixture.body.cases[0]!;
    const tr = container.querySelector<HTMLElement>(`tr[data-case="${row.case_id}"]`)!;
    expect(tr).toHaveTextContent(row.title);
    expect(tr).toHaveTextContent(sentence(row.standing));
    expect(tr).toHaveTextContent(String(row.live_sources));
    expect(tr).toHaveTextContent(sentence(row.latest_run!.status));
    expect(tr).toHaveTextContent(row.latest_run!.profile_id!);
    expect(tr).toHaveTextContent(row.latest_run!.selection_id!);
    expect(tr.querySelector("time")).toHaveAttribute("dateTime", row.created_at);
  });

  test("a parked latest run reads parked with its stop code, not running (CF-044)", () => {
    const first = fixture.body.cases[0]!;
    const one: DirectoryDocument = {
      ...fixture,
      body: {
        cases: [
          {
            ...first,
            latest_run: {
              ...first.latest_run!,
              status: "RUNNING",
              stop_code: "BUDGET_CEILING_REACHED",
            },
          },
        ],
      },
    };
    const { container } = mount(one);
    const row = container.querySelector<HTMLElement>(`tr[data-case="${first.case_id}"]`)!;
    expect(row).toHaveTextContent("Parked");
    expect(row.querySelector("[data-stop-code]")).toHaveTextContent("BUDGET_CEILING_REACHED");
    expect(row).not.toHaveTextContent("Running");
  });

  test("a case with no run yet reads 'No runs yet' rather than a blank cell", () => {
    const one: DirectoryDocument = {
      ...fixture,
      body: {
        cases: [{ ...fixture.body.cases[0]!, latest_run: null }],
      },
    };
    const { container } = mount(one);
    const row = container.querySelector<HTMLElement>(
      `tr[data-case="${one.body.cases[0]!.case_id}"]`,
    )!;
    expect(row).toHaveTextContent("No runs yet");
  });

  test("an observed-empty register renders no rows", () => {
    expect(empty.observed_empty).toBe(true);
    expect(empty.body.cases).toHaveLength(0);
    const { container } = mount(empty);
    expect(rowsOf(container)).toHaveLength(0);
    expect(container).toHaveTextContent("No case matches.");
  });

  test("test_a_refused_action_renders_its_code_and_clearance_and_is_not_hidden", async () => {
    const refused: DirectoryDocument = {
      ...fixture,
      chrome: {
        ...fixture.chrome,
        actions: [
          {
            action: "CREATE_CASE",
            refusal: { code: "NOT_AUTHORISED", clears: "your global role is ANALYST or higher" },
          },
        ],
      },
    };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = mount(refused);
    const control = screen.getByRole("button", { name: "Create case" });
    // Present, not hidden: it renders, carries the refusal, and is not the
    // native `disabled` attribute (CLAUDE.md "Persona is not authority").
    expect(control).toBeVisible();
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toBeDisabled();
    expect(control).toHaveAttribute("data-refusal", "NOT_AUTHORISED");
    expect(control).toHaveTextContent("Create case");
    expect(control.title).toContain("NOT_AUTHORISED");
    expect(control.title).toContain("your global role is ANALYST or higher");
    // Scoped to the create-case control: the Case access panel below carries
    // refusals of its own.
    const newCase = container.querySelector<HTMLElement>("[data-new-case]")!;
    expect(newCase.querySelector("[data-refusal='NOT_AUTHORISED']")).not.toBeNull();
    expect(within(newCase).getByText(/your global role is ANALYST or higher/)).toBeInTheDocument();
    fireEvent.click(control);
    await settle();
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test("an available create-case action posts the command and refetches on success", async () => {
    const live: DirectoryDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "CREATE_CASE", refusal: null }] },
    };
    const newCaseId = "11111111-1111-4111-8111-111111111111";
    const refreshed: DirectoryDocument = {
      ...live,
      body: {
        cases: [
          {
            case_id: newCaseId,
            title: "Acme Holdings",
            created_at: "2026-09-14T10:00:00Z",
            standing: "ADMIN",
            live_sources: 0,
            latest_run: null,
            members: [],
            actions: [],
          },
          ...live.body.cases,
        ],
      },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: newCaseId }, 201))
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchSpy);

    const { container } = mount(live);
    const input = screen.getByLabelText("New case title");
    fireEvent.change(input, { target: { value: "Acme Holdings" } });
    const control = screen.getByRole("button", { name: "Create case" });
    expect(control).not.toHaveAttribute("aria-disabled");
    fireEvent.click(control);
    await settle();
    await settle();

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const [postUrl, postInit] = fetchSpy.mock.calls[0]!;
    expect(postUrl).toBe("/api/v1/cases");
    expect(JSON.parse(postInit.body as string)).toEqual({ title: "Acme Holdings" });
    expect(postInit.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(fetchSpy.mock.calls[1]![0]).toBe("/api/v1/directory");

    const register = container.querySelector<HTMLElement>("table.reg[data-register]")!;
    expect(await within(register).findByText("Acme Holdings")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  test("the idempotency key is reused only for a retry of the same body after offline, and replaced when the body changes", async () => {
    const live: DirectoryDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "CREATE_CASE", refusal: null }] },
    };
    const fetchSpy = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ case_id: "x" }, 201))
      .mockResolvedValueOnce(jsonResponse(live));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const input = screen.getByLabelText("New case title");
    const control = screen.getByRole("button", { name: "Create case" });

    fireEvent.change(input, { target: { value: "Acme" } });
    fireEvent.click(control);
    await settle();
    const key1 = fetchSpy.mock.calls[0]![1].headers["Idempotency-Key"];
    // An offline answer is announced, in the one offline sentence.
    expect(screen.getByRole("alert")).toHaveTextContent(OFFLINE_WORDING);

    // Same body, retried after an offline answer: the same key.
    fireEvent.click(control);
    await settle();
    const key2 = fetchSpy.mock.calls[1]![1].headers["Idempotency-Key"];
    expect(key2).toBe(key1);

    // The body changes before the next submit: a fresh key, even though the
    // previous answer was offline.
    fireEvent.change(input, { target: { value: "Acme Corp" } });
    fireEvent.click(control);
    await settle();
    await settle();
    const key3 = fetchSpy.mock.calls[2]![1].headers["Idempotency-Key"];
    expect(key3).not.toBe(key1);
    vi.unstubAllGlobals();
  });

  test("the idempotency key is replaced after any answer that is not offline, even for the same body", async () => {
    const live: DirectoryDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "CREATE_CASE", refusal: null }] },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ code: "NOT_AUTHORISED", clears: "x" }, 403))
      .mockResolvedValueOnce(jsonResponse({ case_id: "x" }, 201))
      .mockResolvedValueOnce(jsonResponse(live));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const input = screen.getByLabelText("New case title");
    const control = screen.getByRole("button", { name: "Create case" });
    fireEvent.change(input, { target: { value: "Acme" } });

    fireEvent.click(control);
    await settle();
    const key1 = fetchSpy.mock.calls[0]![1].headers["Idempotency-Key"];
    // A refusal is announced, with its code and clearance.
    expect(screen.getByRole("alert")).toHaveTextContent("NOT_AUTHORISED");

    // Same body, but the last answer was a refusal, not offline: a fresh key.
    fireEvent.click(control);
    await settle();
    await settle();
    const key2 = fetchSpy.mock.calls[1]![1].headers["Idempotency-Key"];
    expect(key2).not.toBe(key1);
    vi.unstubAllGlobals();
  });

  test("a success whose refetch fails still shows a persistent success note, plus a visible refresh-failed state", async () => {
    const live: DirectoryDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "CREATE_CASE", refusal: null }] },
    };
    const newCaseId = "33333333-3333-4333-8333-333333333333";
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: newCaseId }, 201))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    fireEvent.change(screen.getByLabelText("New case title"), { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Create case" }));
    await settle();
    await settle();

    expect(await screen.findByText(new RegExp(newCaseId))).toBeInTheDocument();
    expect(screen.getByText(/could not.*refresh|refresh.*failed/i)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  test("an action absent from chrome.actions is not available, and is refused with ACTION_UNPLACED", () => {
    const noActions: DirectoryDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [] },
    };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    mount(noActions);
    const control = screen.getByRole("button", { name: "Create case" });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
    fireEvent.click(control);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test("test_the_demonstration_directory_offers_one_available_command", async () => {
    // The published fixture, not a document this test composed: the ledger
    // entry this closes said every command control in `make dev-ui-demo`
    // renders refused, so what has to be available is the shipped bytes.
    const create = fixture.chrome.actions.find((action) => action.action === "CREATE_CASE");
    expect(create).toEqual({ action: "CREATE_CASE", refusal: null });

    // Available means the command would answer, never that it will succeed.
    // The demonstration API refuses every command with READ_ONLY_DEMO, which
    // the v1 wire does not declare, so what a press proves is the workspace
    // refusing an undeclared answer. The control says so before it is
    // pressed rather than after -- these unit tests run in demo mode, which
    // is what puts that note on screen here.
    // Stubbed rather than taken from the runner: `npm test` runs in demo mode,
    // and a test that silently passes under one mode and fails under another
    // is a worse thing to leave behind than an explicit stub.
    vi.stubEnv("MODE", "demo");
    mount(fixture);
    expect(document.querySelector("[data-demo-command-note]")).toHaveTextContent(
      "Available means the command would answer",
    );
    // Said once as the field's caption, not a disclosure in the register's flow.
    expect(document.querySelector("[data-demo-command-note]")).toHaveClass("fld-hint");
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ code: "READ_ONLY_DEMO", clears: "a real API handles commands" }, 405),
      );
    vi.stubGlobal("fetch", fetchSpy);
    const control = screen.getByRole("button", { name: "Create case" });
    expect(control).not.toHaveAttribute("aria-disabled");
    fireEvent.change(screen.getByLabelText("New case title"), {
      target: { value: "Acme Credit" },
    });
    fireEvent.click(control);
    await settle();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("RESPONSE_INVALID");
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  test("test_every_enabled_demo_fixture_is_a_valid_v1_document", () => {
    const directoryFixtures = [
      "../../fixtures/directory.json",
      "../../fixtures/states/directory.observed-empty.json",
    ];
    for (const path of directoryFixtures) {
      expect(() => parseDirectoryDocument(load(path))).not.toThrow();
    }
    const uploadFixtures = [
      "../../fixtures/upload.json",
      "../../fixtures/states/upload.partial.json",
    ];
    for (const path of uploadFixtures) {
      expect(() => parseUploadDocument(load(path))).not.toThrow();
    }
  });

  test("test_a_case_administrator_grants_and_revokes_from_case_access", async () => {
    const caseId = fixture.body.cases[0]!.case_id;
    const admin = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const writer = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    const newcomer = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    const administered: DirectoryDocument = {
      ...fixture,
      body: {
        cases: [
          {
            ...fixture.body.cases[0]!,
            standing: "ADMIN",
            members: [
              { user_id: admin, standing: "ADMIN" },
              { user_id: writer, standing: "WRITER" },
            ],
            actions: [
              { action: "GRANT_STANDING", refusal: null },
              { action: "REVOKE_STANDING", refusal: null },
            ],
          },
        ],
      },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ case_id: caseId, user_id: newcomer, standing: "APPROVER" }, 201),
      )
      .mockResolvedValueOnce(jsonResponse(administered))
      .mockResolvedValueOnce(jsonResponse({ case_id: caseId, user_id: writer }))
      .mockResolvedValueOnce(jsonResponse(administered));
    vi.stubGlobal("fetch", fetchSpy);

    const { container } = mount(administered);
    const panel = container.querySelector<HTMLElement>(`[data-access="${caseId}"]`)!;
    expect(within(panel).getByText(admin)).toBeInTheDocument();
    expect(panel.querySelector(`[data-member="${writer}"]`)).toHaveTextContent("WRITER");

    fireEvent.change(within(panel).getByLabelText("Member id"), {
      target: { value: newcomer },
    });
    fireEvent.change(within(panel).getByLabelText("Standing"), {
      target: { value: "APPROVER" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Grant standing" }));
    await settle();
    await settle();
    // `grantStanding` builds this request and `parseStandingGranted` narrows its
    // receipt; `refetchDirectory` is the GET after it. `revokeStanding` and
    // `parseStandingRevoked` are driven the same way below.
    const [grantUrl, grantInit] = fetchSpy.mock.calls[0]!;
    expect(grantUrl).toBe(`/api/v1/cases/${caseId}/members`);
    expect(JSON.parse(grantInit.body as string)).toEqual({
      user_id: newcomer,
      standing: "APPROVER",
    });
    expect(fetchSpy.mock.calls[1]![0]).toBe("/api/v1/directory");

    // Revoking asks once more before it is sent (finding FE-7).
    fireEvent.click(within(panel).getByRole("button", { name: `Revoke ${writer}` }));
    fireEvent.click(
      within(panel).getAllByRole("button", { name: /^Confirm Revoke standing$/ })[0]!,
    );
    await settle();
    await settle();
    expect(fetchSpy.mock.calls[2]![0]).toBe(`/api/v1/cases/${caseId}/members/${writer}/revocation`);
    expect(fetchSpy.mock.calls[3]![0]).toBe("/api/v1/directory");
    vi.unstubAllGlobals();
  });

  test("the membership receipts are closed shapes", () => {
    const caseId = fixture.body.cases[0]!.case_id;
    const userId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    expect(parseStandingGranted({ case_id: caseId, user_id: userId, standing: "READER" })).toEqual({
      case_id: caseId,
      user_id: userId,
      standing: "READER",
    });
    expect(() =>
      parseStandingGranted({ case_id: caseId, user_id: userId, standing: "OWNER" }),
    ).toThrow();
    expect(parseStandingRevoked({ case_id: caseId, user_id: userId })).toEqual({
      case_id: caseId,
      user_id: userId,
    });
    expect(() => parseStandingRevoked({ case_id: caseId, user_id: userId, extra: 1 })).toThrow();
  });

  test("test_a_member_below_admin_is_shown_the_membership_controls_refused_not_hidden", () => {
    const { container } = mount(fixture);
    const first = fixture.body.cases[0]!;
    const panel = container.querySelector<HTMLElement>(`[data-access="${first.case_id}"]`)!;
    expect(panel.querySelector("[data-members-withheld]")).not.toBeNull();
    for (const name of ["Grant standing", "Revoke standing"]) {
      const control = within(panel).getByRole("button", { name });
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveAttribute("data-refusal", "NOT_AUTHORISED");
    }
  });
});
