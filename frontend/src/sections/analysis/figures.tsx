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
import { hundredfold } from "@/ds/format";
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

/** The exact sum of a set of values that may include unknown members
    (R24-13): `value` sums only the known ones (null when none are known),
    and `complete` says whether every member was known -- a caller states
    this partial-sum distinction rather than let an aggregate stand in
    silently for a total that may be missing components. */
export interface PartialSum {
  value: string | null;
  complete: boolean;
}

/** The exact sum of decimal strings, and whether every input was known. */
export function sumOf(values: readonly (string | null | undefined)[]): PartialSum {
  const known = values.filter((value): value is string => typeof value === "string");
  const complete = known.length === values.length;
  if (known.length === 0) return { value: null, complete };
  const places = Math.max(...known.map(placesOf));
  return {
    value: fromScaled(
      known.reduce((sum, value) => sum + toScaled(value, places), 0n),
      places,
    ),
    complete,
  };
}

/** How many of `values` are unknown (null or undefined). */
function unknownCount(values: readonly (string | null | undefined)[]): number {
  return values.filter((value) => value == null).length;
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
  const values = segments.map((segment) => at(segment, latest)?.revenue?.value);
  const total = sumOf(values);
  const amount =
    total.value === null ? null : `${formatDecimal(total.value)}${unit ? ` ${unit}` : ""}`;
  return {
    key: "segment-mix",
    table: "cp1.segment_revenue_schedule",
    kind: "stack",
    title: "Revenue by segment",
    summary:
      amount === null
        ? `${segments.length} segments over ${periods.length} periods.`
        : total.complete
          ? `${latest}: ${amount} across ${segments.length} segments.`
          : `${latest}: ${amount} known across ${segments.length - unknownCount(values)} of` +
            ` ${segments.length} segments (${unknownCount(values)} unavailable).`,
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
  const values = items.map((item) => at(item)?.value?.value);
  const net = sumOf(values);
  const amount =
    net.value === null ? null : `${formatDecimal(net.value, true)}${unit ? ` ${unit}` : ""}`;
  return {
    key: "addbacks",
    table: "cp1.adjusted_ebitda_bridge",
    kind: "diverging",
    title: `Add-backs to EBITDA, ${latest}`,
    summary:
      amount === null
        ? `${items.length} add-backs.`
        : net.complete
          ? `Net ${amount} across ${items.length} add-backs.`
          : `Net ${amount} known across ${items.length - unknownCount(values)} of` +
            ` ${items.length} add-backs (${unknownCount(values)} unavailable).`,
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

/** Principal falling due each year, stacked by seniority: the maturity wall.
    A facility with an unknown principal is still a stated maturity (R24-13):
    it is retained through `own` rather than dropped before the years and
    classes it belongs to are chosen, so it is not silently missing from the
    chart and cannot silently lose the nearest-date claim to a facility whose
    principal happens to be known. */
export function maturityLadder(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1.debt_facility_register");
  if (!rows?.length) return null;
  const periods = periodsOf(tables, unique(rows.map((row) => text(row, "period_id"))));
  const latest = periods.at(-1)!;
  const own = rows.filter((row) => text(row, "period_id") === latest);
  if (own.length === 0) return null;
  const yearOf = (row: Row) => /^\d{4}/.exec(text(row, "maturity_date"))?.[0] ?? "Undated";
  const classOf = (row: Row) => `${text(row, "secured_status")} ${text(row, "seniority")}`;
  const years = unique(own.map(yearOf)).sort();
  const classes = unique(own.map(classOf));
  // A class/year with no facility at all is genuinely zero; one whose every
  // facility's principal is unstated is unknown, never silently zero
  // (`sumOf`'s own `?? "0"` fallback used to conflate the two).
  const cell = (klass: string, year: string): Datum => {
    const matched = own.filter((row) => classOf(row) === klass && yearOf(row) === year);
    if (matched.length === 0) return { value: "0" };
    const sum = sumOf(matched.map((row) => row.principal?.value));
    return sum.value === null ? { value: null, reason: "not stated" } : { value: sum.value };
  };
  const dated = own.filter((row) => yearOf(row) !== "Undated");
  // The nearest date is chosen from every dated facility, independently of
  // whether its principal is known: principal availability is not what makes
  // a maturity date the nearest one (R24-13).
  const nearest = [...(dated.length ? dated : own)].sort((a, b) =>
    text(a, "maturity_date").localeCompare(text(b, "maturity_date")),
  )[0]!;
  const unit = periodUnit(tables, latest) ?? unitOf(text(nearest, "currency"), "");
  const values = own.map((row) => row.principal?.value);
  const total = sumOf(values);
  const unknown = unknownCount(values);
  const amount =
    total.value === null ? null : `${formatDecimal(total.value)}${unit ? ` ${unit}` : ""}`;
  const principal =
    amount === null
      ? `Principal unstated for all ${own.length} facilities`
      : total.complete
        ? `${amount} principal in ${own.length} facilities`
        : `${amount} known principal across ${own.length - unknown} of ${own.length}` +
          ` facilities (${unknown} unstated)`;
  return {
    key: "maturities",
    table: "cp1.debt_facility_register",
    kind: "stack",
    title: `Debt maturities by seniority, ${latest}`,
    summary: `${principal}${
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
      data: years.map((year) => cell(klass, year)),
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

/** A fraction the bundle wrote (`current / prior - 1`, a `PERCENT_DECIMAL`
    driver) as the percent a reader reads, moved on its digits. */
const percentDatum = (cell: Cell | undefined, reason: string): Datum =>
  cell?.value != null ? { value: hundredfold(cell.value) } : { value: null, reason };

/** A comparison basis in words for a title, and short for a bar that needs
    one because its neighbours differ. */
const BASIS: Record<string, [string, string]> = {
  YOY_SAME_QUARTER: ["year on year", "YoY"],
  SEQUENTIAL: ["on the prior quarter", "QoQ"],
  YTD_PRIOR: ["year to date", "YTD"],
  LTM_PRIOR: ["last twelve months", "LTM"],
};
const ACRONYMS = new Set(["ebitda", "cfo", "ncfo", "fcf", "sbc", "sga", "ltm", "ytd"]);
/** `adjusted_ebitda` reads "Adjusted EBITDA": a register id as a label. */
const idLabel = (id: string) =>
  id
    .toLowerCase()
    .split("_")
    .map((word, index) =>
      ACRONYMS.has(word)
        ? word.toUpperCase()
        : index === 0
          ? word.charAt(0).toUpperCase() + word.slice(1)
          : word,
    )
    .join(" ");

/** Each metric's change on its reference period, in percent (N56): the one
    unit a revenue change and a debt change share, so they sit on one axis.
    A change the bundle could not calculate is a gap with its status, not a
    zero. */
export function comparatorChanges(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1b.model_comparator_register");
  if (!rows?.length) return null;
  // One basis names the figure; several name each bar, short, so a label
  // is the metric rather than a phrase repeated down the axis.
  const bases = unique(rows.map((row) => text(row, "comparison_basis")));
  const [said] = BASIS[bases[0]!] ?? [bases[0]!.toLowerCase()];
  const categories = rows.map((row) => {
    const metric = idLabel(text(row, "metric_id"));
    const basis = text(row, "comparison_basis");
    return bases.length === 1 ? metric : `${metric} ${BASIS[basis]?.[1] ?? basis}`;
  });
  const data = rows.map((row) =>
    percentDatum(row.percentage_change, text(row, "calculation_status") || "not calculable"),
  );
  // Only to name the largest move: a float orders marks, it never states one.
  const known = data.flatMap((entry, index) =>
    entry.value === null ? [] : [{ index, value: entry.value }],
  );
  const largest = [...known].sort(
    (a, b) => Math.abs(Number(b.value)) - Math.abs(Number(a.value)),
  )[0];
  const gaps = rows.length - known.length;
  return {
    key: "comparator",
    table: "cp1b.model_comparator_register",
    kind: "diverging",
    title: bases.length === 1 ? `Change ${said}, %` : "Change on the reference period, %",
    summary:
      (largest
        ? `Largest move: ${categories[largest.index]} ${formatDecimal(largest.value, true)}%.`
        : `${rows.length} comparisons, none calculable.`) +
      (largest && gaps ? ` ${gaps} not calculable.` : ""),
    unit: "%",
    categories,
    series: [{ key: "change", label: "Change", origin: "model", data }],
    sourceOf: (selection) => {
      const row = rows[selection.index];
      if (!row) return null;
      const flags = ["restatement", "basis_change", "perimeter_change", "definition_change"]
        .filter((flag) => /^(Y|YES|TRUE)$/i.test(text(row, `${flag}_flag`)))
        .map((flag) => flag.replace("_", " "));
      return [
        `${text(row, "current_period_id")} against ${text(row, "reference_period_id")}: ${text(row, "values")}`,
        flags.length ? `flagged: ${flags.join(", ")}` : "",
      ]
        .filter(Boolean)
        .join("; ");
    },
  };
}

/** CP-1B's comparison of each add-back less CP-1's, for the latest period
    validated (N56): zero where they agree. The summary counts what the
    module ruled, since a difference inside tolerance still passes. */
export function addbackValidation(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1b.addback_validation_register");
  if (!rows?.length) return null;
  const latest = unique(rows.map((row) => text(row, "period_id"))).at(-1)!;
  const own = rows.filter((row) => text(row, "period_id") === latest);
  const count = (status: string) =>
    own.filter((row) => text(row, "status").toUpperCase() === status).length;
  const [pass, warn, block] = [count("PASS"), count("WARN"), count("BLOCK")];
  return {
    key: "addback-validation",
    table: "cp1b.addback_validation_register",
    kind: "diverging",
    title: `Add-backs against CP-1, ${latest}`,
    summary:
      `${pass} of ${own.length} pass` +
      (warn ? `, ${warn} warn` : "") +
      (block ? `, ${block} block model readiness` : "") +
      ".",
    // The register names an add-back by its id; its label is CP-1's table.
    categories: own.map((row) => idLabel(text(row, "addback_id"))),
    series: [
      {
        key: "difference",
        label: "CP-1B less CP-1",
        origin: "model",
        data: own.map((row) => datum(row.difference)),
      },
    ],
    sourceOf: (selection) => {
      const row = own[selection.index];
      if (!row) return null;
      return [text(row, "status"), text(row, "explanation"), text(row, "source_or_conflict_ref")]
        .filter(Boolean)
        .join(" · ");
    },
  };
}

const CASE_ORDER = ["BASE", "DOWNSIDE"];

/** Each division's forecast growth, base against downside, by fiscal year
    (N56): one figure a division, as the KPIs are, so two lines share each
    axis. A slot the issuer does not use (`NOT_APPLICABLE` throughout) draws
    nothing. The division is named by its slot: CP-1's allocation that maps
    it to a segment is another module's table. */
export function forecastDrivers(tables: readonly Table[]): Figure[] {
  const rows = (tableOf(tables, "cp2g.cp_model_forecast_drivers") ?? []).filter(
    (row) => text(row, "driver_id") === "division_growth",
  );
  const slots = unique(rows.map((row) => text(row, "slot_id"))).filter((slot) =>
    rows.some((row) => text(row, "slot_id") === slot && text(row, "status") === "READY"),
  );
  return slots.map((slot) => {
    const own = rows.filter((row) => text(row, "slot_id") === slot);
    const years = unique(own.map((row) => text(row, "fiscal_year"))).sort();
    const cases = unique(own.map((row) => text(row, "case"))).sort(
      (a, b) => CASE_ORDER.indexOf(a) - CASE_ORDER.indexOf(b),
    );
    const at = (kase: string, year: string) =>
      own.find((row) => text(row, "case") === kase && text(row, "fiscal_year") === year);
    const label = sentence(slot.replace("_", " "));
    const span = (kase: string) => {
      const first = at(kase, years[0]!)?.value?.value;
      const last = at(kase, years.at(-1)!)?.value?.value;
      return first != null && last != null
        ? `${sentence(kase)} ${formatDecimal(hundredfold(first), true)}% to ${formatDecimal(hundredfold(last), true)}%`
        : null;
    };
    return {
      key: `forecast-${slot}`,
      table: "cp2g.cp_model_forecast_drivers",
      kind: "line" as const,
      title: `${label} growth, %`,
      summary:
        [cases.map(span).filter(Boolean).join("; "), `${years[0]} to ${years.at(-1)}`]
          .filter(Boolean)
          .join(", ") + ".",
      unit: "%",
      categories: years,
      series: cases.map((kase) => ({
        key: kase,
        label: sentence(kase),
        origin: "model" as const,
        data: years.map((year) => percentDatum(at(kase, year)?.value, "not stated")),
      })),
      sourceOf: (selection: ChartSelection) => locate(at(selection.series, selection.category)),
    };
  });
}

/** Every figure a handoff's tables support, in reading order. */
export function figuresOf(handoff: HandoffView): Figure[] {
  const tables = handoff.tables;
  return [
    segmentMix(tables),
    ...kpiLines(tables),
    addbacks(tables),
    maturityLadder(tables),
    comparatorChanges(tables),
    addbackValidation(tables),
    ...forecastDrivers(tables),
  ].filter((figure): figure is Figure => figure !== null);
}

/** CP-2B's catalysts, ranked, each with the date or window it falls in
    (N56): a list, not a chart -- an event is not a magnitude. */
function Catalysts({ tables }: { tables: HandoffView["tables"] }) {
  const rows = tableOf(tables, "cp2b.cp_model_catalysts");
  if (!rows?.length) return null;
  const ranked = [...rows].sort(
    (a, b) =>
      (Number(text(a, "rank")) || Number.MAX_SAFE_INTEGER) -
      (Number(text(b, "rank")) || Number.MAX_SAFE_INTEGER),
  );
  return (
    <section className="catalysts" aria-labelledby="catalysts-heading" data-catalysts>
      <h4 id="catalysts-heading">Catalysts, ranked</h4>
      <ol>
        {ranked.map((row, index) => (
          <li key={`${text(row, "rank")}-${index}`} data-catalyst={text(row, "rank")}>
            <span className="when">{text(row, "event_date_or_window") || "Undated"}</span>
            <span className="what">
              <b>{text(row, "event")}</b>
              {text(row, "credit_relevance") ? <span>{text(row, "credit_relevance")}</span> : null}
              {text(row, "status") && text(row, "status") !== "READY" ? (
                <span className="tag warn">{text(row, "status")}</span>
              ) : null}
            </span>
            {locate(row) ? <span className="src">{locate(row)}</span> : null}
          </li>
        ))}
      </ol>
    </section>
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
      {figures.length ? (
        <div className="figgrid">
          {figures.map((figure) => (
            <div key={figure.key} className={`fig ${figure.kind}`} data-figure={figure.key}>
              <Chart figure={figure} onPick={onPick} />
            </div>
          ))}
        </div>
      ) : null}
      <Catalysts tables={handoff.tables} />
      {handoff.tables.length ? <RawTables tables={handoff.tables} /> : null}
    </section>
  );
}
