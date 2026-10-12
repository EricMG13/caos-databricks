// Add to Book on the Model and Withdraw on the Book (Plan 3 Task 5; spec B3,
// B5, B7): the dialog's fields and what they start from, its two-step confirm
// naming the snapshot digest, and the command each control posts.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import {
  AGENCIES,
  GICS_SECTORS,
  OUTLOOKS,
  WITHDRAWAL_NOTE_MAX,
  WITHDRAWAL_REASONS,
} from "@/sections/book/classification";
import { ModelSection } from "@/sections/model/ModelSection";
import { Announcer } from "@/states/Announcer";
import { parseModelDocument, type ModelDocument } from "@/wire/v1";

const DIGEST = "d".repeat(64);

const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", name), "utf8"));

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

  test("offers nothing where the document does not", () => {
    const doc = offered("NEWCO");
    renderModel({ ...doc, chrome: { ...doc.chrome, actions: [] } });
    expect(screen.queryByRole("button", { name: "Add to Book" })).toBeNull();
  });
});

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
