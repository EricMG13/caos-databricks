// N159 (D109): the run input's command form. CP-2G's `cases`, an override of
// the derived horizon and base, and CP-0's objective, on the existing
// `qualifiers` and `objective` wire; the derived scope is shown before the pin.
import { readFileSync } from "node:fs";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { RunSection } from "@/sections/run/RunSection";
import { parseRunSectionDocument } from "@/wire/v1";
import type { NodeState } from "@/wire";
import type { RunSectionDocument } from "@/wire/v1";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const running = parseRunSectionDocument(load("../../fixtures/run.json"));

const offered = (document: RunSectionDocument): RunSectionDocument => ({
  ...document,
  chrome: { ...document.chrome, actions: [{ action: "PIN_RUN_INPUT", refusal: null }] },
});

const withCp2g = (document: RunSectionDocument): RunSectionDocument => {
  const run = document.body.run!;
  return offered({
    ...document,
    body: {
      ...document.body,
      run: {
        ...run,
        nodes: [
          ...run.nodes,
          {
            route_node_id: "rn-cp-2g",
            module_id: "CP-2G",
            module_name: "Forecast drivers",
            stage: 3,
            state: "BLOCKED" as NodeState,
            waiting_on: [],
            awaiting_gate: false,
            gate_verdict: null,
            gate_reason: null,
          },
        ],
      },
    },
  });
};

function mount(document: RunSectionDocument) {
  return render(
    <MemoryRouter>
      <RunSection document={document} tab={null} />
    </MemoryRouter>,
  );
}

const set = (root: HTMLElement, field: string, value: string) =>
  fireEvent.change(root.querySelector(`[data-field="${field}"]`)!, { target: { value } });

const pin = (root: HTMLElement) =>
  fireEvent.click(root.querySelector('[data-action="PIN_RUN_INPUT"]')!);

/** Pins with `edit` applied and returns the body the form sent. */
async function pinned(document: RunSectionDocument, edit: (root: HTMLElement) => void) {
  const run = document.body.run!;
  const fetchSpy = vi
    .fn()
    .mockResolvedValueOnce(
      jsonResponse({
        run_id: run.run_id,
        source_set_version: run.source_set_version,
        input_fingerprint: "f".repeat(64),
      }),
    )
    .mockResolvedValueOnce(jsonResponse(document));
  vi.stubGlobal("fetch", fetchSpy);
  const { container } = mount(document);
  edit(container);
  pin(container);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  const [, init] = fetchSpy.mock.calls[0]!;
  return JSON.parse((init as RequestInit).body as string);
}

describe("the run input's command form", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("test_the_form_shows_the_derived_scope_before_the_pin", () => {
    const { container } = mount(withCp2g(running));
    const derived = container.querySelector("[data-derived-scope]")!;
    expect(derived).not.toBeNull();
    // The fixture's subject is `Q2 2026`: FY2026 to FY2028 on the Q2 2026 LTM.
    expect(derived.textContent).toContain("FY2026-FY2028");
    expect(derived.textContent).toContain("Q2 2026 LTM");
    // It follows the subject's period as the user edits it.
    set(container, "reporting_period", "Q4 2026");
    expect(container.querySelector("[data-derived-scope]")!.textContent).toContain("FY2027-FY2029");
    set(container, "reporting_period", "H1 2026");
    expect(container.querySelector("[data-derived-scope]")!.textContent).toMatch(/cannot read/i);
  });

  test("test_an_untouched_form_sends_no_command", async () => {
    const sent = await pinned(withCp2g(running), () => undefined);
    expect(sent.qualifiers).toEqual([]);
    expect(sent.objective).toBeNull();
  });

  test("test_the_form_sends_cases_an_override_and_the_objective", async () => {
    const sent = await pinned(withCp2g(running), (root) => {
      set(root, "forecast_horizon", "FY2027-FY2029");
      set(root, "cases", "Base/Downside");
      set(root, "objective", "Is the pack ready for a senior loan.");
    });
    expect(sent.qualifiers).toEqual([
      { module_id: "CP-2G", name: "forecast_horizon", value: "FY2027-FY2029" },
      { module_id: "CP-2G", name: "cases", value: "Base/Downside" },
    ]);
    expect(sent.objective).toBe("Is the pack ready for a senior loan.");
  });

  test("test_a_route_without_cp2g_offers_no_forecast_fields", () => {
    const { container } = mount(offered(running));
    expect(container.querySelector("[data-derived-scope]")).toBeNull();
    expect(container.querySelector('[data-field="cases"]')).toBeNull();
    expect(container.querySelector('[data-field="objective"]')).not.toBeNull();
  });

  test("test_an_invalid_value_is_announced_and_not_sent", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = mount(withCp2g(running));
    set(container, "forecast_horizon", "next year");
    const input = container.querySelector('[data-field="forecast_horizon"]')!;
    expect(input).toHaveAttribute("aria-invalid", "true");
    const message = container.querySelector(`#${input.getAttribute("aria-describedby")}`)!;
    expect(message).toHaveAttribute("role", "alert");
    pin(container);
    expect(fetchSpy).not.toHaveBeenCalled();
    set(container, "forecast_horizon", "");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  test("test_the_servers_typed_refusal_is_shown_in_plain_words", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        jsonResponse(
          {
            code: "REPORTING_PERIOD_UNREADABLE",
            clears: "the reporting period is one the scope rule reads",
          },
          422,
        ),
      ),
    );
    const { container } = mount(withCp2g(running));
    pin(container);
    await waitFor(() =>
      expect(
        container.querySelector('[data-refusal="REPORTING_PERIOD_UNREADABLE"]'),
      ).not.toBeNull(),
    );
    const note = container.querySelector('[data-refusal="REPORTING_PERIOD_UNREADABLE"] .cl')!;
    expect(note.textContent).toMatch(/reporting period/i);
    expect(note.textContent).not.toMatch(/^Available once/);
  });
});
