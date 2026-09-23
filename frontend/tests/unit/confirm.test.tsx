// The confirm step an irreversible governed act asks for (WCAG 3.3.4, finding
// FE-7): sign, freeze, file, withdraw, revoke and cancel. Driven here through
// `ConfirmedControl` itself and, in the section suites, through the sections
// that place it.
import { fireEvent, render, screen } from "@testing-library/react";
import { ConfirmedControl, confirmSentence } from "@/controls/ConfirmedControl";

const STEP = {
  act: "Sign opinion",
  subject: "revision 00000000-0000-4000-8000-0000000000c3",
  digest: `${"a".repeat(60)}beef`,
};

function mount(onConfirm: (() => void) | undefined, busy = false) {
  return render(
    <ConfirmedControl
      action="SIGN_OPINION"
      refusal={null}
      busy={busy}
      step={STEP}
      onConfirm={onConfirm}
      className="rb"
      aria-label="Sign opinion"
    >
      {busy ? "Signing…" : "Sign opinion"}
    </ConfirmedControl>,
  );
}

describe("an irreversible act asks once more", () => {
  test("test_a_single_activation_sends_nothing_until_it_is_confirmed", () => {
    const sent = vi.fn();
    const { container } = mount(sent);
    fireEvent.click(container.querySelector("[data-action='SIGN_OPINION']")!);
    expect(sent).not.toHaveBeenCalled();
    // The step names the act, what it binds and the digest in its short form.
    const step = container.querySelector("[data-confirm='SIGN_OPINION']")!;
    expect(step).toHaveAttribute("role", "group");
    expect(step.querySelector("[data-confirm-sentence]")).toHaveTextContent(
      "Sign opinion — revision 00000000-0000-4000-8000-0000000000c3 · sha256:aaaaaaaa…beef. This cannot be undone.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm Sign opinion" }));
    expect(sent).toHaveBeenCalledOnce();
  });

  test("test_the_confirm_step_takes_focus_and_cancel_gives_it_back", () => {
    const sent = vi.fn();
    const { container } = mount(sent);
    fireEvent.click(container.querySelector("[data-action='SIGN_OPINION']")!);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Confirm Sign opinion" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(sent).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(container.querySelector("[data-action='SIGN_OPINION']"));
  });

  test("test_escape_closes_the_confirm_step_and_returns_focus_to_the_opener", () => {
    const sent = vi.fn();
    const { container } = mount(sent);
    const opener = () => container.querySelector("[data-action='SIGN_OPINION']");
    fireEvent.click(opener()!);
    fireEvent.keyDown(screen.getByRole("button", { name: "Confirm Sign opinion" }), {
      key: "Escape",
    });
    expect(container.querySelector("[data-confirm='SIGN_OPINION']")).toBeNull();
    expect(sent).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(opener());
  });

  test("an act this document does not name is refused, with no step to open", () => {
    const { container } = mount(undefined);
    const control = container.querySelector("[data-action='SIGN_OPINION']")!;
    expect(control).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
    fireEvent.click(control);
    expect(container.querySelector("[data-confirm='SIGN_OPINION']")).toBeNull();
  });

  test("a step with no digest names the act and its subject only", () => {
    expect(confirmSentence({ act: "Cancel run", subject: "run r-1", digest: null })).toBe(
      "Cancel run — run r-1. This cannot be undone.",
    );
  });

  // FE-1's visible half, on a control that carries a fixed aria-label: while
  // the command is in flight the label would override the one thing that
  // changed, so it steps aside for the busy text.
  test("test_a_busy_control_is_aria_disabled_and_named_by_its_busy_text", () => {
    const sent = vi.fn();
    const { container } = mount(sent, true);
    const control = container.querySelector("[data-action='SIGN_OPINION']")!;
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).toHaveAttribute("aria-busy", "true");
    expect(control).not.toHaveAttribute("aria-label");
    expect(screen.getByRole("button", { name: "Signing…" })).toBe(control);
    fireEvent.click(control);
    expect(container.querySelector("[data-confirm='SIGN_OPINION']")).toBeNull();
  });
});
