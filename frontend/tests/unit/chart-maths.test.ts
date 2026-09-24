// The chart primitives' arithmetic, reached by import: exact decimals, the
// bridge's running level and residual, a stack's shares, tick labels, and
// how a mark is named. Every figure a chart prints comes through here, so
// these hold it to the string the API served -- never a float's rendering.
import { acrossLabels, valueTicks } from "@/charts/axes";
import { bandPlot, cellBar } from "@/charts/band";
import { UNRECONCILED, bridgeOf } from "@/charts/bridge";
import { hitBox } from "@/charts/ChartFrame";
import {
  INEXACT,
  UNAVAILABLE,
  UNSERVED,
  formatDecimal,
  fromScaled,
  isDecimal,
  percentShares,
  placesOf,
  readDatum,
  toNumber,
  toScaled,
} from "@/charts/decimal";
import {
  FALLBACK_WIDTH,
  TICK_SIZE,
  VALUE_SIZE,
  fitText,
  textWidth,
  tickLabels,
  valueScale,
} from "@/charts/scale";
import {
  ORIGIN_WORD,
  cellName,
  cellSelection,
  cellText,
  cellsOf,
  poleOf,
  seriesColor,
  seriesLegend,
  seriesTable,
  valueText,
} from "@/charts/series";
import { NO_SHARE, NO_WHOLE, stackOf } from "@/charts/stack";
import type { ChartSeries, WaterfallStep } from "@/charts/types";

const REVENUE: ChartSeries = {
  key: "revenue",
  label: "Revenue",
  origin: "model",
  data: [
    { value: "3100.5" },
    { value: "3412.0" },
    { value: null, reason: "ZERO_OR_NEGATIVE_DENOMINATOR" },
  ],
};
const PERIODS = ["Q1 2026", "Q2 2026", "Q3 2026"];

/** Sums decimal strings exactly, the way a reader adding the labels would. */
function exactSum(values: readonly string[]): string {
  const places = Math.max(...values.map(placesOf));
  return fromScaled(
    values.reduce((sum, value) => sum + toScaled(value, places), 0n),
    places,
  );
}

describe("exact decimals print as served", () => {
  test("digits are grouped by string work, never by a float round trip", () => {
    expect(formatDecimal("1234567.50")).toBe("1,234,567.50");
    expect(formatDecimal("-1234.5")).toBe("-1,234.5");
    expect(formatDecimal("123")).toBe("123");
    expect(formatDecimal("0.000001")).toBe("0.000001");
    // Past 2^53 a float cannot hold the value; the string still can.
    expect(String(Number("9007199254740993"))).toBe("9007199254740992");
    expect(formatDecimal("9007199254740993")).toBe("9,007,199,254,740,993");
  });

  test("a change is signed; zero is not", () => {
    expect(formatDecimal("12.5", true)).toBe("+12.5");
    expect(formatDecimal("-3.25", true)).toBe("-3.25");
    expect(formatDecimal("0.00", true)).toBe("0.00");
    expect(valueText("1234.5", "USD m", true)).toBe("+1,234.5 USD m");
    expect(valueText("1234.5", undefined)).toBe("1,234.5");
  });

  test("the wire's pattern, and nothing looser", () => {
    expect(isDecimal("-0.5")).toBe(true);
    expect(isDecimal("3412.0")).toBe(true);
    for (const refused of ["1e5", "12.", ".5", " 1", "+1", "NaN", "Infinity", "1,000"]) {
      expect(isDecimal(refused)).toBe(false);
    }
  });

  test("scaled counts round-trip exactly and refuse to drop a digit", () => {
    expect(placesOf("12.340")).toBe(3);
    expect(placesOf("12")).toBe(0);
    expect(toScaled("12.34", 3)).toBe(12340n);
    expect(toScaled("-0.5", 2)).toBe(-50n);
    expect(fromScaled(12340n, 3)).toBe("12.340");
    expect(fromScaled(-5n, 3)).toBe("-0.005");
    expect(fromScaled(0n, 0)).toBe("0");
    expect(() => toScaled("1.234", 2)).toThrow(RangeError);
  });

  test("a number is made only to place a mark", () => {
    expect(toNumber("3412.0")).toBe(3412);
    expect(toNumber("-0.25")).toBe(-0.25);
  });

  test("shares are apportioned by largest remainder to exactly 100.0", () => {
    const thirds = percentShares([1n, 1n, 1n]);
    expect(thirds).toEqual(["33.4", "33.3", "33.3"]);
    expect(exactSum(thirds ?? [])).toBe("100.0");
    expect(percentShares([2n, 1n])).toEqual(["66.7", "33.3"]);
    expect(percentShares([0n, 7n])).toEqual(["0.0", "100.0"]);
    expect(percentShares([0n, 0n])).toBeNull();
  });

  test("a datum is read, never guessed", () => {
    expect(readDatum(undefined)).toEqual({ value: null, reason: UNSERVED, origin: null });
    expect(readDatum({ value: "1e5" })).toEqual({ value: null, reason: INEXACT, origin: null });
    expect(readDatum({ value: null })).toEqual({ value: null, reason: UNAVAILABLE, origin: null });
    expect(readDatum({ value: null, reason: "ZERO_OR_NEGATIVE_DENOMINATOR" }).reason).toBe(
      "ZERO_OR_NEGATIVE_DENOMINATOR",
    );
    expect(readDatum({ value: "3.5", origin: "model" })).toEqual({
      value: "3.5",
      reason: null,
      origin: "model",
    });
  });
});

