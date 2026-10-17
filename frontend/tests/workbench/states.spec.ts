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
  // Said in plain words, the typed code beside it for anyone who quotes it.
  await expect(region).toContainText("The store did not answer.");
  await expect(region).toContainText("STORE_UNAVAILABLE");
});

test("partial renders through warning status with its notes and the body", async ({ page }) => {
  await page.goto(`/analysis/?case=${CASE}&fixture=partial`);
  // Said once, in the summary: its verdict and its notes (brief 6.2); the
  // region draws the document rather than a third telling of the warning.
  const summary = page.locator("main#body [data-summary]");
  await expect(summary).toContainText("Partial");
  await expect(page.locator("main#body [data-surface-state='partial']")).toHaveCount(0);
  await expect(page.locator("[data-handoff]").first()).toBeVisible();
  await expect(page.locator("[data-pending-node]").first()).toBeVisible();
});

test("a blocked Analysis shows the Blocked quotes under the node that ended the run", async ({
  page,
}) => {
  await page.goto(`/analysis/?case=${CASE}&fixture=blocked`);
  const row = page.locator("[data-pending-node][data-blocking='yes']");
  await expect(row).toBeVisible();
  await expect(row.locator("[data-blocked-quotes='recorded']")).toBeVisible();
  await expect(row.locator("[data-blocked-quote]")).toHaveCount(2);
});

test("a stale view holds its figures until Reload", async ({ page }) => {
  // The fixture stream announces an accepted handoff; the refetch answers for
  // another displayed run with other figures (brief 4.4, decision 6).
  await page.goto(`/analysis/?case=${CASE}&fixture=stale&tab=rn-cp-0`);
  const figure = page.locator("main#body [data-confidence]").first();
  await expect(figure).toHaveText(/^96 /);
  const stale = page.locator("main#body [data-surface-state='stale']");
  await expect(stale).toBeVisible({ timeout: 10_000 });
  await expect(figure).toHaveText(/^96 /);
  await stale.getByRole("button", { name: "Reload" }).click();
  await expect(stale).toHaveCount(0);
  await expect(figure).toHaveText(/^12 /);
});

test("a read under the desk-wide grant asks for nothing a member alone may read", async ({
  page,
}) => {
  // The fixture serves Analysis as the grant does: no standing, no actions, no
  // id of the case's other runs. The page then opens no event stream and
  // requests no other section, and draws no mutation control.
  const requests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) requests.push(`${request.method()} ${path}`);
  });
  await page.goto(`/analysis/?case=${CASE}&fixture=granted&tab=rn-cp-0`);
  await expect(page.locator("[data-handoff]").first()).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Add to Book|Withdraw|Start|Retry|Cancel/ }),
  ).toHaveCount(0);
  // Let any stream the page might open show itself.
  await page.waitForTimeout(1_000);
  expect(
    requests.filter((request) => /\/(events|run|report|committee|revisions)\b/.test(request)),
  ).toEqual([]);
  expect(requests.filter((request) => request.startsWith("POST"))).toEqual([]);
});
