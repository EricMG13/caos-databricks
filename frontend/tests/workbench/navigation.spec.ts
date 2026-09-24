import { expect, test } from "@playwright/test";

test("the rail is the only navigation and reaches all nine sections", async ({ page }) => {
  await page.goto("/directory/");
  const links = page.locator("nav a[data-section]");
  await expect(links).toHaveCount(9);
  await links.filter({ hasText: "Committee" }).click();
  await expect(page).toHaveURL(/\/committee\/$/);
  await expect(page.locator("nav a[aria-current='page']")).toHaveAttribute(
    "data-section",
    "committee",
  );
  await expect(page.locator("main#body [data-surface-state='unavailable']")).toHaveCount(1);
});

test("command-K opens nothing", async ({ page }) => {
  await page.goto("/analysis/");
  await page.keyboard.press("ControlOrMeta+KeyK");
  await expect(page.locator("[role='dialog']")).toHaveCount(0);
});

test("a pre-v2 slug forwards with its query intact and history replaced", async ({ page }) => {
  await page.goto("/directory/");
  // `commit`, not the default `load`: the slug forwards itself as soon as the
  // document runs, so waiting for the load event of a page that is already
  // being replaced is a race. WebKit lost it twice under CI load, timing out
  // in `goto` at 30s. The assertion below polls, so nothing is given up.
  await page.goto("/deepdive/?case=CASE-2026-CVNA01", { waitUntil: "commit" });
  await expect(page).toHaveURL(/\/analysis\/\?case=CASE-2026-CVNA01$/);
  await page.goBack();
  // The forward replaced history: back lands on the entry before the slug.
  await expect(page).toHaveURL(/\/directory\/$/);
});

test("an absent route shares the private-404 wording", async ({ page }) => {
  await page.goto("/nothing/");
  await expect(page.locator("main#body")).toContainText("Unavailable or not permitted.");
  await page.goto("/analysis/?case=CASE-2026-CVNA01&fixture=unavailable");
  await expect(page.locator("main#body")).toContainText("Unavailable or not permitted.");
});

test("demo fixture HTTP is read-only before fixture selection", async ({ request }) => {
  const get = await request.get("/api/v1/directory");
  expect(get.status()).toBe(200);
  expect(await get.json()).toHaveProperty("chrome");
  const run = await request.get("/api/v1/cases/CASE-2026-CVNA01/run");
  expect(run.status()).toBe(200);
  const model = await request.get("/api/v1/cases/00000000-0000-4000-8000-000000000001/model");
  expect(model.status()).toBe(200);
  expect((await model.json()).body.forecast.route_node_id).toBe("CP-CF");
  // Only supported v1 paths are served.
  for (const path of ["/api/sections/directory", "/api/v1/cases/CASE-2026-CVNA01/book"]) {
    expect((await request.get(path)).status(), path).toBe(404);
  }

  const post = await request.post("/api/v1/directory?fixture=../../directory");
  expect(post.status()).toBe(405);
  expect(post.headers()["allow"]).toBe("GET, HEAD");
  expect(await post.json()).toEqual({
    code: "READ_ONLY_DEMO",
    clears: "a real API handles commands",
  });
});

test("demo Model, Report, and Committee routes render parsed v1 content", async ({ page }) => {
  await page.goto("/model/?case=00000000-0000-4000-8000-000000000001");
  await expect(page.locator("[data-model-v1]")).toBeVisible();
  await expect(page.locator("[data-model-periods]")).toContainText("123.45");
  await expect(page.locator("main#body [data-surface-state]")).toHaveCount(0);
  await page.goto(
    "/report/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3",
  );
  await expect(page.locator("[data-report-v1]")).toBeVisible();
  await expect(page.locator("[data-report-narrative]")).toContainText("Coverage 2.1x");
  await page.goto(
    "/committee/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3",
  );
  await expect(page.locator("[data-committee-v1]")).toBeVisible();
  await expect(page.locator("[data-committee-filing]")).toHaveAttribute("data-state", "filed");
  // Read only: no field, and the one kind of button is a narrative figure's
  // chip, which opens its source page (N59) with its hidden line marked (N27).
  await expect(page.locator("[data-committee-v1] input")).toHaveCount(0);
  await expect(page.locator("[data-committee-v1] button:not([data-figure-chip])")).toHaveCount(0);
  await page.locator("[data-figure-chip]").click();
  const drawer = page.locator("[data-evidence-drawer]");
  await expect(drawer).toContainText("page 7");
  await expect(drawer.locator("[data-page-line]")).toHaveCount(3);
  await expect(drawer.locator("[data-page-line][data-hidden='near_background']")).toHaveCount(1);
  await expect(drawer.locator("[data-hidden-lines]")).toContainText("1 line on this page");
});

test("saved artifacts preserve canonical tables in contained scroll viewers", async ({ page }) => {
  const routes = [
    [
      "/report/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3",
      ["[data-report-artifact-text]", "[data-report-artifact-record]"],
    ],
    [
      "/committee/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3",
      ["[data-committee-artifact-text]", "[data-committee-artifact-record]"],
    ],
  ] as const;
  const table = `| Metric | Value |\n| --- | --- |\n| ${"wide-cell ".repeat(80)}| 2.1x |`;

  for (const [route, selectors] of routes) {
    await page.goto(route);
    for (const selector of selectors) {
      const viewer = page.locator(selector).first();
      await viewer.evaluate((element, text) => {
        element.textContent = text;
      }, table);
      await expect(viewer).toHaveText(table);
      await expect(viewer).toHaveJSProperty("tagName", "PRE");
      await expect(viewer).toHaveCSS("overflow-x", "auto");
      await expect(
        viewer.evaluate((element) => element.scrollWidth > element.clientWidth),
      ).resolves.toBe(true);
      await viewer.focus();
      await expect(viewer).toBeFocused();
      await page.keyboard.press("ArrowRight");
      expect(await viewer.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
    }
  }
});
