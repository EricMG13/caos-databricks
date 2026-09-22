import routes from "@/app/routes.json";
import { forward, sectionFromPath } from "@/app/sections";
import { SECTIONS } from "@/wire/shared";

describe("the forwarding table", () => {
  test("test_forwarding_table_preserves_query_and_replaces_history", () => {
    expect(forward("/deepdive/", "?case=CASE-2026-CVNA01")).toEqual({
      to: "/analysis/?case=CASE-2026-CVNA01",
      replace: true,
    });
    expect(forward("/deepdive", "?case=X&tab=cp-2")).toEqual({
      to: "/analysis/?case=X&tab=cp-2",
      replace: true,
    });
    expect(forward("/issuers/profile", "?id=CASE-2026-CVNA01")).toEqual({
      to: "/analysis/?case=CASE-2026-CVNA01",
      replace: true,
    });
    expect(forward("/pipeline", "")).toEqual({ to: "/run/", replace: true });
    expect(forward("/login", "")).toEqual({ to: "/directory/", replace: true });
    expect(forward("/", "?case=X")).toEqual({ to: "/directory/?case=X", replace: true });
  });

  test("every pre-v2 slug forwards to one of the nine sections", () => {
    for (const [slug, target] of Object.entries(routes.forwards)) {
      expect(forward(slug, "")?.to).toBe(target);
      expect(sectionFromPath(target)).not.toBeNull();
    }
    expect(routes.sections).toEqual(SECTIONS.map((section) => `/${section}/`));
  });

  test("a section without its trailing slash is the same section", () => {
    expect(forward("/analysis", "?case=X")).toEqual({ to: "/analysis/?case=X", replace: true });
    expect(forward("/analysis/", "?case=X")).toBeNull();
  });

  test("an absent route does not forward", () => {
    expect(forward("/nothing/", "")).toBeNull();
    expect(forward("/analysis/deep/", "")).toBeNull();
  });
});
