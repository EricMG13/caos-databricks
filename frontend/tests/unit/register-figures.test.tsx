// The figures drawn from a module's declared registers (N94): read only for
// the module that owns the register id, keyed by the profile's column, every
// value as served, rows of one unit on one axis. Every value here is made up
// (N191): no real issuer's figure stands in a test.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  adjustedDebtBridge,
  auditCounts,
  basketCapacity,
  cashUses,
  covenantHeadroom,
  creditPath,
  downsideSensitivities,
  ebitdaQuality,
  expectedRealised,
  forecastCases,
  impliedEv,
  liquidityBridge,
  liquiditySources,
  lmeExposure,
  peerRanges,
  rateMix,
  rateSensitivities,
  ratingTriggers,
  recoveryByClass,
  refinancingWall,
  registerFigures,
  registerRows,
  riskMatrix,
  scenarioMoves,
  scoreRegisters,
  spreadCurve,
  valueAllocation,
} from "@/sections/analysis/register-figures";
import { caseRank, negatedMagnitude, type Figure } from "@/sections/analysis/figure-core";
import { parseAnalysisDocument, type HandoffView } from "@/wire/v1";

const document = parseAnalysisDocument(
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/analysis.json"), "utf8")),
);
const handoffOf = (module: string) =>
  document.body.handoffs.find((handoff) => handoff.module_id === module)!;

type Register = HandoffView["registers"][number];
type Served = Register["rows"][number][number];

/** A served cell: its text as written and the exact figure the host read
    from it (stated here, as the host's reader would serve it). */
const c = (text: string, value: string | null = null): Served => ({ text, value });

function register(
  id: string,
  columns: readonly string[],
  rows: readonly Served[][],
  declared: readonly (string | null)[] = columns,
): Register {
  return { register_id: id, columns: [...columns], declared: [...declared], rows: [...rows] };
}

const withRegisters = (module: string, registers: Register[]): HandoffView => ({
  ...handoffOf(module),
  registers,
});

// CP-4's T4C.4, as the profile declares it.
const COVENANT = [
  "Test",
  "Test Type",
  "Threshold",
  "Current Basis",
  "Formula",
  "Headroom",
  "Status",
  "Limitation",
  "Risk Mechanic",
  "Credit Implication",
  "Evidence ID",
];

function test4c4(
  name: string,
  type: string,
  threshold: Served,
  current: Served,
  headroom: Served,
  evidence = "E-1",
): Served[] {
  return [
    c(name),
    c(type),
    threshold,
    current,
    c("Net debt / EBITDA"),
    headroom,
    c("Compliant"),
    c(""),
    c(""),
    c(""),
    c(evidence),
  ];
}

const covenantFigures = (rows: Served[][]) =>
  covenantHeadroom(withRegisters("CP-4", [register("T4C.4", COVENANT, rows)]));

/** A figure read as bullets: a figure of any other kind fails the test. */
function bullets(figure: Figure) {
  if (figure.kind !== "bullet") throw new Error(`A ${figure.kind} figure, not bullets.`);
  return figure;
}
const covenants = (rows: Served[][]) => covenantFigures(rows).map(bullets);

// CP-1C's T4.6, as the profile declares it.
const PEERS = [
  "Metric",
  "Borrower Value",
  "Peer Avg",
  "Median",
  "Min",
  "Max",
  "Q1",
  "Q3",
  "N",
  "Borrower Position",
];

const ev = [
  c("EV / EBITDA"),
  c("9.1x", "9.1"),
  c("7.4x", "7.4"),
  c("7.5x [C2]", "7.5"),
  c("5.0x", "5.0"),
  c("11.0x", "11.0"),
  c("6.25x", "6.25"),
  c("8.75x", "8.75"),
  c("12", "12"),
  c("Above Q3"),
];
const leverage = [
  c("Net leverage"),
  c("3.2x", "3.2"),
  c("3.6x", "3.6"),
  c("3.5x", "3.5"),
  c("2.0x", "2.0"),
  c("5.25x", "5.25"),
  c("n/a"),
  c("4.0x", "4.0"),
  c("11", "11"),
  c("Below median"),
];
const margin = [
  c("EBITDA margin"),
  c("18.5%", "18.5"),
  c("16.0%", "16.0"),
  c("15.5%", "15.5"),
  c("9.0%", "9.0"),
  c("24.0%", "24.0"),
  c("12.0%", "12.0"),
  c("19.0%", "19.0"),
  c("12", "12"),
  c("Top quartile"),
];

/** A figure read as range strips: a figure of any other kind fails the test. */
function ranges(figure: Figure) {
  if (figure.kind !== "range") throw new Error(`A ${figure.kind} figure, not ranges.`);
  return figure;
}
const peers = (rows: Served[][], columns = PEERS) =>
  peerRanges(withRegisters("CP-1C", [register("T4.6", columns, rows)])).map(ranges);

test("registerRows reads a register only for its own module, keyed by the profile's column", () => {
  const written = ["metric", "borrower value", ...PEERS.slice(2)];
  const handoff = withRegisters("CP-1C", [register("T4.6", written, [ev], PEERS)]);
  // The header as written does not matter: the declared column keys the cell.
  expect(registerRows(handoff, "CP-1C", "T4.6")![0]!["Borrower Value"]).toEqual(c("9.1x", "9.1"));
  // `T4.6` is CP-1's and CP-1B's register id too: another module reads nothing.
  expect(registerRows(handoff, "CP-1", "T4.6")).toBeNull();
  // A register the module does not serve.
  expect(registerRows(handoff, "CP-1C", "T4.10")).toBeNull();
  // A cell no profile column is bound to keeps its header as written, and a
  // declared column wins over a header cell spelled like it.
  const shadowed = withRegisters("CP-1C", [
    register(
      "T4.6",
      ["Median", "Peer median", "Comment"],
      [[c("x"), c("y"), c("z")]],
      [null, "Median", null],
    ),
  ]);
  expect(registerRows(shadowed, "CP-1C", "T4.6")).toEqual([{ Median: c("y"), Comment: c("z") }]);
});

test("covenantHeadroom: a ceiling, a floor and an unknown direction, each as its Test Type says", () => {
  const figures = covenants([
    test4c4(
      "Senior leverage",
      "Maintenance",
      c("4.50x", "4.50"),
      c("3.25x [C1]", "3.25"),
      c("1.25x", "1.25"),
    ),
    test4c4(
      "Interest cover",
      "  COVERAGE ",
      c("2.00x", "2.00"),
      c("3.10x", "3.10"),
      c("1.10x", "1.10"),
      "E-2",
    ),
    // Named a maximum, but its type is no direction the bundle reads: never
    // inferred from the name.
    test4c4(
      "Maximum total leverage",
      "Springing",
      c("5.00x", "5.00"),
      c("3.80x", "3.80"),
      c("1.20x", "1.20"),
    ),
  ]);
  expect(figures).toHaveLength(1);
  const [figure] = figures;
  expect(figure!.kind).toBe("bullet");
  expect(figure!.table).toBe("T4C.4");
  expect(figure!.title).toBe("Covenant headroom, x");
  expect(figure!.unit).toBe("x");
  expect(figure!.bullets).toEqual([
    {
      key: "0",
      label: "Senior leverage",
      direction: "max",
      threshold: { value: "4.50" },
      current: { value: "3.25" },
      headroom: { value: "1.25" },
      origin: "model",
    },
    {
      key: "1",
      label: "Interest cover",
      direction: "min",
      threshold: { value: "2.00" },
      current: { value: "3.10" },
      headroom: { value: "1.10" },
      origin: "model",
    },
    {
      key: "2",
      label: "Maximum total leverage",
      direction: null,
      threshold: { value: "5.00" },
      current: { value: "3.80" },
      headroom: { value: "1.20" },
      origin: "model",
    },
  ]);
  expect(figure!.summary).toBe(
    "Headroom as served: Senior leverage 1.25; Interest cover 1.10; Maximum total leverage 1.20.",
  );
  expect(
    figure!.sourceOf({
      series: "current",
      category: "Interest cover",
      index: 1,
      value: "3.10",
      origin: "model",
    }),
  ).toBe("Formula: Net debt / EBITDA; Status: Compliant; Evidence ID: E-2");
});

test("every alias the bundle's covenant_headroom.py names reads its direction, and nothing else does", () => {
  const direction = (type: string) =>
    covenants([test4c4("A test", type, c("1x", "1"), c("1x", "1"), c("0x", "0"))])[0]!.bullets![0]!
      .direction;
  for (const type of [
    "max-ratio",
    "max_ratio",
    "maximum",
    "maintenance",
    "ceiling",
    "incurrence-max",
  ])
    expect(direction(type)).toBe("max");
  for (const type of ["min-ratio", "min_ratio", "minimum", "coverage", "floor", "incurrence-min"])
    expect(direction(type)).toBe("min");
  // The bundle reads a space as a hyphen, and a citation marker is no part
  // of the type.
  expect(direction("Max Ratio")).toBe("max");
  expect(direction("Incurrence min [C3]")).toBe("min");
  for (const type of ["", "Max", "springing", "maximum leverage", "N/A"])
    expect(direction(type)).toBeNull();
});

test("a null threshold is a gap with its text, and the unit falls back to the threshold's", () => {
  const [figure] = covenants([
    test4c4("Capex basket", "Maximum", c("Not stated [C4]"), c("2.5x", "2.5"), c("Not Calculable")),
    test4c4(
      "Fixed charge cover",
      "Minimum",
      c("1.20x", "1.20"),
      c("Not Calculable"),
      c("Not Calculable"),
    ),
  ]);
  expect(figure!.title).toBe("Covenant headroom, x");
  expect(figure!.bullets![0]!.threshold).toEqual({ value: null, reason: "Not stated [C4]" });
  expect(figure!.bullets![1]!.current).toEqual({ value: null, reason: "Not Calculable" });
  expect(figure!.summary).toBe(
    "Headroom as served: Capex basket n/a (Not Calculable); Fixed charge cover n/a (Not Calculable).",
  );
});

test("rows of two units split into two figures, in the order they first appear", () => {
  const figures = covenants([
    test4c4(
      "Senior leverage",
      "Maintenance",
      c("4.50x", "4.50"),
      c("3.25x", "3.25"),
      c("1.25x", "1.25"),
      "E-1",
    ),
    test4c4(
      "Equity cure share",
      "Maximum",
      c("25%", "25"),
      c("10% [C2]", "10"),
      c("15%", "15"),
      "E-2",
    ),
    test4c4("Interest cover", "Floor", c("2.0X", "2.0"), c("3.0X", "3.0"), c("1.0X", "1.0"), "E-3"),
    test4c4("Liquidity", "Minimum", c("50", "50"), c("(80)", "-80"), c("Breached"), "E-4"),
  ]);
  expect(figures.map((figure) => [figure.title, figure.unit])).toEqual([
    ["Covenant headroom, x", "x"],
    ["Covenant headroom, %", "%"],
    ["Covenant headroom", undefined],
  ]);
  expect(new Set(figures.map((figure) => figure.key)).size).toBe(3);
  expect(figures[0]!.bullets!.map((row) => row.label)).toEqual([
    "Senior leverage",
    "Interest cover",
  ]);
  // A mark's index is its row's place in its own figure.
  const pressed = {
    series: "current",
    category: "",
    index: 0,
    value: null,
    origin: "model" as const,
  };
  expect(figures[1]!.sourceOf(pressed)).toMatch(/Evidence ID: E-2$/);
  expect(figures[2]!.sourceOf(pressed)).toMatch(/Evidence ID: E-4$/);
  expect(figures[2]!.bullets![0]!.current).toEqual({ value: "-80" });
});

test("peerRanges: a range per metric, the borrower its marker, a null quartile a gap", () => {
  const figures = peers([ev, margin, leverage]);
  expect(figures.map((figure) => [figure.kind, figure.title, figure.unit])).toEqual([
    ["range", "Peer ranges, x", "x"],
    ["range", "Peer ranges, %", "%"],
  ]);
  const [ratios] = figures;
  expect(ratios!.table).toBe("T4.6");
  expect(ratios!.markerLabel).toBe("Borrower value");
  expect(ratios!.ranges).toEqual([
    {
      key: "0",
      label: "EV / EBITDA",
      min: { value: "5.0" },
      q1: { value: "6.25" },
      median: { value: "7.5" },
      q3: { value: "8.75" },
      max: { value: "11.0" },
      marker: { value: "9.1" },
      origin: "model",
    },
    {
      key: "2",
      label: "Net leverage",
      min: { value: "2.0" },
      q1: { value: null, reason: "n/a" },
      median: { value: "3.5" },
      q3: { value: "4.0" },
      max: { value: "5.25" },
      marker: { value: "3.2" },
      origin: "model",
    },
  ]);
  expect(ratios!.summary).toBe(
    "Borrower value as served: EV / EBITDA 9.1 (Above Q3); Net leverage 3.2 (Below median).",
  );
  const pressed = {
    series: "marker",
    category: "",
    index: 1,
    value: "3.2",
    origin: "model" as const,
  };
  expect(ratios!.sourceOf(pressed)).toBe("Peer Avg: 3.6x; N: 11");
});

test("a borrower value not stated is a gap, and the unit falls back to the median's", () => {
  const unstated = [
    c("Interest cover"),
    c("Not disclosed"),
    ...margin.slice(2, 3),
    c("4.5x", "4.5"),
    ...ev.slice(4),
  ];
  const [figure] = peers([unstated]);
  expect(figure!.unit).toBe("x");
  expect(figure!.ranges![0]!.marker).toEqual({ value: null, reason: "Not disclosed" });
  expect(figure!.summary).toBe(
    "Borrower value as served: Interest cover n/a (Not disclosed) (Above Q3).",
  );
});

test("a statistic the register does not declare is left out of its row, not drawn as a gap", () => {
  const columns = PEERS.filter((column) => column !== "Q1" && column !== "Q3");
  const row = ev.filter((_, index) => PEERS[index] !== "Q1" && PEERS[index] !== "Q3");
  const [figure] = peers([row], columns);
  expect(figure!.ranges![0]).not.toHaveProperty("q1");
  expect(figure!.ranges![0]).not.toHaveProperty("q3");
  expect(figure!.ranges![0]!.median).toEqual({ value: "7.5" });
});

test("a register of another module's id draws nothing", () => {
  // CP-1 serves a `T4.6` of its own: it is not CP-1C's peer statistics.
  const cp1 = withRegisters("CP-1", [register("T4.6", PEERS, [ev])]);
  expect(peerRanges(cp1)).toEqual([]);
  expect(registerFigures(cp1)).toEqual([]);
  const cp1c = withRegisters("CP-1C", [
    register("T4C.4", COVENANT, [
      test4c4("Senior leverage", "Maintenance", c("4.5x", "4.5"), c("3x", "3"), c("1.5x", "1.5")),
    ]),
  ]);
  expect(covenantHeadroom(cp1c)).toEqual([]);
  expect(registerFigures(cp1c)).toEqual([]);
  // In their own modules, both are drawn by registerFigures.
  expect(registerFigures(withRegisters("CP-1C", [register("T4.6", PEERS, [ev])]))).toHaveLength(1);
});

