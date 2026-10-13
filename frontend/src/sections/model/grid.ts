// The credit workbook's pure helpers: which lines the grid shows, how a cell
// reads, which columns a group holds, what a cell's passport says and what the
// three charts draw. The server's figures arrive as exact decimal strings and
// are only re-spelled here (digit moves and rounding on the digits), never
// computed on.
import type { ChartSeries, Datum } from "@/charts";
import { displayDecimal, hundredfold } from "@/ds/format";
import type { Citation, Passport } from "@/wire";
import type { ModelDocument } from "@/wire/v1";
import { citationOf } from "@/sections/book/passport";

type Body = ModelDocument["body"];
export type ModelLine = Body["lines"][number];
export type ModelCell = ModelLine["cells"][number];
export type ModelColumn = Body["columns"][number];

const ZERO = /^-?0+(?:\.0+)?$/;

/** A line whose every cell is null or zero adds a row of nothing, so it is
    left out (spec, row economy). A facility is always shown: that it carries
    nothing is itself the fact. */
export function hiddenLine(line: ModelLine): boolean {
  return (
    line.terms === null && line.cells.every((cell) => cell.value === null || ZERO.test(cell.value))
  );
}

/** A cell's marker for a figure it does not have, and the reason in words. */
const MARKERS: Record<NonNullable<ModelCell["reason"]>, { mark: string; why: string }> = {
  NOT_PROJECTED: { mark: "n.p.", why: "Not projected" },
  NOT_APPLICABLE: { mark: "n.a.", why: "Not applicable" },
  NOT_SOURCED: { mark: "n.s.", why: "Not sourced" },
  COMPONENT_MISSING: { mark: "n.s.", why: "A component is not sourced" },
  ZERO_OR_NEGATIVE_DENOMINATOR: { mark: "n.a.", why: "The denominator is zero or negative" },
  NOT_STATED: { mark: "n.s.", why: "Not stated in the sources" },
};

export interface ShownCell {
  text: string;
  /** The exact figure, or the reason there is none. */
  title: string;
  /** False for an `n.p.`, `n.a.` or `n.s.` marker. */
  figure: boolean;
}

/** Money in brackets when negative, no sign anywhere else it would be read
    twice: PERCENT and RATE are fractions the host wrote (0.2034 reads 20.3%),
    a MULTIPLE is read with an `x`. */
export function spelled(line: Pick<ModelLine, "unit" | "unit_label">, value: string): string {
  switch (line.unit) {
    case "MONEY": {
      const text = displayDecimal(value, 0);
      return text.startsWith("-") ? `(${text.slice(1)})` : text;
    }
    case "PERCENT":
      return `${displayDecimal(hundredfold(value), 1)}%`;
    case "RATE":
      return `${displayDecimal(hundredfold(value), 2)}%`;
    case "MULTIPLE":
      return `${displayDecimal(value, 1)}x`;
    case "KPI":
      // A KPI states its own unit; a percentage KPI is already in points.
      return line.unit_label === "PERCENT"
        ? `${displayDecimal(value, 1)}%`
        : displayDecimal(value, 0);
    case "DAYS":
    case "COUNT":
      return displayDecimal(value, 0);
  }
}

export function shownCell(line: ModelLine, cell: ModelCell): ShownCell {
  if (cell.value === null) {
    const marker = cell.reason ? MARKERS[cell.reason] : { mark: "n.a.", why: "No figure served" };
    return { text: marker.mark, title: marker.why, figure: false };
  }
  return { text: spelled(line, cell.value), title: cell.value, figure: true };
}

/** One fact per cell: a facility's cell the host marks as assumed refinanced
    wears the refinanced tint. */
export function refinanced(line: ModelLine, cell: ModelCell): boolean {
  return line.terms !== null && cell.note === "assumed refinanced";
}

// ---- column groups ----

export const GROUP_IDS = ["quarters", "ytd", "fy", "ltm", "pf", "base", "downside"] as const;
export type GroupId = (typeof GROUP_IDS)[number];

