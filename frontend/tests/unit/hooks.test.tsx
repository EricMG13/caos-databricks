// The hooks and the two label maps the workspace exports. A hook is reached by
// rendering something that calls it, so the section suites exercise them
// without naming any — which is what left their failure modes untested:
// `useEvidence` outside its provider, and a tail opened where `EventSource`
// does not exist. `useLedger`'s two cases went with the Book (decision D2).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { SECTION_ABBREVIATIONS, SECTION_LABELS } from "@/app/sections";
import { useEvidence } from "@/evidence/EvidenceContext";
import { Overlay } from "@/evidence/Overlay";
import { SECTIONS } from "@/wire/shared";

describe("every section has a word and an abbreviation", () => {
  test("both maps cover the nine, and the strip rail's is one word each", () => {
    expect(Object.keys(SECTION_LABELS).sort()).toEqual([...SECTIONS].sort());
    expect(Object.keys(SECTION_ABBREVIATIONS).sort()).toEqual([...SECTIONS].sort());
    for (const section of SECTIONS) {
      expect(SECTION_ABBREVIATIONS[section]).toHaveLength(2);
      expect(SECTION_LABELS[section]).not.toContain(" ");
    }
  });
});

describe("a hook outside its provider says so rather than rendering nothing", () => {
  test("useEvidence outside a provider opens nothing and holds no chip", () => {
    // Deliberately the other answer: the drawer belongs to the page it was
    // opened on, so a component that asks for it off-page gets a context that
    // does nothing rather than an exception that blanks the section.
    function AsksOffPage() {
      const evidence = useEvidence();
      return <span>{String(evidence.activeChip)}</span>;
    }
    render(<AsksOffPage />);
    expect(screen.getByText("null")).toBeInTheDocument();
  });
});

describe("the evidence overlay returns focus to the opener it was given (N64)", () => {
  // The opener is passed, never inferred from focus: WebKit does not focus a
  // clicked button, and an inferred opener drops focus to the landmark.
  function Opens({ onClose, nested = false }: { onClose: () => void; nested?: boolean }) {
    const opener = useRef<HTMLButtonElement>(null);
    const inner = useRef<HTMLButtonElement>(null);
    const [open, setOpen] = useState(false);
    const [second, setSecond] = useState(false);
    return (
      <>
        <button ref={opener} onClick={() => setOpen(true)}>
          open
        </button>
        {open ? (
          <Overlay
            look="modal"
            title="First"
            opener={opener.current}
            onClose={() => (setOpen(false), onClose())}
          >
            <button ref={inner} onClick={() => setSecond(true)}>
              inside
            </button>
            {nested && second ? (
              <Overlay
                look="drawer"
                title="Second"
                opener={inner.current}
                onClose={() => setSecond(false)}
              >
                <p>second</p>
              </Overlay>
            ) : null}
          </Overlay>
        ) : null}
      </>
    );
  }

  const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

  test("Escape closes it and focus returns to its opener", async () => {
    const closed = vi.fn();
    render(<Opens onClose={closed} />);
    fireEvent.click(screen.getByText("open"));
    await settle();
    expect(screen.getByRole("dialog", { name: "First" })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await settle();
    expect(closed).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByText("open"));
  });

  test("Escape closes only the topmost of two, and focus returns to that one's opener", async () => {
    const closed = vi.fn();
    render(<Opens onClose={closed} nested />);
    fireEvent.click(screen.getByText("open"));
    await settle();
    fireEvent.click(screen.getByText("inside"));
    await settle();
    expect(screen.getByRole("dialog", { name: "Second" })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await settle();
    expect(screen.queryByRole("dialog", { name: "Second" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "First" })).toBeInTheDocument();
    expect(closed).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByText("inside"));
  });

  test("the close button closes it", async () => {
    const closed = vi.fn();
    render(<Opens onClose={closed} />);
    fireEvent.click(screen.getByText("open"));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: /Close/ }));
    await settle();
    expect(closed).toHaveBeenCalledOnce();
  });

  // FE-4: an opener that has left the page cannot take focus. Calling focus()
  // on it silently drops focus to <body>, which is what the caller's own
  // fallback (SourceDrawer's section heading) exists to prevent -- so the
  // overlay must not call it at all.
  test("test_focus_is_not_handed_to_an_opener_that_has_left_the_page", async () => {
    const gone = window.document.createElement("button");
    const focused = vi.fn();
    gone.focus = focused;
    function Gone() {
      const [open, setOpen] = useState(true);
      return open ? (
        <Overlay look="modal" title="Gone" opener={gone} onClose={() => setOpen(false)}>
          <span>panel</span>
        </Overlay>
      ) : null;
    }
    render(<Gone />);
    await settle();
    expect(gone.isConnected).toBe(false);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await settle();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(focused).not.toHaveBeenCalled();
  });
});