test("a register past the marks a figure may draw is stated, not drawn", () => {
  const many = Array.from({ length: 1001 }, (_, index) =>
    test4c4(`Test ${index}`, "Maximum", c("4x", "4"), c("3x", "3"), c("1x", "1")),
  );
  const [figure] = covenantFigures(many);
  expect(figure!.oversized).toBe(true);
  expect(figure!.title).toBe("Covenant headroom, x");
  expect(figure!.summary).toMatch(/^2002 marks: too many to draw\./);
});

// CP-1D's T1D.4, as the profile declares it.
const QUALITY = [
  "Step",
  "Amount",
  "Basis",
  "Supported / Challenged / Rejected",
  "Cumulative EBITDA",
  "Evidence ID",
];
const t1d4 = (step: string, amount: Served, status: string, cumulative: Served, id = "E-1") => [
  c(step),
  amount,
  c(`Basis of ${step}`),
  c(status),
  cumulative,
  c(id),
];

/** A CP-1D handoff: the fixture has none, so CP-1's stands in, renamed,
    with no tables and only the registers given. */
const cp1dWith = (registers: Register[]): HandoffView => ({
  ...handoffOf("CP-1"),
  module_id: "CP-1D",
  tables: [],
  registers,
});

/** A figure read as a waterfall: a figure of any other kind fails the test. */
function waterfall(figure: Figure) {
  if (figure.kind !== "waterfall") throw new Error(`A ${figure.kind} figure, not a waterfall.`);
  return figure;
}
const quality = (rows: Served[][]) =>
  ebitdaQuality(cp1dWith([register("T1D.4", QUALITY, rows)])).map(waterfall);

test("ebitdaQuality: opening total, deltas as served, a stated total, a gap, the closing total", () => {
  const [figure, ...rest] = quality([
    t1d4("Reported EBITDA", c("100.0", "100.0"), "Supported", c("100.0", "100.0")),
    t1d4("Restructuring", c("12.5", "12.5"), " challenged ", c("112.5", "112.5"), "E-2"),
    t1d4("Pro forma synergies", c("(4.0)", "-4.0"), "REJECTED", c("108.5", "108.5")),
    t1d4("Subtotal", c(""), "", c("108.5", "108.5")),
    t1d4("Run-rate savings", c("Not quantified"), "Insufficient Information", c("")),
    // A status is matched exactly, past its case and spaces: a cited one is not.
    t1d4("Rebate", c("0.0", "0.0"), "Supported [C1]", c("108.5", "108.5")),
    t1d4("FX", c("1.5", "1.5"), "Under review", c("110.0", "110.0"), "E-6"),
  ]);
  expect(rest).toEqual([]);
  expect(figure!.key).toBe("ebitda-quality");
  expect(figure!.table).toBe("T1D.4");
  expect(figure!.title).toBe("EBITDA quality bridge");
  expect(figure!.steps).toEqual([
    {
      key: "0",
      label: "Reported EBITDA",
      kind: "total",
      value: "100.0",
      origin: "model",
      status: "Supported",
    },
    {
      key: "1",
      label: "Restructuring",
      kind: "delta",
      value: "12.5",
      origin: "model",
      color: "series-3",
      status: "challenged",
    },
    {
      key: "2",
      label: "Pro forma synergies",
      kind: "delta",
      value: "-4.0",
      origin: "model",
      color: "negative",
      status: "REJECTED",
    },
    { key: "3", label: "Subtotal", kind: "total", value: "108.5", origin: "model" },
    {
      key: "4",
      label: "Run-rate savings",
      kind: "delta",
      value: null,
      reason: "Not quantified",
      origin: "model",
      color: "series-4",
      status: "Insufficient Information",
    },
    {
      key: "5",
      label: "Rebate",
      kind: "delta",
      value: "0.0",
      origin: "model",
      status: "Supported [C1]",
    },
    { key: "6", label: "FX", kind: "delta", value: "1.5", origin: "model", status: "Under review" },
    { key: "closing", label: "Cumulative EBITDA", kind: "total", value: "110.0", origin: "model" },
  ]);
  // The opening total's Supported is said, not coloured, and the gap's
  // Insufficient Information is worn by no drawn mark: neither is listed.
  expect(figure!.statuses).toEqual([
    { color: "series-3", label: "Challenged" },
    { color: "negative", label: "Rejected" },
  ]);
  expect(figure!.summary).toBe("Reported EBITDA 100.0 to Cumulative EBITDA 110.0, as served.");
  const pressed = (series: string) => ({
    series,
    category: "",
    index: 0,
    value: null,
    origin: "model" as const,
  });
  expect(figure!.sourceOf(pressed("1"))).toBe("Basis: Basis of Restructuring; Evidence ID: E-2");
  // The closing total is the last row's own cumulative figure.
  expect(figure!.sourceOf(pressed("closing"))).toBe("Basis: Basis of FX; Evidence ID: E-6");
  expect(figure!.sourceOf(pressed("5:unreconciled"))).toBeNull();
});

test("an opening row with no amount opens on its cumulative figure; a last stated total closes", () => {
  const [figure] = quality([
    t1d4("Reported EBITDA", c("n/a"), "Supported", c("80", "80")),
    t1d4("Add-back", c("5", "5"), "Supported", c("85", "85")),
    t1d4("Adjusted EBITDA", c(""), "Supported", c("85", "85")),
  ]);
  expect(figure!.steps.map((step) => [step.kind, step.label, step.value])).toEqual([
    ["total", "Reported EBITDA", "80"],
    ["delta", "Add-back", "5"],
    ["total", "Adjusted EBITDA", "85"],
  ]);
  expect(figure!.statuses).toEqual([{ color: "positive", label: "Supported" }]);
});

test("a bridge that ends on a change with no cumulative figure names no change as its end", () => {
  const [figure] = quality([
    t1d4("Reported EBITDA", c("100.0", "100.0"), "Supported", c("100.0", "100.0")),
    t1d4("FX", c("1.5", "1.5"), "Supported", c("n/a")),
  ]);
  expect(figure!.steps.at(-1)!.kind).toBe("delta");
  expect(figure!.summary).toBe(
    "Reported EBITDA 100.0; the last change, FX, states no Cumulative EBITDA.",
  );
  const [gap] = quality([
    t1d4("Reported EBITDA", c("100.0", "100.0"), "Supported", c("100.0", "100.0")),
    t1d4("Run-rate savings", c("Not quantified"), "Insufficient Information", c("—")),
  ]);
  expect(gap!.summary).toBe(
    "Reported EBITDA 100.0; the last change, Run-rate savings, states no Cumulative EBITDA.",
  );
});

test("the schema's empty bridge, and a register of another module, draw nothing", () => {
  expect(quality([t1d4(" NONE ", c("—"), "—", c("—"))])).toEqual([]);
  expect(quality([])).toEqual([]);
  const cp1 = withRegisters("CP-1", [
    register("T1D.4", QUALITY, [t1d4("Reported EBITDA", c("1", "1"), "Supported", c("1", "1"))]),
  ]);
  expect(ebitdaQuality(cp1)).toEqual([]);
  expect(registerFigures(cp1)).toEqual([]);
  const cp1d = cp1dWith([
    register("T1D.4", QUALITY, [t1d4("Reported EBITDA", c("1", "1"), "Supported", c("1", "1"))]),
  ]);
  expect(registerFigures(cp1d).map((figure) => figure.key)).toEqual(["ebitda-quality"]);
});

test("a bridge past the marks a figure may draw is stated, not drawn", () => {
  const many = Array.from({ length: 2001 }, (_, index) =>
    t1d4(`Step ${index}`, c("1", "1"), "Supported", c(`${index + 1}`, `${index + 1}`)),
  );
  expect(ebitdaQuality(cp1dWith([register("T1D.4", QUALITY, many)]))).toEqual([
    expect.objectContaining({ oversized: true, key: "ebitda-quality" }),
  ]);
});

test("negatedMagnitude: a decimal's magnitude negated, exactly, zero unsigned", () => {
  expect(negatedMagnitude("800")).toBe("-800");
  expect(negatedMagnitude("-800")).toBe("-800");
  expect(negatedMagnitude("0")).toBe("0");
  expect(negatedMagnitude("-0")).toBe("0");
  expect(negatedMagnitude("-0.00")).toBe("0.00");
  expect(negatedMagnitude("0.50")).toBe("-0.50");
  expect(negatedMagnitude("9007199254740993.10")).toBe("-9007199254740993.10");
});

// CP-2D's T2E.5, as the profile declares it.
const LIQUIDITY = [
  "Bridge Item",
  "Amount",
  "Source / Calculation",
  "Status",
  "Credit Comment",
  "Source Trace",
];
const t2e5 = (item: string, amount: Served, trace = "E-1") => [
  c(item),
  amount,
  c(`Basis of ${item}`),
  c("Reported"),
  c(""),
  c(trace),
];
const cp2dWith = (registers: Register[]): HandoffView => ({
  ...handoffOf("CP-1"),
  module_id: "CP-2D",
  tables: [],
  registers,
});
const liquidity = (rows: Served[][]) =>
  liquidityBridge(cp2dWith([register("T2E.5", LIQUIDITY, rows)])).map(waterfall);

test("liquidityBridge: totals stated, each use drawn as its magnitude subtracted", () => {
  const [figure, ...rest] = liquidity([
    t2e5("Beginning cash", c("70", "70")),
    t2e5("Accessible revolver availability", c("30", "30")),
    t2e5("  BEGINNING accessible liquidity", c("100", "100")),
    t2e5("Operating cash inflow/outflow", c("(10)", "-10")),
    t2e5("Cash interest", c("8", "8"), "E-4"),
    t2e5("Cash taxes", c("(2)", "-2")),
    t2e5("Mandatory capex", c("0", "0")),
    t2e5("Debt amortization/maturities", c("Not disclosed")),
    t2e5("Other cash uses", c("1.5", "1.5")),
    t2e5("Committed inflows", c("4", "4")),
    t2e5("Ending accessible liquidity", c("82.5", "82.5"), "E-9"),
  ]);
  expect(rest).toEqual([]);
  expect(figure!.key).toBe("liquidity-bridge");
  expect(figure!.table).toBe("T2E.5");
  expect(figure!.title).toBe("Liquidity bridge, 12 months");
  const use = (served: string) => `served ${served}, a use the method subtracts`;
  expect(figure!.steps).toEqual([
    { key: "0", label: "Beginning cash", kind: "delta", value: "70", origin: "model" },
    {
      key: "1",
      label: "Accessible revolver availability",
      kind: "delta",
      value: "30",
      origin: "model",
    },
    {
      key: "2",
      label: "BEGINNING accessible liquidity",
      kind: "total",
      value: "100",
      origin: "model",
    },
    {
      key: "3",
      label: "Operating cash inflow/outflow",
      kind: "delta",
      value: "-10",
      origin: "model",
    },
    {
      key: "4",
      label: "Cash interest",
      kind: "delta",
      value: "-8",
      origin: "model",
      note: use("8"),
    },
    { key: "5", label: "Cash taxes", kind: "delta", value: "-2", origin: "model", note: use("-2") },
    {
      key: "6",
      label: "Mandatory capex",
      kind: "delta",
      value: "0",
      origin: "model",
      note: use("0"),
    },
    {
      key: "7",
      label: "Debt amortization/maturities",
      kind: "delta",
      value: null,
      reason: "Not disclosed",
      origin: "model",
    },
    {
      key: "8",
      label: "Other cash uses",
      kind: "delta",
      value: "-1.5",
      origin: "model",
      note: use("1.5"),
    },
    { key: "9", label: "Committed inflows", kind: "delta", value: "4", origin: "model" },
    {
      key: "10",
      label: "Ending accessible liquidity",
      kind: "total",
      value: "82.5",
      origin: "model",
    },
  ]);
  expect(figure!.summary).toBe(
    "BEGINNING accessible liquidity 100 to Ending accessible liquidity 82.5, as served.",
  );
  const pressed = (series: string) => ({
    series,
    category: "",
    index: 0,
    value: null,
    origin: "model" as const,
  });
  expect(figure!.sourceOf(pressed("4"))).toBe(
    "Source / Calculation: Basis of Cash interest; Status: Reported; Source Trace: E-4",
  );
  expect(figure!.sourceOf(pressed("10:unreconciled"))).toBeNull();
});

test("a liquidity bridge with no stated ending says so; another module's draws nothing", () => {
  const [figure] = liquidity([
    t2e5("Beginning accessible liquidity", c("n/a")),
    t2e5("Cash interest", c("8", "8")),
  ]);
  expect(figure!.summary).toBe(
    "Beginning accessible liquidity n/a (n/a) to no ending accessible liquidity stated, as served.",
  );
  expect(liquidity([])).toEqual([]);
  const cp1 = withRegisters("CP-1", [
    register("T2E.5", LIQUIDITY, [t2e5("Cash interest", c("8", "8"))]),
  ]);
  expect(liquidityBridge(cp1)).toEqual([]);
});

// CP-4C's T4E.5 and T4E.6, as the profile declares them.
const ALLOCATION = [
  "scenario",
  "entity",
  "available value",
  "priority claim",
  "allocation",
  "residual",
  "legal evidence ID",
];
const FULCRUM = [
  "scenario/EV range",
  "last covered class",
  "first impaired class",
  "fulcrum class/range",
  "uncertainty",
];
const t4e5 = (
  scenario: string,
  entity: string,
  available: Served,
  claim: string,
  allocation: Served,
  residual: Served,
  id = "L-1",
) => [c(scenario), c(entity), available, c(claim), allocation, residual, c(id)];
const t4e6 = (range: string, fulcrum: string) => [c(range), c(""), c(""), c(fulcrum), c("")];
const cp4cWith = (registers: Register[]): HandoffView => ({
  ...handoffOf("CP-1"),
  module_id: "CP-4C",
  tables: [],
  registers,
});
const allocations = (rows: Served[][], fulcrums: Served[][] = []) =>
  valueAllocation(
    cp4cWith([register("T4E.5", ALLOCATION, rows), register("T4E.6", FULCRUM, fulcrums)]),
  ).map(waterfall);

