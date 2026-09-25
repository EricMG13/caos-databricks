import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Digest } from "@/ds/Digest";

const HASH = `0b582ff0${"a".repeat(52)}30df`;

describe("Digest: one treatment for an id or a digest (brief 6.1)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("is short on the page and whole in its title and to a screen reader", () => {
    const { container } = render(<Digest value={HASH} prefix="sha256:" copy={false} />);
    const shown = container.querySelector(`[title="sha256:${HASH}"]`)!;
    expect(shown).toHaveTextContent("sha256:0b582ff0…30df");
    expect(shown).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".sr-only")).toHaveTextContent(`sha256:${HASH}`);
    expect(container.querySelector("[data-digest]")).toHaveAttribute(
      "data-digest",
      `sha256:${HASH}`,
    );
  });

  it("reads a missing value as its fallback, with nothing to copy", () => {
    const { container } = render(<Digest value={null} fallback="not pinned" />);
    expect(container).toHaveTextContent("not pinned");
    expect(container.querySelector("button")).toBeNull();
  });

  it("draws no copy control where the browser has no clipboard, or on the paper", () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const { container, rerender } = render(<Digest value={HASH} />);
    expect(container.querySelector("button")).toBeNull();
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    rerender(<Digest value={HASH} copy={false} />);
    expect(container.querySelector("button")).toBeNull();
  });

  it("copies the whole value in one press and says so beside the control", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<Digest value={HASH} prefix="sha256:" />);
    const control = screen.getByRole("button", { name: `Copy sha256:${HASH}` });
    await act(async () => {
      fireEvent.click(control);
      await Promise.resolve();
    });
    expect(writeText).toHaveBeenCalledWith(`sha256:${HASH}`);
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says so when the browser refuses the write, rather than seeming to do nothing", async () => {
    const writeText = vi.fn(() => Promise.reject(new Error("denied")));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<Digest value={HASH} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: `Copy ${HASH}` }));
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Not copied");
  });
});
