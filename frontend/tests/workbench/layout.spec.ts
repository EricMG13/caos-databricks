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
  await page.goto("/upload/?case=ff1fbf5a-e56f-4f84-a983-2f5a507675f0");
  const stamp = page.locator("tr.wd [data-withdrawal] time").first();
  await expect(stamp).toBeVisible();
  expect(await lines(stamp)).toBe(1);
  expect(await stamp.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
});