test("valueAllocation: a waterfall per scenario and entity, each allocation drawn subtracted", () => {
  const figures = allocations(
    [
      t4e5("Low", "HoldCo", c("50", "50"), "Super senior RCF", c("20", "20"), c("30", "30")),
      t4e5("Base", "HoldCo", c("90", "90"), "Senior", c("60", "60"), c("30", "30"), "L-2"),
      t4e5("Low", "HoldCo", c("50", "50"), "Senior secured", c("-30", "-30"), c("0", "0"), "L-3"),
      t4e5("Base", "OpCo", c("40", "40"), "Trade claims", c("n/q"), c("n/q")),
      t4e5("Base", "HoldCo", c("90", "90"), "Senior notes", c("30", "30"), c("0", "0")),
    ],
    [
      t4e6("Base case (EV 90)", "Senior notes, 0% recovery"),
      t4e6("low case", "Senior secured term loan"),
    ],
  );
  expect(figures.map((figure) => [figure.key, figure.table, figure.title])).toEqual([
    ["value-allocation-0", "T4E.5", "Value allocation, Low"],
    ["value-allocation-1", "T4E.5", "Value allocation, Base, HoldCo"],
    ["value-allocation-2", "T4E.5", "Value allocation, Base, OpCo"],
  ]);
  const [low, base, opco] = figures;
  const claim = (served: string) => `served ${served}, an allocation of the available value`;
  expect(low!.steps).toEqual([
    { key: "opening", label: "Available value", kind: "total", value: "50", origin: "model" },
    {
      key: "0",
      label: "Super senior RCF",
      kind: "delta",
      value: "-20",
      origin: "model",
      note: claim("20"),
    },
    {
      key: "2",
      label: "Senior secured (fulcrum)",
      kind: "delta",
      value: "-30",
      origin: "model",
      note: claim("-30"),
    },
    { key: "closing", label: "Residual", kind: "total", value: "0", origin: "model" },
  ]);
  expect(low!.summary).toBe(
    "Available value 50 to Residual 0, as served; fulcrum: Senior secured term loan.",
  );
  // The longer claim the fulcrum's text starts with is the fulcrum.
  expect(base!.steps.map((step) => step.label)).toEqual([
    "Available value",
    "Senior",
    "Senior notes (fulcrum)",
    "Residual",
  ]);
  expect(base!.summary).toBe(
    "Available value 90 to Residual 0, as served; fulcrum: Senior notes, 0% recovery.",
  );
  expect(opco!.steps.slice(1)).toEqual([
    {
      key: "3",
      label: "Trade claims",
      kind: "delta",
      value: null,
      reason: "n/q",
      origin: "model",
    },
    {
      key: "closing",
      label: "Residual",
      kind: "total",
      value: null,
      reason: "n/q",
      origin: "model",
    },
  ]);
  const pressed = (series: string) => ({
    series,
    category: "",
    index: 0,
    value: null,
    origin: "model" as const,
  });
  expect(low!.sourceOf(pressed("2"))).toBe("legal evidence ID: L-3");
  expect(base!.sourceOf(pressed("opening"))).toBe("legal evidence ID: L-2");
  expect(base!.sourceOf(pressed("closing"))).toBe("legal evidence ID: L-1");
});

test("a scenario T4E.6 names no fulcrum for marks none; each register draws for its own module", () => {
  const [figure] = allocations(
    [t4e5("Stress", "HoldCo", c("10", "10"), "Senior", c("10", "10"), c("0", "0"))],
    [t4e6("Base", "Senior")],
  );
  expect(figure!.steps.map((step) => step.label)).toContain("Senior");
  expect(figure!.summary).toBe(
    "Available value 10 to Residual 0, as served; T4E.6 names no fulcrum for this scenario.",
  );
  expect(allocations([])).toEqual([]);
  const rows = [t4e5("Low", "HoldCo", c("10", "10"), "Senior", c("10", "10"), c("0", "0"))];
  expect(valueAllocation(withRegisters("CP-4", [register("T4E.5", ALLOCATION, rows)]))).toEqual([]);
  const cp4c = cp4cWith([register("T4E.5", ALLOCATION, rows)]);
  expect(registerFigures(cp4c).map((figure) => figure.key)).toEqual(["value-allocation-0"]);
  const cp2d = cp2dWith([register("T2E.5", LIQUIDITY, [t2e5("Cash taxes", c("1", "1"))])]);
  expect(registerFigures(cp2d).map((figure) => figure.key)).toEqual(["liquidity-bridge"]);
});

test("of two claims as long once lowercased, the first is the fulcrum", () => {
  // "İ" lowercases to two code units, so lengths are compared lowercased.
  const [figure] = allocations(
    [
      t4e5("Base", "HoldCo", c("10", "10"), "İstanbul notes", c("5", "5"), c("0", "0")),
      t4e5("Base", "HoldCo", c("10", "10"), "i\u0307stanbul notes", c("5", "5"), c("0", "0")),
    ],
    [t4e6("Base", "İstanbul notes, 0% recovery")],
  );
  expect(figure!.steps.slice(1, 3).map((step) => step.label)).toEqual([
    "İstanbul notes (fulcrum)",
    "i\u0307stanbul notes",
  ]);
});

// CP-1D's T1E.3, as the profile declares it.
const DEBT = ["Step", "Amount", "Basis", "Cumulative Adjusted Debt", "Evidence ID"];
const t1e3 = (step: string, amount: Served, cumulative: Served, id = "E-1") => [
  c(step),
  amount,
  c(`Basis of ${step}`),
  cumulative,
  c(id),
];
const debt = (rows: Served[][]) =>
  adjustedDebtBridge(cp1dWith([register("T1E.3", DEBT, rows)])).map(waterfall);

test("adjustedDebtBridge: T1E.3 read as the EBITDA bridge reads T1D.4, with no status colour", () => {
  const [figure, ...rest] = debt([
    t1e3("Reported debt", c("400", "400"), c("400", "400")),
    t1e3("Leases", c("35.5", "35.5"), c("435.5", "435.5"), "E-2"),
    t1e3("Cash netting", c("(20)", "-20"), c("415.5", "415.5")),
    t1e3("Pension deficit", c("Not quantified"), c("")),
    t1e3("Earn-out", c("4.5", "4.5"), c("420.0", "420.0"), "E-5"),
  ]);
  expect(rest).toEqual([]);
  expect(figure!.key).toBe("adjusted-debt-bridge");
  expect(figure!.table).toBe("T1E.3");
  expect(figure!.title).toBe("Adjusted debt bridge");
  expect(figure!.steps).toEqual([
    { key: "0", label: "Reported debt", kind: "total", value: "400", origin: "model" },
    { key: "1", label: "Leases", kind: "delta", value: "35.5", origin: "model" },
    { key: "2", label: "Cash netting", kind: "delta", value: "-20", origin: "model" },
    {
      key: "3",
      label: "Pension deficit",
      kind: "delta",
      value: null,
      reason: "Not quantified",
      origin: "model",
    },
    { key: "4", label: "Earn-out", kind: "delta", value: "4.5", origin: "model" },
    {
      key: "closing",
      label: "Cumulative Adjusted Debt",
      kind: "total",
      value: "420.0",
      origin: "model",
    },
  ]);
  expect(figure!.statuses).toBeUndefined();
  expect(figure!.summary).toBe("Reported debt 400 to Cumulative Adjusted Debt 420.0, as served.");
  const pressed = (series: string) => ({
    series,
    category: "",
    index: 0,
    value: null,
    origin: "model" as const,
  });
  expect(figure!.sourceOf(pressed("1"))).toBe("Basis: Basis of Leases; Evidence ID: E-2");
  expect(figure!.sourceOf(pressed("closing"))).toBe("Basis: Basis of Earn-out; Evidence ID: E-5");
  const [open] = debt([
    t1e3("Reported debt", c("400", "400"), c("400", "400")),
    t1e3("Leases", c("35.5", "35.5"), c("n/a")),
  ]);
  expect(open!.summary).toBe(
    "Reported debt 400; the last change, Leases, states no Cumulative Adjusted Debt.",
  );
});

test("the empty adjusted-debt bridge, and T1E.3 served by another module, draw nothing", () => {
  expect(debt([t1e3("NONE", c("—"), c("—"))])).toEqual([]);
  const rows = [t1e3("Reported debt", c("1", "1"), c("1", "1"))];
  expect(adjustedDebtBridge(withRegisters("CP-1", [register("T1E.3", DEBT, rows)]))).toEqual([]);
  const cp1d = cp1dWith([register("T1E.3", DEBT, rows)]);
  expect(registerFigures(cp1d).map((figure) => figure.key)).toEqual(["adjusted-debt-bridge"]);
});

// CP-1C's T4.10, as the profile declares it.
const IMPLIED = [
  "Method",
  "Multiple Source",
  "Multiple Value",
  "Borrower Metric",
  "Period",
  "Implied EV",
  "Low",
  "Median",
  "High",
  "Calc Status",
  "Limitations",
];
const t4_10 = (method: string, ev: Served, low: Served, median: Served, high: Served) => [
  c(method),
  c(`Source of ${method}`),
  c("7.0x", "7.0"),
  c("LTM EBITDA 50"),
  c("FY24"),
  ev,
  low,
  median,
  high,
  c("Calculated"),
  c("Small set"),
];
const implied = (rows: Served[][]) =>
  impliedEv(withRegisters("CP-1C", [register("T4.10", IMPLIED, rows)])).map(ranges);

test("impliedEv: each method's low, median and high, its implied EV marked, no quartiles", () => {
  const [figure, ...rest] = implied([
    t4_10(
      "Trading comparables",
      c("350 [C1]", "350"),
      c("300", "300"),
      c("340", "340"),
      c("410", "410"),
    ),
    t4_10("Precedents", c("Not Calculable"), c("320", "320"), c("n/a"), c("450", "450")),
  ]);
  expect(rest).toEqual([]);
  expect(figure!.key).toBe("implied-ev");
  expect(figure!.table).toBe("T4.10");
  expect(figure!.title).toBe("Implied enterprise value by method");
  expect(figure!.unit).toBeUndefined();
  expect(figure!.markerLabel).toBe("Implied EV");
  expect(figure!.categoryLabel).toBe("Method");
  expect(figure!.ranges).toEqual([
    {
      key: "0",
      label: "Trading comparables",
      origin: "model",
      min: { value: "300" },
      median: { value: "340" },
      max: { value: "410" },
      marker: { value: "350" },
    },
    {
      key: "1",
      label: "Precedents",
      origin: "model",
      min: { value: "320" },
      median: { value: null, reason: "n/a" },
      max: { value: "450" },
      marker: { value: null, reason: "Not Calculable" },
    },
  ]);
  expect(figure!.summary).toBe(
    "Implied EV as served: Trading comparables 350; Precedents n/a (Not Calculable).",
  );
  expect(
    figure!.sourceOf({ series: "marker", category: "", index: 1, value: null, origin: "model" }),
  ).toBe(
    "Multiple Source: Source of Precedents; Multiple Value: 7.0x; Borrower Metric: LTM EBITDA 50; Period: FY24; Calc Status: Calculated",
  );
});

test("implied EV rows split by unit as peer ranges do; another module's T4.10 draws nothing", () => {
  const figures = implied([
    t4_10("Multiple", c("7.5x", "7.5"), c("6.0x", "6.0"), c("7.0x", "7.0"), c("8.0x", "8.0")),
    t4_10("DCF", c("500", "500"), c("450", "450"), c("500", "500"), c("550", "550")),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title])).toEqual([
    ["implied-ev-x", "Implied enterprise value by method, x"],
    ["implied-ev", "Implied enterprise value by method"],
  ]);
  const rows = [t4_10("DCF", c("1", "1"), c("1", "1"), c("1", "1"), c("1", "1"))];
  expect(impliedEv(withRegisters("CP-1", [register("T4.10", IMPLIED, rows)]))).toEqual([]);
  const cp1c = withRegisters("CP-1C", [register("T4.10", IMPLIED, rows)]);
  expect(registerFigures(cp1c).map((figure) => figure.key)).toEqual(["implied-ev"]);
});

/** A figure read as a stack: a figure of any other kind fails the test. */
function stack(figure: Figure) {
  if (figure.kind !== "stack") throw new Error(`A ${figure.kind} figure, not a stack.`);
  return figure;
}
const pick = (series: string, category: string) => ({
  series,
  category,
  index: 0,
  value: null,
  origin: "model" as const,
});
const gap = { value: null, reason: "not stated" };

// CP-2D's T2E.2 and T2E.3, as the profile declares them.
const SOURCES = [
  "Liquidity Component",
  "Source-Supported Amount",
  "Accessibility Status",
  "Source Trace",
  "Limitation / Restriction",
  "Risk Mechanic",
  "Credit Implication",
];
const t2e2 = (component: string, amount: Served, status: string, trace: string, limit = "") =>
  [component, amount, status, trace, limit, "", ""].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const USES = [
  "Cash Use",
  "Amount",
  "Timing",
  "Mandatory / Discretionary",
  "Source Trace",
  "Risk Mechanic",
  "Credit Implication",
  "Limitation",
];
const t2e3 = (use: string, amount: Served, timing: string, kind: string, trace: string) =>
  [use, amount, timing, kind, trace, "", "", ""].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );

test("liquiditySources: components stacked by accessibility, a component with no amount a gap", () => {
  const [figure, ...rest] = liquiditySources(
    cp2dWith([
      register("T2E.2", SOURCES, [
        t2e2("Cash", c("40", "40"), "Accessible", "E-1"),
        t2e2("Revolver", c("25", "25"), "Accessible", "E-2", "Springing covenant"),
        t2e2("Trapped cash", c("10", "10"), "Restricted", "E-3", "Offshore"),
        t2e2("Cash", c("5", "5"), "Restricted", "E-4", "Minimum cash"),
        t2e2("Delayed draw", c("Not disclosed"), "Conditional", "E-5"),
      ]),
    ]),
  ).map(stack);
  expect(rest).toEqual([]);
  expect(figure).toMatchObject({
    key: "liquidity-sources",
    table: "T2E.2",
    title: "Liquidity by accessibility",
    categoryLabel: "Accessibility Status",
    summary: "Source-Supported Amount, summed over the 4 of 5 rows that state one: 80.",
    categories: ["Accessible", "Restricted", "Conditional"],
  });
  expect(figure!.unit).toBeUndefined();
  expect(figure!.series).toEqual([
    {
      key: "Cash",
      label: "Cash",
      origin: "model",
      data: [{ value: "40" }, { value: "5" }, { value: "0" }],
    },
    {
      key: "Revolver",
      label: "Revolver",
      origin: "model",
      data: [{ value: "25" }, { value: "0" }, { value: "0" }],
    },
    {
      key: "Trapped cash",
      label: "Trapped cash",
      origin: "model",
      data: [{ value: "0" }, { value: "10" }, { value: "0" }],
    },
    {
      key: "Delayed draw",
      label: "Delayed draw",
      origin: "model",
      data: [{ value: "0" }, { value: "0" }, gap],
    },
  ]);
  expect(figure!.sourceOf(pick("Revolver", "Accessible"))).toBe(
    "Revolver (Source Trace: E-2; Limitation / Restriction: Springing covenant)",
  );
  expect(figure!.sourceOf(pick("Revolver", "Restricted"))).toBeNull();
});

const cashUses2d = (rows: Served[][]) =>
  cashUses(cp2dWith([register("T2E.3", USES, rows)])).map(stack);

test("cashUses: a segment is the exact sum of its uses, its source naming each one summed", () => {
  const [figure, ...rest] = cashUses2d([
    t2e3("Cash interest", c("12.5", "12.5"), "Next 12 months", "Mandatory", "E-1"),
    t2e3("Amortisation", c("7.5", "7.5"), "Next 12 months", "Mandatory", "E-2"),
    t2e3("Dividend", c("4", "4"), "Next 12 months", "Discretionary", "E-3"),
    t2e3("Cash interest", c("TBD"), "Months 13-24", "Mandatory", "E-4"),
    t2e3("Lease payments", c("3", "3"), "Months 13-24", "Mandatory", "E-5"),
    t2e3("Tax", c("Not disclosed"), "Months 25-36", "Mandatory", "E-6"),
  ]);
  expect(rest).toEqual([]);
  expect(figure).toMatchObject({
    key: "cash-uses",
    table: "T2E.3",
    title: "Cash uses by timing",
    categoryLabel: "Timing",
    summary: "Amount, summed over the 4 of 6 rows that state one: 27.0.",
    categories: ["Next 12 months", "Months 13-24", "Months 25-36"],
  });
  expect(figure!.series.map((series) => [series.key, series.data])).toEqual([
    ["Mandatory", [{ value: "20.0" }, { value: "3" }, gap]],
    ["Discretionary", [{ value: "4" }, { value: "0" }, { value: "0" }]],
  ]);
  expect(figure!.sourceOf(pick("Mandatory", "Next 12 months"))).toBe(
    "Sum of 2 rows: Cash interest (Source Trace: E-1); Amortisation (Source Trace: E-2)",
  );
  expect(figure!.sourceOf(pick("Mandatory", "Months 13-24"))).toBe(
    "Sum of 2 rows, 1 stating no amount: Cash interest (Source Trace: E-4);" +
      " Lease payments (Source Trace: E-5)",
  );
  expect(figure!.sourceOf(pick("Discretionary", "Months 13-24"))).toBeNull();
});

