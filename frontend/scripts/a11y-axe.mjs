// axe-core over the static export, on three engines, nine routes plus every
// fixture state, at three viewports. No remote code: axe is injected from
// node_modules. WCAG 2.0/2.1/2.2 A+AA plus best-practice, and three layout
// probes the WCAG tags miss (clipped controls, target size, page overflow).
// Floor: the result matrix must contain every engine x route x viewport entry
// with zero scan_error, else exit 1 — a matrix with a hole is not a pass.
// Adapted from the predecessor's scripts/a11y-axe.mjs at f454c65.
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox, webkit } from "playwright";
import { summarizeAxeViolations } from "./axe-results.mjs";
import { ENGINES, LOADING, ROUTES, SETTLED, VIEWPORTS } from "./fixture-routes.mjs";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const PORT = 4173;
const BASE = process.env.BASE || `http://localhost:${PORT}`;
const resultFile = process.env.A11Y_RESULT_FILE || "a11y-results/matrix.json";
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const engines = (process.env.ENGINES || ENGINES.join(",")).split(",");
// WIDTHxHEIGHT parsed by hand rather than `/^(\d+)x(\d+)$/` — the same
// anchor-adjacent quantified shape already replaced elsewhere in this
// codebase (javascript/typescript:S8786).
function isDigits(part) {
  return part.length > 0 && [...part].every((ch) => ch >= "0" && ch <= "9");
}
function parseViewport(value) {
  const trimmed = value.trim();
  const x = trimmed.indexOf("x");
  if (x < 0) return null;
  const width = trimmed.slice(0, x);
  const height = trimmed.slice(x + 1);
  return isDigits(width) && isDigits(height)
    ? { width: Number(width), height: Number(height) }
    : null;
}
const viewports = (process.env.VIEWPORTS || VIEWPORTS.join(",")).split(",").map((value) => {
  const parsed = parseViewport(value);
  if (!parsed) throw new Error(`bad viewport "${value}"`);
  return parsed;
});
const routes = process.env.ROUTES ? process.env.ROUTES.split(",") : ROUTES;

// The pinned binary by path, never `npx`: `npx` resolves through PATH and may
// fetch and run a package's lifecycle scripts, and its wrapper process does not
// forward a signal to vite — which then holds the port the workbench needs.
const VITE = fileURLToPath(new URL("../node_modules/vite/bin/vite.js", import.meta.url));

async function startPreview() {
  if (process.env.BASE) return null;
  const child = spawn(
    process.execPath,
    [
      VITE,
      "preview",
      "--mode",
      "demo",
      "--outDir",
      "dist-demo",
      "--strictPort",
      "--port",
      String(PORT),
    ],
    {
      stdio: ["ignore", "pipe", "inherit"],
      // Its own process group, so the kill below reaches every child.
      detached: true,
    },
  );
  await new Promise((resolveReady, reject) => {
    const timer = setTimeout(() => reject(new Error("vite preview did not start")), 30_000);
    child.stdout.on("data", (output) => {
      if (String(output).includes(String(PORT))) {
        clearTimeout(timer);
        resolveReady();
      }
    });
    child.on("exit", (code) => reject(new Error(`vite preview exited ${code}`)));
  });
  return child;
}

const LAYOUT_PROBE = () => {
  const rootWidth = document.documentElement.clientWidth;
  const visible = (element) => {
    if (element.matches(".sr-only:not(:focus), [hidden]")) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity) !== 0 &&
      rect.width > 0 &&
      rect.height > 0 &&
      !element.closest('[aria-hidden="true"]')
    );
  };
  const scrollOwner = (element) => {
    let parent = element.parentElement;
    while (parent && parent !== document.body) {
      const style = getComputedStyle(parent);
      if (/(auto|scroll)/.test(style.overflowX) && parent.scrollWidth > parent.clientWidth + 1) {
        return true;
      }
      parent = parent.parentElement;
    }
    return false;
  };
  const interactive = [
    ...document.querySelectorAll(
      'a[href], button, input, select, textarea, [role="button"], [role="tab"], [tabindex]:not([tabindex="-1"])',
    ),
  ]
    .filter(visible)
    .filter((element) => !element.matches(":disabled"));
  const describe = (element, dimensions) => ({
    tag: element.tagName.toLowerCase(),
    label: (element.getAttribute("aria-label") || element.textContent || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 120),
    ...dimensions,
  });
  const clipped = interactive
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      return (rect.left < -1 || rect.right > rootWidth + 1) && !scrollOwner(element);
    })
    .slice(0, 20)
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return describe(element, { left: Math.round(rect.left), right: Math.round(rect.right) });
    });
  // WCAG 2.2 target-size exempts a target that sits in a sentence: an inline
  // element with non-whitespace text among its siblings.
  const inSentence = (element) =>
    getComputedStyle(element).display.startsWith("inline") &&
    [...(element.parentNode?.childNodes ?? [])].some(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== "",
    );
  const small = interactive
    .filter((element) => !inSentence(element))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width >= 24 && rect.height >= 24) return false;
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      return interactive.some((other) => {
        if (other === element) return false;
        const o = other.getBoundingClientRect();
        return Math.hypot(cx - (o.left + o.width / 2), cy - (o.top + o.height / 2)) < 24;
      });
    })
    .slice(0, 20)
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return describe(element, { width: Math.round(rect.width), height: Math.round(rect.height) });
    });
  const overflow =
    Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0) - rootWidth;
  return {
    page_overflow_px: Math.max(0, Math.round(overflow)),
    clipped_controls: clipped,
    target_size_failures: small,
  };
};

