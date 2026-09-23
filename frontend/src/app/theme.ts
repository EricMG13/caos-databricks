// The reader's colour theme: light, dark, or the system's (the default). Only
// an explicit pick is kept, in this browser; `system` keeps nothing. The CSS
// reads the system itself (tokens.css), so a system-dark reader is dark before
// any script has run; a pick sets `.light` or `.dark` on <html>.

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "caos.theme";

export function storedTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

/** Mark <html> for a choice. Transitions are held off until the next frame,
    so every surface repaints at once instead of each fading on its own. */
export function applyTheme(choice: ThemeChoice, root: HTMLElement = document.documentElement) {
  root.classList.add("theme-switching");
  root.classList.toggle("light", choice === "light");
  root.classList.toggle("dark", choice === "dark");
  requestAnimationFrame(() => root.classList.remove("theme-switching"));
}

export function chooseTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // Storage refused (a private window): the choice lasts this page.
  }
  applyTheme(choice);
}
