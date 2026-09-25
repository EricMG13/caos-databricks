import { expect, test, type Page } from "@playwright/test";
import {
  DISABLED_SECTIONS,
  ENABLED_SECTIONS,
  SECTIONS,
  sectionRoute,
} from "../../scripts/fixture-routes.mjs";

// Every enabled section reads the v1 wire (brief 4.1, decision 9; slices
// 4.1h-k). `composeChrome` (decision 5) composes an empty `ribbon.actions`
// for every one of them, because 4.1 offers no action; a still-disabled
// section never reaches a ribbon at all.
const V1_SECTIONS = ENABLED_SECTIONS;

/** The API paths a page asked for while it loaded. */
function apiRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname.startsWith("/api/")) seen.push(pathname);
  });
  return seen;
}

for (const section of SECTIONS) {
  const disabled = DISABLED_SECTIONS.includes(section);
  test(`${section}: the header names the section above the body, one nav, served role read-only`, async ({
    page,
  }) => {
    const requests = apiRequests(page);
    await page.goto(sectionRoute(section, disabled ? "reader" : null));
    await expect(page.locator("main#body [data-surface-state='loading']")).toHaveCount(0);
    // One banner, outside the body, whose heading is the section.
    const banner = page.getByRole("banner");
    await expect(banner).toHaveCount(1);
    await expect(banner.getByRole("heading", { level: 1 })).toHaveCount(1);
    const bannerPrecedes = await page.evaluate(() => {
      const header = document.querySelector("header");
      const body = document.querySelector("main#body");
      return Boolean(
        header &&
        body &&
        !body.contains(header) &&
        header.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    });
    expect(bannerPrecedes).toBe(true);
    // A section with a document summarises it at the top of the body; one with
    // none says its state in the header and the region, and nothing else.
    await expect(page.locator("main#body section[aria-label='Summary']")).toHaveCount(
      disabled ? 0 : 1,
    );
    await expect(page.locator("nav")).toHaveCount(1);
    const demo = page.getByRole("complementary", { name: "Demonstration mode" });
    await expect(demo).toContainText("Read-only demonstration");
    await expect(demo).toContainText("nothing is persisted");
    for (const off of DISABLED_SECTIONS) {
      await expect(page.locator(`nav a[data-section='${off}']`)).toContainText("Unavailable");
    }
    if (disabled) {
      // Disabled in every mode, demo included: no document, no request, no tail.
      await expect(page.locator("main#body [data-surface-state='unavailable']")).toHaveCount(1);
      await expect(page.locator("[data-served-role]")).toHaveCount(0);
      await expect(page.locator("header [data-primary]")).toHaveCount(0);
      expect(requests).toEqual([]);
      return;
    }
    const role = page.locator("[data-served-role]");
    await expect(role).toHaveCount(1);
    await expect(role.locator("button, a, select, input")).toHaveCount(0);
    // Every enabled section's composed ribbon offers no action (brief 4.1,
    // decision 5).
    expect(V1_SECTIONS).toContain(section);
    await expect(page.locator("header [data-primary]")).toHaveCount(0);
  });
}

test("a case section with no case is unavailable and sends no request", async ({ page }) => {
  const requests = apiRequests(page);
  await page.goto("/analysis/");
  await expect(page.locator("main#body [data-surface-state='unavailable']")).toHaveCount(1);
  expect(requests).toEqual([]);
});

test("on a wide desk screen the summary stops at its reading measure", async ({ page }) => {
  // Desktop only (D63), and a wide screen is the ordinary case: the summary
  // card spans the body, but its verdict, headline and cells stop at 78rem
  // rather than sitting 400px apart (D64).
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(sectionRoute("run"));
  const summary = page.locator("main#body section[aria-label='Summary']");
  await expect(summary).toBeVisible();
  const measure = await summary.evaluate((card) => {
    const left = card.getBoundingClientRect().left;
    const right = (selector: string) =>
      Math.max(
        ...[...card.querySelectorAll(selector)].map((el) => el.getBoundingClientRect().right),
      );
    return {
      card: card.getBoundingClientRect().width,
      headline: right("[data-headline]") - left,
      cells: right("[data-cell]") - left,
    };
  });
  const limit = 78 * 16;
  expect(measure.card).toBeGreaterThan(limit);
  expect(measure.headline).toBeLessThanOrEqual(limit);
  expect(measure.cells).toBeLessThanOrEqual(limit);
});
