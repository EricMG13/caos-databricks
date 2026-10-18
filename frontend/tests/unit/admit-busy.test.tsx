// The Admit button while its command is in flight (N221): the busy label is
// the control's accessible name, not the fixed "Admit sources".
import { readFileSync } from "node:fs";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { UploadSection } from "@/sections/upload/UploadSection";
import { parseUploadDocument, type UploadDocument } from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const fixture = parseUploadDocument(load("../../fixtures/upload.json"));

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("Admit busy label (N221)", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("while the admit is in flight the button's accessible name is its busy label", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(() => undefined)));
    render(
      <MemoryRouter>
        <UploadSection document={live} tab={null} />
      </MemoryRouter>,
    );
    const file = new File(["contents"], "a.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Choose documents"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    await settle();
    expect(screen.getByRole("button", { name: "Admitting…" })).toHaveAttribute("aria-busy", "true");
  });
});