describe("a bridge is exact", () => {
  const step = (label: string, kind: WaterfallStep["kind"], value: string | null) => ({
    label,
    kind,
    value,
    origin: "host" as const,
  });

  test("0.1 + 0.2 reaches a stated 0.3: no residual where floats would draw one", () => {
    expect(0.1 + 0.2).not.toBe(0.3);
    const bridge = bridgeOf([
      step("Opening", "total", "0"),
      step("Price", "delta", "0.1"),
      step("Volume", "delta", "0.2"),
      step("Closing", "total", "0.3"),
    ]);
    expect(bridge.map((one) => one.kind)).toEqual(["total", "delta", "delta", "total"]);
    expect(bridge[2]?.end).toBe("0.3");
  });

  test("a difference floats cannot see is drawn as the residual, to the unit", () => {
    // 9007199254740993 + 1 is 9007199254740994, not the stated total; as
    // doubles both sides are 9007199254740992 and the bridge would "close".
    expect(Number("9007199254740993") + 1).toBe(Number("9007199254740993"));
    const bridge = bridgeOf([
      step("Opening", "total", "9007199254740993"),
      step("Change", "delta", "1"),
      step("Closing", "total", "9007199254740993"),
    ]);
    const residual = bridge.find((one) => one.kind === "residual");
    expect(residual).toMatchObject({
      label: UNRECONCILED,
      value: "-1",
      start: "9007199254740994",
      end: "9007199254740993",
      origin: null,
      before: "Closing",
    });
  });

  test("the residual stands before the total it fails to reach, with its exact amount", () => {
    const bridge = bridgeOf([
      { ...step("Reported EBITDA", "total", "100.0"), key: "reported" },
      step("Restructuring", "delta", "12.5"),
      step("FX", "delta", "-3.25"),
      step("Adjusted EBITDA", "total", "110.00"),
    ]);
    expect(bridge.map((one) => one.label)).toEqual([
      "Reported EBITDA",
      "Restructuring",
      "FX",
      UNRECONCILED,
      "Adjusted EBITDA",
    ]);
    expect(bridge[0]?.key).toBe("reported");
    expect(bridge[2]).toMatchObject({ start: "112.50", end: "109.25" });
    expect(bridge[3]).toMatchObject({ value: "0.75", start: "109.25", end: "110.00" });
    // The served values stay as served; only the levels are at the bridge's scale.
    expect(bridge[4]).toMatchObject({ value: "110.00", start: "0.00", end: "110.00" });
  });

  test("an unavailable step moves nothing, and the next total's residual carries it", () => {
    const bridge = bridgeOf([
      step("Opening", "total", "100"),
      { ...step("Disposals", "delta", null), reason: "NOT_DISCLOSED" },
      step("Growth", "delta", "5"),
      step("Closing", "total", "110"),
    ]);
    expect(bridge[1]).toMatchObject({
      value: null,
      reason: "NOT_DISCLOSED",
      start: null,
      end: null,
    });
    expect(bridge[2]).toMatchObject({ start: "100", end: "105" });
    expect(bridge[3]).toMatchObject({ kind: "residual", value: "5" });
  });

  test("a bridge without an opening total starts from zero", () => {
    const bridge = bridgeOf([
      step("Retail", "delta", "10"),
      step("Wholesale", "delta", "5"),
      step("Revenue", "total", "15"),
    ]);
    expect(bridge.some((one) => one.kind === "residual")).toBe(false);
    expect(bridge[0]).toMatchObject({ start: "0", end: "10" });
  });
});

