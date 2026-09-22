import { expect, test } from "@playwright/test";
import { DEMO_CASE_BY_SECTION } from "../../scripts/fixture-routes.mjs";

const CASE = DEMO_CASE_BY_SECTION.analysis;

test("offline is one page-level sentence and never engine text", async ({ page }) => {
  // The transport fails here rather than at the fixture middleware, which
  // simulates offline by destroying the socket. That reset carries no response,
  // so a browser may legitimately retry the request (RFC 9110 9.2.2) -- WebKit
  // does, and the retry's backoff outran this assertion on main. Aborting the
  // route states the same thing the middleware means, in one engine-independent
  // step: the request never reached the server. It has to be a transport
  // failure and not a status, because `fetchSection` reads offline from a
  // rejected `fetch` and every status is some other state.
  await page.route("**/api/v1/**", (route) => route.abort("connectionfailed"));
  await page.goto(`/analysis/?case=${CASE}&fixture=offline`);
  const alert = page.locator("[data-page-alert]");
  await expect(alert).toHaveCount(1);
  await expect(alert).toHaveText("The request did not reach the server.");
  await expect(page.getByText("The request did not reach the server.")).toHaveCount(1);
  await expect(page.locator("main#body [data-surface-state='offline']")).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText(/TypeError|Failed to fetch|ECONNRESET/);
});

test("observed-empty is timestamped and never inferred", async ({ page }) => {
  await page.goto("/directory/?fixture=observed-empty");
  const region = page.locator("main#body [data-surface-state='observed-empty']");
  await expect(region).toBeVisible();
  await expect(region.locator("time[datetime]")).toHaveCount(1);
});

test("a typed refusal shows its code and what clears it", async ({ page }) => {
  await page.goto(`/analysis/?case=${CASE}&fixture=error`);
  const region = page.locator("main#body [data-surface-state='error']");
  await expect(region).toContainText("STORE_UNAVAILABLE");
  await expect(region).toContainText("Clears when");
});

test("partial renders through warning status with its notes and the body", async ({ page }) => {
  await page.goto(`/analysis/?case=${CASE}&fixture=partial`);
  await expect(page.locator("main#body [data-surface-state='partial']")).toBeVisible();
  await expect(page.locator("[data-handoff]").first()).toBeVisible();
  await expect(page.locator("[data-pending-node]").first()).toBeVisible();
});

test("a stale view holds its figures until Reload", async ({ page }) => {
  // The fixture stream announces an accepted handoff; the refetch answers for
  // another displayed run with other figures (brief 4.4, decision 6).
  await page.goto(`/analysis/?case=${CASE}&fixture=stale`);
  const figure = page.locator("main#body [data-confidence]").first();
  await expect(figure).toHaveText(/^96 /);
  const stale = page.locator("main#body [data-surface-state='stale']");
  await expect(stale).toBeVisible({ timeout: 10_000 });
  await expect(figure).toHaveText(/^96 /);
  await stale.getByRole("button", { name: "RELOAD" }).click();
  await expect(stale).toHaveCount(0);
  await expect(figure).toHaveText(/^12 /);
});
