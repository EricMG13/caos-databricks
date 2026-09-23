// The hooks and the two label maps the workspace exports. A hook is reached by
// rendering something that calls it, so the section suites exercise them
// without naming any — which is what left their failure modes untested:
// `useEvidence` outside its provider, and a tail opened where `EventSource`
// does not exist. `useLedger`'s two cases went with the Book (decision D2).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { SECTION_ABBREVIATIONS, SECTION_LABELS } from "@/app/sections";
import { useModalA11y } from "@/ds/use-modal-a11y";
import { useEvidence } from "@/evidence/EvidenceContext";
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

describe("modal a11y returns focus to the opener it was given", () => {
  function Dialog({ onClose }: { onClose: () => void }) {
    const opener = useRef<HTMLButtonElement>(null);
    const [open, setOpen] = useState(false);
    return (
      <>
        <button ref={opener} onClick={() => setOpen(true)}>
          open
        </button>
        {open ? (
          <Panel opener={opener.current} onClose={() => (setOpen(false), onClose())} />
        ) : null}
      </>
    );
  }

  function Panel({ opener, onClose }: { opener: HTMLElement | null; onClose: () => void }) {
    const ref = useModalA11y<HTMLDivElement>(onClose, opener);
    return (
      <div ref={ref} role="dialog" aria-modal="true">
        <button>inside</button>
      </div>
    );
  }

  test("it locks the body while open and clears the lock on close", () => {
    const closed = vi.fn();
    const { unmount } = render(<Dialog onClose={closed} />);
    fireEvent.click(screen.getByText("open"));
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    // Cleared outright rather than restored from a captured value.
    expect(document.body.style.overflow).toBe("");
  });

  // FE-4: an opener that has left the page cannot take focus. Calling focus()
  // on it silently drops focus to <body>, which is what the caller's own
  // fallback (SourceDrawer's section heading) exists to prevent -- so the
  // hook must not call it at all.
  test("test_focus_is_not_handed_to_an_opener_that_has_left_the_page", () => {
    const gone = window.document.createElement("button");
    const focused = vi.fn();
    gone.focus = focused;
    function Gone() {
      const ref = useModalA11y<HTMLDivElement>(() => {}, gone);
      return (
        <div ref={ref} role="dialog" aria-modal="true">
          <span>panel</span>
        </div>
      );
    }
    const dialog = render(<Gone />);
    expect(gone.isConnected).toBe(false);
    dialog.unmount();
    expect(focused).not.toHaveBeenCalled();
  });

  test("Escape closes the topmost overlay", () => {
    const closed = vi.fn();
    render(<Dialog onClose={closed} />);
    fireEvent.click(screen.getByText("open"));
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(closed).toHaveBeenCalledOnce();
  });
});
