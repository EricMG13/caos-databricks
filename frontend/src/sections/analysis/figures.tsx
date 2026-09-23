// A module's figures, drawn from the tagged tables the server read with the
// bundle's own reader (D32). The tables are the model's, like its prose, so
// every mark is model-authored: outlined and hatched, printed exactly as
// served. Sums are exact (BigInt); a float only places a mark.
import { useState } from "react";
import {
  DivergingBarChart,
  LineChart,
  StackedBarChart,
  formatDecimal,
  type ChartColor,
  type ChartSelection,
  type ChartSeries,
  type Datum,
} from "@/charts";
import { fromScaled, placesOf, toScaled } from "@/charts/decimal";
import type { HandoffView } from "@/wire/v1";

type Table = HandoffView["tables"][number];
type Cell = Table["rows"][number][number];
type Row = Record<string, Cell | undefined>;

/** A table's rows keyed by column name. */
export function recordsOf(table: Table): Row[] {
  return table.rows.map((row) =>
    Object.fromEntries(table.columns.map((column, index) => [column, row[index]])),
  );
}

const text = (row: Row, column: string) => row[column]?.text ?? "";
const datum = (cell: Cell | undefined): Datum =>
  cell?.value != null
    ? { value: cell.value }
    : { value: null, reason: cell?.text ? cell.text : "not stated" };

/** The exact sum of decimal strings; null when there is none to add. */
export function sumOf(values: readonly (string | null | undefined)[]): string | null {
  const known = values.filter((value): value is string => typeof value === "string");
  if (known.length === 0) return null;
  const places = Math.max(...known.map(placesOf));
  return fromScaled(
    known.reduce((sum, value) => sum + toScaled(value, places), 0n),
    places,
  );
}

const SCALE: Record<string, string> = {
  UNITS: "",
  THOUSANDS: " k",
  MILLIONS: " m",
  BILLIONS: " bn",
};

/** "USD" and "MILLIONS" read "USD m"; anything else reads as served. */
export function unitOf(currency: string, scale: string): string | undefined {
  if (!currency) return undefined;
  return `${currency}${SCALE[scale.toUpperCase()] ?? (scale ? ` ${scale.toLowerCase()}` : "")}`;
}

/** One figure: what it shows, drawn by which chart, from which table. */
export interface Figure {
  key: string;
  table: string;
  kind: "stack" | "line" | "diverging";
  title: string;
  summary: string;
  unit?: string;
  categories: string[];
  series: ChartSeries[];
  /** Where the model says a mark's figure came from: its source locator. */
  sourceOf: (selection: ChartSelection) => string | null;
}

function tableOf(tables: readonly Table[], id: string): Row[] | null {
  const table = tables.find((entry) => entry.table_id === id);
  return table ? recordsOf(table) : null;
}

/** Periods in the register's order, else in the order they first appear. */
function periodsOf(tables: readonly Table[], present: readonly string[]): string[] {
  const register = (tableOf(tables, "cp1.model_period_register") ?? []).map((row) =>
    text(row, "period_id"),
  );
  const wanted = new Set(present);
  const ordered = register.filter((period) => wanted.has(period));
  return [...ordered, ...present.filter((period) => !ordered.includes(period))];
}

/** The register's currency and scale for a period. */
function periodUnit(tables: readonly Table[], period: string | undefined): string | undefined {
  const row = (tableOf(tables, "cp1.model_period_register") ?? []).find(
    (entry) => text(entry, "period_id") === period,
  );
  return row ? unitOf(text(row, "currency"), text(row, "unit")) : undefined;
}

const unique = (values: readonly string[]) => [...new Set(values)];
// A priority the model did not state sorts last, never as NaN.
const priority = (row: Row) => Number(text(row, "display_priority")) || Number.MAX_SAFE_INTEGER;
const byPriority = (rows: readonly Row[], key: string) =>
  unique([...rows].sort((a, b) => priority(a) - priority(b)).map((row) => text(row, key)));
const locate = (row: Row | undefined) =>
  row ? [text(row, "source_id"), text(row, "source_locator")].filter(Boolean).join(", ") : null;

/** Revenue by segment, stacked by period. */
export function segmentMix(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1.segment_revenue_schedule");
  if (!rows?.length) return null;
  const periods = periodsOf(tables, unique(rows.map((row) => text(row, "period_id"))));
  const at = (segment: string, period: string) =>
    rows.find((row) => text(row, "segment_id") === segment && text(row, "period_id") === period);
  const segments = byPriority(rows, "segment_id");
  const series = segments.map((segment) => ({
    key: segment,
    label: text(
      rows.find((row) => text(row, "segment_id") === segment)!,
      "segment_name",
    ),
    origin: "model" as const,
    data: periods.map((period) => datum(at(segment, period)?.revenue)),
  }));
  const latest = periods.at(-1)!;
  const unit = periodUnit(tables, latest);
  const total = sumOf(segments.map((segment) => at(segment, latest)?.revenue?.value));
  return {
    key: "segment-mix",
    table: "cp1.segment_revenue_schedule",
    kind: "stack",
    title: "Revenue by segment",
    summary: total
      ? `${latest}: ${formatDecimal(total)}${unit ? ` ${unit}` : ""} across ${segments.length} segments.`
      : `${segments.length} segments over ${periods.length} periods.`,
    unit,
    categories: periods,
    series,
    sourceOf: (selection) => locate(at(selection.series, selection.category)),
  };
}