test("cash uses state every amount summed, none unstated; past MAX_MARKS they are stated", () => {
  const [figure] = cashUses2d([
    t2e3("Interest", c("1", "1"), "Q1", "Mandatory", "E-1"),
    t2e3("Capex", c("2", "2"), "Q1", "Discretionary", ""),
  ]);
  expect(figure!.summary).toBe("Amount, summed over 2 rows: 3.");
  expect(figure!.sourceOf(pick("Discretionary", "Q1"))).toBe("Capex");
  const [none] = cashUses2d([t2e3("Interest", c("TBD"), "Q1", "Mandatory", "E-1")]);
  expect(none!.summary).toBe("The 1 row states no figure for Amount.");
  const many = Array.from({ length: 2001 }, (_, index) =>
    t2e3("Interest", c("1", "1"), `Week ${index}`, "Mandatory", "E-1"),
  );
  const [oversized] = cashUses2d(many);
  expect(oversized).toMatchObject({ oversized: true, key: "cash-uses", series: [] });
});

// CP-2E's T2F.2, as the profile declares it.
const RATES = [
  "Debt Instrument",
  "Amount",
  "Fixed / Floating",
  "Base Rate",
  "Margin / Coupon",
  "Currency",
  "Maturity",
  "Hedge Status",
  "Source Trace",
  "Credit Implication",
];
const t2f2 = (debt: string, amount: Served, kind: string, rate: string, currency: string) =>
  [debt, amount, kind, rate, "+3.50%", currency, "2030", "Unhedged", "E-1", ""].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const rates = (rows: Served[][]) =>
  rateMix({ ...cp2dWith([register("T2F.2", RATES, rows)]), module_id: "CP-2E" }).map(stack);

test("rateMix: a figure per currency, fixed against floating, stacked by instrument", () => {
  const figures = rates([
    t2f2("Term loan", c("400", "400"), "Floating", "SOFR", "USD"),
    t2f2("Notes", c("300", "300"), "Fixed", "n/a", "USD"),
    t2f2("Euro loan", c("150", "150"), "Floating", "EURIBOR", "EUR"),
    t2f2("Revolver", c("Undrawn"), "Floating", "SOFR", "USD"),
    t2f2("Local facility", c("20", "20"), "Floating", "", ""),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["rate-mix-USD", "Fixed and floating debt, USD", "USD"],
    ["rate-mix-EUR", "Fixed and floating debt, EUR", "EUR"],
    ["rate-mix", "Fixed and floating debt", undefined],
  ]);
  const [usd, eur] = figures;
  expect(usd!.categories).toEqual(["Floating", "Fixed"]);
  expect(usd!.categoryLabel).toBe("Fixed / Floating");
  expect(usd!.series.map((series) => [series.key, series.data])).toEqual([
    ["Term loan", [{ value: "400" }, { value: "0" }]],
    ["Notes", [{ value: "0" }, { value: "300" }]],
    ["Revolver", [gap, { value: "0" }]],
  ]);
  expect(usd!.summary).toBe("Amount, summed over the 2 of 3 rows that state one: 700 USD.");
  expect(eur!.series.map((series) => series.key)).toEqual(["Euro loan"]);
  expect(usd!.sourceOf(pick("Term loan", "Floating"))).toBe(
    "Term loan (Base Rate: SOFR; Margin / Coupon: +3.50%; Hedge Status: Unhedged; Source Trace: E-1)",
  );
});

// CP-3C's T3D.2, as the profile declares it.
const WALL = [
  "Instrument",
  "Amount",
  "Currency",
  "Maturity Date",
  "Years to Maturity",
  "Seniority / Lien",
  "Coupon / Margin",
  "Fixed / Floating",
  "Call Date",
  "Refinancing Pressure",
  "Credit Implication",
  "Source Trace",
];
const t3d2 = (name: string, amount: Served, currency: string, date: string, lien: string) =>
  [name, amount, currency, date, "", lien, "", "", "", "", "", `Trace ${name}`].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const cp3cWith = (rows: Served[][]): HandoffView => ({
  ...cp2dWith([register("T3D.2", WALL, rows)]),
  module_id: "CP-3C",
});

test("refinancingWall: a wall per currency, years sorted, Undated last, summed as CP-1's", () => {
  const figures = refinancingWall(
    cp3cWith([
      t3d2("Notes 2031", c("250", "250"), "USD", "2031-06-30", "Senior unsecured"),
      t3d2("Term loan", c("500", "500"), "USD", "2029-03-31", "First lien"),
      t3d2("Revolver", c("Undrawn"), "USD", "2028-12-15", "First lien"),
      t3d2("Second lien loan", c("100.5", "100.5"), "USD", "2029-09-30", "Second lien"),
      t3d2("Euro notes", c("200", "200"), "EUR", "2030-01-15", "Senior secured"),
      t3d2("Shareholder loan", c("50", "50"), "USD", "", "Subordinated"),
      t3d2("Bridge", c("75", "75"), "USD", "2029-01-31", "First lien"),
    ]),
  ).map(stack);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["refinancing-wall-USD", "Maturities by seniority, USD", "USD"],
    ["refinancing-wall-EUR", "Maturities by seniority, EUR", "EUR"],
  ]);
  const [usd, eur] = figures;
  expect(usd!.table).toBe("T3D.2");
  expect(usd!.categoryLabel).toBe("Year");
  expect(usd!.categories).toEqual(["2028", "2029", "2031", "Undated"]);
  expect(usd!.series.map((series) => [series.key, series.data])).toEqual([
    ["Senior unsecured", [{ value: "0" }, { value: "0" }, { value: "250" }, { value: "0" }]],
    ["First lien", [gap, { value: "575" }, { value: "0" }, { value: "0" }]],
    ["Second lien", [{ value: "0" }, { value: "100.5" }, { value: "0" }, { value: "0" }]],
    ["Subordinated", [{ value: "0" }, { value: "0" }, { value: "0" }, { value: "50" }]],
  ]);
  expect(usd!.summary).toBe(
    "975.5 USD known amount across 5 of 6 instruments (1 unstated); the nearest," +
      " Revolver, falls due 2028-12-15.",
  );
  expect(eur!.summary).toBe(
    "200 EUR amount in 1 instrument; the nearest, Euro notes, falls due 2030-01-15.",
  );
  expect(usd!.sourceOf(pick("First lien", "2029"))).toBe(
    "Sum of 2 rows: Term loan (Source Trace: Trace Term loan); Bridge (Source Trace: Trace Bridge)",
  );
});

test("the stacked registers draw only for their own module", () => {
  const sources = register("T2E.2", SOURCES, [t2e2("Cash", c("1", "1"), "Accessible", "E-1")]);
  const uses = register("T2E.3", USES, [t2e3("Tax", c("1", "1"), "Q1", "Mandatory", "E-1")]);
  expect(registerFigures(cp2dWith([sources, uses])).map((figure) => figure.key)).toEqual([
    "liquidity-sources",
    "cash-uses",
  ]);
  const cp1 = withRegisters("CP-1", [sources, uses]);
  expect([...liquiditySources(cp1), ...cashUses(cp1)]).toEqual([]);
  const rows = [t3d2("Notes", c("1", "1"), "USD", "2030-01-01", "Senior")];
  expect(refinancingWall({ ...cp3cWith(rows), module_id: "CP-3D" })).toEqual([]);
  expect(registerFigures(cp3cWith(rows)).map((figure) => figure.key)).toEqual([
    "refinancing-wall-USD",
  ]);
  const debt = register("T2F.2", RATES, [t2f2("Loan", c("1", "1"), "Fixed", "", "GBP")]);
  expect(rateMix(cp2dWith([debt]))).toEqual([]);
  expect(registerFigures({ ...cp2dWith([debt]), module_id: "CP-2E" })).toHaveLength(1);
});

function bars(figure: Figure) {
  if (figure.kind !== "bars") throw new Error(`A ${figure.kind} figure, not grouped bars.`);
  return figure;
}
const said = (figure: { series: { data: readonly unknown[] }[] }) =>
  figure.series.map((series) => series.data);

// CP-3C's T3D.8, as the profile declares it.
const EXPOSURE = [
  "Creditor Class",
  "Exposure: Base Case",
  "Exposure: Stress Case",
  "Exposure: LME Case",
  "Recovery Implication",
  "Priming / Subordination Risk",
  "Source Trace",
];
const t3d8 = (name: string, base: Served, stress: Served, lme: Served, trace: string) =>
  [name, base, stress, lme, "Partial", "Low", trace].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const exposures = (rows: Served[][], module = "CP-3C") =>
  lmeExposure({ ...cp2dWith([register("T3D.8", EXPOSURE, rows)]), module_id: module });

test("lmeExposure: base, stress and LME grouped by class; a row of two units splits by cell", () => {
  const figures = exposures([
    t3d8("Senior secured", c("100", "100"), c("120", "120"), c("Not modelled"), "E-1"),
    t3d8("Mezzanine", c("40%", "40"), c("30% [C2]", "30"), c("20%", "20"), "E-2"),
    t3d8("Unsecured", c("50", "50"), c("70", "70"), c("90", "90"), "E-3"),
    t3d8("Second lien", c("25", "25"), c("60%", "60"), c("TBD"), "E-4"),
  ]).map(bars);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["lme-exposure", "Exposure by case", undefined],
    ["lme-exposure-percent", "Exposure by case, %", "%"],
  ]);
  const [plain, percent] = figures;
  expect(plain).toMatchObject({ table: "T3D.8", categoryLabel: "Creditor Class" });
  expect(plain!.series.map((series) => [series.key, series.label])).toEqual([
    ["base", "Base"],
    ["stress", "Stress"],
    ["lme", "LME"],
  ]);
  // A cell written in another unit is a gap here, drawn in its own unit's figure.
  const elsewhere = (text: string) => ({
    value: null,
    reason: `${text}, drawn in its unit's figure`,
  });
  expect(plain!.categories).toEqual(["Senior secured", "Unsecured", "Second lien"]);
  expect(said(plain!)).toEqual([
    [{ value: "100" }, { value: "50" }, { value: "25" }],
    [{ value: "120" }, { value: "70" }, elsewhere("60%")],
    [{ value: null, reason: "Not modelled" }, { value: "90" }, { value: null, reason: "TBD" }],
  ]);
  expect(percent!.categories).toEqual(["Mezzanine", "Second lien"]);
  expect(said(percent!)).toEqual([
    [{ value: "40" }, elsewhere("25")],
    [{ value: "30" }, { value: "60" }],
    [{ value: "20" }, { value: null, reason: "TBD" }],
  ]);
  expect(percent!.summary).toBe(
    "Exposure as served, Base / Stress / LME: Mezzanine 40 / 30 / 20;" +
      " Second lien n/a (25, drawn in its unit's figure) / 60 / n/a (TBD).",
  );
  // A mark's index is its row's place in its own figure.
  expect(percent!.sourceOf({ ...pick("base", "Second lien"), index: 1 })).toBe(
    "Recovery Implication: Partial; Priming / Subordination Risk: Low; Source Trace: E-4",
  );
});

// CP-4's T4C.5, as the profile declares it.
const BASKETS = [
  "Capacity Type",
  "Basket / Test",
  "Formula",
  "Conditions",
  "Current Input",
  "Usage",
  "Estimated Capacity",
  "Remaining Capacity",
  "Status",
  "Severity",
  "Risk Mechanic",
  "Credit Implication",
  "Evidence ID",
];
const t4c5 = (name: string, usage: Served, estimated: Served, remaining: Served) =>
  ["Debt", name, "", "", "", usage, estimated, remaining, "Open", "Medium", "", "", "E-9"].map(
    (cell) => (typeof cell === "string" ? c(cell) : cell),
  );

test("basketCapacity: usage stacked on remaining capacity, the estimate named, never drawn", () => {
  const cp4 = (rows: Served[][], module = "CP-4") =>
    basketCapacity({ ...cp2dWith([register("T4C.5", BASKETS, rows)]), module_id: module });
  const figures = cp4([
    t4c5("General basket", c("10", "10"), c("999", "999"), c("40", "40")),
    t4c5("Leverage test", c("1.5x", "1.5"), c("2.0x", "2.0"), c("0.5x", "0.5")),
    t4c5("Ratio debt", c("Not disclosed"), c("75", "75"), c("25", "25")),
  ]).map(stack);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["basket-capacity", "Baskets, used and remaining", undefined],
    ["basket-capacity-x", "Baskets, used and remaining, x", "x"],
  ]);
  const [plain] = figures;
  expect(plain).toMatchObject({ table: "T4C.5", categoryLabel: "Basket / Test" });
  expect(plain!.categories).toEqual(["General basket", "Ratio debt"]);
  expect(plain!.series.map((series) => [series.key, series.label, series.data])).toEqual([
    ["usage", "Usage", [{ value: "10" }, { value: null, reason: "Not disclosed" }]],
    ["remaining", "Remaining Capacity", [{ value: "40" }, { value: "25" }]],
  ]);
  expect(plain!.summary).toBe(
    "Baskets as served, Usage / Remaining Capacity:" +
      " General basket 10 / 40; Ratio debt n/a (Not disclosed) / 25.",
  );
  expect(plain!.sourceOf(pick("usage", "General basket"))).toBe(
    "Estimated Capacity: 999; Status: Open; Severity: Medium; Evidence ID: E-9",
  );
  expect(cp4([t4c5("General basket", c("1", "1"), c("2", "2"), c("1", "1"))], "CP-4C")).toEqual([]);
});

// CP-4C's T4E.7 and T4E.2, as the profile declares them.
const RECOVERY = [
  "scenario",
  "class/instrument",
  "allowed claim",
  "cash/debt/equity/warrant value",
  "total recovery",
  "timing",
  "currency",
];
const t4e7 = (scenario: string, name: string, claim: Served, total: Served, currency: string) =>
  [scenario, name, claim, "60 / 20 / 10 / 0", total, "Exit", currency].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const CLAIMS = [
  "class/claim ID",
  "obligor",
  "principal/accrued/PIK",
  "currency",
  "security/guarantee",
  "priority",
  "disputed/contingent",
  "evidence",
];

