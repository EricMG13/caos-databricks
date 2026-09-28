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
  await expect(page.locator("[data-route-not-pinned]")).toContainText("Route not pinned");
  // Nothing to draw: the empty pattern, no canvas of dot grid (brief 6.6).
  await expect(page.locator(".dag")).toHaveCount(0);
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

test("the subject's four fields are two pairs, never three and a stray", async ({ page }) => {
  // At 1440 the card held three columns of fields and put the fourth alone
  // on a row (brief 6.10); four fields are two pairs at any width that holds two.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/run/?case=${CASE}&fixture=acts`);
  const fields = page.locator("[data-pin-input] > .pb > label.fld");
  await expect(fields).toHaveCount(4);
  const tops = await fields.evaluateAll((labels) =>
    labels.map((label) => Math.round(label.getBoundingClientRect().top)),
  );
  expect(new Set(tops).size).toBe(2);
  expect(tops[0]).toBe(tops[1]);
  expect(tops[2]).toBe(tops[3]);
});

test("dependency flow preserves keyboard selection and reduced motion at desk and zoom widths", async ({
  page,
}, testInfo) => {
  await page.route("**/live.js?*", (route) => route.abort());
  await page.route("**/api/v1/cases/*/events*", (route) => route.abort("connectionfailed"));
  await page.route("**/api/v1/cases/*/run*", async (route) => {
    const response = await route.fetch();
    const document = await response.json();
    document.body.run.nodes.find(
      (node: { module_id: string }) => node.module_id === "CP-6",
    ).awaiting_gate = false;
    await route.fulfill({ response, json: document });
  });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "no-preference" });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/run/?case=${CASE}`);
    const dag = page.locator(".dag");
    await dag.scrollIntoViewIfNeeded();
    const flow = page.locator(".route-flow");
    await expect(flow).toHaveAttribute("data-motion", "active");
    const active = page.locator('.edges path[data-progress="active"]:not(.gate)');
    await expect(active).toHaveCount(1);
    await expect(active).toHaveClass(/caos-running/);
    expect(
      await active.evaluate((path) => {
        const style = getComputedStyle(path);
        return { animation: style.animationName, duration: style.animationDuration };
      }),
    ).toEqual({ animation: "caos-pulse", duration: "1.92s" });
    const cp5 = page.locator('button.node[data-node="CP-5"]');
    await cp5.press("Enter");
    await expect(cp5).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator('[data-node-detail="CP-5"]')).toBeVisible();
    const gate = page.locator(".edges path.gate");
    await expect(gate).toHaveAttribute("data-connected", "true");
    expect(await gate.evaluate((path) => getComputedStyle(path).strokeWidth)).toBe("3px");
    expect(await gate.getAttribute("marker-end")).toBe(
      `url(#${await page.locator(".edges marker").getAttribute("id")})`,
    );
    if (testInfo.project.name === "chromium") {
      await page.screenshot({ path: testInfo.outputPath(`route-${colorScheme}-desk.png`) });
    }

    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await active.evaluate((path) => getComputedStyle(path).animationName)).toBe("none");
    expect(await gate.evaluate((path) => getComputedStyle(path).strokeWidth)).toBe("3px");
    await expect(cp5).toHaveAttribute("aria-pressed", "true");
    await page.setViewportSize({ width: 320, height: 640 });
    await dag.scrollIntoViewIfNeeded();
    const box = await dag.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
    await expect(cp5).toHaveAttribute("aria-pressed", "true");
    if (testInfo.project.name === "chromium") {
      await page.screenshot({ path: testInfo.outputPath(`route-${colorScheme}-zoom.png`) });
    }
  }
});
