// The demonstration Admin fixture is prose about the deployment, and prose
// can go stale while every shape check still passes. `server/api/health.py`
// has served `GET /api/health` since §53.8; the fixture said it was not.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const RAW = readFileSync(resolve(process.cwd(), "fixtures", "admin.json"), "utf8");

describe("the demonstration admin fixture", () => {
  test("test_the_demonstration_admin_panel_names_the_health_route_as_served", () => {
    // No wording anywhere in it may call the health route unserved.
    expect(RAW).not.toMatch(/health[^"]*not served/i);
    const fixture = JSON.parse(RAW) as {
      chrome: { ribbon: { chips: { label: string }[] } };
      body: { missing: { name: string; code: string }[] };
    };
    const inventory = fixture.body.missing.find((entry) =>
      entry.name.startsWith("Deployment inventory"),
    );
    expect(inventory?.code).toBe("GET /api/health · SERVED, NO PANEL");
    const chips = fixture.chrome.ribbon.chips.map((chip) => chip.label);
    expect(chips).toContain("HEALTH · SERVED");
  });
});
