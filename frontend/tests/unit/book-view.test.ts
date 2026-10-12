// The Book view state: pure, URL round-trip (spec B12-B14).
import { describe, expect, it } from "vitest";
import {
  DEFAULT_VIEW,
  LOCKED,
  MOODYS_SCALE,
  SP_FITCH_SCALE,
  fromParams,
  toParams,
  type BookView,
} from "@/sections/book/view";

const roundTrip = (view: BookView): BookView =>
  fromParams(new URLSearchParams(toParams(view).toString()));

describe("book view", () => {
  it("round-trips every normalised view through URLSearchParams", () => {
    const views: BookView[] = [
      DEFAULT_VIEW,
      {
        basis: "PF_LTM",
        columns: [
          "id:issuer_name",
          "id:reporting_period",
          "m:revenue",
          "m:metric:net_leverage_adjusted@DOWNSIDE_FY1",
        ],
        filters: [
          { kind: "range", column: "m:revenue", min: "100.50", max: null },
          { kind: "range", column: "m:total_debt", min: null, max: "-3" },
          { kind: "set", column: "id:sector", values: ["Media, Telecom", "a|b", "C&D=1"] },
          { kind: "notch", agency: "moodys", best: "Baa3", worst: "B1" },
        ],
        sort: { column: "m:revenue", dir: "desc" },
        currency: "EUR",
      },
      { ...DEFAULT_VIEW, basis: "BASE_FY1", sort: { column: "id:composite", dir: "asc" } },
      { ...DEFAULT_VIEW, columns: [...LOCKED] },
    ];
    for (const view of views) expect(roundTrip(view)).toEqual(view);
  });

  it("keeps decimals as exact strings", () => {
    const view: BookView = {
      ...DEFAULT_VIEW,
      filters: [
        {
          kind: "range",
          column: "m:revenue",
          min: "0.1000000000000000055",
          max: "12345678901234567890.5",
        },
      ],
    };
    expect(roundTrip(view).filters).toEqual(view.filters);
  });

  it("locked columns survive removal attempts", () => {
    const stripped = fromParams(
      new URLSearchParams([
        ["col", "m:revenue"],
        ["col", "id:reporting_period"],
      ]),
    );
    expect(stripped.columns.slice(0, 2)).toEqual([...LOCKED]);
    expect(stripped.columns).toEqual(["id:issuer_name", "id:reporting_period", "m:revenue"]);
    const none = fromParams(new URLSearchParams([["col", "id:issuer_name"]]));
    expect(none.columns).toEqual([...LOCKED]);
    const out = toParams({ ...DEFAULT_VIEW, columns: ["m:revenue"] });
    expect(out.getAll("col").slice(0, 2)).toEqual([...LOCKED]);
  });

  it("de-duplicates columns", () => {
    const view = fromParams(
      new URLSearchParams([
        ["col", "m:revenue"],
        ["col", "m:revenue"],
        ["col", "id:sector"],
      ]),
    );
    expect(view.columns).toEqual([
      "id:issuer_name",
      "id:reporting_period",
      "m:revenue",
      "id:sector",
    ]);
  });

  it("ignores unknown params", () => {
    const p = toParams(DEFAULT_VIEW);
    p.set("utm", "x");
    p.append("zzz", "1");
    expect(fromParams(p)).toEqual(DEFAULT_VIEW);
  });

  it("an empty query is the default view", () => {
    expect(fromParams(new URLSearchParams())).toEqual(DEFAULT_VIEW);
  });

  it("round-trips every basis, suffix and a sort on a suffixed key", () => {
    for (const basis of ["LTM", "PF_LTM", "BASE_FY1", "DOWNSIDE_FY1"] as const) {
      const view: BookView = {
        ...DEFAULT_VIEW,
        basis,
        columns: [
          ...LOCKED,
          "m:revenue@LTM",
          "m:revenue@PF_LTM",
          "m:revenue@DOWNSIDE_FY1",
          "m:revenue@BASE_FY1",
        ],
        sort: { column: "m:revenue@PF_LTM", dir: "asc" },
      };
      expect(roundTrip(view)).toEqual(view);
    }
  });

  it("drops inert filters", () => {
    const view = fromParams(
      new URLSearchParams([
        ["f", "set|id%3Asector|"],
        ["f", "range|m%3Arevenue||"],
        ["f", "notch|sp||"],
      ]),
    );
    expect(view.filters).toEqual([]);
  });

  it("drops a range whose min exceeds its max, comparing exactly", () => {
    const one = (min: string, max: string) =>
      fromParams(new URLSearchParams([["f", `range|m%3Arevenue|${min}|${max}`]])).filters;
    expect(one("5", "1")).toEqual([]);
    expect(one("0.10000000000000002", "0.1")).toEqual([]);
    expect(one("9007199254740993", "9007199254740992")).toEqual([]);
    expect(one("1", "1")).toHaveLength(1);
    expect(one("0.1", "0.10000000000000002")).toHaveLength(1);
  });

  it("accepts only a three-letter capital currency", () => {
    const cur = (value: string) => fromParams(new URLSearchParams([["cur", value]])).currency;
    expect(cur("EUR")).toBe("EUR");
    expect(cur("eur")).toBeNull();
    expect(cur("EURO")).toBeNull();
    expect(cur("<script>")).toBeNull();
    expect(cur("")).toBeNull();
  });

  it("carries the agency scales of caos/book/classification.py", () => {
    expect(MOODYS_SCALE).toHaveLength(21);
    expect(MOODYS_SCALE[0]).toBe("Aaa");
    expect(MOODYS_SCALE[20]).toBe("C");
    expect(SP_FITCH_SCALE).toHaveLength(22);
    expect(SP_FITCH_SCALE[0]).toBe("AAA");
    expect(SP_FITCH_SCALE[21]).toBe("D");
  });

  it("drops notch filters with unknown labels, another agency's labels or an inverted pair", () => {
    const notch = (agency: string, best: string, worst: string) =>
      fromParams(
        new URLSearchParams([
          ["f", `notch|${agency}|${encodeURIComponent(best)}|${encodeURIComponent(worst)}`],
        ]),
      ).filters;
    expect(notch("sp", "zzz", "B")).toEqual([]);
    expect(notch("sp", "AAA", "<img>")).toEqual([]);
    expect(notch("sp", "Baa1", "B")).toEqual([]);
    expect(notch("moodys", "BBB", "B1")).toEqual([]);
    expect(notch("moodys", "D", "C")).toEqual([]);
    expect(notch("fitch", "B", "AAA")).toEqual([]);
    expect(notch("sp", "B", "B")).toHaveLength(1);
    expect(notch("fitch", "BBB-", "D")).toHaveLength(1);
    expect(notch("moodys", "Aaa", "C")).toHaveLength(1);
  });

  describe("malformed values are ignored without throwing", () => {
    const parse = (...pairs: [string, string][]) => fromParams(new URLSearchParams(pairs));
    it("basis", () => expect(parse(["basis", "WEEKLY"]).basis).toBe("LTM"));
    it("columns", () => {
      const view = parse(
        ["col", "id:nonsense"],
        ["col", "m:"],
        ["col", "m:revenue@WEEKLY"],
        ["col", "bogus"],
        ["col", "m:revenue@BASE_FY1"],
      );
      expect(view.columns).toEqual(["id:issuer_name", "id:reporting_period", "m:revenue@BASE_FY1"]);
    });
    it.each([
      ["a non-decimal bound", "range|m%3Arevenue|abc|5"],
      ["a missing field", "range|m%3Arevenue"],
      ["an unknown column", "range|id%3Anope|1|2"],
      ["a range on an identifier column", "range|id%3Aissuer_name|1|"],
      ["an extra field", "range|m%3Arevenue|1|2|x"],
      ["a bad escape in a range", "range|%ZZ|1|2"],
      ["a bad escape in a bound", "range|m%3Arevenue|%ZZ|2"],
      ["a set with a third field", "set|id%3Asector|a|x"],
      ["a set with a bad escape", "set|id%3Asector|%ZZ"],
      ["a set on an unknown column", "set|bogus|a"],
      ["a notch with a bad escape", "notch|sp|%ZZ|D"],
      ["a notch with an unknown agency", "notch|gb|A|B"],
      ["a notch missing a label", "notch|sp|A"],
      ["an unknown kind", "mystery|x"],
    ])("filter: %s", (_name, raw) => expect(parse(["f", raw]).filters).toEqual([]));
    it.each([
      ["an unknown direction", "up|m%3Arevenue"],
      ["an unknown column", "asc|bogus"],
      ["an extra part", "asc|m%3Arevenue|x"],
      ["a bad escape", "asc|%ZZ"],
      ["no column", "asc"],
    ])("sort: %s", (_name, raw) => expect(parse(["sort", raw]).sort).toBeNull());
  });

  it("default view matches the spec columns", () => {
    expect(DEFAULT_VIEW.basis).toBe("LTM");
    expect(DEFAULT_VIEW.filters).toEqual([]);
    expect(DEFAULT_VIEW.sort).toBeNull();
    expect(DEFAULT_VIEW.currency).toBeNull();
    expect(DEFAULT_VIEW.columns).toEqual([
      "id:issuer_name",
      "id:reporting_period",
      "id:currency",
      "id:unit",
      "id:sector",
      "id:composite",
      "id:moodys",
      "id:moodys_outlook",
      "id:sp",
      "id:sp_outlook",
      "id:fitch",
      "id:fitch_outlook",
      "m:revenue",
      "m:adjusted_ebitda",
      "m:metric:adjusted_ebitda_margin",
      "m:total_debt",
      "m:liquidity",
      "m:metric:net_leverage_adjusted",
      "m:metric:lease_adjusted_net_leverage",
      "m:metric:interest_coverage_adjusted",
      "m:metric:fcf_to_debt",
      "m:metric:ffo_to_debt",
      "m:metric:net_leverage_adjusted@BASE_FY1",
      "m:metric:net_leverage_adjusted@DOWNSIDE_FY1",
    ]);
    expect([...LOCKED]).toEqual(["id:issuer_name", "id:reporting_period"]);
  });
});
