// Every route the gates drive: the nine sections in their default fixture, the
// fixture states each section must render distinctly, and the two page-level
// wordings. One list, so the a11y matrix and the workbench share it.
export const SECTIONS = [
  "directory",
  "upload",
  "analysis",
  "book",
  "run",
  "model",
  "report",
  "committee",
  "admin",
];

/** The sections served in every mode; Admin renders `unavailable` with no
    request (brief 4.1, decision 9). Mirrors src/app/sections.ts. */
export const ENABLED_SECTIONS = [
  "directory",
  "upload",
  "run",
  "analysis",
  "book",
  "model",
  "report",
  "committee",
];
export const DISABLED_SECTIONS = SECTIONS.filter((section) => !ENABLED_SECTIONS.includes(section));

/** The demo fixtures' case, for a section still on the legacy wire. A case
    section with no case sends no request. */
export const DEMO_CASE = "CASE-2026-CVNA01";

/** Every enabled section's v1 fixture carries the case as a UUID. Run,
    Analysis and Model (slices 4.1i-k) share one case id; Upload pins its own. */
export const DEMO_CASE_BY_SECTION = {
  upload: "ff1fbf5a-e56f-4f84-a983-2f5a507675f0",
  run: "00000000-0000-4000-8000-000000000001",
  analysis: "00000000-0000-4000-8000-000000000001",
  model: "00000000-0000-4000-8000-000000000001",
  report: "00000000-0000-4000-8000-000000000001",
  committee: "00000000-0000-4000-8000-000000000001",
};

export const DEMO_RUN_BY_SECTION = {
  report: "00000000-0000-4000-8000-0000000000b2",
  committee: "00000000-0000-4000-8000-0000000000b2",
};
export const DEMO_REVISION_BY_SECTION = {
  report: "00000000-0000-4000-8000-0000000000c3",
  committee: "00000000-0000-4000-8000-0000000000c3",
};

/** A section's page, with the demo case where the section is case-scoped.
    @param {string} section
    @param {string | null} [fixture] */
export function sectionRoute(section, fixture = null) {
  const params = new URLSearchParams();
  if (["upload", "run", "analysis", "model", "report", "committee"].includes(section)) {
    params.set("case", DEMO_CASE_BY_SECTION[section] ?? DEMO_CASE);
  }
  if (DEMO_RUN_BY_SECTION[section]) params.set("run", DEMO_RUN_BY_SECTION[section]);
  if (DEMO_REVISION_BY_SECTION[section]) params.set("revision", DEMO_REVISION_BY_SECTION[section]);
  if (fixture) params.set("fixture", fixture);
  const search = params.toString();
  return `/${section}/${search ? `?${search}` : ""}`;
}

/** A section's `acts` fixture with the confirm step of `action` opened: the
    a11y gate presses the act's control before it scans (`arm`), so the step
    is measured as a reader sees it. The page itself ignores the parameter.
    @param {string} section
    @param {string} action */
export function armedRoute(section, action) {
  return `${sectionRoute(section, "acts")}&arm=${action}`;
}

export const STATE_ROUTES = [
  sectionRoute("directory", "observed-empty"),
  sectionRoute("book", "observed-empty"),
  sectionRoute("upload", "partial"),
  sectionRoute("analysis", "partial"),
  sectionRoute("analysis", "stale"),
  sectionRoute("analysis", "offline"),
  sectionRoute("analysis", "unavailable"),
  sectionRoute("analysis", "error"),
  sectionRoute("run", "gate"),
  // Every act the demo otherwise serves refused, offered: the filing acts,
  // withdraw, revoke and cancel among them. Refused, a control carries its
  // reason line and is spaced by it; offered, it is not, and until these
  // states the gate had never measured one (DF-9).
  sectionRoute("directory", "acts"),
  sectionRoute("upload", "acts"),
  sectionRoute("run", "acts"),
  sectionRoute("report", "acts"),
  armedRoute("report", "SIGN_OPINION"),
  armedRoute("upload", "WITHDRAW_SOURCE"),
  "/analysis/",
  "/nothing/",
];

export const ROUTES = [...SECTIONS.map((section) => sectionRoute(section)), ...STATE_ROUTES];

// 320x640 is 400% zoom on a 1280 px display, which is what WCAG 1.4.10 asks
// of reflow: without it the matrix never measured a narrow viewport and the
// register, the book cells and the withdraw controls were clipped out of
// reach with nothing to scroll them (finding FE-5).
export const VIEWPORTS = ["1440x900", "1280x800", "1024x768", "320x640"];
export const ENGINES = ["chromium", "firefox", "webkit"];

/** The page has settled: the loading marker is gone and either the chrome
    or a state region is on screen. Both are required, so a skeleton is never
    scanned as a page. */
export const LOADING = "main#body [data-surface-state='loading']";
export const SETTLED = "main#body [data-summary], main#body [data-surface-state]";
