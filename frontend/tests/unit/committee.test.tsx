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

  test("a filed revision is paper, with its stamp, signatures and digests; a frozen one is not (N62)", () => {
    const filed = committee();
    const { container, unmount } = render(<CommitteeSection document={filed} tab={null} />);
    const paper = container.querySelector("[data-paper]")!;
    expect(paper.tagName).toBe("ARTICLE");
    expect(paper).toHaveAccessibleName(filed.body.case_title);
    expect(paper.querySelector(".paper-stamp")).toHaveTextContent("Filed");
    expect(paper.querySelector("[data-figure-chip]")).not.toBeNull();
    const sign = paper.querySelector(".paper-sign")!;
    expect(sign).toHaveTextContent("Signed by");
    expect(sign).toHaveTextContent("Filed by");
    // Short on the page, whole in the title.
    const payload = paper.querySelector(`[title="sha256:${filed.body.payload_sha256}"]`);
    expect(payload).not.toBeNull();
    expect(paper.querySelector(".paper-filed")).toHaveTextContent("filed event");
    // The full receipt is still the record below it.
    expect(container.querySelector("[data-committee-receipt]")).not.toBeNull();
    unmount();
    const frozen = parseCommitteeDocument({
      ...filed,
      body: { ...filed.body, state: "frozen", filed_by: null, receipt: null, package_url: null },
    });
    const { container: held } = render(<CommitteeSection document={frozen} tab={null} />);
    expect(held.querySelector("[data-paper]")).toBeNull();
    expect(held.querySelector("[data-committee-narrative]")).not.toBeNull();
  });

  // Security review note 1: only the host's own read of this revision is
  // linked; another origin, a script or another revision is refused.
  test("a link that is not this revision's own read is refused, never followed", () => {
    const filed = committee();
    for (const [render_url, package_url] of [
      ["https://evil.example/render", "//evil.example/package"],
      ["javascript:alert(1)", "data:text/html,x"],
      [
        filed.body.render_url.replace(
          filed.body.revision_id,
          "00000000-0000-4000-8000-0000000000ff",
        ),
        filed.body.package_url!.replace(filed.body.case_id, "00000000-0000-4000-8000-0000000000fe"),
      ],
    ]) {
      const odd = parseCommitteeDocument({
        ...filed,
        body: { ...filed.body, render_url, package_url },
      });
      const { container, unmount } = render(<CommitteeSection document={odd} tab={null} />);
      const downloads = container.querySelector("[data-committee-downloads]")!;
      expect(downloads.querySelector("a")).toBeNull();
      expect(downloads.querySelectorAll('[data-refusal="LINK_NOT_OWN"]')).toHaveLength(2);
      unmount();
    }
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