const GROUP_LABELS: Record<GroupId, string> = {
  quarters: "Quarters",
  ytd: "YTD",
  fy: "FY",
  ltm: "LTM",
  pf: "PF-LTM",
  base: "Base case",
  downside: "Downside case",
};

/** The most history a group shows until the reader asks for all of it. */
const RECENT: Partial<Record<GroupId, number>> = { quarters: 4, fy: 3 };

export function groupOf(column: ModelColumn): GroupId {
  switch (column.kind) {
    case "QUARTER":
      return "quarters";
    case "PYTD":
    case "YTD":
      return "ytd";
    case "FY":
      return "fy";
    case "LTM":
      return "ltm";
    case "PF_LTM":
      return "pf";
    case "PROJECTED":
      return column.case === "DOWNSIDE" ? "downside" : "base";
  }
}

/** The tint a column wears, by its kind. */
export function tintOf(column: ModelColumn): "pf" | "base" | "down" | null {
  if (column.kind === "PF_LTM") return "pf";
  if (column.kind !== "PROJECTED") return null;
  return column.case === "DOWNSIDE" ? "down" : "base";
}

export interface GridColumn {
  column: ModelColumn;
  /** Its position in every line's `cells`. */
  index: number;
}

export interface ColumnGroup {
  id: GroupId;
  label: string;
  /** The columns drawn; none while the group is collapsed. */
  columns: GridColumn[];
  /** How many the group holds, drawn or not. */
  total: number;
  collapsed: boolean;
  /** True while older columns of the group are left out. */
  trimmed: boolean;
  /** How many recent columns the group shows by default; null for all. */
  recent: number | null;
}

/** The URL's comma-separated list of group ids; anything else is dropped. */
export function groupList(text: string | null): Set<GroupId> {
  const wanted = new Set((text ?? "").split(","));
  return new Set(GROUP_IDS.filter((id) => wanted.has(id)));
}

export function columnGroups(
  columns: readonly ModelColumn[],
  collapsed: ReadonlySet<GroupId>,
  full: ReadonlySet<GroupId>,
): ColumnGroup[] {
  return GROUP_IDS.flatMap((id) => {
    const held = columns
      .map((column, index) => ({ column, index }))
      .filter((entry) => groupOf(entry.column) === id);
    if (held.length === 0) return [];
    const limit = RECENT[id];
    const trimmed = limit !== undefined && !full.has(id) && held.length > limit;
    const shown = trimmed ? held.slice(-limit) : held;
    return [
      {
        id,
        label: GROUP_LABELS[id],
        columns: collapsed.has(id) ? [] : shown,
        total: held.length,
        collapsed: collapsed.has(id),
        trimmed,
        recent: limit ?? null,
      },
    ];
  });
}

/** A group id in or out of the URL's list, in the order the groups are drawn. */
export function toggled(list: ReadonlySet<GroupId>, id: GroupId): string {
  const next = new Set(list);
  if (!next.delete(id)) next.add(id);
  return GROUP_IDS.filter((entry) => next.has(entry)).join(",");
}

// ---- the passport ----

export interface PassportInput {
  body: Body;
  line: ModelLine;
  column: ModelColumn;
  cell: ModelCell;
  /** The line's column position, for the rate it was priced at. */
  index: number;
  observedAt: string;
}

/** What opens when a cell is pressed: its value and the basis it stands on,
    the figure the sources state where that is not the one served, the note,
    and the sources (a citation opens the evidence). A projected interest
    figure also names the weighted-average rate and the deck it came from. */