test("recoveryByClass: claim beside recovery per scenario and currency; the packed value not drawn", () => {
  const figures = recoveryByClass(
    cp4cWith([
      register("T4E.7", RECOVERY, [
        t4e7("Base", "Senior", c("100", "100"), c("90", "90"), "USD"),
        t4e7("Base", "Junior", c("50", "50"), c("10", "10"), "USD"),
        t4e7("Base", "Euro notes", c("30", "30"), c("15", "15"), "EUR"),
        t4e7("Downside", "Senior", c("100", "100"), c("TBD"), "USD"),
      ]),
    ]),
  ).map(bars);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["recovery-by-class-0", "Recovery by class, Base, USD", "USD"],
    ["recovery-by-class-1", "Recovery by class, Base, EUR", "EUR"],
    ["recovery-by-class-2", "Recovery by class, Downside", "USD"],
  ]);
  const [usd, , downside] = figures;
  expect(usd).toMatchObject({ table: "T4E.7", categoryLabel: "class/instrument" });
  expect(usd!.categories).toEqual(["Senior", "Junior"]);
  // N192: the packed column is never a series.
  expect(usd!.series.map((series) => [series.key, series.label, series.data])).toEqual([
    ["claim", "allowed claim", [{ value: "100" }, { value: "50" }]],
    ["recovery", "total recovery", [{ value: "90" }, { value: "10" }]],
  ]);
  expect(usd!.summary).toBe(
    "Recovery as served, allowed claim / total recovery: Senior 100 / 90; Junior 50 / 10.",
  );
  expect(downside!.series[1]!.data).toEqual([{ value: null, reason: "TBD" }]);
  expect(usd!.sourceOf({ ...pick("claim", "Junior"), index: 1 })).toBe(
    "timing: Exit; cash/debt/equity/warrant value: 60 / 20 / 10 / 0",
  );
});

const recoveries = (rows: Served[][]) =>
  recoveryByClass(cp4cWith([register("T4E.7", RECOVERY, rows)])).map(bars);

test("a blank scenario leaves its part out of a title", () => {
  const [allocation] = allocations([
    t4e5(" ", "HoldCo", c("10", "10"), "Senior", c("10", "10"), c("0", "0")),
  ]);
  expect(allocation!.title).toBe("Value allocation");
  const titles = (rows: Served[][]) => recoveries(rows).map((figure) => figure.title);
  expect(titles([t4e7("", "Senior", c("1", "1"), c("1", "1"), "USD")])).toEqual([
    "Recovery by class",
  ]);
  expect(
    titles([
      t4e7("", "Senior", c("1", "1"), c("1", "1"), "USD"),
      t4e7("", "Euro notes", c("1", "1"), c("1", "1"), "EUR"),
    ]),
  ).toEqual(["Recovery by class, USD", "Recovery by class, EUR"]);
});

test("a recovery written in % or x draws in its own unit's figure, not on the currency's", () => {
  const figures = recoveries([
    t4e7("Base", "Senior", c("100", "100"), c("45%", "45"), "USD"),
    t4e7("Base", "Junior", c("50", "50"), c("10", "10"), "USD"),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["recovery-by-class-0", "Recovery by class, Base", "USD"],
    ["recovery-by-class-0-percent", "Recovery by class, Base, %", "%"],
  ]);
  const elsewhere = (text: string) => ({
    value: null,
    reason: `${text}, drawn in its unit's figure`,
  });
  const [amounts, percent] = figures;
  expect(said(amounts!)).toEqual([
    [{ value: "100" }, { value: "50" }],
    [elsewhere("45%"), { value: "10" }],
  ]);
  expect(percent!.categories).toEqual(["Senior"]);
  expect(said(percent!)).toEqual([[elsewhere("100")], [{ value: "45" }]]);
});

test("T4E.2 draws nothing: its one amount column packs principal, accrued and PIK (N192)", () => {
  const row = ["Senior", "OpCo", "100 / 5 / 2", "USD", "First lien", "1", "No", "E-1"].map((cell) =>
    c(cell),
  );
  expect(registerFigures(cp4cWith([register("T4E.2", CLAIMS, [row])]))).toEqual([]);
});

test("the grouped registers draw only for their own module, and past MAX_MARKS are stated", () => {
  const exposure = register("T3D.8", EXPOSURE, [
    t3d8("Senior", c("1", "1"), c("2", "2"), c("3", "3"), "E-1"),
  ]);
  const baskets = register("T4C.5", BASKETS, [
    t4c5("Basket", c("1", "1"), c("2", "2"), c("1", "1")),
  ]);
  const recovery = register("T4E.7", RECOVERY, [
    t4e7("Base", "Senior", c("1", "1"), c("1", "1"), "USD"),
  ]);
  const all = [exposure, baskets, recovery];
  const keys = (module: string) =>
    registerFigures({ ...cp2dWith(all), module_id: module }).map((figure) => figure.key);
  expect(keys("CP-3C")).toEqual(["lme-exposure"]);
  expect(keys("CP-4")).toEqual(["basket-capacity"]);
  expect(keys("CP-4C")).toEqual(["recovery-by-class-0"]);
  expect(exposures(exposure.rows, "CP-3D")).toEqual([]);
  // Three bars a row: 667 rows are 2,001 marks.
  const many = Array.from({ length: 667 }, (_, index) =>
    t3d8(`Class ${index}`, c("1", "1"), c("1", "1"), c("1", "1"), "E-1"),
  );
  expect(exposures(many)[0]).toMatchObject({ oversized: true, key: "lme-exposure" });
});

// CP-2G's T2H.4 and T2H.6, as the profile declares them.
const FORECAST = [
  "period",
  "case",
  "revenue",
  "EBITDA",
  "margin",
  "CFO",
  "capex",
  "FCF",
  "evidence/assumption IDs",
];
const t2h4 = (period: string, kase: string, revenue: Served, ebitda: Served, fcf: Served) =>
  [period, kase, revenue, ebitda, "", "", "", fcf, `A-${period}`].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const CREDIT_PATH = [
  "period",
  "case",
  "gross/net leverage",
  "coverage",
  "FCF/debt",
  "liquidity runway",
  "definition IDs",
];
const t2h6 = (period: string, kase: string, leverage: Served, coverage: Served, ratio: Served) =>
  [period, kase, leverage, coverage, ratio, "18 months", `D-${period}`].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const cp2gWith = (registers: Register[], module = "CP-2G"): HandoffView => ({
  ...handoffOf("CP-1"),
  module_id: module,
  tables: [],
  registers,
});
function line(figure: Figure) {
  if (figure.kind !== "line") throw new Error(`A ${figure.kind} figure, not a line.`);
  return figure;
}

test("caseRank: BASE, then DOWNSIDE, then any other case, trimmed and case-insensitive", () => {
  const cases = ["Stress", " downside", "Upside", "base "];
  expect([...cases].sort((a, b) => caseRank(a) - caseRank(b))).toEqual([
    "base ",
    " downside",
    "Stress",
    "Upside",
  ]);
});

test("forecastCases: a line figure a metric, base then downside then the rest, as served", () => {
  const figures = forecastCases(
    cp2gWith([
      register("T2H.4", FORECAST, [
        t2h4("FY26", "Upside", c("130", "130"), c("30", "30"), c("12", "12")),
        t2h4("FY26", " downside ", c("90", "90"), c("15", "15"), c("TBD")),
        t2h4("FY26", "Base", c("100", "100"), c("20", "20"), c("8", "8")),
        t2h4("FY27", "Base", c("110", "110"), c("22", "22"), c("9", "9")),
        t2h4("FY27", " downside ", c("80", "80"), c("12", "12"), c("-2", "-2")),
      ]),
    ]),
  ).map(line);
  expect(figures.map((figure) => [figure.key, figure.table, figure.title, figure.unit])).toEqual([
    ["forecast-cases-revenue", "T2H.4", "Revenue, base and downside", undefined],
    ["forecast-cases-ebitda", "T2H.4", "EBITDA, base and downside", undefined],
    ["forecast-cases-fcf", "T2H.4", "FCF, base and downside", undefined],
  ]);
  const [revenue, , fcf] = figures;
  expect(revenue!.categories).toEqual(["FY26", "FY27"]);
  expect(revenue!.series.map((series) => [series.key, series.label, series.origin])).toEqual([
    ["BASE", "Base", "model"],
    ["DOWNSIDE", "downside", "model"],
    ["UPSIDE", "Upside", "model"],
  ]);
  expect(said(revenue!)).toEqual([
    [{ value: "100" }, { value: "110" }],
    [{ value: "90" }, { value: "80" }],
    [{ value: "130" }, { value: null, reason: "not stated" }],
  ]);
  expect(said(fcf!)[1]).toEqual([{ value: null, reason: "TBD" }, { value: "-2" }]);
  expect(revenue!.summary).toBe(
    "Revenue as served, Base / downside / Upside: FY26 100 / 90 / 130;" +
      " FY27 110 / 80 / n/a (not stated).",
  );
  expect(revenue!.sourceOf(pick("DOWNSIDE", "FY27"))).toBe("evidence/assumption IDs: A-FY27");
  expect(revenue!.sourceOf(pick("UPSIDE", "FY27"))).toBeNull();
});

test("creditPath: leverage, coverage and FCF/debt, a packed leverage cell a gap (N192)", () => {
  const figures = creditPath(
    cp2gWith([
      register("T2H.6", CREDIT_PATH, [
        t2h6("FY26", "BASE", c("4.2x / 3.9x"), c("2.5x", "2.5"), c("10%", "10")),
        t2h6("FY27", "BASE", c("3.8x", "3.8"), c("2.8x", "2.8"), c("12%", "12")),
        t2h6("FY26", "DOWNSIDE", c("5.1x", "5.1"), c("1.9x", "1.9"), c("6%", "6")),
      ]),
    ]),
  ).map(line);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["credit-path-gross-net-leverage", "Gross/net leverage, base and downside", "x"],
    ["credit-path-coverage", "Coverage, base and downside", "x"],
    ["credit-path-fcf-debt", "FCF/debt, base and downside", "%"],
  ]);
  const [leverage] = figures;
  expect(leverage!.series.map((series) => series.key)).toEqual(["BASE", "DOWNSIDE"]);
  expect(said(leverage!)).toEqual([
    [{ value: null, reason: "4.2x / 3.9x" }, { value: "3.8" }],
    [{ value: "5.1" }, { value: null, reason: "not stated" }],
  ]);
  expect(leverage!.sourceOf(pick("BASE", "FY26"))).toBe("definition IDs: D-FY26");
});

test("a metric written in two units draws a figure per unit, each cell in its own", () => {
  const figures = creditPath(
    cp2gWith([
      register("T2H.6", CREDIT_PATH, [
        t2h6("FY26", "Base", c("4x", "4"), c("2x", "2"), c("10%", "10")),
        t2h6("FY27", "Base", c("3x", "3"), c("2x", "2"), c("0.5x", "0.5")),
      ]),
    ]),
  ).map(line);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit])).toEqual([
    ["credit-path-gross-net-leverage", "Gross/net leverage, base and downside", "x"],
    ["credit-path-coverage", "Coverage, base and downside", "x"],
    ["credit-path-fcf-debt-percent", "FCF/debt, base and downside, %", "%"],
    ["credit-path-fcf-debt-x", "FCF/debt, base and downside, x", "x"],
  ]);
  const [, , percent, multiple] = figures;
  expect(said(percent!)).toEqual([
    [{ value: "10" }, { value: null, reason: "0.5x, drawn in its unit's figure" }],
  ]);
  expect(said(multiple!)).toEqual([
    [{ value: null, reason: "10%, drawn in its unit's figure" }, { value: "0.5" }],
  ]);
});

test("the case lines draw only for CP-2G, and past MAX_MARKS are stated", () => {
  const forecast = register("T2H.4", FORECAST, [
    t2h4("FY26", "Base", c("1", "1"), c("1", "1"), c("1", "1")),
  ]);
  const credit = register("T2H.6", CREDIT_PATH, [
    t2h6("FY26", "Base", c("1x", "1"), c("1x", "1"), c("1%", "1")),
  ]);
  const keys = (module: string) =>
    registerFigures(cp2gWith([forecast, credit], module)).map((figure) => figure.key);
  expect(keys("CP-2G")).toEqual([
    "forecast-cases-revenue",
    "forecast-cases-ebitda",
    "forecast-cases-fcf",
    "credit-path-gross-net-leverage",
    "credit-path-coverage",
    "credit-path-fcf-debt",
  ]);
  expect(keys("CP-2D")).toEqual([]);
  // Two cases over 1,001 periods are 2,002 points.
  const many = Array.from({ length: 1001 }, (_, index) => [
    t2h4(`P${index}`, "Base", c("1", "1"), c("1", "1"), c("1", "1")),
    t2h4(`P${index}`, "Downside", c("1", "1"), c("1", "1"), c("1", "1")),
  ]).flat();
  expect(forecastCases(cp2gWith([register("T2H.4", FORECAST, many)]))[0]).toMatchObject({
    oversized: true,
    key: "forecast-cases-revenue",
  });
});

test("a period and case stated twice draws a gap naming both, unless they agree", () => {
  const [leverage, coverage] = creditPath(
    cp2gWith([
      register("T2H.6", CREDIT_PATH, [
        t2h6("FY26", "Base", c("4.0x", "4.0"), c("2x", "2"), c("10%", "10")),
        t2h6("FY26", "Base", c("5.0x", "5.0"), c("2x", "2"), c("10%", "10")),
        t2h6("FY27", "Base", c("3.0x", "3.0"), c("2.5x", "2.5"), c("11%", "11")),
      ]),
    ]),
  ).map(line);
  expect(said(leverage!)).toEqual([
    [{ value: null, reason: "stated twice: 4.0x, 5.0x" }, { value: "3.0" }],
  ]);
  expect(said(coverage!)).toEqual([[{ value: "2" }, { value: "2.5" }]]);
  // Both rows name the one definition: a point's source states it once.
  expect(leverage!.sourceOf(pick("BASE", "FY26"))).toBe("definition IDs: D-FY26");
  expect(leverage!.summary).toBe(
    "Gross/net leverage as served, Base: FY26 n/a (stated twice: 4.0x, 5.0x); FY27 3.0.",
  );
});

test("cases group trimmed and case-insensitive, periods trimmed, a blank case named", () => {
  const [revenue] = forecastCases(
    cp2gWith([
      register("T2H.4", FORECAST, [
        t2h4("FY26 ", "Base", c("100", "100"), c("20", "20"), c("8", "8")),
        t2h4("FY27", "BASE", c("110", "110"), c("22", "22"), c("9", "9")),
        t2h4("FY26", " ", c("70", "70"), c("10", "10"), c("1", "1")),
      ]),
    ]),
  ).map(line);
  expect(revenue!.categories).toEqual(["FY26", "FY27"]);
  expect(revenue!.series.map((series) => [series.key, series.label])).toEqual([
    ["BASE", "Base"],
    ["row 3, case not stated", "row 3, case not stated"],
  ]);
  expect(said(revenue!)).toEqual([
    [{ value: "100" }, { value: "110" }],
    [{ value: "70" }, { value: null, reason: "not stated" }],
  ]);
  expect(revenue!.sourceOf(pick("BASE", "FY27"))).toBe("evidence/assumption IDs: A-FY27");
});