describe("a stack is exact", () => {
  const mix = (values: (string | null)[]): ChartSeries[] =>
    values.map((value, index) => ({
      key: `s${index}`,
      label: `Segment ${index}`,
      origin: "host",
      data: [{ value, reason: value === null ? "NOT_SERVED" : null }],
    }));

  test("normalised shares sum to exactly 100.0 and the stack fills to 100", () => {
    const cells = cellsOf(["FY2025"], mix(["1", "1", "1"]));
    const { segments, totals } = stackOf(cells, 1, true);
    expect(segments.map((segment) => segment.share)).toEqual(["33.4", "33.3", "33.3"]);
    expect(exactSum(segments.map((segment) => segment.share ?? "0"))).toBe("100.0");
    expect(segments[0]?.from).toBe(0);
    expect(segments.at(-1)?.to).toBe(100);
    expect(segments.map((segment) => segment.stacked)).toEqual([false, true, true]);
    expect(totals).toEqual([null]);
  });

  test("a negative value has no share, and a zero whole shares nothing", () => {
    const negative = stackOf(cellsOf(["FY2025"], mix(["30", "-5", "10"])), 1, true).segments;
    expect(negative.map((segment) => segment.gap)).toEqual([null, NO_SHARE, null]);
    expect(negative.map((segment) => segment.share)).toEqual(["75.0", null, "25.0"]);
    const zero = stackOf(cellsOf(["FY2025"], mix(["0", "0"])), 1, true).segments;
    expect(zero.map((segment) => segment.gap)).toEqual([NO_WHOLE, NO_WHOLE]);
  });

  test("absolute stacks hang a negative below zero and total exactly", () => {
    const { segments, totals } = stackOf(
      cellsOf(["FY2025"], mix(["10.5", "4.25", "-1.75"])),
      1,
      false,
    );
    expect(segments.map((segment) => [segment.from, segment.to])).toEqual([
      [0, 10.5],
      [10.5, 14.75],
      [0, -1.75],
    ]);
    expect(totals).toEqual([{ at: "14.75", net: "13.00" }]);
  });

  test("a total with a part unavailable is no total", () => {
    const { segments, totals } = stackOf(cellsOf(["FY2025"], mix(["10", null])), 1, false);
    expect(segments[1]?.gap).toBe("NOT_SERVED");
    expect(totals).toEqual([null]);
  });
});

describe("axes print nice numbers, not float residue", () => {
  test("tick labels take the fewest decimals that state every tick", () => {
    // One precision for every tick, so the column of them aligns.
    expect(tickLabels([0, 0.1, 0.2, 0.30000000000000004])).toEqual(["0.0", "0.1", "0.2", "0.3"]);
    expect(tickLabels([0, 500, 1000, 1500])).toEqual(["0", "500", "1,000", "1,500"]);
    expect(tickLabels([-0.05, 0, 0.05])).toEqual(["-0.05", "0.00", "0.05"]);
  });

  test("a value scale is nice, holds its extent, and widens an empty one", () => {
    const { scale, ticks } = valueScale([-3, 17], [200, 0], 5);
    expect(scale.domain()).toEqual([-5, 20]);
    expect(ticks).toContain(0);
    expect(valueScale([0, 0], [100, 0], 5).scale.domain()).toEqual([0, 1]);
    const axis = valueTicks([0, 1500], [200, 0], 44, true);
    expect(axis.ticks.every((tick) => tick.text.endsWith("%"))).toBe(true);
    expect(axis.widest).toBe(textWidth("1,500%", TICK_SIZE));
    expect(axis.at(0)).toBe(200);
  });

  test("text is sized at the floors, and cut rather than crowded", () => {
    expect(TICK_SIZE).toBe(11);
    expect(VALUE_SIZE).toBe(12);
    expect(FALLBACK_WIDTH).toBeGreaterThan(0);
    expect(textWidth("12345", 10)).toBeCloseTo(31);
    expect(fitText("Q1", 60, TICK_SIZE)).toBe("Q1");
    const cut = fitText("Annual report and accounts 2025", 60, TICK_SIZE);
    expect(cut.endsWith("…")).toBe(true);
    expect(textWidth(cut, TICK_SIZE)).toBeLessThanOrEqual(60);
    // Labels too wide for their step are thinned at an even step, never overlapped.
    const labels = acrossLabels(
      ["January 2026", "February 2026", "March 2026"],
      (i) => i * 50,
      50,
      0,
    );
    expect(labels.map((label) => label.x)).toEqual([0, 100]);
  });
});