export function passportOfCell(input: PassportInput): Passport {
  const { body, line, column, cell, index } = input;
  const shown = shownCell(line, cell);
  const derivation: string[] = [];
  if (cell.stated !== null) derivation.push(`Stated in the sources: ${cell.stated}`);
  if (cell.note !== null) derivation.push(cell.note);
  if (line.line_id === "cash_interest" && column.kind === "PROJECTED") {
    const rate = body.lines.find((entry) => entry.line_id === "wa_rate")?.cells[index];
    if (rate?.value) {
      derivation.push(
        `Weighted-average rate ${displayDecimal(hundredfold(rate.value), 2)}%, ${
          body.rate_deck ? `rate deck as of ${body.rate_deck.as_of}` : "no rate deck"
        }`,
      );
    }
  }
  const located = cell.sources;
  if (located.length) {
    derivation.push(
      `Sources: ${located.map((source) => `${source.source_id} ${source.source_locator}`).join("; ")}`,
    );
  }
  const citations: Citation[] = cell.sources.flatMap((source) =>
    source.citation ? [citationOf(source.citation, input.observedAt)] : [],
  );
  return {
    label: `${line.label} · ${column.label}`,
    value: shown.text,
    unit:
      line.unit === "MONEY" && body.currency ? `${body.currency} ${body.unit ?? ""}`.trim() : null,
    definition: cell.reason
      ? shown.title
      : `${line.kind.toLowerCase()} · exact value ${shown.title}`,
    period: column.end_date ?? column.label,
    scenario: column.case ?? "Actual",
    reporting_period: column.fiscal_year,
    computed_at: input.observedAt,
    snapshot: body.displayed_run_id ?? "",
    method: cell.basis ?? "Not computed",
    derivation: derivation.length ? derivation.join(". ") : "Read from the credit model",
    citations,
    supporting_research: [],
    driver: null,
    deviation: null,
  };
}

// ---- the chart strip ----

export interface StripChart {
  key: string;
  title: string;
  unit: string;
  categories: string[];
  series: ChartSeries[];
}

const STRIP: { lineId: string; title: string; multiple: boolean }[] = [
  { lineId: "metric:net_leverage_adjusted", title: "Adjusted net leverage", multiple: true },
  {
    lineId: "metric:interest_coverage_adjusted",
    title: "Adjusted interest coverage",
    multiple: true,
  },
  { lineId: "liquidity", title: "Liquidity", multiple: false },
];

/** Adjusted net leverage, adjusted interest coverage and liquidity: the
    history is the FY and LTM columns, and Base and Downside are two projected
    series over the projected years. A cell with no figure is a gap with its
    reason, never zero. */
export function stripCharts(body: Body): StripChart[] {
  const history = body.columns
    .map((column, index) => ({ column, index }))
    .filter((entry) => entry.column.kind === "FY" || entry.column.kind === "LTM");
  const years = [
    ...new Set(
      body.columns.filter((column) => column.kind === "PROJECTED").map((column) => column.label),
    ),
  ];
  const categories = [...history.map((entry) => entry.column.label), ...years];
  return STRIP.flatMap((spec) => {
    const line = body.lines.find((entry) => entry.line_id === spec.lineId);
    if (!line) return [];
    const datum = (cell: ModelCell | undefined): Datum =>
      cell && cell.value !== null
        ? { value: cell.value }
        : { value: null, reason: cell?.reason ?? "not served" };
    const projected = (name: "BASE" | "DOWNSIDE"): Datum[] =>
      years.map((label) => {
        const index = body.columns.findIndex(
          (column) => column.kind === "PROJECTED" && column.case === name && column.label === label,
        );
        return datum(index === -1 ? undefined : line.cells[index]);
      });
    const gaps = (count: number): Datum[] =>
      Array.from({ length: count }, () => ({ value: null, reason: "not projected" }));
    const series: ChartSeries[] = [
      {
        key: `${spec.lineId}:actual`,
        label: "Actual",
        origin: "host" as const,
        data: [...history.map((entry) => datum(line.cells[entry.index])), ...gaps(years.length)],
      },
      ...(["BASE", "DOWNSIDE"] as const).map((name) => ({
        key: `${spec.lineId}:${name}`,
        label: name === "BASE" ? "Base case" : "Downside case",
        origin: "host" as const,
        data: [...gaps(history.length), ...projected(name)],
      })),
    ].filter((entry) => entry.data.some((point) => point.value !== null));
    if (series.length === 0 || categories.length < 2) return [];
    return [
      {
        key: spec.lineId,
        title: spec.title,
        unit: spec.multiple ? "multiple" : `${body.currency ?? ""} ${body.unit ?? ""}`.trim(),
        categories,
        series,
      },
    ];
  });
}