// CP-2E's T2F.5, CP-2A's T2B.6, CP-3D's T3E.8 and CP-2H's T2R.4, as the
// profiles declare them.
const RATE_SENSITIVITY = [
  "Sensitivity",
  "Formula",
  "Source Inputs",
  "Estimated Cash Impact",
  "FCF / Liquidity Implication",
  "Status",
  "Source Trace",
];
const t2f5 = (name: string, impact: Served, trace = `S-${name}`) =>
  [name, "Debt x shift", "", impact, "", "Calculated", trace].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const DOWNSIDE_SENSITIVITY = [
  "Sensitivity",
  "Input Basis",
  "Formula / Method",
  "Result",
  "Credit Interpretation",
  "Status",
  "Source Trace",
];
const t2b6 = (name: string, result: Served) =>
  [name, "", "EBITDA less 10%", result, "", "Supported", `S-${name}`].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const MOVES = [
  "scenario",
  "driver",
  "spread/yield/price assumption",
  "calculated move",
  "convexity/call limitation",
];
const t3e8 = (scenario: string, driver: string, move: Served) =>
  [scenario, driver, `+50bp ${driver}`, move, "Callable at par"].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const TRIGGERS = [
  "agency",
  "rating type",
  "trigger direction",
  "metric",
  "threshold",
  "case/period value",
  "headroom",
  "status",
];
const t2r4 = (
  agency: string,
  type: string,
  direction: string,
  metric: string,
  threshold: Served,
  current: Served,
  headroom: Served,
  status = "Within range",
) =>
  [agency, type, direction, metric, threshold, current, headroom, status].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const moduleWith = (module: string, registers: Register[]) => cp2gWith(registers, module);
function diverging(figure: Figure) {
  if (figure.kind !== "diverging") throw new Error(`A ${figure.kind} figure, not diverging.`);
  return figure;
}

test("rateSensitivities: a tornado, largest first by size, a gap last, every value as served", () => {
  const figures = rateSensitivities(
    moduleWith("CP-2E", [
      register("T2F.5", RATE_SENSITIVITY, [
        t2f5("Rates +100bp", c("(12.5)", "-12.5")),
        t2f5("Commodity", c("TBD")),
        t2f5("FX 10% EUR", c("30", "30")),
        t2f5("Rates -100bp", c("8", "8")),
      ]),
    ]),
  ).map(diverging);
  expect(figures).toHaveLength(1);
  const [figure] = figures;
  expect([figure!.key, figure!.table, figure!.title, figure!.unit]).toEqual([
    "rate-sensitivities",
    "T2F.5",
    "Rate and FX sensitivities",
    undefined,
  ]);
  expect(figure!.categories).toEqual(["FX 10% EUR", "Rates +100bp", "Rates -100bp", "Commodity"]);
  expect(figure!.series.map((series) => [series.key, series.label, series.origin])).toEqual([
    ["value", "Estimated Cash Impact", "model"],
  ]);
  expect(said(figure!)).toEqual([
    [{ value: "30" }, { value: "-12.5" }, { value: "8" }, { value: null, reason: "TBD" }],
  ]);
  expect(figure!.summary).toBe(
    "Estimated Cash Impact as served, largest first: FX 10% EUR 30; Rates +100bp -12.5;" +
      " Rates -100bp 8; Commodity n/a (TBD).",
  );
  expect(figure!.sourceOf(pick("value", "Rates -100bp"))).toBe(
    "Formula: Debt x shift; Status: Calculated; Source Trace: S-Rates -100bp",
  );
  expect(figure!.sourceOf(pick("value", "Nothing"))).toBeNull();
});

test("a sensitivity stated twice is a gap naming both, unless they agree; units split", () => {
  const [plain, percent] = rateSensitivities(
    moduleWith("CP-2E", [
      register("T2F.5", RATE_SENSITIVITY, [
        t2f5("Rates +100bp", c("5", "5"), "S-1"),
        t2f5("Rates +100bp", c("7", "7"), "S-2"),
        t2f5("FX", c("4", "4"), "S-3"),
        t2f5("FX", c("4", "4"), "S-3"),
        t2f5("Margin", c("2%", "2")),
        t2f5(" ", c("1", "1")),
      ]),
    ]),
  ).map(diverging);
  expect(plain!.categories).toEqual(["FX", "row 6, Sensitivity not stated", "Rates +100bp"]);
  expect(said(plain!)).toEqual([
    [{ value: "4" }, { value: "1" }, { value: null, reason: "stated twice: 5, 7" }],
  ]);
  // Both rows are named, each source once.
  expect(plain!.sourceOf(pick("value", "Rates +100bp"))).toBe(
    "Formula: Debt x shift; Status: Calculated; Source Trace: S-1; " +
      "Formula: Debt x shift; Status: Calculated; Source Trace: S-2",
  );
  expect(plain!.sourceOf(pick("value", "FX"))).toBe(
    "Formula: Debt x shift; Status: Calculated; Source Trace: S-3",
  );
  expect([percent!.key, percent!.title, percent!.unit, percent!.categories]).toEqual([
    "rate-sensitivities-percent",
    "Rate and FX sensitivities, %",
    "%",
    ["Margin"],
  ]);
});

test("downsideSensitivities: CP-2A's results as a tornado, its own sources", () => {
  const [figure] = downsideSensitivities(
    moduleWith("CP-2A", [
      register("T2B.6", DOWNSIDE_SENSITIVITY, [
        t2b6("EBITDA -10%", c("4.1x", "4.1")),
        t2b6("EBITDA -20%", c("-5.0x", "-5.0")),
      ]),
    ]),
  ).map(diverging);
  expect([figure!.key, figure!.table, figure!.title, figure!.unit]).toEqual([
    "downside-sensitivities-x",
    "T2B.6",
    "Downside sensitivities, x",
    "x",
  ]);
  expect(figure!.categories).toEqual(["EBITDA -20%", "EBITDA -10%"]);
  expect(said(figure!)).toEqual([[{ value: "-5.0" }, { value: "4.1" }]]);
  expect(figure!.sourceOf(pick("value", "EBITDA -10%"))).toBe(
    "Formula / Method: EBITDA less 10%; Status: Supported; Source Trace: S-EBITDA -10%",
  );
});

test("scenarioMoves: a tornado per scenario, its drivers by the size of their move", () => {
  const figures = scenarioMoves(
    moduleWith("CP-3D", [
      register("T3E.8", MOVES, [
        t3e8("Widening", "Spread", c("-3.5", "-3.5")),
        t3e8("Widening", "Rates", c("-1.25", "-1.25")),
        t3e8(" Tightening", "Spread", c("2", "2")),
        t3e8("Widening", "Call", c("n/a")),
        t3e8("Tightening ", "Rates", c("4", "4")),
      ]),
    ]),
  ).map(diverging);
  expect(figures.map((figure) => [figure.key, figure.title, figure.categories])).toEqual([
    ["scenario-moves-0", "Scenario moves, Widening", ["Spread", "Rates", "Call"]],
    ["scenario-moves-1", "Scenario moves, Tightening", ["Rates", "Spread"]],
  ]);
  expect(said(figures[0]!)).toEqual([
    [{ value: "-3.5" }, { value: "-1.25" }, { value: null, reason: "n/a" }],
  ]);
  expect(figures[1]!.sourceOf(pick("value", "Spread"))).toBe(
    "spread/yield/price assumption: +50bp Spread; convexity/call limitation: Callable at par",
  );
});

function triggers(rows: Served[][]) {
  return ratingTriggers(moduleWith("CP-2H", [register("T2R.4", TRIGGERS, rows)])).map(bullets);
}

test("ratingTriggers: bullets per agency, direction only as the bundle reads it", () => {
  const figures = triggers([
    t2r4(
      "Agency A",
      "Issuer",
      "Max-Ratio",
      "Leverage",
      c("5.0x", "5.0"),
      c("4.0x", "4.0"),
      c("1.0x", "1.0"),
    ),
    t2r4(
      "Agency B",
      "Issuer",
      "Floor",
      "Coverage",
      c("2.0x", "2.0"),
      c("3.0x", "3.0"),
      c("1.0x", "1.0"),
    ),
    // An agency's words, not a side the bundle reads: never inferred.
    t2r4(
      "Agency A",
      "Senior",
      "Downgrade",
      "Max leverage",
      c("6.0x", "6.0"),
      c("4.2x / 3.9x"),
      c("TBD"),
      "Not Calculable",
    ),
  ]);
  expect(figures.map((figure) => [figure.key, figure.table, figure.title, figure.unit])).toEqual([
    ["rating-triggers-0-x", "T2R.4", "Rating triggers, Agency A, x", "x"],
    ["rating-triggers-1-x", "T2R.4", "Rating triggers, Agency B, x", "x"],
  ]);
  const [a, b] = figures;
  expect(a!.bullets).toEqual([
    {
      key: "0",
      label: "Leverage (Issuer, max-ratio)",
      direction: "max",
      threshold: { value: "5.0" },
      current: { value: "4.0" },
      headroom: { value: "1.0" },
      origin: "model",
    },
    // Keyed by its place among its agency's rows.
    {
      key: "1",
      label: "Max leverage (Senior, downgrade)",
      direction: null,
      threshold: { value: "6.0" },
      current: { value: null, reason: "4.2x / 3.9x" },
      headroom: { value: null, reason: "TBD" },
      origin: "model",
    },
  ]);
  expect(b!.bullets![0]!.direction).toBe("min");
  expect(a!.summary).toBe(
    "Headroom as served: Leverage (Issuer, max-ratio) 1.0; Max leverage (Senior, downgrade) n/a (TBD).",
  );
  expect(
    a!.sourceOf({
      series: "current",
      category: "Max leverage (Senior, downgrade)",
      index: 1,
      value: null,
      origin: "model",
    }),
  ).toBe("status: Not Calculable");
});

test("a trigger stated twice in one agency is a gap naming both; other modules draw nothing", () => {
  const [figure] = triggers([
    // An upgrade and a downgrade trigger on one metric are two triggers.
    t2r4("A", "", "Ceiling", "Leverage", c("5", "5"), c("4", "4"), c("1", "1")),
    t2r4("A", "", "minimum", "Leverage", c("3.5", "3.5"), c("4", "4"), c("0.5", "0.5")),
    // The same metric, rating type and direction, however spelt: one trigger.
    t2r4("A", "", " ceiling ", "Leverage", c("6", "6"), c("4", "4"), c("2", "2")),
  ]);
  expect(figure!.bullets).toEqual([
    {
      key: "0",
      label: "Leverage (ceiling)",
      direction: "max",
      threshold: { value: null, reason: "stated twice: 5, 6" },
      current: { value: "4" },
      headroom: { value: null, reason: "stated twice: 1, 2" },
      origin: "model",
    },
    {
      key: "1",
      label: "Leverage (minimum)",
      direction: "min",
      threshold: { value: "3.5" },
      current: { value: "4" },
      headroom: { value: "0.5" },
      origin: "model",
    },
  ]);
  const t2r = register("T2R.4", TRIGGERS, [
    t2r4("A", "", "ceiling", "Leverage", c("5", "5"), c("4", "4"), c("1", "1")),
  ]);
  const t2f = register("T2F.5", RATE_SENSITIVITY, [t2f5("FX", c("4", "4"))]);
  const t2b = register("T2B.6", DOWNSIDE_SENSITIVITY, [t2b6("FX", c("4", "4"))]);
  const t3e = register("T3E.8", MOVES, [t3e8("Base", "FX", c("4", "4"))]);
  const keys = (module: string) =>
    registerFigures(moduleWith(module, [t2r, t2f, t2b, t3e])).map((figure) => figure.key);
  expect(keys("CP-2H")).toEqual(["rating-triggers-0"]);
  // A blank metric is named, never an empty mark; a blank direction is left out.
  const [blank] = triggers([t2r4("A", "Issuer", "", " ", c("5", "5"), c("4", "4"), c("1", "1"))]);
  expect(blank!.bullets![0]!.label).toBe("row 1, metric not stated (Issuer)");
  expect(keys("CP-2E")).toEqual(["rate-sensitivities"]);
  expect(keys("CP-2A")).toEqual(["downside-sensitivities"]);
  expect(keys("CP-3D")).toEqual(["scenario-moves-0"]);
  expect(keys("CP-2G")).toEqual([]);
  // A bar a sensitivity: 2,001 are too many to draw.
  const many = Array.from({ length: 2001 }, (_, index) => t2f5(`S${index}`, c("1", "1")));
  expect(
    rateSensitivities(moduleWith("CP-2E", [register("T2F.5", RATE_SENSITIVITY, many)]))[0],
  ).toMatchObject({ oversized: true, key: "rate-sensitivities" });
});

const FACTORS = [
  "Category",
  "Factor",
  "Weight",
  "Raw Score 1–5",
  "Weighted Score",
  "Confidence",
  "Evidence",
  "Risk Mechanic",
  "Credit Implication",
];
const t33 = (factor: string, weighted: Served, category = "Business") =>
  [category, factor, "20%", "4", weighted, "High", "E-1", "m", "i"].map((cell) =>
    typeof cell === "string" ? c(cell) : cell,
  );
const scores = (module: string, registers: Register[]) =>
  scoreRegisters(moduleWith(module, registers)).map(bars);

test("scoreRegisters: CP-3's factors as horizontal bars, the highest and lowest named as served", () => {
  const figures = scores("CP-3", [
    register("T3.3", FACTORS, [
      t33("Scale", c("0.80", "0.80")),
      t33("Leverage", c("1.2", "1.2"), "Financial"),
      t33("Liquidity", c("0.4", "0.4"), "Financial"),
      t33("Governance", c("TBD")),
    ]),
  ]);
  expect(figures).toHaveLength(1);
  const [figure] = figures;
  expect([figure!.key, figure!.table, figure!.title, figure!.orientation]).toEqual([
    "weighted-factor-scores",
    "T3.3",
    "Weighted factor scores",
    "horizontal",
  ]);
  expect(figure!.categories).toEqual(["Scale", "Leverage", "Liquidity", "Governance"]);
  expect(figure!.series.map((series) => [series.key, series.label, series.origin])).toEqual([
    ["score", "Weighted Score", "model"],
  ]);
  expect(said(figure!)).toEqual([
    [{ value: "0.80" }, { value: "1.2" }, { value: "0.4" }, { value: null, reason: "TBD" }],
  ]);
  expect(figure!.summary).toBe(
    "Weighted Score as served. Highest: Leverage 1.2. Lowest: Liquidity 0.4.",
  );
  expect(figure!.sourceOf(pick("score", "Liquidity"))).toBe(
    "Category: Financial; Weight: 20%; Raw Score 1–5: 4; Confidence: High",
  );
});

test("scoreRegisters: a factor stated twice is one bar, a gap naming each text where they differ", () => {
  const [figure] = scores("CP-3", [
    register("T3.3", FACTORS, [
      t33("Scale", c("0.8", "0.8")),
      t33("Scale", c("0.8", "0.8")),
      t33("Leverage", c("1", "1")),
      t33("Leverage", c("2", "2")),
    ]),
  ]);
  expect(figure!.categories).toEqual(["Scale", "Leverage"]);
  expect(said(figure!)).toEqual([
    [{ value: "0.8" }, { value: null, reason: "stated twice: 1, 2" }],
  ]);
  expect(figure!.summary).toBe(
    "Weighted Score as served. One factor scores: Scale 0.8; 1 is n/a. Leverage stated twice.",
  );
});

test("scoreRegisters: no row states a score, the summary says so", () => {
  const [figure] = scores("CP-3", [register("T3.3", FACTORS, [t33("Scale", c("TBD"))])]);
  expect(figure!.summary).toBe("Weighted Score as served. No row states a score.");
});

const RANKING = [
  "Rank",
  "Issuer",
  "Security / Tranche",
  "Composite Score /100",
  "Normalized /5.0",
  "Credit Tier",
  "Fundamental View",
  "Relative Value View",
  "Final Recommendation",
];
const t37 = (rank: string, issuer: string, tranche: string, score: Served) => [
  c(rank, /^[0-9]+$/.test(rank) ? rank : null),
  c(issuer),
  c(tranche),
  score,
  c("3.5", "3.5"),
  c("Tier 2"),
  c("f"),
  c("r"),
  c("Buy"),
];

