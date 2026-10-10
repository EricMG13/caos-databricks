// The figures drawn from a module's declared registers (N94): read only for
// the module that owns the register id, keyed by the profile's column, every
// value as served, rows of one unit on one axis. Every value here is made up
// (N191): no real issuer's figure stands in a test.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  covenantHeadroom,
  peerRanges,
  registerFigures,
  registerRows,
} from "@/sections/analysis/register-figures";
import type { Figure } from "@/sections/analysis/figure-core";
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
