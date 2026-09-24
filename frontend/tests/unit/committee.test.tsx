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
    // The saved text is text: the only links are the host's two reads (N4),
    // and the only buttons a narrative carries are its figures' chips (N59).
    for (const saved of root.querySelectorAll(
      "[data-committee-artifact], [data-committee-narrative]",
    )) {
      expect(saved.querySelector("img, script, a, input, textarea, [contenteditable]")).toBeNull();
      expect(saved.querySelector("button:not([data-figure-chip])")).toBeNull();
    }
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

  test("offers the rendered paper, and the package once filed, refused not hidden before (N4)", () => {
    const filed = committee();
    const { container, unmount } = render(<CommitteeSection document={filed} tab={null} />);
    expect(container.querySelector("[data-committee-render]")).toHaveAttribute(
      "href",
      filed.body.render_url,
    );
    const pkg = container.querySelector("[data-committee-package]")!;
    expect(pkg).toHaveAttribute("href", filed.body.package_url!);
    expect(pkg).toHaveAttribute("download");
    unmount();
    const frozen = parseCommitteeDocument({
      ...filed,
      body: { ...filed.body, state: "frozen", filed_by: null, receipt: null, package_url: null },
    });
    const { container: held } = render(<CommitteeSection document={frozen} tab={null} />);
    expect(held.querySelector("[data-committee-render]")).not.toBeNull();
    expect(held.querySelector("[data-committee-package]")).toBeNull();
    const refused = held.querySelector('[data-refusal="PACKAGE_NOT_FILED"]')!;
    expect(refused).toHaveTextContent("Download the package (.zip)");
    expect(refused).toHaveAttribute("aria-disabled", "true");
    expect(held).toHaveTextContent("Available once the revision is filed.");
  });

  test("renders distinct hostile narrative spans and typed figures as text", () => {
    const { container } = render(<CommitteeSection document={committee()} tab={null} />);
    const narrative = container.querySelector("[data-committee-narrative]")!;
    expect(narrative).toHaveTextContent("<svg onload=window.pwned=1>");
    // The figure is its quote and a chip naming its module and page (N59).
    expect(narrative.querySelector("q")).toHaveTextContent("Coverage 2.1x");
    expect(narrative.querySelector("[data-figure-chip]")).toHaveTextContent("CP-1 · p.7");
    expect(narrative.querySelector("svg, img, script")).toBeNull();
  });
});