const KPI_UNIT: Record<string, string> = { UNITS: "units", PERCENT: "%", RATIO: "x" };

/** One line per operating KPI, each on its own axis: their units differ. */
export function kpiLines(tables: readonly Table[]): Figure[] {
  const rows = tableOf(tables, "cp1.operating_kpi_schedule");
  if (!rows?.length) return [];
  return byPriority(rows, "kpi_id").map((kpi) => {
    const own = rows.filter((row) => text(row, "kpi_id") === kpi);
    const periods = periodsOf(tables, unique(own.map((row) => text(row, "period_id"))));
    const at = (period: string) => own.find((row) => text(row, "period_id") === period);
    const label = text(own[0]!, "kpi_label");
    const unit = KPI_UNIT[text(own[0]!, "unit").toUpperCase()] ?? text(own[0]!, "unit");
    const first = at(periods[0]!);
    const last = at(periods.at(-1)!);
    return {
      key: `kpi-${kpi}`,
      table: "cp1.operating_kpi_schedule",
      kind: "line" as const,
      title: label,
      summary: `${periods[0]}: ${text(first!, "value")}; ${periods.at(-1)}: ${text(last!, "value")}.`,
      unit: unit || undefined,
      categories: periods,
      series: [
        {
          key: kpi,
          label,
          origin: "model" as const,
          data: periods.map((period) => datum(at(period)?.value)),
        },
      ],
      sourceOf: (selection: ChartSelection) => locate(at(selection.category)),
    };
  });
}

/** The latest period's add-backs, each above or below zero. */
export function addbacks(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1.adjusted_ebitda_bridge");
  if (!rows?.length) return null;
  const periods = periodsOf(tables, unique(rows.map((row) => text(row, "period_id"))));
  const latest = periods.at(-1)!;
  const own = rows.filter((row) => text(row, "period_id") === latest);
  const items = byPriority(own, "addback_id");
  const at = (item: string) => own.find((row) => text(row, "addback_id") === item);
  const unit = periodUnit(tables, latest);
  const net = sumOf(items.map((item) => at(item)?.value?.value));
  return {
    key: "addbacks",
    table: "cp1.adjusted_ebitda_bridge",
    kind: "diverging",
    title: `Add-backs to EBITDA, ${latest}`,
    summary: net
      ? `Net ${formatDecimal(net, true)}${unit ? ` ${unit}` : ""} across ${items.length} add-backs.`
      : `${items.length} add-backs.`,
    unit,
    // A band scale drops a repeated category, so two add-backs the model
    // labelled alike keep their ids beside the label.
    categories: items.map((item, index) => {
      const label = text(at(item)!, "addback_label");
      const twin = items.some(
        (other, at2) => at2 !== index && text(at(other)!, "addback_label") === label,
      );
      return twin ? `${label} (${item})` : label;
    }),
    series: [
      {
        key: "addbacks",
        label: "Add-back",
        origin: "model",
        data: items.map((item) => datum(at(item)?.value)),
      },
    ],
    sourceOf: (selection) => locate(at(items[selection.index] ?? "")),
  };
}

const TRANCHE: Record<string, ChartColor> = {
  "SECURED SENIOR": "tranche-1l",
  "SECURED SECOND_LIEN": "tranche-2l",
  "SECURED JUNIOR": "tranche-2l",
  "UNSECURED SENIOR": "tranche-unsec",
  "UNSECURED SUBORDINATED": "tranche-sub",
};
const sentence = (words: string) => words.charAt(0) + words.slice(1).toLowerCase();

