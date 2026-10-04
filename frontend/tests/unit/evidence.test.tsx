import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CitationChip } from "@/evidence/CitationChip";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import { MetricPassport } from "@/evidence/MetricPassport";
import { wholeLine } from "@/evidence/TracedLine";
import { PASSPORT_FIELDS, type Citation, type Passport } from "@/wire";

const CITATION: Citation = {
  chip: "D-04 p.68 ¶2",
  document_sha256: "a".repeat(64),
  source_label: "D-04 · 8-K Senior Secured Notes Indenture",
  page: 68,
  bboxes: [[0.085, 0.41, 0.83, 0.06]],
  matched_text:
    "the Issuer shall not permit the Consolidated Net Leverage Ratio to exceed 3.50 to 1.00",
  observed_at: "2026-09-09T14:30:00Z",
  render_url: "/api/pages/D-04-p68.svg",
};

const ACTUAL: Passport = {
  label: "Net leverage",
  value: "1.2x",
  unit: "x",
  definition: "Net debt over LTM adjusted EBITDA, per the indenture definition",
  period: "LTM to 2026-06-30",
  scenario: "Base",
  reporting_period: "Q2 2026",
  computed_at: "2026-09-09T14:30:00Z",
  snapshot: "snp_cvna_q2_2026",
  method: "leverage_ratio · verified",
  derivation: "(total_debt − cash) / ltm_adjusted_ebitda",
  citations: [CITATION],
  supporting_research: [
    { title: "CP-1 canonical data foundation", module_id: "CP-1", state: "ACCEPTED" },
  ],
  driver: null,
  deviation: null,
};

const PROJECTED: Passport = {
  ...ACTUAL,
  label: "Net leverage · FY2027 Q2",
  value: "1.4x",
  period: "FY2027 Q2",
  scenario: "Downside",
  method: "cash_flow_forecast · verified",
  derivation: "closing_debt − closing_cash / ebitda",
  driver: { name: "EBITDA margin", value: "9.1%", citation: CITATION },
};

describe("the evidence surface", () => {
  test("test_dialog_opener_is_explicit", async () => {
    render(
      <EvidenceProvider>
        <button type="button">elsewhere</button>
        <CitationChip citation={CITATION} />
      </EvidenceProvider>,
    );
    const chip = screen.getByRole("button", { name: "Evidence D-04 p.68 ¶2" });
    // WebKit does not focus a button on click: focus is elsewhere when the click lands.
    screen.getByRole("button", { name: "elsewhere" }).focus();
    fireEvent.click(chip);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.querySelector("img")).toHaveAttribute("src", "/api/pages/D-04-p68.svg");
    expect(dialog.querySelectorAll(".bbox")).toHaveLength(1);
    // A key event targets what has focus and bubbles to the document, where
    // the overlay listens (N64); one dispatched at `window` alone reaches no
    // element and no browser sends it.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    // To the chip that was passed, not back to where focus sat before the
    // click; the dialog places it a tick after it closes.
    await waitFor(() => expect(document.activeElement).toBe(chip));
  });

  test("the drawer shows the whole source line, the cited excerpt marked (D105)", () => {
    const line = {
      before: "Commencing with the first full fiscal quarter, ",
      excerpt: CITATION.matched_text,
      after: ".",
    };
    const { unmount } = render(
      <EvidenceProvider>
        <CitationChip citation={{ ...CITATION, line }} />
      </EvidenceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Evidence D-04 p.68 ¶2" }));
    const shown = screen.getByRole("dialog").querySelector("blockquote.matched")!;
    expect(shown.textContent).toBe(line.before + line.excerpt + line.after);
    expect(shown.querySelector("mark")!.textContent).toBe(CITATION.matched_text);
    unmount();
    // A citation with no line beside it is its own line (`wholeLine`).
    expect(wholeLine("Coverage 2.1x")).toEqual({
      before: "",
      excerpt: "Coverage 2.1x",
      after: "",
    });
    render(
      <EvidenceProvider>
        <CitationChip citation={CITATION} />
      </EvidenceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Evidence D-04 p.68 ¶2" }));
    const alone = screen.getByRole("dialog").querySelector("blockquote.matched")!;
    expect(alone.querySelector("mark")!.textContent).toBe(CITATION.matched_text);
    expect(alone.textContent).toBe(CITATION.matched_text);
  });

  test("a citation of a withdrawn source is marked on the chip and in the drawer", () => {
    const withdrawn: Citation = {
      ...CITATION,
      chip: "D-06 p.1 ¶3",
      withdrawn_at: "2026-09-09T09:41:00Z",
    };
    render(
      <EvidenceProvider>
        <CitationChip citation={withdrawn} />
      </EvidenceProvider>,
    );
    const chip = screen.getByRole("button", { name: "Evidence D-06 p.1 ¶3 · source withdrawn" });
    expect(chip).toHaveClass("withdrawn");
    fireEvent.click(chip);
    const dialog = screen.getByRole("dialog");
    expect(dialog.querySelector("[data-withdrawn]")).toHaveTextContent("2026-09-09T09:41:00Z");
  });

  test("a citation the host re-anchored says which page the module cited (D94)", () => {
    const moved: Citation = { ...CITATION, chip: "D-04 p.68 ¶3", cited_page: 67 };
    render(
      <EvidenceProvider>
        <CitationChip citation={CITATION} />
        <CitationChip citation={moved} />
      </EvidenceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Evidence D-04 p.68 ¶2" }));
    expect(screen.getByRole("dialog").querySelector("[data-reanchored]")).toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Evidence D-04 p.68 ¶3" }));
    expect(screen.getByRole("dialog").querySelector("[data-reanchored]")).toHaveTextContent(
      "Cited p.67, found p.68",
    );
  });

  test("test_passport_contract", () => {
    for (const passport of [ACTUAL, PROJECTED]) {
      const { unmount } = render(
        <EvidenceProvider>
          <MetricPassport passport={passport} opener={null} onClose={() => {}} />
        </EvidenceProvider>,
      );
      const fields = [...document.querySelectorAll("[data-passport] > [data-passport-field]")].map(
        (el) => el.getAttribute("data-passport-field"),
      );
      for (const field of PASSPORT_FIELDS) expect(fields).toContain(field);
      expect(
        fields.filter((f) => (PASSPORT_FIELDS as readonly string[]).includes(f!)),
      ).toHaveLength(10);
      expect(screen.getByText("Supporting research")).toBeInTheDocument();
      const chips = screen.getAllByRole("button", { name: "Evidence D-04 p.68 ¶2" });
      if (passport.driver) {
        expect(fields).toContain("driver");
        expect(screen.getByText(/EBITDA margin/)).toBeInTheDocument();
        expect(chips).toHaveLength(2);
      } else {
        expect(chips).toHaveLength(1);
        expect(fields).not.toContain("driver");
      }
      unmount();
    }
  });
});