test("scoreRegisters: CP-3's composite scores in rank order, a rank that is no number last", () => {
  const [figure] = scores("CP-3", [
    register("T3.7", RANKING, [
      t37("2", "Alpha", "Sr Notes", c("71.5", "71.5")),
      t37("n/a", "Delta", "TL", c("40", "40")),
      t37("tbd", "Omega", "RCF", c("10", "10")),
      t37("1", "Beta", "2L", c("88", "88")),
      t37("3", "Gamma", "Sub", c("55.25", "55.25")),
    ]),
  ]);
  expect([figure!.key, figure!.title, figure!.orientation]).toEqual([
    "composite-score",
    "Composite score /100",
    "horizontal",
  ]);
  expect(figure!.categories).toEqual([
    "Beta 2L",
    "Alpha Sr Notes",
    "Gamma Sub",
    "Delta TL",
    "Omega RCF",
  ]);
  expect(figure!.series[0]!.label).toBe("Composite Score /100");
  expect(said(figure!)).toEqual([
    [{ value: "88" }, { value: "71.5" }, { value: "55.25" }, { value: "40" }, { value: "10" }],
  ]);
  expect(figure!.summary).toBe(
    "Composite Score /100 as served. Highest: Beta 2L 88. Lowest: Omega RCF 10.",
  );
  expect(figure!.sourceOf(pick("score", "Beta 2L"))).toBe(
    "Credit Tier: Tier 2; Final Recommendation: Buy",
  );
});

test("scoreRegisters: CP-4's legal areas and CP-6's debate dimensions, each its own columns", () => {
  const legal = scores("CP-4", [
    register(
      "T4.11",
      [
        "Area",
        "Score 1–5",
        "Evidence",
        "Risk Mechanic",
        "Credit Implication",
        "Confidence",
        "Evidence ID",
      ],
      [
        [c("Security"), c("4", "4"), c("e"), c("m"), c("i"), c("Med"), c("L-1")],
        [c("Priming"), c("2", "2"), c("e"), c("m"), c("i"), c("Low"), c("L-2")],
      ],
    ),
  ]);
  expect(legal.map((f) => [f.key, f.table, f.title, f.categories, f.series[0]!.label])).toEqual([
    [
      "legal-area-scores",
      "T4.11",
      "Legal area scores, 1 to 5",
      ["Security", "Priming"],
      "Score 1–5",
    ],
  ]);
  expect(legal[0]!.sourceOf(pick("score", "Priming"))).toBe("Confidence: Low; Evidence ID: L-2");
  const debate = scores("CP-6", [
    register(
      "T6A.6",
      ["Dimension", "Score (1-5)", "Bull Evidence", "Bear Evidence", "Chair Assessment"],
      [[c("Cash flow"), c("3.5", "3.5"), c("b"), c("r"), c("Balanced")]],
    ),
  ]);
  expect(debate.map((f) => [f.key, f.title, f.series[0]!.label, f.orientation])).toEqual([
    ["debate-scores", "Debate scores by dimension, 1 to 5", "Score (1-5)", "horizontal"],
  ]);
  expect(debate[0]!.sourceOf(pick("score", "Cash flow"))).toBe("Chair Assessment: Balanced");
  expect(debate[0]!.summary).toBe("Score (1-5) as served. One dimension scores: Cash flow 3.5.");
});

test("scoreRegisters: a register of another module draws nothing", () => {
  expect(scores("CP-2A", [register("T3.3", FACTORS, [t33("Scale", c("1", "1"))])])).toEqual([]);
});

// CP-8's T7.4, as the profile declares it.
const OUTCOME = [
  "Metric",
  "Expected",
  "Realized",
  "Variance (direction + magnitude)",
  "Confidence",
  "Evidence ID",
];
const t74 = (metric: string, expected: Served, realized: Served, variance: string, id = "V-1") => [
  c(metric),
  expected,
  realized,
  c(variance),
  c("Medium"),
  c(id),
];
function dumbbell(figure: Figure) {
  if (figure.kind !== "dumbbell") throw new Error(`A ${figure.kind} figure, not a dumbbell.`);
  return figure;
}
const outcomes = (rows: Served[][], module = "CP-8") =>
  expectedRealised(moduleWith(module, [register("T7.4", OUTCOME, rows)])).map(dumbbell);

test("expectedRealised: a dumbbell a metric, expected to realised, a figure a unit", () => {
  const figures = outcomes([
    t74("Leverage", c("4.0x", "4.0"), c("4.6x", "4.6"), "Up 0.6x, adverse", "V-1"),
    t74("EBITDA margin", c("20%", "20"), c("17.5%", "17.5"), "Down 2.5pp", "V-2"),
    t74("Coverage", c("3.0x", "3.0"), c("Not yet reported"), "", "V-3"),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit, figure.table])).toEqual([
    ["expected-realised-x", "Expected against realised, x", "x", "T7.4"],
    ["expected-realised-percent", "Expected against realised, %", "%", "T7.4"],
  ]);
  const [ratios] = figures;
  expect([ratios!.fromLabel, ratios!.toLabel, ratios!.categoryLabel]).toEqual([
    "Expected",
    "Realized",
    "Metric",
  ]);
  expect(ratios!.dumbbells).toEqual([
    {
      key: "0",
      label: "Leverage",
      from: { value: "4.0" },
      to: { value: "4.6" },
      origin: "model",
    },
    {
      key: "2",
      label: "Coverage",
      from: { value: "3.0" },
      to: { value: null, reason: "Not yet reported" },
      origin: "model",
    },
  ]);
  // The variance as served, never computed from the two ends.
  expect(ratios!.summary).toBe(
    "Variance as served: Leverage Up 0.6x, adverse; Coverage not stated.",
  );
  const pressed = {
    series: "to",
    category: "Coverage",
    index: 1,
    value: null,
    origin: "model" as const,
  };
  expect(ratios!.sourceOf(pressed)).toBe("Confidence: Medium; Evidence ID: V-3");
  expect(ratios!.sourceOf({ ...pressed, index: 0 })).toBe(
    "Variance (direction + magnitude): Up 0.6x, adverse; Confidence: Medium; Evidence ID: V-1",
  );
});

test("expectedRealised: a metric stated twice is one row, a gap naming each text where they differ", () => {
  const [figure] = outcomes([
    t74("Leverage", c("4.0x", "4.0"), c("4.6x", "4.6"), "Up 0.6x"),
    t74("Leverage", c("4.0x", "4.0"), c("4.8x", "4.8"), "Up 0.8x"),
  ]);
  expect(figure!.dumbbells).toEqual([
    {
      key: "0",
      label: "Leverage",
      from: { value: "4.0" },
      to: { value: null, reason: "stated twice: 4.6x, 4.8x" },
      origin: "model",
    },
  ]);
  expect(figure!.summary).toBe(
    "Variance as served: Leverage stated twice: Up 0.6x, Up 0.8x. Leverage stated twice.",
  );
});

test("expectedRealised: ends in two units join each unit's figure, the other end a gap naming it", () => {
  const figures = outcomes([t74("", c("4.0x", "4.0"), c("45%", "45"), "Mixed")]);
  expect(figures.map((figure) => [figure.key, figure.dumbbells])).toEqual([
    [
      "expected-realised-x",
      [
        {
          key: "0",
          label: "row 1, Metric not stated",
          from: { value: "4.0" },
          to: { value: null, reason: "45%, drawn in its unit's figure" },
          origin: "model",
        },
      ],
    ],
    [
      "expected-realised-percent",
      [
        {
          key: "0",
          label: "row 1, Metric not stated",
          from: { value: null, reason: "4.0x, drawn in its unit's figure" },
          to: { value: "45" },
          origin: "model",
        },
      ],
    ],
  ]);
});

test("expectedRealised: another module's T7.4 draws nothing; past the marks it is stated", () => {
  expect(outcomes([t74("Leverage", c("4", "4"), c("5", "5"), "Up 1")], "CP-7")).toEqual([]);
  const cp8 = moduleWith("CP-8", [
    register("T7.4", OUTCOME, [t74("Leverage", c("4", "4"), c("5", "5"), "Up 1")]),
  ]);
  expect(registerFigures(cp8).map((figure) => figure.key)).toEqual(["expected-realised"]);
  // Two dots a metric: 1,001 metrics are too many to draw.
  const many = Array.from({ length: 1001 }, (_, index) =>
    t74(`M${index}`, c("4", "4"), c("5", "5"), "Up 1"),
  );
  expect(expectedRealised(moduleWith("CP-8", [register("T7.4", OUTCOME, many)]))[0]).toMatchObject({
    oversized: true,
    key: "expected-realised",
    summary: expect.stringMatching(/^2002 marks/),
  });
});

// CP-3D's T3E.3, as the profile declares it.
const ISSUER_CURVE = [
  "security_id",
  "maturity/call date",
  "spread/yield",
  "seniority",
  "curve residual",
  "explanation status",
];
const t3e3 = (id: string, date: string, spread: Served, seniority: string, residual = "+12") => [
  c(id),
  c(date),
  spread,
  c(seniority),
  c(residual),
  c("Explained"),
];
function scatter(figure: Figure) {
  if (figure.kind !== "scatter") throw new Error(`A ${figure.kind} figure, not a scatter.`);
  return figure;
}
const curves = (rows: Served[][], module = "CP-3D") =>
  spreadCurve(moduleWith(module, [register("T3E.3", ISSUER_CURVE, rows)])).map(scatter);

test("spreadCurve: a point a security, its spread at its date, coloured by seniority", () => {
  const figures = curves([
    t3e3("NOTE-A", "2031-06-15 [C1]", c("412.5", "412.5"), "Senior secured"),
    t3e3("NOTE-B", "2029-03", c("275", "275"), "Subordinated", "-8"),
    t3e3("", "03/04/2031", c("Not quoted"), ""),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit, figure.table])).toEqual([
    ["spread-curve", "Spread against maturity", undefined, "T3E.3"],
  ]);
  const [curve] = figures;
  expect([curve!.xLabel, curve!.pointLabel, curve!.valueLabel, curve!.groupLabel]).toEqual([
    "maturity/call date",
    "security_id",
    "spread/yield",
    "seniority",
  ]);
  // The date as written past its citation markers; the chart reads it, never this.
  expect(curve!.points).toEqual([
    {
      key: "0",
      label: "NOTE-A",
      at: "2031-06-15",
      value: { value: "412.5" },
      group: "Senior secured",
      origin: "model",
    },
    {
      key: "1",
      label: "NOTE-B",
      at: "2029-03",
      value: { value: "275" },
      group: "Subordinated",
      origin: "model",
    },
    {
      key: "2",
      label: "row 3, security_id not stated",
      at: "03/04/2031",
      value: { value: null, reason: "Not quoted" },
      group: "seniority not stated",
      origin: "model",
    },
  ]);
  expect(curve!.summary).toBe(
    "spread/yield as served, by maturity/call date: NOTE-A 2031-06-15 412.5; NOTE-B 2029-03 275; row 3, security_id not stated 03/04/2031 n/a (Not quoted).",
  );
  const pressed = { series: "Subordinated", category: "NOTE-B", index: 1, value: "275" };
  expect(curve!.sourceOf({ ...pressed, origin: "model" })).toBe(
    "curve residual: -8; explanation status: Explained",
  );
});

test("spreadCurve: a security stated twice is one point, each cell a gap naming each text where they differ", () => {
  const [curve] = curves([
    t3e3("NOTE-A", "2031-06-15", c("412.5", "412.5"), "Senior"),
    t3e3("NOTE-A", "2032-06-15", c("415", "415"), "Senior", "+3"),
    t3e3("NOTE-B", "2030", c("200", "200"), "Senior"),
    t3e3("NOTE-B", "2030", c("200", "200"), "Senior"),
  ]);
  expect(curve!.points.map(({ key, at, value, group }) => [key, at, value, group])).toEqual([
    ["0", "", { value: null, reason: "stated twice: 412.5, 415" }, "Senior"],
    ["2", "2030", { value: "200" }, "Senior"],
  ]);
  expect(
    curve!.sourceOf({
      series: "Senior",
      category: "NOTE-A",
      index: 0,
      value: null,
      origin: "model",
    }),
  ).toBe(
    "curve residual: +12; explanation status: Explained; curve residual: +3; explanation status: Explained",
  );
});

test("spreadCurve: a yield in % and a spread are two figures, never one axis", () => {
  const figures = curves([
    t3e3("NOTE-A", "2031", c("350", "350"), "Senior"),
    t3e3("NOTE-B", "2032", c("6.5%", "6.5"), "Senior"),
  ]);
  expect(
    figures.map((figure) => [figure.key, figure.title, figure.unit, figure.points.length]),
  ).toEqual([
    ["spread-curve", "Spread against maturity", undefined, 1],
    ["spread-curve-percent", "Spread against maturity, %", "%", 1],
  ]);
});

test("spreadCurve: another module's T3E.3 draws nothing; past the marks it is stated", () => {
  const row = t3e3("NOTE-A", "2031", c("350", "350"), "Senior");
  expect(curves([row], "CP-3C")).toEqual([]);
  const cp3d = moduleWith("CP-3D", [register("T3E.3", ISSUER_CURVE, [row])]);
  expect(registerFigures(cp3d).map((figure) => figure.key)).toEqual(["spread-curve"]);
  const many = Array.from({ length: 2001 }, (_, n) => t3e3(`N${n}`, "2031", c("1", "1"), "S"));
  expect(
    spreadCurve(moduleWith("CP-3D", [register("T3E.3", ISSUER_CURVE, many)]))[0],
  ).toMatchObject({
    oversized: true,
    key: "spread-curve",
    summary: expect.stringMatching(/^2001 marks/),
  });
});

// CP-2A's T5.4, as the profile declares it.
const PI_MATRIX = ["Event ID", "Description", "Probability", "Impact", "P/I Classification"];
const t54 = (id: string, probability: string, impact: string, classification = "Watch") =>
  [id, `Event ${id}`, probability, impact, classification].map((cell) => c(cell));
function matrixOf(figure: Figure) {
  if (figure.kind !== "matrix") throw new Error(`A ${figure.kind} figure, not a matrix.`);
  return figure;
}
const matrices = (rows: Served[][], module = "CP-2A") =>
  riskMatrix(moduleWith(module, [register("T5.4", PI_MATRIX, rows)])).map(matrixOf);

test("riskMatrix: an event a row, its labels past their citation markers; High/High counted in the summary", () => {
  const figures = matrices([
    t54("EV-1", "High [C1]", "High", "Critical"),
    t54("EV-2", "Medium", "Low"),
    t54("", " high", "HIGH \\[C2\\]", "Critical"),
    t54("EV-4", "Likely", "High"),
  ]);
  expect(figures.map((figure) => [figure.key, figure.title, figure.unit, figure.table])).toEqual([
    ["risk-matrix", "Probability and impact", "events", "T5.4"],
  ]);
  const [matrix] = figures;
  expect(matrix!.events[0]).toEqual({
    key: "0",
    label: "EV-1",
    description: "Event EV-1",
    probability: "High",
    impact: "High",
    classification: "Critical",
    origin: "model",
  });
  expect(
    matrix!.events.map(({ label, probability, impact }) => [label, probability, impact]),
  ).toEqual([
    ["EV-1", "High", "High"],
    ["EV-2", "Medium", "Low"],
    ["row 3, Event ID not stated", " high", "HIGH"],
    ["EV-4", "Likely", "High"],
  ]);
  expect(matrix!.summary).toBe(
    "High probability and high impact: 2 of 4 events, EV-1, row 3, Event ID not stated.",
  );
  const pressed = { series: "Probability High", category: "Impact High", index: 2 };
  expect(matrix!.sourceOf({ ...pressed, value: "2", origin: "model" })).toBeNull();
});

