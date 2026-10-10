// The figures drawn from a module's declared registers (N94): read only for
// the module that owns the register id, keyed by the profile's column, every
// value as served, rows of one unit on one axis. Every value here is made up
// (N191): no real issuer's figure stands in a test.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  adjustedDebtBridge,
  covenantHeadroom,
  ebitdaQuality,
  impliedEv,
  liquidityBridge,
  peerRanges,
  registerFigures,
  registerRows,
  valueAllocation,
} from "@/sections/analysis/register-figures";
import { negatedMagnitude, type Figure } from "@/sections/analysis/figure-core";
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
  // The opening total's Supported is said, not coloured: no legend entry.
  expect(figure!.statuses).toEqual([
    { color: "series-3", label: "Challenged" },
    { color: "negative", label: "Rejected" },
    { color: "series-4", label: "Insufficient Information" },
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
    "Reported EBITDA 100.0; the last change, FX, states no cumulative EBITDA.",
  );
  const [gap] = quality([
    t1d4("Reported EBITDA", c("100.0", "100.0"), "Supported", c("100.0", "100.0")),
    t1d4("Run-rate savings", c("Not quantified"), "Insufficient Information", c("—")),
  ]);
  expect(gap!.summary).toBe(
    "Reported EBITDA 100.0; the last change, Run-rate savings, states no cumulative EBITDA.",
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
    "Reported debt 400; the last change, Leases, states no cumulative Adjusted Debt.",
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
