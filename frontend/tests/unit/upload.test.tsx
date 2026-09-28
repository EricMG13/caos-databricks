import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OFFLINE_WORDING } from "@/app/transport";
import { UploadSection } from "@/sections/upload/UploadSection";
import { parseUploadDocument, type UploadDocument } from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const fixture = parseUploadDocument(load("../../fixtures/upload.json"));
const partial = parseUploadDocument(load("../../fixtures/states/upload.partial.json"));

function mount(document: UploadDocument) {
  return render(
    <MemoryRouter>
      <UploadSection document={document} tab={null} />
    </MemoryRouter>,
  );
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const sourceRow = (container: HTMLElement, id: string) =>
  container.querySelector<HTMLElement>(`table.reg[data-source-pack] tr[data-source="${id}"]`)!;

describe("Upload", () => {
  test("an older admission refresh cannot replace a newer source pack", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const added = {
      ...live.body.sources[0]!,
      source_id: "66666666-6666-4666-8666-666666666666",
      filename: "second-new.txt",
    };
    const newer = { ...live, body: { ...live.body, sources: [...live.body.sources, added] } };
    let olderAnswer!: (response: Response) => void;
    let newerAnswer!: (response: Response) => void;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            olderAnswer = resolve;
          }),
      )
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            newerAnswer = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetch);
    try {
      mount(live);
      const input = screen.getByLabelText("Documents to admit");
      const submit = screen.getByRole("button", { name: "Admit sources" });
      fireEvent.change(input, { target: { files: [new File(["one"], "first.txt")] } });
      fireEvent.click(submit);
      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
      fireEvent.change(input, { target: { files: [new File(["two"], "second.txt")] } });
      fireEvent.click(submit);
      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
      await act(async () => newerAnswer(jsonResponse(newer)));
      await act(async () => olderAnswer(jsonResponse(live)));
      expect(screen.getByText("second-new.txt")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("a parent source pack wins over a late local refresh", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const added = {
      ...live.body.sources[0]!,
      source_id: "77777777-7777-4777-8777-777777777777",
      filename: "parent-new.txt",
    };
    const parent = { ...live, body: { ...live.body, sources: [...live.body.sources, added] } };
    let answer!: (response: Response) => void;
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      );
    vi.stubGlobal("fetch", fetch);
    try {
      const view = mount(live);
      fireEvent.change(screen.getByLabelText("Documents to admit"), {
        target: { files: [new File(["one"], "first.txt")] },
      });
      fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
      view.rerender(
        <MemoryRouter>
          <UploadSection document={parent} tab={null} />
        </MemoryRouter>,
      );
      await act(async () => answer(jsonResponse(live)));
      expect(screen.getByText("parent-new.txt")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_source_rows_show_filename_digest_admitted_time_extractor_identity_and_set_versions", () => {
    const { container } = mount(fixture);
    expect(container.querySelector("table.reg[data-source-pack]")).not.toBeNull();
    expect(container.querySelectorAll("tr[data-source]")).toHaveLength(fixture.body.sources.length);
    const source = fixture.body.sources[0]!;
    const row = sourceRow(container, source.source_id);
    expect(row).toHaveTextContent(source.filename);
    expect(row).toHaveTextContent(source.extractor_identity!);
    // One treatment for a digest (brief 6.1): 8…4 shown, whole in its title.
    const digest = row.querySelector("[data-digest]")!;
    expect(digest).toHaveAttribute("data-digest", source.document_sha256);
    expect(digest.querySelector("[title]")).toHaveAttribute("title", source.document_sha256);
    expect(digest).toHaveTextContent(
      `${source.document_sha256.slice(0, 8)}…${source.document_sha256.slice(-4)}`,
    );
    const pills = Array.from(row.querySelectorAll(".pill")).map((pill) => pill.textContent);
    expect(pills).toEqual(source.set_versions.map(String));
    // No disposition tag, grade, page count, label or family on the row
    // itself: the v1 SourceRow does not carry them. (The header's own
    // "N WITHDRAWN" count is a different thing — not a per-row disposition.)
    expect(row).not.toHaveTextContent(/ADMITTED|EXCLUDED_LOW_VALUE|PENDING/);
    expect(row.querySelector(".grade")).toBeNull();
  });

  test("a null extractor identity reads as an em dash, not a blank cell", () => {
    const { container } = mount(fixture);
    const withdrawn = fixture.body.sources.find((s) => s.extractor_identity === null)!;
    const row = sourceRow(container, withdrawn.source_id);
    expect(row.querySelectorAll("td")[3]).toHaveTextContent("—");
  });

  test("test_withdrawal_is_checked_live_and_shown", () => {
    const { container } = mount(fixture);
    const live = sourceRow(container, fixture.body.sources[0]!.source_id);
    const clock = `${fixture.observed_at.slice(11, 16)}Z`;
    expect(live).toHaveTextContent(new RegExp(`checked live at ${clock}`));
    expect(live).not.toHaveClass("wd");
    const withdrawn = fixture.body.sources.find((s) => s.withdrawn_at !== null)!;
    const wd = container.querySelector<HTMLElement>("table.reg[data-source-pack] tr.wd")!;
    expect(wd).toHaveAttribute("data-source", withdrawn.source_id);
    expect(wd).toHaveTextContent("Withdrawn");
    expect(wd).toHaveTextContent(new RegExp(`checked live at ${clock}`));
  });

  test("an empty pack says the pack is empty", () => {
    const { container } = mount({ ...fixture, body: { ...fixture.body, sources: [] } });
    expect(container).toHaveTextContent("The pack holds no source.");
  });

  test("set versions show their fingerprint and member count, with no pin state", () => {
    const { container } = mount(fixture);
    const rows = container.querySelectorAll("[data-set-version]");
    expect(rows).toHaveLength(fixture.body.set_versions.length);
    const top = fixture.body.set_versions[0]!;
    const row = container.querySelector<HTMLElement>(`[data-set-version="${top.version}"]`)!;
    expect(row).toHaveTextContent(String(top.member_count));
    expect(row.querySelector("[data-digest]")).toHaveAttribute("data-digest", top.fingerprint);
    // No pinning affordance: 4.1 offers no actions (brief decision 5).
    expect(container.querySelectorAll("[data-set-versions] button")).toHaveLength(0);
  });

  test("a partial document with LIST_TRUNCATED still renders its sources", () => {
    expect(partial.status).toBe("partial");
    expect(partial.notes).toEqual(["LIST_TRUNCATED"]);
    const { container } = mount(partial);
    expect(container.querySelectorAll("tr[data-source]")).toHaveLength(partial.body.sources.length);
  });

  test("test_a_refused_action_renders_its_code_and_clearance_and_is_not_hidden", async () => {
    const refused: UploadDocument = {
      ...fixture,
      chrome: {
        ...fixture.chrome,
        actions: [
          {
            action: "ADMIT_SOURCES",
            refusal: { code: "NOT_AUTHORISED", clears: "your case standing is WRITER or higher" },
          },
        ],
      },
    };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    mount(refused);
    const control = screen.getByRole("button", { name: "Admit sources" });
    expect(control).toBeVisible();
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toBeDisabled();
    expect(control).toHaveAttribute("data-refusal", "NOT_AUTHORISED");
    expect(control.title).toContain("NOT_AUTHORISED");
    expect(control.title).toContain("your case standing is WRITER or higher");
    expect(document.querySelector("[data-refusal='NOT_AUTHORISED']")).not.toBeNull();
    expect(screen.getByText(/your case standing is WRITER or higher/)).toBeInTheDocument();
    fireEvent.click(control);
    await settle();
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test("an available admit-sources action posts a multipart command and refetches on success", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const newSourceId = "22222222-2222-4222-8222-222222222222";
    const refreshed: UploadDocument = {
      ...live,
      body: {
        ...live.body,
        sources: [
          ...live.body.sources,
          {
            source_id: newSourceId,
            filename: "new-filing.pdf",
            document_sha256: "b".repeat(64),
            admitted_at: "2026-09-14T10:00:00Z",
            withdrawn_at: null,
            extractor_identity: null,
            set_versions: [],
          },
        ],
      },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ case_id: live.body.case_id, source_ids: [newSourceId] }, 201),
      )
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const file = new File(["contents"], "new-filing.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText("Documents to admit");
    // The workspace's own button and the names chosen, not the browser's
    // "No file chosen"; still the file input it labels (brief 6.10).
    const chosen = document.querySelector("[data-admit-chosen]")!;
    expect(chosen).toHaveTextContent("No documents chosen");
    fireEvent.change(input, { target: { files: [file] } });
    expect(chosen).toHaveTextContent("new-filing.pdf");
    expect(input).toHaveAttribute("type", "file");
    const control = screen.getByRole("button", { name: "Admit sources" });
    expect(control).not.toHaveAttribute("aria-disabled");
    fireEvent.click(control);
    await settle();
    await settle();

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const [postUrl, postInit] = fetchSpy.mock.calls[0]!;
    expect(postUrl).toBe(`/api/v1/cases/${live.body.case_id}/sources`);
    const form = postInit.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect((form.getAll("document")[0] as File).name).toBe("new-filing.pdf");
    expect(postInit.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(fetchSpy.mock.calls[1]![0]).toBe(`/api/v1/cases/${live.body.case_id}/upload`);

    expect(await screen.findByText("new-filing.pdf")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  test("the file input is cleared after a successful admit", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockResolvedValueOnce(jsonResponse(live));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const file = new File(["contents"], "new-filing.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText("Documents to admit") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    expect(input.files).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    await settle();
    await settle();

    // jsdom's `files` on a file input is a fixed snapshot once fireEvent sets
    // it (there is no real OS picker to clear); `.value` is the one property
    // this control's own reset can move, and is what a real browser clears
    // its displayed filename from.
    expect(input.value).toBe("");
    vi.unstubAllGlobals();
  });

  test("the idempotency key is reused only for a retry of the same file set after offline, and replaced when the set changes", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const fetchSpy = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockResolvedValueOnce(jsonResponse(live));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const fileA = new File(["a"], "a.pdf", { type: "application/pdf" });
    const fileB = new File(["b"], "b.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText("Documents to admit");
    const control = screen.getByRole("button", { name: "Admit sources" });

    fireEvent.change(input, { target: { files: [fileA] } });
    fireEvent.click(control);
    await settle();
    const key1 = fetchSpy.mock.calls[0]![1].headers["Idempotency-Key"];
    // An offline answer is announced, in the one offline sentence.
    expect(screen.getByRole("alert")).toHaveTextContent(OFFLINE_WORDING);

    // Same file set, retried after offline: the same key.
    fireEvent.change(input, { target: { files: [fileA] } });
    fireEvent.click(control);
    await settle();
    const key2 = fetchSpy.mock.calls[1]![1].headers["Idempotency-Key"];
    expect(key2).toBe(key1);

    // A different file set: a fresh key, even though the previous answer was
    // offline.
    fireEvent.change(input, { target: { files: [fileB] } });
    fireEvent.click(control);
    await settle();
    await settle();
    const key3 = fetchSpy.mock.calls[2]![1].headers["Idempotency-Key"];
    expect(key3).not.toBe(key1);
    vi.unstubAllGlobals();
  });

  test("a success whose refetch fails still shows a persistent success note, plus a visible refresh-failed state", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            case_id: live.body.case_id,
            source_ids: [
              "44444444-4444-4444-8444-444444444444",
              "55555555-5555-4555-8555-555555555555",
            ],
          },
          201,
        ),
      )
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchSpy);

    mount(live);
    const file = new File(["contents"], "new-filing.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Documents to admit"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));

    expect(await screen.findByText(/could not.*refresh|refresh.*failed/i)).toBeInTheDocument();
    expect(document.querySelector("[data-admit-sources-success]")).toHaveTextContent("2");
    vi.unstubAllGlobals();
  });

  test("test_a_live_source_offers_withdrawal_and_a_withdrawn_one_offers_nothing", () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "WITHDRAW_SOURCE", refusal: null }] },
    };
    const { container } = mount(live);
    const alive = live.body.sources.find((s) => s.withdrawn_at === null)!;
    const gone = live.body.sources.find((s) => s.withdrawn_at !== null)!;
    const control = sourceRow(container, alive.source_id).querySelector("button")!;
    expect(control).toHaveAttribute("data-action", "WITHDRAW_SOURCE");
    expect(control).toHaveAccessibleName(`Withdraw ${alive.filename}`);
    expect(control).not.toHaveAttribute("aria-disabled");
    // A withdrawn source has no act left to offer: the row already says when
    // it was withdrawn, and the command would answer EVIDENCE_NOT_AVAILABLE.
    expect(sourceRow(container, gone.source_id).querySelector("button")).toBeNull();
  });

  test("a refused withdrawal renders its code and clearance and is not hidden", () => {
    const refused: UploadDocument = {
      ...fixture,
      chrome: {
        ...fixture.chrome,
        actions: [
          {
            action: "WITHDRAW_SOURCE",
            refusal: { code: "NOT_AUTHORISED", clears: "the actor holds WRITER standing" },
          },
        ],
      },
    };
    const { container } = mount(refused);
    const alive = refused.body.sources.find((s) => s.withdrawn_at === null)!;
    const control = sourceRow(container, alive.source_id).querySelector("button")!;
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).toHaveAttribute("data-refusal", "NOT_AUTHORISED");
    expect(container).toHaveTextContent("the actor holds WRITER standing");
    // Said once above the pack, not down the column; each control keeps it
    // as its accessible description.
    const shared = container.querySelectorAll("[data-shared-refusal]");
    expect(shared).toHaveLength(1);
    expect(shared[0]).toHaveTextContent(
      "Withdraw: Available once the actor holds WRITER standing.",
    );
    expect(container.querySelectorAll("[data-withdraw-control] .caos-action-reason")).toHaveLength(
      0,
    );
    expect(control).toHaveAccessibleDescription("Available once the actor holds WRITER standing.");
  });

  test("the pack's two commands refused for one reason say it once", () => {
    // Admit's reason under its button and Withdraw's over the table read one
    // over the other, the same words twice (brief 5, Upload; 6.3).
    const { container } = mount({ ...fixture, chrome: { ...fixture.chrome, actions: [] } });
    const shared = container.querySelectorAll("[data-shared-refusal]");
    expect(shared).toHaveLength(1);
    expect(shared[0]).toHaveTextContent("Admit and withdraw: Not offered on this page yet.");
    const admit = screen.getByRole("button", { name: "Admit sources" });
    expect(admit).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
    expect(admit).toHaveAccessibleDescription("Not offered on this page yet.");
    expect(document.getElementById(admit.getAttribute("aria-describedby")!)).toHaveClass("sr-only");
  });

  test("an absent withdrawal action is ACTION_UNPLACED, and a click sends nothing", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = mount({ ...fixture, chrome: { ...fixture.chrome, actions: [] } });
    const alive = fixture.body.sources.find((s) => s.withdrawn_at === null)!;
    const control = sourceRow(container, alive.source_id).querySelector("button")!;
    expect(control).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
    fireEvent.click(control);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test("test_withdrawing_a_source_posts_its_withdrawal_and_re_reads_the_pack", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "WITHDRAW_SOURCE", refusal: null }] },
    };
    const alive = live.body.sources.find((s) => s.withdrawn_at === null)!;
    const refreshed: UploadDocument = {
      ...live,
      body: {
        ...live.body,
        sources: live.body.sources.map((row) =>
          row.source_id === alive.source_id
            ? { ...row, withdrawn_at: "2026-09-17T09:00:00Z" }
            : row,
        ),
      },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ case_id: live.body.case_id, source_id: alive.source_id }),
      )
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchSpy);

    const { container } = mount(live);
    // Withdrawing asks once more before it is sent (finding FE-7).
    fireEvent.click(sourceRow(container, alive.source_id).querySelector("button")!);
    fireEvent.click(
      sourceRow(container, alive.source_id).querySelector("[data-confirm-yes]") as HTMLElement,
    );
    await settle();
    await settle();

    // `withdrawSource` builds this request and `parseSourceWithdrawn` narrows
    // its receipt; both are driven here through the mounted section rather
    // than called directly, as is `refetchUpload`, the one GET after it.
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe(`/api/v1/cases/${live.body.case_id}/sources/${alive.source_id}/withdrawal`);
    expect(init.method).toBe("POST");
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(fetchSpy.mock.calls[1]![0]).toBe(`/api/v1/cases/${live.body.case_id}/upload`);
    // The pack it re-read is what says the source is gone, never this control.
    expect(sourceRow(container, alive.source_id)).toHaveClass("wd");
    expect(sourceRow(container, alive.source_id).querySelector("button")).toBeNull();
    vi.unstubAllGlobals();
  });

  test("an action absent from chrome.actions is not available, and is refused with ACTION_UNPLACED", () => {
    const noActions: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [] },
    };
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    mount(noActions);
    const control = screen.getByRole("button", { name: "Admit sources" });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
    fireEvent.click(control);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test("a later withdrawal refresh wins over an earlier admission refresh", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: {
        ...fixture.chrome,
        actions: [
          { action: "ADMIT_SOURCES", refusal: null },
          { action: "WITHDRAW_SOURCE", refusal: null },
        ],
      },
    };
    const alive = live.body.sources.find((source) => source.withdrawn_at === null)!;
    const newer: UploadDocument = {
      ...live,
      body: {
        ...live.body,
        sources: live.body.sources.map((source) =>
          source.source_id === alive.source_id
            ? { ...source, withdrawn_at: "2026-09-28T00:00:00Z" }
            : source,
        ),
      },
    };
    let answer!: (response: Response) => void;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)))
      .mockResolvedValueOnce(
        jsonResponse({ case_id: live.body.case_id, source_id: alive.source_id }),
      )
      .mockResolvedValueOnce(jsonResponse(newer));
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = mount(live);
    fireEvent.change(screen.getByLabelText("Documents to admit"), {
      target: { files: [new File(["a"], "first.txt")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: `Withdraw ${alive.filename}` }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm Withdraw source" }));
    });
    expect(sourceRow(container, alive.source_id)).toHaveClass("wd");
    await act(async () => answer(jsonResponse(live)));
    expect(sourceRow(container, alive.source_id)).toHaveClass("wd");
    vi.unstubAllGlobals();
  });

  test("an admission completed after leaving Upload starts no refresh", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    let answer!: (response: Response) => void;
    const fetchSpy = vi.fn(() => new Promise<Response>((resolve) => (answer = resolve)));
    vi.stubGlobal("fetch", fetchSpy);
    const { unmount } = mount(live);
    fireEvent.change(screen.getByLabelText("Documents to admit"), {
      target: { files: [new File(["a"], "first.txt")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    unmount();
    await act(async () =>
      answer(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201)),
    );
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  test("a delayed admission refresh cannot undo a newer withdrawal", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    let answer!: (response: Response) => void;
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)));
    vi.stubGlobal("fetch", fetchSpy);
    const { container, rerender } = mount(live);
    fireEvent.change(screen.getByLabelText("Documents to admit"), {
      target: { files: [new File(["a"], "first.txt")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    const newer: UploadDocument = {
      ...live,
      body: {
        ...live.body,
        sources: live.body.sources.map((row, i) =>
          i === 0 ? { ...row, withdrawn_at: "2026-09-28T00:00:00Z" } : row,
        ),
      },
    };
    rerender(
      <MemoryRouter>
        <UploadSection document={newer} tab={null} />
      </MemoryRouter>,
    );
    expect(sourceRow(container, newer.body.sources[0]!.source_id)).toHaveClass("wd");
    await act(async () => answer(jsonResponse(live)));
    expect(sourceRow(container, newer.body.sources[0]!.source_id)).toHaveClass("wd");
    vi.unstubAllGlobals();
  });

  test("admitting one selection preserves files chosen while its request is pending", async () => {
    const live: UploadDocument = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "ADMIT_SOURCES", refusal: null }] },
    };
    let answer!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => new Promise<Response>((resolve) => (answer = resolve)))
        .mockResolvedValueOnce(jsonResponse(live)),
    );
    const { container } = mount(live);
    const input = screen.getByLabelText("Documents to admit");
    fireEvent.change(input, { target: { files: [new File(["a"], "first.txt")] } });
    fireEvent.click(screen.getByRole("button", { name: "Admit sources" }));
    fireEvent.change(input, { target: { files: [new File(["b"], "second.txt")] } });
    await act(async () =>
      answer(jsonResponse({ case_id: live.body.case_id, source_ids: [] }, 201)),
    );
    expect(container.querySelector("[data-admit-chosen]")).toHaveTextContent("second.txt");
    vi.unstubAllGlobals();
  });
});
