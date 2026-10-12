// Add to Book on the Model and Withdraw on the Book (Plan 3 Task 5; spec B3,
// B5, B7): the dialog's fields and what they start from, its two-step confirm
// naming the snapshot digest, and the command each control posts.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import { shortDigest } from "@/ds/format";
import { BookSection } from "@/sections/book/BookSection";
import {
  AGENCIES,
  GICS_SECTORS,
  OUTLOOKS,
  WITHDRAWAL_NOTE_MAX,
  WITHDRAWAL_REASONS,
} from "@/sections/book/classification";
import { canWithdraw } from "@/sections/book/WithdrawEntry";
import { ModelSection } from "@/sections/model/ModelSection";
import { Announcer } from "@/states/Announcer";
import {
  parseBookDocument,
  parseModelDocument,
  type BookDocument,
  type ModelDocument,
} from "@/wire/v1";

const DIGEST = "d".repeat(64);
const RUN = "00000000-0000-4000-8000-0000000000a1";

const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", name), "utf8"));

function book(): BookDocument {
  return parseBookDocument(fixture("book.json"));
}

/** The Model fixture as a writer reads a complete default view: the digest an
    add binds, the run's subject and `ADD_TO_BOOK` in the chrome. */
function offered(issuerId: string, name = "Carvana Co."): ModelDocument {
  const raw = fixture("model.json");
  raw.chrome.actions = [{ action: "ADD_TO_BOOK", refusal: null }];
  raw.body.snapshot_sha256 = DIGEST;
  // The header is under test, not the grid: no lines, no columns, no chart.
  raw.body.lines = [];
  raw.body.columns = [];
  raw.body.subject = {
    issuer_id: issuerId,
    issuer_name: name,
    reporting_period: "FY2025",
    analysis_date: "2026-09-08",
  };
  return parseModelDocument(raw);
}

interface Call {
  url: string;
  method: string;
  body: unknown;
  key: string | null;
}
let calls: Call[] = [];
let answers: (call: Call) => { status: number; body: unknown } | null;

beforeEach(() => {
  calls = [];
  answers = () => null;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    const call: Call = {
      url,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
      key: headers.get("Idempotency-Key"),
    };
    calls.push(call);
    const made = answers(call);
    const answer = made ?? { status: 404, body: {} };
    return new Response(JSON.stringify(answer.body), { status: answer.status });
  });
});
afterEach(() => vi.unstubAllGlobals());

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

function renderModel(doc: ModelDocument) {
  return render(
    <MemoryRouter initialEntries={["/model/"]}>
      <Announcer>
        <EvidenceProvider>
          <ModelSection document={doc} tab={null} />
        </EvidenceProvider>
      </Announcer>
    </MemoryRouter>,
  );
}

async function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Add to Book" }));
  await screen.findByLabelText("Sector");
  return within(screen.getByRole("dialog"));
}

const value = (el: HTMLElement) => (el as HTMLSelectElement | HTMLInputElement).value;
const choose = (el: HTMLElement, to: string) => fireEvent.change(el, { target: { value: to } });

