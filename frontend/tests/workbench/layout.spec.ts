import { expect, test, type Locator } from "@playwright/test";

// Layout the unit suite cannot see: jsdom lays nothing out, so a label that runs
// into its neighbour or text cut through the middle of a line is only caught
// where an engine draws the page. Each test measures what a reader sees.

/** How many lines an element's own text is drawn on. */
function lines(locator: Locator) {
  return locator.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const tops = [...range.getClientRects()]
      .filter((rect) => rect.width > 0)
      .map((rect) => Math.round(rect.top));
    return new Set(tops).size;
  });
}

test("route stage headers stay in their columns and node reasons are never cut mid-line", async ({
  page,
}) => {
  await page.goto("/run/?case=00000000-0000-4000-8000-000000000001");
  await expect(page.locator(".dag[data-route]")).toBeVisible();
  const layout = await page.evaluate(() => {
    const headers = [...document.querySelectorAll(".stagehdr")].map((header) =>
      header.getBoundingClientRect(),
    );
    const nodes = [...document.querySelectorAll("button.node")];
    const firstRow = Math.min(...nodes.map((node) => node.getBoundingClientRect().top));
    const overlaps = headers.slice(1).filter((header, i) => headers[i]!.right > header.left + 0.5);
    const crowding = headers.filter((header) => header.bottom > firstRow + 0.5);
    const clipped = nodes.filter((node) => {
      const why = node.querySelector(".why")!.getBoundingClientRect();
      return why.bottom > node.getBoundingClientRect().bottom + 0.5;
    });
    return {
      headers: headers.length,
      overlaps: overlaps.length,
      crowding: crowding.length,
      clipped: clipped.length,
    };
  });
  expect(layout.headers).toBeGreaterThan(1);
  expect(layout).toMatchObject({ overlaps: 0, crowding: 0, clipped: 0 });
});

test("timestamps never wrap inside themselves", async ({ page }) => {
  // Report's module-id rule and the prose-wrap rule rode Model and Committee,
  // which are unavailable in every mode (brief 4.1, decision 9). Upload reads
  // the v1 wire since slice 4.1h, whose case is a UUID.
  await page.goto("/upload/?case=00000000-0000-4000-8000-000000000001");
  const stamp = page.locator("tr.wd [data-withdrawal] time").first();
  await expect(stamp).toBeVisible();
  expect(await lines(stamp)).toBe(1);
  expect(await stamp.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
});

test("a long pinned Directory title leaves its row action clickable", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  const title = `Issuer${"X".repeat(160)}`;
  await page.route("**/api/v1/directory", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.body.cases[0].title = title;
    await route.fulfill({ response, json: body });
  });
  await page.goto("/directory/");
  const region = page.getByRole("region", { name: "Case register rows" });
  const link = page.getByRole("link", { name: `Open case ${title}` });
  await expect(link).toBeVisible();
  await region.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  const box = await link.boundingBox();
  expect(box).toBeTruthy();
  const hit = await page.evaluate(
    ({ x, y }) => document.elementFromPoint(x, y)?.closest("a")?.getAttribute("aria-label"),
    { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 },
  );
  expect(hit).toBe(`Open case ${title}`);
});

test("a selected Run node stays with its detail before the action controls", async ({ page }) => {
  await page.route("**/api/v1/cases/*/events*", (route) => route.abort("connectionfailed"));
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/run/?case=00000000-0000-4000-8000-000000000001");
  await page.locator('button.node[data-node="CP-5"]').click();
  const detail = page.locator('[data-node-detail="CP-5"]');
  await expect(detail).toBeVisible();
  const focus = page.locator('[data-run-focus="CP-5"]');
  await expect(focus).toContainText("Evidence trace validator · CP-5");
  await expect(focus).toContainText("Complete · accepted");
  const focusBox = await focus.boundingBox();
  expect(focusBox).toBeTruthy();
  expect(focusBox!.y + focusBox!.height).toBeLessThan(768);
  const reason = await detail.locator(".node-reason").textContent();
  expect(reason).toBeTruthy();
  expect(await focus.textContent()).toContain(reason!);
  const route = page.locator(".dag[data-route]");
  const actions = page.locator(".actgroup");
  const routeBox = await route.boundingBox();
  const detailBox = await detail.boundingBox();
  const actionBox = await actions.boundingBox();
  expect(routeBox && detailBox && actionBox).toBeTruthy();
  expect(detailBox!.y).toBeGreaterThanOrEqual(routeBox!.y + routeBox!.height);
  expect(detailBox!.y + detailBox!.height).toBeLessThanOrEqual(actionBox!.y);

  await page.setViewportSize({ width: 1280, height: 720 });
  const wideRoute = await route.boundingBox();
  const wideDetail = await detail.boundingBox();
  expect(wideRoute && wideDetail).toBeTruthy();
  expect(wideDetail!.x).toBeGreaterThanOrEqual(wideRoute!.x + wideRoute!.width);
  await expect(focus).toBeHidden();
});