/** Principal falling due each year, stacked by seniority: the maturity wall. */
export function maturityLadder(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1.debt_facility_register");
  if (!rows?.length) return null;
  const periods = periodsOf(tables, unique(rows.map((row) => text(row, "period_id"))));
  const latest = periods.at(-1)!;
  const own = rows.filter((row) => text(row, "period_id") === latest && row.principal?.value);
  if (own.length === 0) return null;
  const yearOf = (row: Row) => /^\d{4}/.exec(text(row, "maturity_date"))?.[0] ?? "Undated";
  const classOf = (row: Row) => `${text(row, "secured_status")} ${text(row, "seniority")}`;
  const years = unique(own.map(yearOf)).sort();
  const classes = unique(own.map(classOf));
  const cell = (klass: string, year: string) =>
    sumOf(
      own
        .filter((row) => classOf(row) === klass && yearOf(row) === year)
        .map((row) => row.principal?.value),
    ) ?? "0";
  const dated = own.filter((row) => yearOf(row) !== "Undated");
  const nearest = [...(dated.length ? dated : own)].sort((a, b) =>
    text(a, "maturity_date").localeCompare(text(b, "maturity_date")),
  )[0]!;
  const unit = periodUnit(tables, latest) ?? unitOf(text(nearest, "currency"), "");
  const total = sumOf(own.map((row) => row.principal?.value));
  return {
    key: "maturities",
    table: "cp1.debt_facility_register",
    kind: "stack",
    title: `Debt maturities by seniority, ${latest}`,
    summary: `${formatDecimal(total ?? "0")}${unit ? ` ${unit}` : ""} principal in ${own.length} facilities${
      dated.length
        ? `; the nearest, ${text(nearest, "facility_name")}, falls due ${text(nearest, "maturity_date")}`
        : ""
    }.`,
    unit,
    categories: years,
    series: classes.map((klass) => ({
      key: klass,
      label: sentence(klass.replace("_", " ")),
      origin: "model" as const,
      color: TRANCHE[klass] ?? "neutral",
      data: years.map((year) => ({ value: cell(klass, year) })),
    })),
    // A segment sums every facility of its class falling due that year, so it
    // names each one's stated source, not the first's (rewrite tournament).
    sourceOf: (selection) => {
      const summed = own.filter(
        (row) => classOf(row) === selection.series && yearOf(row) === selection.category,
      );
      return summed.length
        ? summed.map((row) => `${text(row, "facility_name")}: ${locate(row)}`).join("; ")
        : null;
    },
  };
}

/** Every figure a handoff's tables support, in reading order. */
export function figuresOf(handoff: HandoffView): Figure[] {
  const tables = handoff.tables;
  return [segmentMix(tables), ...kpiLines(tables), addbacks(tables), maturityLadder(tables)].filter(
    (figure): figure is Figure => figure !== null,
  );
}

/** What the right column shows for a pressed mark. */
export interface FigurePick {
  figure: string;
  table: string;
  label: string;
  value: string | null;
  unit?: string;
  source: string | null;
}

function Chart({
  figure,
  onPick,
}: {
  figure: Figure;
  onPick: (pick: FigurePick, opener: HTMLElement) => void;
}) {
  const onSelect = (selection: ChartSelection, opener: HTMLElement) => {
    const series = figure.series.find((entry) => entry.key === selection.series);
    onPick(
      {
        figure: figure.title,
        table: figure.table,
        label: [series?.label, selection.category].filter(Boolean).join(" · "),
        value: selection.value,
        unit: figure.unit,
        source: figure.sourceOf(selection),
      },
      opener,
    );
  };
  const common = { title: figure.title, summary: figure.summary, unit: figure.unit, onSelect };
  if (figure.kind === "line") {
    return <LineChart {...common} categories={figure.categories} series={figure.series} />;
  }
  if (figure.kind === "diverging") {
    return (
      <DivergingBarChart {...common} categories={figure.categories} series={figure.series[0]!} />
    );
  }
  return <StackedBarChart {...common} categories={figure.categories} series={figure.series} />;
}

/** The module's own tables, as served, for whoever needs every cell. */
function RawTables({ tables }: { tables: HandoffView["tables"] }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="help tables" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>The module&apos;s tables ({tables.length})</summary>
      {open
        ? tables.map((table) => (
            <div
              key={table.table_id}
              className="tscroll"
              tabIndex={0}
              role="region"
              aria-label={table.table_id}
            >
              <table className="tbl raw" data-raw-table={table.table_id}>
                <caption>{table.table_id}</caption>
                <thead>
                  <tr>
                    {table.columns.map((column) => (
                      <th key={column} scope="col" className="l">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, index) => (
                    <tr key={index}>
                      {row.map((cell, column) => (
                        <td key={column} className={cell.value === null ? "l" : undefined}>
                          {cell.text}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))
        : null}
    </details>
  );
}

export function Figures({
  handoff,
  onPick,
}: {
  handoff: HandoffView;
  onPick: (pick: FigurePick, opener: HTMLElement) => void;
}) {
  if (handoff.tables_unavailable_reason) {
    return (
      <p className="note" data-tables-unavailable={handoff.tables_unavailable_reason}>
        This module&apos;s tables could not be read ({handoff.tables_unavailable_reason}), so it
        shows no figures. Its prose below is unaffected.
      </p>
    );
  }
  const figures = figuresOf(handoff);
  if (figures.length === 0 && handoff.tables.length === 0) return null;
  return (
    <section className="figures" aria-labelledby="figures-heading" data-figures>
      <h3 id="figures-heading" className="grouphead">
        Figures <span className="cp">model-authored, drawn outlined</span>
      </h3>
      <div className="figgrid">
        {figures.map((figure) => (
          <div key={figure.key} className={`fig ${figure.kind}`} data-figure={figure.key}>
            <Chart figure={figure} onPick={onPick} />
          </div>
        ))}
      </div>
      {handoff.tables.length ? <RawTables tables={handoff.tables} /> : null}
    </section>
  );
}
