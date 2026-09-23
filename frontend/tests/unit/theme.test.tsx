// The reader's theme is theirs: the system's until they pick one, and only a
// pick is kept. The sidebar turns into a sheet below md, read from the media
// query itself.
import { render } from "@testing-library/react";
import { applyTheme, chooseTheme, storedTheme } from "@/app/theme";
import { useIsMobile } from "@/hooks/use-mobile";

const root = document.documentElement;

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  root.className = "";
});

test("the system's theme is the default, and only a pick is kept", () => {
  expect(storedTheme()).toBe("system");
  chooseTheme("dark");
  expect(storedTheme()).toBe("dark");
  expect(root).toHaveClass("dark");
  expect(root).not.toHaveClass("light");
  chooseTheme("light");
  expect(root).toHaveClass("light");
  expect(root).not.toHaveClass("dark");
  chooseTheme("system");
  expect(localStorage.getItem("caos.theme")).toBeNull();
  expect(root).not.toHaveClass("light");
  expect(root).not.toHaveClass("dark");
  // Anything else stored reads as no pick at all.
  localStorage.setItem("caos.theme", "sepia");
  expect(storedTheme()).toBe("system");
});

test("a theme change repaints at once: transitions are held for one frame", () => {
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  applyTheme("dark");
  expect(root).toHaveClass("dark", "theme-switching");
  frames.forEach((callback) => callback(0));
  expect(root).not.toHaveClass("theme-switching");
});

test("storage that refuses leaves the choice for this page and never throws", () => {
  vi.stubGlobal("localStorage", {
    getItem: () => {
      throw new Error("denied");
    },
    setItem: () => {
      throw new Error("denied");
    },
    removeItem: () => {
      throw new Error("denied");
    },
  });
  expect(storedTheme()).toBe("system");
  expect(() => chooseTheme("dark")).not.toThrow();
  expect(root).toHaveClass("dark");
});

function Probe() {
  return <output>{useIsMobile() ? "sheet" : "sidebar"}</output>;
}

test("useIsMobile reads the media query, and a page without one is a desktop", () => {
  vi.stubGlobal("matchMedia", undefined);
  const { container, unmount } = render(<Probe />);
  expect(container).toHaveTextContent("sidebar");
  unmount();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(max-width: 767px)",
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
  expect(render(<Probe />).container).toHaveTextContent("sheet");
});