test("the saved Report begins with its narrative", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(
    "/report/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3",
  );
  const narrative = page.locator("[data-report-narrative]");
  await expect(narrative).toBeVisible();
  const heading = await narrative.locator("h2").boundingBox();
  const firstParagraph = await narrative
    .locator("[data-narrative-paragraph]")
    .first()
    .boundingBox();
  expect(heading && firstParagraph).toBeTruthy();
  expect(heading!.y).toBeLessThan(720);
  expect(firstParagraph!.y).toBeLessThan(720);
});

test("the Book title survives zoom reflow in both colour schemes", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto("/book/?case=00000000-0000-4000-8000-000000000001");
    const title = page.getByRole("heading", { name: "Book", level: 1 });
    await expect(title).toBeVisible();
    await expect(page.getByText("Partial", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Colour theme" })).toBeVisible();
    const titleBox = await title.boundingBox();
    expect(titleBox).toBeTruthy();
    expect(titleBox!.x + titleBox!.width).toBeLessThanOrEqual(320);
    expect(await title.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(
      1,
    );
  }
});

test("Analysis keeps the selected module name and review reason visible at desk and zoom widths", async ({
  page,
}) => {
  await page.route("**/api/v1/cases/*/events*", (route) => route.abort("connectionfailed"));
  for (const width of [1280, 320]) {
    await page.setViewportSize({ width, height: width === 320 ? 640 : 720 });
    await page.goto("/analysis/?case=00000000-0000-4000-8000-000000000001&tab=rn-cp-1c");
    const selected = page.locator("[data-selected-view]");
    await expect(selected).toContainText("Peer benchmark");
    await expect(selected).toContainText("one peer's most recent filing is more than 200 days old");
    await expect(selected).toHaveAttribute("aria-live", "polite");
    const box = await selected.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(box!.y).toBeLessThan(width === 320 ? 640 : 720);
    await expect(page.locator("[data-summary-review]")).toContainText(
      "was accepted with a review point",
    );
  }
  await page.goto("/analysis/?case=00000000-0000-4000-8000-000000000001");
  await page.locator("[data-summary-review] a").click();
  await expect(page).toHaveURL(/tab=rn-cp-1c/);
});

test("Analysis module names support keyboard selection and zoom reflow in both themes", async ({
  page,
}) => {
  await page.route("**/live.js?*", (route) => route.abort());
  await page.route("**/api/v1/cases/*/events*", (route) => route.abort("connectionfailed"));
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/analysis/?case=00000000-0000-4000-8000-000000000001&tab=rn-cp-0");
    const issuer = page.getByRole("banner").locator("[data-case]");
    await expect(issuer).toBeVisible();
    expect(
      await issuer.evaluate((node) => {
        const style = getComputedStyle(node);
        return {
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          height: node.getBoundingClientRect().height,
        };
      }),
    ).toEqual({ fontSize: "16px", fontWeight: "500", height: 24 });
    const tabs = page.getByRole("tablist", { name: "Analysis views" });
    const source = tabs.getByRole("tab", { name: /^Source readiness\s*, success$/ });
    await expect(source).toBeVisible();
    await expect(source).toHaveAttribute("aria-selected", "true");
    expect(
      await source.evaluate((node) => ({
        height: node.getBoundingClientRect().height,
        padding: getComputedStyle(node).paddingLeft,
      })),
    ).toEqual({ height: 28, padding: "6px" });
    await source.press("ArrowRight");
    await expect(page).toHaveURL(/tab=rn-cp-1$/);
    await expect(
      tabs.getByRole("tab", { name: /^Canonical data foundation\s*, success$/ }),
    ).toBeFocused();
    await tabs.getByRole("tab", { name: /^Canonical data foundation\s*, success$/ }).press("End");
    await expect(page).toHaveURL(/tab=rn-cp-cf$/);
    await expect(tabs.getByRole("tab", { name: /^Cash-flow forecast\s*, success$/ })).toBeVisible();
    await page.setViewportSize({ width: 320, height: 640 });
    await expect(issuer).not.toBeVisible();
    await expect(page.getByRole("heading", { name: "Analysis", level: 1 })).toBeVisible();
    const select = page.getByRole("combobox", { name: "Analysis view", exact: true });
    await expect(select).toBeVisible();
    await expect(select.locator("option").first()).toHaveText("Source readiness");
    await select.selectOption("rn-cp-1c");
    await expect(page).toHaveURL(/tab=rn-cp-1c$/);
    await expect(page.locator("[data-selected-view]")).toContainText("Peer benchmark");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
  }
});
