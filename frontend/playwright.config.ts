import { defineConfig, devices } from "@playwright/test";

// The workbench smoke: three engines, no retries — a flake is a defect. Runs
// against the separate demo export served by `vite preview`, whose fixture
// middleware answers the wire.
export default defineConfig({
  testDir: "tests/workbench",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "line" : "list",
  use: { baseURL: "http://localhost:4173", trace: "retain-on-failure" },
  webServer: {
    command: "npm run preview:demo",
    url: "http://localhost:4173/directory/",
    reuseExistingServer: false,
    timeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
