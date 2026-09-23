import { expect, test } from "@playwright/test";

// The evidence drawer over the v1 page fixture (brief 4.4, decisions 7-9).
const CASE = "00000000-0000-4000-8000-000000000001";
const SOURCE = "f9b54532-f1d3-48b8-bca2-5e29b9d3b16b";
const QUOTE = "Carvana Co. is an e-commerce platform for buying and selling used cars.";

// The demo event stream advances one frame counter shared by every test, so a
// concurrent spec could change the document under an open drawer. These specs
// are about the drawer, not the stream: it is refused here.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/cases/*/events*", (route) => route.abort("connectionfailed"));
});

test("the highlight covers the rendered words of the matched text", async ({ page }) => {
  await page.goto(`/analysis/?case=${CASE}&tab=rn-cp-0`);
  await page.locator(`[data-fact-chip='${SOURCE}']`).click();
  const drawer = page.locator("[data-evidence-drawer]");
  await expect(drawer).toContainText("Text layer from the token index");
  const line = drawer.locator("[data-page-line]", { hasText: QUOTE });
  const highlight = drawer.locator("[data-highlight]");
  await expect(line).toBeVisible();
  await expect(highlight).toHaveCount(1);
  // The highlight and the line are placed from the same stored rectangle.
  // Polled: the drawer may still be settling when it first becomes visible.
  await expect
    .poll(async () => {
      const words = await line.boundingBox();
      const box = await highlight.boundingBox();
      if (!words || !box) return false;
      return (
        Math.abs(box.x - words.x) <= 3 &&
        Math.abs(box.y - words.y) <= 3 &&
        Math.abs(box.width - words.width) <= 4 &&
        Math.abs(box.height - words.height) <= 4
      );
    })
    .toBe(true);
  // Every word is drawn inside that box, none clipped past its right edge.
  const clipped = await line.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(clipped).toBeLessThanOrEqual(1);
});

test("Escape returns focus to the chip that opened the drawer", async ({ page }) => {
  await page.goto(`/analysis/?case=${CASE}&tab=rn-cp-0`);
  const chip = page.locator(`[data-fact-chip='${SOURCE}']`);
  await chip.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(chip).toBeFocused();
});