describe("Add to Book", () => {
  test("pre-fills from the issuer's previous entry", async () => {
    answers = (call) =>
      call.url === "/api/v1/book" ? { status: 200, body: fixture("book.json") } : null;
    renderModel(offered("cvna "));
    const dialog = await openDialog();
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/book"]);
    expect(value(dialog.getByLabelText("Sector"))).toBe("Consumer Discretionary");
    expect(value(dialog.getByLabelText("Industry group"))).toBe(
      "Consumer Discretionary Distribution & Retail",
    );
    expect(value(dialog.getByLabelText(/Domicile/))).toBe("US");
    expect(value(dialog.getByLabelText("Moody's rating"))).toBe("B2");
    expect(value(dialog.getByLabelText("Moody's outlook"))).toBe("POSITIVE");
    expect(value(dialog.getByLabelText("S&P rating"))).toBe("B");
    expect(value(dialog.getByLabelText("S&P outlook"))).toBe("POSITIVE");
    expect(value(dialog.getByLabelText("Fitch rating"))).toBe("");
    expect(dialog.getByLabelText("Fitch outlook")).toHaveAttribute("aria-disabled", "true");
  });

  test("starts blank for an issuer the Book does not hold", async () => {
    answers = (call) =>
      call.url === "/api/v1/book" ? { status: 200, body: fixture("book.json") } : null;
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    expect(value(dialog.getByLabelText("Sector"))).toBe("");
    expect(value(dialog.getByLabelText(/Domicile/))).toBe("");
  });

  test("says so, and starts blank, when the Book cannot be read", async () => {
    renderModel(offered("CVNA"));
    const dialog = await openDialog();
    expect(dialog.getByText(/could not be read/)).toBeInTheDocument();
    expect(value(dialog.getByLabelText("Sector"))).toBe("");
  });

  test("industry groups follow the chosen sector", async () => {
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    const group = dialog.getByLabelText("Industry group");
    expect(group).toHaveAttribute("aria-disabled", "true");
    choose(dialog.getByLabelText("Sector"), "Financials");
    expect(
      within(group)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["No industry group", "Banks", "Financial Services", "Insurance"]);
    choose(group, "Banks");
    choose(dialog.getByLabelText("Sector"), "Energy");
    // A group belongs to its sector: another sector clears it.
    expect(value(group)).toBe("");
    expect(
      within(group)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["No industry group", "Energy"]);
  });

  test("an outlook needs a rating", async () => {
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    const outlook = dialog.getByLabelText("S&P outlook");
    expect(outlook).toHaveAttribute("aria-disabled", "true");
    // A change to a rated-less outlook is ignored.
    choose(outlook, "STABLE");
    expect(value(outlook)).toBe("");
    expect(dialog.getAllByText("An outlook needs a rating.")).toHaveLength(3);
    choose(dialog.getByLabelText("S&P rating"), "BB+");
    expect(outlook).not.toHaveAttribute("aria-disabled");
    choose(outlook, "WATCH_NEG");
    expect(value(outlook)).toBe("WATCH_NEG");
    // Taking the rating away takes its outlook with it.
    choose(dialog.getByLabelText("S&P rating"), "");
    expect(outlook).toHaveAttribute("aria-disabled", "true");
    expect(value(outlook)).toBe("");
    // Each agency's own scale.
    const moodys = within(dialog.getByLabelText("Moody's rating")).getAllByRole("option");
    expect(moodys.map((o) => o.textContent)).toContain("Baa3");
    expect(moodys.map((o) => o.textContent)).not.toContain("BBB-");
  });

  test("refuses inline until the sector and domicile are stated", async () => {
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    const add = dialog.getByRole("button", { name: "Add Carvana Co. to the Book" });
    expect(add).toHaveAttribute("aria-disabled", "true");
    fireEvent.blur(dialog.getByLabelText("Sector"));
    expect(dialog.getByText("Choose a sector.")).toBeInTheDocument();
    fireEvent.change(dialog.getByLabelText(/Domicile/), { target: { value: "g1b" } });
    // Upper-cased, letters only, two of them.
    expect(value(dialog.getByLabelText(/Domicile/))).toBe("GB");
    choose(dialog.getByLabelText("Sector"), "Energy");
    expect(add).not.toHaveAttribute("aria-disabled");
  });

  test("confirms with the snapshot digest and posts the classification", async () => {
    answers = (call) => {
      if (call.method === "POST")
        return { status: 201, body: { entry_id: "00000000-0000-4000-8000-0000000000f1" } };
      if (call.url.startsWith("/api/v1/cases/"))
        return { status: 200, body: fixture("model.json") };
      return null;
    };
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    choose(dialog.getByLabelText("Sector"), "Energy");
    choose(dialog.getByLabelText("Industry group"), "Energy");
    fireEvent.change(dialog.getByLabelText(/Domicile/), { target: { value: "gb" } });
    choose(dialog.getByLabelText("Moody's rating"), "Ba2");
    choose(dialog.getByLabelText("Moody's outlook"), "STABLE");
    choose(dialog.getByLabelText("Fitch rating"), "BB-");
    fireEvent.click(dialog.getByRole("button", { name: "Add Carvana Co. to the Book" }));
    const sentence = dialog.getByRole("group", { name: "Confirm Add to Book" });
    expect(sentence).toHaveTextContent(`sha256:${shortDigest(DIGEST)}`);
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    fireEvent.click(dialog.getByRole("button", { name: "Confirm Add to Book" }));
    await settle();
    const [post] = calls.filter((c) => c.method === "POST");
    expect(post!.url).toBe(
      "/api/v1/cases/00000000-0000-4000-8000-000000000001/runs/" + RUN + "/book-entry",
    );
    expect(post!.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(post!.body).toEqual({
      snapshot_sha256: DIGEST,
      sector: "Energy",
      industry_group: "Energy",
      domicile: "GB",
      moodys: "Ba2",
      moodys_outlook: "STABLE",
      sp: null,
      sp_outlook: null,
      fitch: "BB-",
      fitch_outlook: null,
    });
    // The outcome is said in the dialog; the Model is read again on closing it.
    expect(dialog.getByText(/is in the Book/)).toBeInTheDocument();
    expect(calls.filter((c) => c.url.includes("/model"))).toHaveLength(0);
    fireEvent.click(dialog.getByRole("button", { name: /^Close/ }));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/model"))).toHaveLength(1));
  });

  test("shows a refusal as it came and sends nothing else", async () => {
    answers = (call) =>
      call.method === "POST"
        ? {
            status: 409,
            body: { code: "COMMAND_EXPECTATION_STALE", clears: "the snapshot is read again" },
          }
        : null;
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    choose(dialog.getByLabelText("Sector"), "Utilities");
    fireEvent.change(dialog.getByLabelText(/Domicile/), { target: { value: "FR" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add Carvana Co. to the Book" }));
    fireEvent.click(dialog.getByRole("button", { name: "Confirm Add to Book" }));
    await settle();
    expect(await dialog.findByRole("alert")).toHaveTextContent("COMMAND_EXPECTATION_STALE");
  });

  test("ties each blurred field's error to the field", async () => {
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    const sector = dialog.getByLabelText("Sector");
    const domicile = dialog.getByLabelText(/Domicile/);
    fireEvent.blur(sector);
    fireEvent.blur(domicile);
    const hint = (field: HTMLElement) =>
      document.getElementById(field.getAttribute("aria-describedby") ?? "")?.textContent;
    expect(hint(sector)).toBe("Choose a sector.");
    expect(hint(domicile)).toBe("Two letters, for example GB.");
  });

  test("names the focus guards a screen reader can land on", async () => {
    renderModel(offered("NEWCO"));
    await openDialog();
    const guards = [...document.querySelectorAll("[data-base-ui-focus-guard]")];
    expect(guards.length).toBeGreaterThan(0);
    for (const guard of guards) expect(guard).toHaveAttribute("aria-label", "Edge of the dialog");
  });

  test("a close while the add is in flight still reads the Model again once it lands", async () => {
    let land: () => void = () => undefined;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", body: null, key: null });
      if (init?.method === "POST") {
        await new Promise<void>((resolve) => (land = resolve));
        return new Response(JSON.stringify({ entry_id: "00000000-0000-4000-8000-0000000000f1" }), {
          status: 201,
        });
      }
      return new Response(JSON.stringify(fixture("model.json")), { status: 200 });
    });
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    choose(dialog.getByLabelText("Sector"), "Energy");
    fireEvent.change(dialog.getByLabelText(/Domicile/), { target: { value: "GB" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add Carvana Co. to the Book" }));
    fireEvent.click(dialog.getByRole("button", { name: "Confirm Add to Book" }));
    await settle();
    fireEvent.click(dialog.getByRole("button", { name: /^Close/ }));
    await settle();
    expect(calls.filter((c) => c.url.includes("/model"))).toHaveLength(0);
    land();
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/model"))).toHaveLength(1));
  });

  test("says so when the Model cannot be read again after an add", async () => {
    answers = (call) =>
      call.method === "POST"
        ? { status: 201, body: { entry_id: "00000000-0000-4000-8000-0000000000f1" } }
        : null;
    renderModel(offered("NEWCO"));
    const dialog = await openDialog();
    choose(dialog.getByLabelText("Sector"), "Energy");
    fireEvent.change(dialog.getByLabelText(/Domicile/), { target: { value: "GB" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add Carvana Co. to the Book" }));
    fireEvent.click(dialog.getByRole("button", { name: "Confirm Add to Book" }));
    await settle();
    expect(document.querySelector("[data-model-refresh-failed]")).toBeNull();
    fireEvent.click(dialog.getByRole("button", { name: /^Close/ }));
    await waitFor(() =>
      expect(document.querySelector("[data-model-refresh-failed]")).not.toBeNull(),
    );
  });

  test("offers nothing where the document does not", () => {
    const doc = offered("NEWCO");
    renderModel({ ...doc, chrome: { ...doc.chrome, actions: [] } });
    expect(screen.queryByRole("button", { name: "Add to Book" })).toBeNull();
  });
});

function renderBook(doc: BookDocument) {
  return render(
    <MemoryRouter initialEntries={["/book/"]}>
      <Announcer>
        <BookSection document={doc} tab={null} />
      </Announcer>
    </MemoryRouter>,
  );
}

describe("the dialogs' vocabularies", () => {
  test("are the words the server checks, in order", () => {
    expect(Object.keys(GICS_SECTORS)).toContain("Energy");
    expect(OUTLOOKS.map(([word]) => word)).toEqual([
      "STABLE",
      "POSITIVE",
      "NEGATIVE",
      "DEVELOPING",
      "WATCH_POS",
      "WATCH_NEG",
      "WATCH_DEV",
    ]);
    expect(AGENCIES.map((agency) => agency.key)).toEqual(["moodys", "sp", "fitch"]);
    expect(WITHDRAWAL_REASONS.map(([word]) => word)).toEqual([
      "ADDED_IN_ERROR",
      "DATA_ERROR",
      "SUPERSEDED_SOURCES",
      "OTHER",
    ]);
    expect(WITHDRAWAL_NOTE_MAX).toBe(1000);
  });
});

describe("Withdraw", () => {
  test("is offered only on an entry the Book says this viewer may withdraw", () => {
    const [first, second] = book().body.issuers;
    expect(canWithdraw(first!.displayed)).toBe(true);
    expect(canWithdraw(second!.displayed)).toBe(false);
    renderBook(book());
    expect(screen.getByRole("button", { name: "Withdraw Carvana Co." })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Withdraw Caesars Entertainment, Inc." }),
    ).toBeNull();
  });

  test("withdraw requires a note for Other", async () => {
    const doc = book();
    const entry = doc.body.issuers[0]!.displayed;
    answers = (call) =>
      call.method === "POST"
        ? { status: 200, body: { entry_id: entry.entry_id } }
        : call.url === "/api/v1/book"
          ? { status: 200, body: fixture("book.json") }
          : null;
    renderBook(doc);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw Carvana Co." }));
    const panel = within(document.querySelector<HTMLElement>("[data-withdraw-displayed]")!);
    const withdraw = panel.getByRole("button", { name: /^Withdraw entry/ });
    // No reason, no withdrawal.
    expect(withdraw).toHaveAttribute("aria-disabled", "true");
    choose(panel.getByLabelText(/Reason for withdrawing/), "OTHER");
    expect(withdraw).toHaveAttribute("aria-disabled", "true");
    expect(panel.getByLabelText(/Note \(required\)/)).toBeInTheDocument();
    fireEvent.change(panel.getByLabelText(/Note/), { target: { value: "  Wrong issuer id " } });
    expect(withdraw).not.toHaveAttribute("aria-disabled");
    fireEvent.click(withdraw);
    expect(panel.getByRole("group", { name: "Confirm Withdraw entry" })).toHaveTextContent(
      `sha256:${shortDigest(entry.snapshot_sha256)}`,
    );
    fireEvent.click(panel.getByRole("button", { name: "Confirm Withdraw entry" }));
    await settle();
    const [post] = calls.filter((c) => c.method === "POST");
    // The entry's own stored digest, on the entry's own case.
    expect(post!.url).toBe(
      `/api/v1/cases/${entry.case_id}/book-entries/${entry.entry_id}/withdrawal`,
    );
    expect(post!.body).toEqual({
      snapshot_sha256: entry.snapshot_sha256,
      reason: "OTHER",
      note: "Wrong issuer id",
    });
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/v1/book")).toHaveLength(1));
  });

  test("marks the blank note an Other withdrawal needs, and says why", () => {
    renderBook(book());
    fireEvent.click(screen.getByRole("button", { name: "Withdraw Carvana Co." }));
    const panel = within(document.querySelector<HTMLElement>("[data-withdraw-displayed]")!);
    const note = panel.getByLabelText(/Note/);
    expect(note).not.toHaveAttribute("aria-invalid");
    choose(panel.getByLabelText(/Reason for withdrawing/), "OTHER");
    expect(note).toHaveAttribute("aria-invalid", "true");
    expect(document.getElementById(note.getAttribute("aria-describedby") ?? "")).toHaveTextContent(
      "A note is required for Other.",
    );
    fireEvent.change(note, { target: { value: "x" } });
    expect(note).not.toHaveAttribute("aria-invalid");
  });

  test("the row's Withdraw opens the panel, never closes it, and moves focus to it", () => {
    renderBook(book());
    const button = screen.getByRole("button", { name: "Withdraw Carvana Co." });
    fireEvent.click(button);
    const panel = document.querySelector<HTMLElement>("[data-withdraw-displayed]")!;
    expect(document.activeElement).toBe(panel);
    (document.activeElement as HTMLElement).blur();
    fireEvent.click(button);
    expect(document.querySelector("[data-withdraw-displayed]")).toBe(panel);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(panel);
  });

  test("a reason other than Other sends no note when none is written", async () => {
    const entry = book().body.issuers[0]!.displayed;
    answers = (call) =>
      call.method === "POST" ? { status: 200, body: { entry_id: entry.entry_id } } : null;
    renderBook(book());
    fireEvent.click(screen.getByRole("button", { name: "Withdraw Carvana Co." }));
    const panel = within(document.querySelector<HTMLElement>("[data-withdraw-displayed]")!);
    choose(panel.getByLabelText(/Reason for withdrawing/), "DATA_ERROR");
    fireEvent.click(panel.getByRole("button", { name: /^Withdraw entry/ }));
    fireEvent.click(panel.getByRole("button", { name: "Confirm Withdraw entry" }));
    await settle();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      snapshot_sha256: entry.snapshot_sha256,
      reason: "DATA_ERROR",
      note: null,
    });
  });
});