describe("a mark says what it is", () => {
  test("its name carries the series, category, exact value, unit and origin", () => {
    const [first, second, third] = cellsOf(PERIODS, [REVENUE]);
    expect(second && cellName(second, "USD m")).toBe(
      "Revenue, Q2 2026: 3,412.0 USD m (model-authored)",
    );
    expect(third && cellName(third, "USD m")).toBe(
      "Revenue, Q3 2026: n/a (ZERO_OR_NEGATIVE_DENOMINATOR)",
    );
    expect(first && cellSelection(first)).toEqual({
      series: "revenue",
      category: "Q1 2026",
      index: 0,
      value: "3100.5",
      origin: "model",
    });
    expect(ORIGIN_WORD).toEqual({ host: "host-verified", model: "model-authored" });
  });

  test("a datum overriding its series' origin is said in its table cell", () => {
    const series: ChartSeries = {
      ...REVENUE,
      origin: "host",
      data: [{ value: "5", origin: "model" }],
    };
    const [cell] = cellsOf(["Q1 2026"], [series]);
    expect(cell && cellText(cell)).toBe("5 (model-authored)");
    const twin = seriesTable("Period", ["Q1 2026"], [series], cell ? [cell] : [], "USD m");
    expect(twin.head).toEqual(["Period", "Revenue, USD m (host-verified)"]);
    expect(twin.rows[0]?.cells).toEqual(["Q1 2026", "5 (model-authored)"]);
  });

  test("colour follows the series, and runs out rather than cycling", () => {
    expect(seriesColor({ color: "tranche-1l" }, 0)).toBe("tranche-1l");
    expect([0, 1, 2, 3, 4, 5].map((index) => seriesColor({}, index))).toEqual([
      "series-1",
      "series-2",
      "series-3",
      "series-4",
      "series-5",
      "neutral",
    ]);
    expect(seriesLegend([REVENUE], "fill")).toEqual([]);
    expect(seriesLegend([REVENUE, { ...REVENUE, key: "ebitda", label: "EBITDA" }], "line")).toEqual(
      [
        { key: "revenue", label: "Revenue", tone: "series-1", shape: "line", origin: "model" },
        { key: "ebitda", label: "EBITDA", tone: "series-2", shape: "line", origin: "model" },
      ],
    );
  });

  test("a sign picks its pole from the string", () => {
    expect(poleOf("12")).toBe("positive");
    expect(poleOf("-0.5")).toBe("negative");
    expect(poleOf("-0.00")).toBe("neutral");
    expect(poleOf(null)).toBe("neutral");
  });

  test("a bar runs from zero to its value, and an unavailable one is a gap", () => {
    const [first, , third] = cellsOf(PERIODS, [REVENUE]);
    const bar = first && cellBar(first, "USD m", { signed: true });
    expect(bar).toMatchObject({ from: 0, to: 3100.5, gap: false, label: "+3,100.5" });
    expect(third && cellBar(third, "USD m")).toMatchObject({ gap: true, label: null });
  });

  test("a hit target grows to 24px about the mark's centre", () => {
    expect(hitBox({ x: 10, y: 10, width: 4, height: 100 })).toEqual({
      x: 0,
      y: 10,
      width: 24,
      height: 100,
    });
    expect(hitBox({ x: 0, y: 0, width: 30, height: 30 })).toEqual({
      x: 0,
      y: 0,
      width: 30,
      height: 30,
    });
  });

  test("a band plot lays bars up or along, and hatches only what the model authored", () => {
    const cells = cellsOf(PERIODS, [REVENUE, { ...REVENUE, key: "host", origin: "host" }]);
    const bars = cells.map((cell) => cellBar(cell, "USD m"));
    const hatch = (tone: string) => `url(#${tone})`;
    const up = bandPlot(
      { orientation: "vertical", categories: PERIODS, slots: 2, bars },
      600,
      hatch,
    );
    const along = bandPlot(
      { orientation: "horizontal", categories: PERIODS, slots: 2, bars },
      600,
      hatch,
    );
    expect(up.marks).toHaveLength(6);
    expect(up.hatched).toEqual(["series-1"]);
    const [upFirst, upSecond] = up.marks;
    const [alongFirst] = along.marks;
    // Standing up, value is height; running along, value is width.
    expect(upFirst && upSecond && upFirst.box.width === upSecond.box.width).toBe(true);
    expect(upFirst && upFirst.box.height > upFirst.box.width).toBe(true);
    expect(alongFirst && alongFirst.box.width > alongFirst.box.height).toBe(true);
  });
});
