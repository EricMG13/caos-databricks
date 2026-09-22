import { expect, test } from "@playwright/test";

// The v1 fixture's ids (brief 4.1, slice 4.1i): fixture-routes.mjs's
// `DEMO_CASE` is not a UUID and is shared with sections not yet cut over, so
// this file names its own case and run ids to match `fixtures/run.json` and
// `fixtures/states/*.json` directly (see the deviation note in the task report).
const CASE = "00000000-0000-4000-8000-000000000001";
const RUN_LATEST = "00000000-0000-4000-8000-0000000000b2";
const RUN_OLDER = "00000000-0000-4000-8000-0000000000a1";

test("the route reads as a DAG, the QA gate as a gate, and the stream advances a frame", async ({
  page,
}) => {
  await page.goto(`/run/?case=${CASE}&run=${RUN_LATEST}`);
  await expect(page.locator(".dag[data-route]")).toBeVisible();
  await expect(page.locator("[data-gate]")).toContainText("QA_GATE");
  const cp6 = page.locator("button.node[data-node='CP-6']");
  await expect(cp6).toHaveAttribute("data-state", "RUNNABLE");
  // The fixture stream emits run_progress; the client refetches and renders
  // the later frame.
  await expect(cp6).toHaveAttribute("data-state", "COMPLETE", { timeout: 10_000 });
});

test("the route is a preview, not yet pinned", async ({ page }) => {
  await page.goto(`/run/?case=${CASE}&fixture=gate`);
  await expect(page.locator("[data-route-not-pinned]")).toBeVisible();
  await expect(page.locator(".dag[data-route]")).toHaveAttribute("data-route", "0 nodes · 0 edges");
});

test("a displayed run behind the latest is labelled, never silently swapped", async ({ page }) => {
  await page.goto(`/run/?case=${CASE}&run=${RUN_OLDER}&fixture=superseded`);
  await expect(page.locator("[data-stale-run]")).toBeVisible();
  const row = page.locator(`[data-run-row='${RUN_OLDER}']`);
  await expect(row).toHaveAttribute("data-displayed", "true");
  await expect(row).toHaveAttribute("data-latest", "false");
});

test("a dropped stream resumes after its Last-Event-ID", async ({ page }) => {
  // `drop` ends the first connection after frame 0.2. A client that restarted
  // without its marker would be dropped at 0.2 again and never see 0.3.
  const resumed = page.waitForRequest(
    async (request) =>
      request.url().includes(`/api/v1/cases/${CASE}/events`) &&
      (await request.allHeaders())["last-event-id"] === "0.2",
  );
  await page.goto(`/run/?case=${CASE}&run=${RUN_LATEST}&fixture=drop`);
  await resumed;
  await expect(page.locator("button.node[data-node='CP-6']")).toHaveAttribute(
    "data-state",
    "COMPLETE",
    { timeout: 10_000 },
  );
});