test("riskMatrix: none High/High is said as none", () => {
  const [matrix] = matrices([t54("EV-1", "Low", "High")]);
  expect(matrix!.summary).toBe("High probability and high impact: 0 of 1 event.");
});

test("riskMatrix: blank ids are told apart by their row; the summary names at most ten", () => {
  const rows = Array.from({ length: 12 }, (_, n) =>
    t54(n < 2 ? "" : `EV-${n + 1}`, "High", "High"),
  );
  const [matrix] = matrices(rows);
  expect(matrix!.events.slice(0, 2).map((event) => event.label)).toEqual([
    "row 1, Event ID not stated",
    "row 2, Event ID not stated",
  ]);
  expect(matrix!.summary).toBe(
    "High probability and high impact: 12 of 12 events, row 1, Event ID not stated, row 2, Event ID not stated, EV-3, EV-4, EV-5, EV-6, EV-7, EV-8, EV-9, EV-10, …and 2 more.",
  );
  expect(matrix!.computed).toBe("a count of the model's rows");
  expect(matrix!.unitOne).toBe("event");
});

test("riskMatrix: another module's T5.4 draws nothing", () => {
  const row = t54("EV-1", "High", "High");
  expect(matrices([row], "CP-2B")).toEqual([]);
  expect(matrices([])).toEqual([]);
  const cp2a = moduleWith("CP-2A", [register("T5.4", PI_MATRIX, [row])]);
  expect(registerFigures(cp2a).map((figure) => figure.key)).toEqual(["risk-matrix"]);
});

// CP-5's T5.9 and CP-L10's topic registers, as the profiles declare them.
const ISSUE_LOG = [
  "Issue ID",
  "Severity",
  "Module",
  "Issue Type",
  "Description",
  "Required Fix",
  "Clearance Impact",
  "Status",
];
const t59 = (id: string, severity: string, module: string) =>
  [id, severity, module, "Citation", "Made up", "Cite it", "None", "Open"].map((cell) => c(cell));
const TOPICS = [
  "topic_id",
  "topic_label",
  "source_owner_modules",
  "materiality",
  "evidence_status",
  "disposition",
  "priority_rank",
  "summary",
  "source_refs",
  "upgrade_module_ids",
];
const tl = (id: string, materiality: string, disposition: string, refs = "") =>
  [id, `Topic ${id}`, "CP-1", materiality, "Supported", disposition, "1", "Made up", refs, ""].map(
    (cell) => c(cell),
  );
const counts = (module: string, registers: Register[]) =>
  auditCounts(moduleWith(module, registers)).map(stack);
const segments = (figure: Figure) =>
  stack(figure).series.map((series) => [series.label, series.data.map((datum) => datum.value)]);

test("auditCounts: CP-5's issue log counted by module and severity, in the reference's order", () => {
  const [figure, ...rest] = counts("CP-5", [
    register("T5.9", ISSUE_LOG, [
      t59("I-1", "Minor", "CP-1"),
      t59("I-2", "CRITICAL", "CP-2"),
      t59("I-3", "Unrated", "CP-1"),
      t59("I-4", " minor [C1]", ""),
      t59("I-5", "", "CP-2"),
      t59("I-6", "MATERIAL", "CP-1"),
      t59("I-7", "Minor", "CP-1"),
    ]),
    // The issue log consolidates T5.2 to T5.8: they are not counted again.
    register("T5.2", ["Severity", "Module"], [[c("CRITICAL"), c("CP-1")]]),
  ]);
  expect(rest).toEqual([]);
  expect([figure!.key, figure!.table, figure!.title, figure!.unit]).toEqual([
    "issue-counts",
    "T5.9",
    "Issues by module and severity, count",
    "issues",
  ]);
  expect(figure!.categoryLabel).toBe("Module");
  expect(figure!.categories).toEqual(["CP-1", "CP-2", "Module not stated"]);
  // CRITICAL, MATERIAL, MINOR first, each keyed by the reference's term
  // whatever its case; the rest as written and as they first appear; every
  // segment an exact integer.
  expect(segments(figure!)).toEqual([
    ["CRITICAL", ["0", "1", "0"]],
    ["MATERIAL", ["1", "0", "0"]],
    ["MINOR", ["2", "0", "1"]],
    ["Unrated", ["1", "0", "0"]],
    ["Severity not stated", ["0", "1", "0"]],
  ]);
  expect(figure!.computed).toBe("a count of the model's rows");
  expect(figure!.summary).toBe(
    "7 issues counted: 1 CRITICAL, 1 MATERIAL, 3 MINOR, 1 Unrated, 1 Severity not stated.",
  );
  // T5.9 declares no source column.
  expect(figure!.sourceOf({ ...pick("MINOR", "CP-1"), value: "2", origin: "model" })).toBeNull();
  expect(figure!.unitOne).toBe("issue");
});

test("auditCounts: each topic register CP-L10 writes counted by materiality and disposition", () => {
  const figures = counts("CP-L10", [
    register("TL30.2", TOPICS, [tl("T-9", "High", "Upgrade")]),
    register("TL10.2", TOPICS, [
      tl("T-1", "High", "Retain", "Doc A p.2"),
      tl("T-2", "Low", "Discard"),
      tl("T-3", "High", "Retain", "Doc B p.4"),
      tl("T-4", "", ""),
    ]),
  ]);
  expect(figures.map((figure) => [figure.key, figure.table, figure.title, figure.unit])).toEqual([
    ["topic-counts-TL10.2", "TL10.2", "Topics by materiality, count (TL10.2)", "topics"],
    ["topic-counts-TL30.2", "TL30.2", "Topics by materiality, count (TL30.2)", "topics"],
  ]);
  const [topics] = figures;
  expect(topics!.categories).toEqual(["High", "Low", "materiality not stated"]);
  expect(segments(topics!)).toEqual([
    ["Retain", ["2", "0", "0"]],
    ["Discard", ["0", "1", "0"]],
    ["disposition not stated", ["0", "0", "1"]],
  ]);
  expect(topics!.summary).toBe("4 topics counted: 2 Retain, 1 Discard, 1 disposition not stated.");
  expect(topics!.computed).toBe("a count of the model's rows");
  expect(topics!.sourceOf({ ...pick("Retain", "High"), value: "2", origin: "model" })).toBe(
    "source_refs: Doc A p.2; source_refs: Doc B p.4",
  );
  expect(figures[1]!.summary).toBe("1 topic counted: 1 Upgrade.");
  expect(figures[1]!.unitOne).toBe("topic");
});

test("auditCounts: another module's registers count nothing, and no count is a Figure", () => {
  const log = register("T5.9", ISSUE_LOG, [t59("I-1", "MINOR", "CP-1")]);
  const topics = register("TL10.2", TOPICS, [tl("T-1", "High", "Retain")]);
  expect(counts("CP-4", [log, topics])).toEqual([]);
  expect(counts("CP-5", [register("T5.9", ISSUE_LOG, [])])).toEqual([]);
  expect(registerFigures(moduleWith("CP-5", [log]))).toEqual([]);
  expect(registerFigures(moduleWith("CP-L10", [topics]))).toEqual([]);
});

test("auditCounts: past the marks a count is stated, not drawn", () => {
  const many = Array.from({ length: 2001 }, (_, n) => t59(`I-${n}`, "MINOR", `CP-${n}`));
  expect(auditCounts(moduleWith("CP-5", [register("T5.9", ISSUE_LOG, many)]))[0]).toMatchObject({
    oversized: true,
    key: "issue-counts",
    summary: expect.stringMatching(/^2001 marks/),
  });
});

// The series tidy: currencies apart, blanks by row, restatements named,
// summaries capped, counts of one singular.

test("a written currency sign splits figures as a unit does: $12 and €8 never share an axis", () => {
  const rows = [
    t2f5("A", c("$12", "12")),
    t2f5("B", c("(8 €) [C1]", "-8")),
    t2f5("C", c("€1x", "1")),
  ];
  const handoff = moduleWith("CP-2E", [register("T2F.5", RATE_SENSITIVITY, rows)]);
  expect(rateSensitivities(handoff).map((figure) => `${figure.key}: ${figure.title}`)).toEqual([
    "rate-sensitivities-dollar: Rate and FX sensitivities, $",
    "rate-sensitivities-euro: Rate and FX sensitivities, €",
    "rate-sensitivities-euro-x: Rate and FX sensitivities, € x",
  ]);
});

test("blank categories are named by their row and never merge: a bar figure and a line figure", () => {
  const rows = [t33("Scale", c("1", "1")), t33(" ", c("2", "2")), t33("", c("3", "3"))];
  const [figure] = scores("CP-3", [register("T3.3", FACTORS, rows)]);
  const blank = (n: number, column: string) => `row ${n}, ${column} not stated`;
  expect(figure!.categories).toEqual(["Scale", blank(2, "Factor"), blank(3, "Factor")]);
  expect(said(figure!)).toEqual([[{ value: "1" }, { value: "2" }, { value: "3" }]]);
  const lines = [
    ["FY26", "Base"],
    ["", "Base"],
    [" ", "Base"],
    ["FY26", ""],
    ["FY26", " "],
  ];
  const forecast = lines.map(([period, kase], n) =>
    t2h4(period!, kase!, c(`${n}`, `${n}`), c(""), c("")),
  );
  const [revenue] = forecastCases(cp2gWith([register("T2H.4", FORECAST, forecast)])).map(line);
  expect(revenue!.categories).toEqual(["FY26", blank(2, "period"), blank(3, "period")]);
  expect(revenue!.series.map((series) => [series.label, series.data])).toEqual([
    ["Base", [{ value: "0" }, { value: "1" }, { value: "2" }]],
    [blank(4, "case"), [{ value: "3" }, gap, gap]],
    [blank(5, "case"), [{ value: "4" }, gap, gap]],
  ]);
});

test("an available value, a fulcrum or a liquidity total stated twice is named, never the first taken", () => {
  const [allocation] = allocations(
    [
      t4e5("Base", "HoldCo", c("90", "90"), "Senior", c("60", "60"), c("30", "30")),
      t4e5("Base", "HoldCo", c("95", "95"), "Junior", c("30", "30"), c("0", "0")),
    ],
    [t4e6("Base", "Senior"), t4e6("Base case", "Junior")],
  );
  expect(allocation!.summary).toBe(
    "Available value n/a (stated twice: 90, 95) to Residual 0, as served; fulcrum stated twice: Senior, Junior.",
  );
  const begin = "Beginning accessible liquidity";
  const [bridge] = liquidity([t2e5(begin, c("100", "100")), t2e5(begin, c("110", "110"))]);
  expect(bridge!.summary).toMatch(/^Beginning accessible liquidity stated twice: 100, 110 to no/);
});

test("a summary listing every row names at most ten, the rest counted", () => {
  const twelve = Array.from({ length: 12 }, (_, n) => t74(`M${n}`, c("4", "4"), c("5", "5"), "Up"));
  expect(outcomes(twelve)[0]!.summary).toMatch(/: M0 Up; M1 Up; .*; M9 Up; …and 2 more\.$/);
  const points = Array.from({ length: 11 }, (_, n) => t3e3(`N${n}`, "2031", c("1", "1"), "S"));
  expect(curves(points)[0]!.summary).toMatch(/; N9 2031 1; …and 1 more\.$/);
});

test("scores: all equal or one bar is said so; a stated-twice score is named; a unit splits", () => {
  const figures = (rows: Served[][]) => scores("CP-3", [register("T3.3", FACTORS, rows)]);
  const summary = (...rows: Served[][]) => figures(rows)[0]!.summary.slice(26);
  const [one, two, four] = [c("1", "1"), c("2", "2"), c("4", "4")];
  expect(summary(t33("A", c("4.0", "4.0")), t33("B", four), t33("C", four))).toBe(
    "All 3 factors score 4.0.",
  );
  expect(summary(t33("A", four), t33("B", c("TBD")))).toBe("One factor scores: A 4; 1 is n/a.");
  expect(summary(t33("A", one), t33("B", four), t33("C", one), t33("C", two))).toBe(
    "Highest: B 4. Lowest: A 1. C stated twice.",
  );
  const split = figures([t33("A", four), t33("B", c("4%", "4"))]);
  expect(split.map((figure) => `${figure.key}: ${figure.categories}`)).toEqual([
    "weighted-factor-scores: A",
    "weighted-factor-scores-percent: B",
  ]);
});

test("triggers read their threshold and value by unit and name a restatement; labels leave markers", () => {
  const value = c("4.0x", "4.0");
  const [plain, multiple] = triggers([
    t2r4("A", "Issuer [C1]", "Ceiling", "Leverage [C2]", c("5", "5"), value, c("1", "1")),
    t2r4("A", "Issuer", "Ceiling", "Leverage", c("6", "6"), value, c("1", "1")),
  ]);
  expect([plain!.key, multiple!.key]).toEqual(["rating-triggers-0", "rating-triggers-0-x"]);
  expect(plain!.bullets[0]).toMatchObject({
    label: "Leverage (Issuer, ceiling)",
    threshold: { value: null, reason: "stated twice: 5, 6" },
    current: { value: null, reason: "4.0x, drawn in its unit's figure" },
  });
  expect(plain!.summary).toMatch(/1\. Leverage \(Issuer, ceiling\) stated twice\.$/);
  expect(multiple!.bullets[0]!.current).toEqual({ value: "4.0" });
  const fx = moduleWith("CP-2E", [register("T2F.5", RATE_SENSITIVITY, [t2f5("FX [C3]", value)])]);
  expect(diverging(rateSensitivities(fx)[0]!).categories).toEqual(["FX"]);
});

test("a security's restated date is its reason for not being placed; markers alone never restate", () => {
  const [curve] = curves([
    t3e3("NOTE-A", "2031-06 [C1]", c("4", "4"), "Senior"),
    t3e3("NOTE-A", "2031-06 [C2]", c("4", "4"), "Senior"),
    t3e3("NOTE-B", "2031", c("5", "5"), "Senior"),
    t3e3("NOTE-B", "2032", c("5", "5"), "Senior"),
  ]);
  expect(curve!.points.map(({ at, unread }) => [at, unread])).toEqual([
    ["2031-06", undefined],
    ["", "stated twice: 2031, 2032"],
  ]);
  expect(curve!.summary).toMatch(/: NOTE-A 2031-06 4; NOTE-B stated twice: 2031, 2032 5\.$/);
});

test("counts of one are singular: one row of two stating an amount", () => {
  const rows = [t2e2("Cash", c("5", "5"), "Open", "T-1"), t2e2("RCF", c("TBD"), "Open", "T-2")];
  expect(liquiditySources(cp2dWith([register("T2E.2", SOURCES, rows)]))[0]!.summary).toBe(
    "Source-Supported Amount, summed over the 1 of 2 rows that states one: 5.",
  );
});
