import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { RateDeckView } from "@/wire/v1";
import { saveRateDeck } from "@/app/commands";
import { fetchRateDeck } from "@/app/transport";
import { parseLatestRateDeck, parseRateDeckSaved } from "@/wire/v1";
import { Announcer } from "@/states/Announcer";
import { AdminSection } from "@/sections/admin/AdminSection";
import { decimalToPercent, percentToDecimal } from "@/sections/admin/RateDeckCard";

const DECK = "3f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const LATEST: RateDeckView = {
  deck_id: DECK,
  as_of: "2026-10-01",
  saved_at: "2026-10-02T09:30:00.123456Z",
  rates: [
    { reference_rate: "SOFR", year_offset: 1, base_rate: "0.0380", downside_rate: "0.0420" },
    { reference_rate: "EURIBOR", year_offset: 3, base_rate: "-0.0025", downside_rate: "0.0100" },
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const DIRECTORY = JSON.parse(
  readFileSync(resolve(process.cwd(), "fixtures", "directory.json"), "utf8"),
);

function directoryAs(globalRole: string): Response {
  return jsonResponse({
    ...DIRECTORY,
    chrome: { ...DIRECTORY.chrome, served_role: { global_role: globalRole, standing: null } },
  });
}

function stubServer(
  post: () => Response | Promise<Response>,
  latest: unknown = LATEST,
  role: string | null = "ADMIN",
) {
  const spy = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") return Promise.resolve(post());
    if (url.endsWith("/latest")) return Promise.resolve(jsonResponse(latest));
    if (url.startsWith("/api/v1/directory")) {
      return role === null
        ? Promise.reject(new TypeError("down"))
        : Promise.resolve(directoryAs(role));
    }
    return Promise.resolve(null);
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function mount() {
  return render(
    <Announcer>
      <AdminSection />
    </Announcer>,
  );
}

const cell = (name: string) => screen.getByRole<HTMLInputElement>("textbox", { name });

describe("the rate deck card", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("prefills the grid from the latest deck", async () => {
    stubServer(() => jsonResponse({}));
    mount();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    expect(cell("SOFR FY+1 downside").value).toBe("4.20");
    expect(cell("EURIBOR FY+3 base").value).toBe("-0.25");
    expect(cell("SONIA FY+5 downside").value).toBe("");
    expect(screen.getByLabelText<HTMLInputElement>("As of").value).toBe("2026-10-01");
    expect(screen.getByText(/Current deck: as of 2026-10-01/)).toHaveTextContent(
      "saved 2026-10-02T09:30:00.123456Z",
    );
    expect(screen.getAllByRole("textbox")).toHaveLength(40);
  });

  test("refuses a non-numeric rate inline", async () => {
    const spy = stubServer(() => jsonResponse({ deck_id: DECK }, 201));
    mount();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    fireEvent.change(cell("SOFR FY+2 base"), { target: { value: "abc" } });
    fireEvent.change(cell("SOFR FY+2 downside"), { target: { value: "150" } });
    fireEvent.change(screen.getByLabelText("As of"), { target: { value: "" } });
    fireEvent.click(await screen.findByRole("button", { name: "Save rate deck" }));
    const bad = cell("SOFR FY+2 base");
    expect(bad).toHaveAttribute("aria-invalid", "true");
    const message = document.getElementById(bad.getAttribute("aria-describedby")!)!;
    expect(message).toHaveTextContent("a number between -100 and 100");
    expect(cell("SOFR FY+2 downside")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("As of")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("An as-of date is required.")).toBeInTheDocument();
    expect(spy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    fireEvent.change(bad, { target: { value: "2" } });
    expect(bad).not.toHaveAttribute("aria-invalid");
  });

  test("posts percent values as decimals", async () => {
    const spy = stubServer(() => jsonResponse({ deck_id: DECK }, 201));
    mount();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    fireEvent.change(cell("SONIA FY+2 base"), { target: { value: "0.07" } });
    fireEvent.change(cell("SONIA FY+2 downside"), { target: { value: "12.5" } });
    fireEvent.click(await screen.findByRole("button", { name: "Save rate deck" }));
    await screen.findByText(/Rate deck saved/);
    const post = spy.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(post[0]).toBe("/api/v1/rate-decks");
    expect((post[1]!.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
    const sent = JSON.parse(post[1]!.body as string);
    expect(sent.as_of).toBe("2026-10-01");
    expect(sent.rates).toEqual([
      { reference_rate: "SOFR", year_offset: 1, base_rate: "0.0380", downside_rate: "0.0420" },
      { reference_rate: "EURIBOR", year_offset: 3, base_rate: "-0.0025", downside_rate: "0.0100" },
      { reference_rate: "SONIA", year_offset: 2, base_rate: "0.0007", downside_rate: "0.125" },
    ]);
  });

  test("shows the server refusal for a non-admin", async () => {
    stubServer(() =>
      jsonResponse({ code: "ENDPOINT_NOT_FOUND", clears: "the endpoint exists for you" }, 404),
    );
    mount();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    fireEvent.click(await screen.findByRole("button", { name: "Save rate deck" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/the endpoint exists for you/);
  });

  test.each(["READER", "ANALYST"])("a %s sees the card read-only, with no Save", async (role) => {
    stubServer(() => jsonResponse({ deck_id: DECK }, 201), LATEST, role);
    mount();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    await waitFor(() => expect(cell("SOFR FY+1 base")).toHaveAttribute("readonly"));
    for (const input of screen.getAllByRole("textbox")) expect(input).toHaveAttribute("readonly");
    expect(screen.getByLabelText("As of")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save rate deck" })).toBeNull();
  });

  test("an ADMIN sees editable inputs and an enabled Save", async () => {
    stubServer(() => jsonResponse({ deck_id: DECK }, 201));
    mount();
    const save = await screen.findByRole("button", { name: "Save rate deck" });
    expect(save).not.toHaveAttribute("aria-disabled");
    expect(cell("SOFR FY+1 base")).not.toHaveAttribute("readonly");
    expect(screen.getByLabelText("As of")).not.toHaveAttribute("readonly");
  });

  test("while the role is unread, and when it cannot be read, the card is read-only", async () => {
    stubServer(() => jsonResponse({ deck_id: DECK }, 201), LATEST, null);
    mount();
    expect(screen.queryByRole("button", { name: "Save rate deck" })).toBeNull();
    await waitFor(() => expect(cell("SOFR FY+1 base").value).toBe("3.80"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(cell("SOFR FY+1 base")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save rate deck" })).toBeNull();
  });

  test("a row with only one of its two rates is refused inline", async () => {
    stubServer(() => jsonResponse({ deck_id: DECK }, 201), null);
    mount();
    await waitFor(() => expect(screen.getByText(/No deck has been saved/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("As of"), { target: { value: "2026-10-05" } });
    fireEvent.change(cell("SOFR FY+1 base"), { target: { value: "3" } });
    fireEvent.click(await screen.findByRole("button", { name: "Save rate deck" }));
    expect(cell("SOFR FY+1 downside")).toHaveAttribute("aria-invalid", "true");
    expect(document.body).toHaveTextContent("Enter both rates, or neither.");
  });

  test("an empty deck is refused before anything is sent", async () => {
    const spy = stubServer(() => jsonResponse({ deck_id: DECK }, 201), null);
    mount();
    await waitFor(() => expect(screen.getByText(/No deck has been saved/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("As of"), { target: { value: "2026-10-05" } });
    fireEvent.click(await screen.findByRole("button", { name: "Save rate deck" }));
    expect(screen.getByText("Enter at least one rate.")).toBeInTheDocument();
    expect(spy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  test("an offline read says so and a row still has its inputs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    mount();
    expect(await screen.findByText(/did not reach the server/)).toBeInTheDocument();
    expect(within(document.body).getAllByRole("textbox")).toHaveLength(40);
  });
});

describe("the rate deck card's surface state", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });
  const state = () =>
    document.querySelector("[data-rate-deck]")?.getAttribute("data-surface-state");

  test("loading while the read is outstanding", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    mount();
    expect(state()).toBe("loading");
  });

  test("ready with a deck on show", async () => {
    stubServer(() => jsonResponse({}));
    mount();
    await screen.findByText(/Current deck: as of/);
    expect(state()).toBe("ready");
  });

  test("observed-empty when no deck has been saved", async () => {
    stubServer(() => jsonResponse({}), null);
    mount();
    await screen.findByText("No deck has been saved.");
    expect(state()).toBe("observed-empty");
  });

  test("error when the server refuses the read", async () => {
    stubServer(() => jsonResponse({}), { nope: 1 });
    mount();
    await screen.findByText(/WIRE_SHAPE_INVALID/);
    expect(state()).toBe("error");
  });

  test("unavailable when the deck is not found", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(url.endsWith("/latest") ? jsonResponse({}, 404) : directoryAs("ADMIN")),
      ),
    );
    mount();
    await waitFor(() => expect(state()).toBe("unavailable"));
  });

  test("offline when the read does not reach the server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    mount();
    await waitFor(() => expect(state()).toBe("offline"));
  });
});

describe("the rate deck helpers", () => {
  test("percentToDecimal shifts the point exactly, never through a float", () => {
    expect(percentToDecimal("3.80")).toBe("0.0380");
    expect(percentToDecimal("0.07")).toBe("0.0007");
    expect(percentToDecimal("-0.25")).toBe("-0.0025");
    expect(percentToDecimal("12")).toBe("0.12");
    expect(percentToDecimal("99.9999999999999999")).toBe("0.999999999999999999");
    expect(percentToDecimal("-0")).toBe("0.00");
    expect(percentToDecimal("100")).toBeNull();
    expect(percentToDecimal("-100.01")).toBeNull();
    expect(percentToDecimal("1e2")).toBeNull();
    expect(percentToDecimal("3,8")).toBeNull();
    expect(percentToDecimal("")).toBeNull();
    expect(percentToDecimal("1".repeat(70))).toBeNull();
  });

  test("decimalToPercent is its inverse", () => {
    expect(decimalToPercent("0.0380")).toBe("3.80");
    expect(decimalToPercent("-0.0025")).toBe("-0.25");
    expect(decimalToPercent("0.5")).toBe("50");
    expect(decimalToPercent("0")).toBe("0");
    expect(decimalToPercent("0.0007")).toBe("0.07");
  });

  test("the transport reads the latest deck and sends the save", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(null)));
    expect(await fetchRateDeck()).toEqual({ kind: "ready", deck: null });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ nope: 1 })));
    expect(await fetchRateDeck()).toMatchObject({
      kind: "error",
      refusal: { code: "WIRE_SHAPE_INVALID" },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 404)));
    expect(await fetchRateDeck()).toEqual({ kind: "unavailable" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ deck_id: DECK }, 201)));
    const saved = await saveRateDeck({ as_of: "2026-10-01", rates: LATEST.rates });
    expect(saved.kind).toBe("ok");
    vi.unstubAllGlobals();
  });

  test("the wire parsers take the served shapes and refuse the rest", () => {
    expect(parseLatestRateDeck(null)).toBeNull();
    expect(parseLatestRateDeck(LATEST)).toEqual(LATEST);
    expect(() => parseLatestRateDeck({ ...LATEST, extra: 1 })).toThrow();
    expect(parseRateDeckSaved({ deck_id: DECK })).toEqual({ deck_id: DECK });
    expect(() => parseRateDeckSaved({ deck_id: "not-a-uuid" })).toThrow();
  });
});