function layoutFails(layout) {
  return (
    (layout.page_overflow_px || 0) > 1 ||
    layout.clipped_controls.length > 0 ||
    layout.target_size_failures.length > 0
  );
}

async function scan(page, route, viewport) {
  await page.setViewportSize(viewport);
  await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 30_000 });
  try {
    await page.locator("main#body").waitFor({ state: "attached", timeout: 15_000 });
    await page.locator(LOADING).waitFor({ state: "detached", timeout: 15_000 });
    await page.locator(SETTLED).first().waitFor({ state: "attached", timeout: 15_000 });
  } catch (error) {
    return { url: route, viewport, scan_error: `not ready: ${error.message}`, violations: [] };
  }
  await page.addScriptTag({ path: axePath });
  const raw = await page.evaluate(async (tags) => {
    const result = await window.axe.run(document, { runOnly: { type: "tag", values: tags } });
    return result.violations;
  }, TAGS);
  const violations = summarizeAxeViolations(raw, { nodeLimit: 4, includeHtml: true });
  const layout = await page.evaluate(LAYOUT_PROBE);
  return { url: route, viewport, layout, violations };
}

const preview = await startPreview();
const out = {};
try {
  for (const engineName of engines) {
    const engine = { chromium, firefox, webkit }[engineName];
    const browser = await engine.launch();
    const page = await browser.newPage({ viewport: viewports[0] });
    for (const viewport of viewports) {
      for (const route of routes) {
        const key = `${engineName} ${route} @${viewport.width}x${viewport.height}`;
        console.error(`axe: ${key}`);
        try {
          out[key] = await scan(page, route, viewport);
        } catch (error) {
          out[key] = { url: route, viewport, scan_error: error.message, violations: [] };
        }
      }
    }
    await browser.close();
  }
} finally {
  if (preview) {
    try {
      process.kill(-preview.pid, "SIGTERM");
    } catch {
      // already gone
    }
    // Wait for the port to be released before the workbench claims it.
    await Promise.race([once(preview, "exit"), new Promise((r) => setTimeout(r, 10_000))]);
  }
}

const expected = engines.length * viewports.length * routes.length;
let nodes = 0;
let scanErrors = 0;
let layoutFailures = 0;
const failing = {};
for (const [key, result] of Object.entries(out)) {
  if (result.scan_error) scanErrors += 1;
  if (result.layout && layoutFails(result.layout)) layoutFailures += 1;
  for (const violation of result.violations) nodes += violation.n;
  if (
    result.scan_error ||
    result.violations.length ||
    (result.layout && layoutFails(result.layout))
  ) {
    failing[key] = result;
  }
}
const summary = {
  base: BASE,
  tags: TAGS,
  engines,
  viewports,
  routes,
  entries: Object.keys(out).length,
  expected_entries: expected,
  violation_nodes: nodes,
  scan_errors: scanErrors,
  layout_failures: layoutFailures,
  failing,
};
await mkdir(dirname(resultFile), { recursive: true });
await writeFile(resultFile, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ ...summary, failing: undefined }, null, 2));
if (Object.keys(failing).length) console.log(JSON.stringify(failing, null, 2));
const complete = Object.keys(out).length === expected;
if (!complete) console.error(`matrix incomplete: ${Object.keys(out).length}/${expected}`);
process.exit(complete && nodes === 0 && scanErrors === 0 && layoutFailures === 0 ? 0 : 1);
