import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { CommitteeSection } from "@/sections/committee/CommitteeSection";
import { parseCommitteeDocument } from "@/wire/v1";

const committee = () =>
  parseCommitteeDocument(
    JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/committee-v1.json"), "utf8")),
  );

describe("Committee v1", () => {
  test("renders the exact filed saved payload as escaped read-only text", () => {
    const document = committee();
    const { container } = render(<CommitteeSection document={document} tab={null} />);
    const root = container.querySelector("[data-committee-v1]")!;

    for (const [name, value] of [
      ["case", document.body.case_id],
      ["run", document.body.displayed_run_id],
      ["revision", document.body.revision_id],
      ["payload", document.body.payload_sha256],
    ]) {
      expect(root).toHaveAttribute(`data-${name}`, value);
    }
    expect(root).toHaveTextContent('<img src=x onerror="window.pwned=1">');
    expect(root).toHaveTextContent("<script>limit</script>");
    expect(
      root.querySelector("img, script, a, button, input, textarea, [contenteditable]"),
    ).toBeNull();
    expect(root.querySelectorAll("[data-committee-artifact]")).toHaveLength(
      document.body.artifacts.length,
    );
    expect(root.querySelector("[data-committee-filing]")).toHaveAttribute("data-state", "filed");
    for (const signer of document.body.signed_by) expect(root).toHaveTextContent(signer);
    for (const value of Object.values(document.body.receipt!))
      expect(root).toHaveTextContent(value);
  });

  test("distinguishes frozen from filed and does not invent a receipt", () => {
    const filed = committee();
    const frozen = parseCommitteeDocument({
      ...filed,
      body: { ...filed.body, state: "frozen", filed_by: null, receipt: null },
    });
    const { container } = render(<CommitteeSection document={frozen} tab={null} />);
    expect(container.querySelector("[data-committee-filing]")).toHaveAttribute(
      "data-state",
      "frozen",
    );
    expect(container.querySelector("[data-committee-receipt]")).toBeNull();
    expect(container).toHaveTextContent(frozen.body.frozen_by);
    expect(container).toHaveTextContent("—");
  });

  test("renders distinct hostile narrative spans and typed figures as text", () => {
    const { container } = render(<CommitteeSection document={committee()} tab={null} />);
    const narrative = container.querySelector("[data-committee-narrative]")!;
    expect(narrative).toHaveTextContent("<svg onload=window.pwned=1>");
    expect(narrative).toHaveTextContent("CP-1 · p.7 · Coverage 2.1x");
    expect(narrative.querySelector("svg, img, script")).toBeNull();
  });
});
