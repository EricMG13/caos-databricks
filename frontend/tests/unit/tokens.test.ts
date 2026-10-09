// The theme's own consistency (D122). A stylesheet that reads a custom
// property nothing defines draws nothing there -- `color-mix()` over an
// undefined `var()` is invalid at computed-value time, so the fill or edge
// silently goes (F613). A remapped page ink must reach every surface's text,
// with a dark menu lighter than the card it floats over (F614). And a status
// badge is its tint over the card, so the bands and rows depth adds under it
// cannot take its words below 4.5:1 (F615).
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const STYLES = resolve(process.cwd(), "src/styles");
const SRC = resolve(process.cwd(), "src");

function sources(directory: string, suffix: RegExp): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(directory, entry.name);
    if (entry.isDirectory()) return sources(full, suffix);
    return suffix.test(entry.name) ? [readFileSync(full, "utf8")] : [];
  });
}

const sheets = sources(STYLES, /\.css$/);
const tokens = readFileSync(resolve(STYLES, "tokens.css"), "utf8");
// Each theme's own values: light on :root, dark in its variant block.
const [light = "", dark = ""] = tokens.split("@variant dark");

function value(theme: string, name: string): string {
  return new RegExp(`--${name}:\\s*([^;]+);`).exec(theme)?.[1]?.trim() ?? "";
}

/** An oklch() token's lightness, the axis "lighter than" is read on. */
function lightness(theme: string, name: string): number {
  return Number(/^oklch\(([\d.]+)/.exec(value(theme, name))?.[1] ?? Number.NaN);
}

test("reads no custom property that no stylesheet, @property or style prop defines", () => {
  const defined = new Set<string>();
  for (const sheet of sheets) {
    for (const match of sheet.matchAll(/(--[\w-]+)\s*:/g)) defined.add(match[1]!);
    for (const match of sheet.matchAll(/@property\s+(--[\w-]+)/g)) defined.add(match[1]!);
  }
  // A value computed at runtime goes through a style prop (the production CSP).
  for (const source of sources(SRC, /\.tsx?$/)) {
    for (const match of source.matchAll(/["'](--[\w-]+)["']\s*:/g)) defined.add(match[1]!);
  }
  const read = new Set(
    sheets.flatMap((sheet) => [...sheet.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]!)),
  );
  expect(read.size).toBeGreaterThan(50);
  expect([...read].filter((name) => !defined.has(name))).toEqual([]);
});

test("sets card, menu, secondary and accent text in the page's own ink, in both themes", () => {
  for (const theme of [light, dark]) {
    const ink = value(theme, "foreground");
    expect(ink).not.toBe("");
    for (const name of [
      "card-foreground",
      "popover-foreground",
      "secondary-foreground",
      "accent-foreground",
    ]) {
      expect(value(theme, name), name).toBe(ink);
    }
    expect(value(theme, "sidebar-ring")).toBe(value(theme, "ring"));
  }
});

test("lifts a dark menu above the card it floats over, and a card above the canvas", () => {
  expect(lightness(dark, "popover")).toBeGreaterThan(lightness(dark, "card"));
  expect(lightness(dark, "card")).toBeGreaterThan(lightness(dark, "background"));
  expect(lightness(light, "card")).toBeGreaterThan(lightness(light, "background"));
});

test("fills every status badge, tag and citation chip with its tint over the card, never over what lies under it", () => {
  const [caos = "", charts = ""] = ["caos.css", "charts.css"].map((name) =>
    readFileSync(resolve(STYLES, name), "utf8"),
  );
  for (const tone of ["success", "warning", "destructive", "info"]) {
    expect(value(tokens, `${tone}-tint`), tone).toBe(
      `color-mix(in oklab, var(--${tone}) var(--tint), var(--card))`,
    );
  }
  // A tinted fill that mixes with `transparent` shows the band, row or menu
  // beneath it: the dark header band took destructive words to 4.46:1.
  for (const sheet of [caos, charts]) {
    for (const rule of sheet.matchAll(/\.(?:tag\.\w+|chip)\s*\{[^}]*\}/g)) {
      expect(rule[0]).not.toMatch(/var\(--tint\), transparent\)/);
    }
  }
  const badge = readFileSync(resolve(SRC, "components/ui/badge.tsx"), "utf8");
  expect(badge).not.toMatch(/bg-(?:success|warning|destructive|info)\/1[05]\b/);
});
