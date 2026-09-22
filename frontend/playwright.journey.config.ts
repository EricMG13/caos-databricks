import { defineConfig, devices } from "@playwright/test";

// The real-stack journey (Task 4.5 decision 11, slice 4.5e2). Run only by
// `tests/journey/run.py`, which brings up the disposable smoke stack and the
// test edge on 127.0.0.1:18080 *before* this config is loaded, and tears both
// down afterwards -- so there is no `webServer` entry here, unlike
// `playwright.config.ts`'s demo-fixture workbench. `workers: 1` and no
// retries: the journey drives one shared browser page through one shared
// case end to end, and a flake here is a defect in the real stack, not
// something to paper over.
export default defineConfig({
  testDir: "tests/journey",
  // The worker-kill-and-restart test waits out a real 300 s work lease
  // (server/store/work.py's LEASE_SECONDS) before the restarted container
  // may resume the run -- see that test's own comment -- stacked with the
  // reload-driven polling `waitForNode` uses instead of trusting the SSE
  // tail to repaint live (the tail does stay open against the real API; it
  // is the repaint under browser automation that this journey no longer
  // depends on), so this carries real margin on top of the lease itself.
  timeout: 900_000,
  expect: { timeout: 15_000 },
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: process.env.CI ? "line" : "list",
  // TLS under the throwaway self-signed certificate `tests/journey/run.py`
  // mints per run (docs/DECISIONS.md section 93), which is what lets the
  // edge's cookie carry `Secure` and the `__Host-` prefix; the browser is
  // told to accept that one certificate's errors and nothing else changes.
  use: {
    baseURL: "https://127.0.0.1:18080",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
