import { render, screen } from "@testing-library/react";
import { QualificationStrip } from "@/chrome/QualificationStrip";

const EVIDENCE = "a".repeat(64);

function response(state: "QUALIFIED" | "UNQUALIFIED" | "RESTRICTED" | "UNAVAILABLE") {
  return new Response(
    JSON.stringify({
      evidence_sha256: EVIDENCE,
      state,
      qualification_set_sha256: state === "QUALIFIED" ? "b".repeat(64) : null,
      performed_sha256: state === "QUALIFIED" ? "c".repeat(64) : null,
      build_id: state === "QUALIFIED" ? "build" : null,
      adapter_version: state === "QUALIFIED" ? "adapter" : null,
      provider: state === "QUALIFIED" ? "openrouter" : null,
      model: state === "QUALIFIED" ? "model" : null,
      reviewer: state === "QUALIFIED" ? "Reviewer" : null,
      decided_at: state === "QUALIFIED" ? "2026-09-15T10:00:00Z" : null,
      expires_at: state === "QUALIFIED" ? "2026-09-16T10:00:00Z" : null,
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

test("qualification states are never composed from a section verdict", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("RESTRICTED")));
  render(<QualificationStrip evidenceSha256={EVIDENCE} />);

  expect(await screen.findByText("Restricted")).toBeInTheDocument();
  expect(screen.getByLabelText("Qualification")).toHaveTextContent(
    "Qualification metadata requires an analyst role.",
  );
});

test("an unbound workspace has no qualification claim or request", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<QualificationStrip evidenceSha256={null} />);

  expect(screen.queryByLabelText("Qualification")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("unverifiable persisted evidence is unavailable, not unqualified", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response("UNAVAILABLE")));
  render(<QualificationStrip evidenceSha256={EVIDENCE} />);

  expect(await screen.findByText("Unavailable")).toBeInTheDocument();
  expect(screen.getByLabelText("Qualification")).toHaveTextContent(
    "Qualification evidence cannot be verified.",
  );
});
