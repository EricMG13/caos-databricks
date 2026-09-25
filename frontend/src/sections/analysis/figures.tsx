// A module's figures, drawn from the tagged tables the server read with the
// bundle's own reader (D32). The tables are the model's, like its prose, so
// every mark is model-authored: outlined and hatched, printed exactly as
// served. Sums are exact (BigInt); a float only places a mark.
import { useMemo, type ReactNode } from "react";
import {
  DivergingBarChart,
  LineChart,
  ProvenanceKeyed,
  StackedBarChart,
  Swatch,
  formatDecimal,
  type ChartColor,
  type ChartSelection,
  type ChartSeries,
  type Datum,
} from "@/charts";
import { fromScaled, placesOf, toScaled } from "@/charts/decimal";
import { hundredfold, plainName } from "@/ds/format";
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
  /** Past `MAX_MARKS`: stated, not drawn. */
  oversized?: boolean;
}

/** A figure past this many marks is stated, not drawn, and past this many
    figures a module's are stated too. The tables are model-authored and may
    run to 2,000 rows: a cross product of two of their columns is millions of
    marks, and drawing them froze the tab (security review, F327). */
const MAX_MARKS = 2_000;
const MAX_FIGURES = 24;

function oversized(key: string, table: string, title: string, marks: number): Figure {
  return {
    key,
    table,
    kind: "stack",
    title,
    summary: `${marks} marks: too many to draw. The Appendix tab lists every row.`,
    categories: [],
    series: [],
    sourceOf: () => null,
    oversized: true,
  };
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
  const placed = new Set(ordered);
  return [...ordered, ...present.filter((period) => !placed.has(period))];
}

/** The register's currency and scale for a period. */
function periodUnit(tables: readonly Table[], period: string | undefined): string | undefined {
  const row = (tableOf(tables, "cp1.model_period_register") ?? []).find(
    (entry) => text(entry, "period_id") === period,
  );
  return row ? unitOf(text(row, "currency"), text(row, "unit")) : undefined;
}

const unique = (values: readonly string[]) => [...new Set(values)];
/** Rows grouped by `key`, in table order, built once: a `find` or `filter`
    per mark made the figures cubic in a table's rows. */
function groupBy(rows: readonly Row[], key: (row: Row) => string): Map<string, Row[]> {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const k = key(row);
    const group = groups.get(k);
    if (group) group.push(row);
    else groups.set(k, [row]);
  }
  return groups;
}
/** Two cells as one key; the separator cannot occur in a served cell's text. */
const pair = (a: string, b: string) => `${a}\u0000${b}`;
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
  const segments = byPriority(rows, "segment_id");
  if (segments.length * periods.length > MAX_MARKS) {
    return oversized(
      "segment-mix",
      "cp1.segment_revenue_schedule",
      "Revenue by segment",
      segments.length * periods.length,
    );
  }
  const cells = groupBy(rows, (row) => pair(text(row, "segment_id"), text(row, "period_id")));
  const at = (segment: string, period: string) => cells.get(pair(segment, period))?.[0];
  const named = groupBy(rows, (row) => text(row, "segment_id"));
  const series = segments.map((segment) => ({
    key: segment,
    label: text(named.get(segment)![0]!, "segment_name"),
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
  const byKpi = groupBy(rows, (row) => text(row, "kpi_id"));
  return byPriority(rows, "kpi_id").map((kpi) => {
    const own = byKpi.get(kpi)!;
    const periods = periodsOf(tables, unique(own.map((row) => text(row, "period_id"))));
    const byPeriod = groupBy(own, (row) => text(row, "period_id"));
    const at = (period: string) => byPeriod.get(period)?.[0];
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
  if (items.length > MAX_MARKS) {
    return oversized(
      "addbacks",
      "cp1.adjusted_ebitda_bridge",
      `Add-backs to EBITDA, ${latest}`,
      items.length,
    );
  }
  const byItem = groupBy(own, (row) => text(row, "addback_id"));
  const at = (item: string) => byItem.get(item)?.[0];
  const labels = groupBy(own, (row) => text(row, "addback_label"));
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
    categories: items.map((item) => {
      const label = text(at(item)!, "addback_label");
      const twin = new Set(labels.get(label)!.map((row) => text(row, "addback_id"))).size > 1;
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
  if (classes.length * years.length > MAX_MARKS) {
    return oversized(
      "maturities",
      "cp1.debt_facility_register",
      `Debt maturities by seniority, ${latest}`,
      classes.length * years.length,
    );
  }
  const falling = groupBy(own, (row) => pair(classOf(row), yearOf(row)));
  // A class/year with no facility at all is genuinely zero; one whose every
  // facility's principal is unstated is unknown, never silently zero
  // (`sumOf`'s own `?? "0"` fallback used to conflate the two).
  const cell = (klass: string, year: string): Datum => {
    const matched = falling.get(pair(klass, year)) ?? [];
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
      // Every underscore, and a status said once: `NOT_STATED NOT_STATED`
      // reads "Not stated".
      label: sentence(unique(klass.split(" ")).join(" ").replaceAll("_", " ")),
      origin: "model" as const,
      color: TRANCHE[klass] ?? "neutral",
      data: years.map((year) => cell(klass, year)),
    })),
    // A segment sums every facility of its class falling due that year, so it
    // names each one's stated source, not the first's (rewrite tournament).
    sourceOf: (selection) => {
      const summed = falling.get(pair(selection.series, selection.category)) ?? [];
      return summed.length
        ? summed.map((row) => `${text(row, "facility_name")}: ${locate(row)}`).join("; ")
        : null;
    },
  };
}

/** A rate as the percent a reader reads. The model may write it either way:
    a bare fraction (`0.08`, a `PERCENT_DECIMAL` driver) is moved two places
    on its digits, while `8%` already is one -- the host's reader strips the
    sign and keeps the points (`caos/methodology/tables.py`), so the served
    value is `8`, and scaling it again drew 800%. */
const percentDatum = (cell: Cell | undefined, reason: string): Datum => {
  if (cell?.value == null) return { value: null, reason };
  return { value: cell.text.trim().endsWith("%") ? cell.value : hundredfold(cell.value) };
};

/** A comparison basis in words for a title, and short for a bar that needs
    one because its neighbours differ. */
const BASIS: Record<string, [string, string]> = {
  YOY_SAME_QUARTER: ["year on year", "YoY"],
  SEQUENTIAL: ["on the prior quarter", "QoQ"],
  YTD_PRIOR: ["year to date", "YTD"],
  LTM_PRIOR: ["last twelve months", "LTM"],
};
/** Each metric's change on its reference period, in percent (N56): the one
    unit a revenue change and a debt change share, so they sit on one axis.
    A change the bundle could not calculate is a gap with its status, not a
    zero. */
export function comparatorChanges(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1b.model_comparator_register");
  if (!rows?.length) return null;
  if (rows.length > MAX_MARKS) {
    return oversized("comparator", "cp1b.model_comparator_register", "Change", rows.length);
  }
  // One basis names the figure; several name each bar, short, so a label
  // is the metric rather than a phrase repeated down the axis.
  const bases = unique(rows.map((row) => text(row, "comparison_basis")));
  const [said] = BASIS[bases[0]!] ?? [bases[0]!.toLowerCase()];
  const named = rows.map((row) => {
    const metric = plainName(text(row, "metric_id"));
    const basis = text(row, "comparison_basis");
    return bases.length === 1 ? metric : `${metric} ${BASIS[basis]?.[1] ?? basis}`;
  });
  // A metric compared twice on one basis (two quarters' revenue) is two
  // bars: each names its period, so neither is read as the other.
  const seen = new Map<string, number>();
  for (const label of named) seen.set(label, (seen.get(label) ?? 0) + 1);
  const categories = named.map((label, index) =>
    seen.get(label) === 1 ? label : `${label}, ${text(rows[index]!, "current_period_id")}`,
  );
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

/** One headline figure: the value now, what it is compared with, and the
    change, each printed as served. */
export interface KeyFigure {
  key: string;
  label: string;
  value: string;
  reference: string | null;
  change: Datum;
}

/** Headline tiles past this many would crowd the view they sit beside; the
    appendix and the figure below carry every row. */
const KEY_FIGURES = 6;

/** CP-1B's comparator register as the headline figures beside the module's
    view (D60). The host's reader typed it, so each value is the served
    decimal, never one read from the prose (D32). */
export function keyFigures(tables: readonly Table[]): KeyFigure[] {
  const rows = (tableOf(tables, "cp1b.model_comparator_register") ?? []).slice(0, KEY_FIGURES);
  const served = (cell: Cell | undefined) =>
    cell?.value == null ? cell?.text || "n/a" : formatDecimal(cell.value);
  // A metric compared over two periods would print two identical labels.
  const repeated = (metric: string) =>
    rows.filter((row) => text(row, "metric_id") === metric).length > 1;
  return rows.map((row, index) => ({
    key: `${text(row, "metric_id")}-${index}`,
    label: [
      plainName(text(row, "metric_id")),
      repeated(text(row, "metric_id")) ? plainName(text(row, "current_period_id")) : "",
    ]
      .filter(Boolean)
      .join(" · "),
    value: served(row.current_value),
    reference: row.reference_value ? served(row.reference_value) : null,
    // A change the host could not type ("(5.1%) reported") prints as written.
    change: percentDatum(
      row.percentage_change,
      text(row, "percentage_change") || text(row, "calculation_status") || "not calculable",
    ),
  }));
}

/** CP-1B's comparison of each add-back less CP-1's, every period it
    validated (N56): zero where they agree. Every period, not a "latest" one:
    this register carries no period order of its own (CP-1's register is
    another module's table), and a row order that put an older period last
    hid a BLOCK in the newer one. The summary counts what the module ruled,
    since a difference inside tolerance still passes. */
export function addbackValidation(tables: readonly Table[]): Figure | null {
  const rows = tableOf(tables, "cp1b.addback_validation_register");
  if (!rows?.length) return null;
  if (rows.length > MAX_MARKS) {
    return oversized(
      "addback-validation",
      "cp1b.addback_validation_register",
      "Add-backs against CP-1",
      rows.length,
    );
  }
  const count = (status: string) =>
    rows.filter((row) => text(row, "status").toUpperCase() === status).length;
  const [pass, warn, block] = [count("PASS"), count("WARN"), count("BLOCK")];
  const periods = unique(rows.map((row) => text(row, "period_id")));
  return {
    key: "addback-validation",
    table: "cp1b.addback_validation_register",
    kind: "diverging",
    title: "Add-backs against CP-1",
    summary:
      `${pass} of ${rows.length} pass` +
      (warn ? `, ${warn} warn` : "") +
      (block ? `, ${block} block model readiness` : "") +
      ` across ${periods.length === 1 ? periods[0] : `${periods.length} periods`}.`,
    // The register names an add-back by its id (its label is CP-1's table),
    // and each bar by its period too, so no two read alike.
    categories: rows.map(
      (row) => `${plainName(text(row, "addback_id"))}, ${text(row, "period_id")}`,
    ),
    series: [
      {
        key: "difference",
        label: "CP-1B less CP-1",
        origin: "model",
        data: rows.map((row) => datum(row.difference)),
      },
    ],
    sourceOf: (selection) => {
      const row = rows[selection.index];
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
  const bySlot = groupBy(rows, (row) => text(row, "slot_id"));
  return slots.map((slot) => {
    const own = bySlot.get(slot)!;
    const years = unique(own.map((row) => text(row, "fiscal_year"))).sort();
    // A case the bundle does not name sorts after the two it does, never
    // before BASE (`indexOf` is -1).
    const order = (kase: string) =>
      CASE_ORDER.includes(kase) ? CASE_ORDER.indexOf(kase) : CASE_ORDER.length;
    const cases = unique(own.map((row) => text(row, "case"))).sort((a, b) => order(a) - order(b));
    const cells = groupBy(own, (row) => pair(text(row, "case"), text(row, "fiscal_year")));
    const at = (kase: string, year: string) => cells.get(pair(kase, year))?.[0];
    const label = sentence(slot.replace("_", " "));
    const span = (kase: string) => {
      const first = percentDatum(at(kase, years[0]!)?.value, "").value;
      const last = percentDatum(at(kase, years.at(-1)!)?.value, "").value;
      return first != null && last != null
        ? `${sentence(kase)} ${formatDecimal(first, true)}% to ${formatDecimal(last, true)}%`
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
  // The key figures beside the view already print every comparison when
  // there are no more than they hold; the chart would say them again.
  const compared = tableOf(tables, "cp1b.model_comparator_register")?.length ?? 0;
  const figures = [
    segmentMix(tables),
    ...kpiLines(tables),
    addbacks(tables),
    maturityLadder(tables),
    compared > KEY_FIGURES ? comparatorChanges(tables) : null,
    addbackValidation(tables),
    ...forecastDrivers(tables),
  ].filter((figure): figure is Figure => figure !== null);
  if (figures.length <= MAX_FIGURES) return figures;
  const rest = figures.length - (MAX_FIGURES - 1);
  return [
    ...figures.slice(0, MAX_FIGURES - 1),
    {
      ...oversized("more", figures[MAX_FIGURES - 1]!.table, `${rest} more figures`, 0),
      summary: `${rest} more figures are not drawn. The Appendix tab lists every row.`,
    },
  ];
}

/** CP-2B's catalysts, ranked, each with the date or window it falls in
    (N56): a list, not a chart -- an event is not a magnitude. */
function Catalysts({ tables }: { tables: HandoffView["tables"] }) {
  const rows = tableOf(tables, "cp2b.cp_model_catalysts");
  if (!rows?.length) return null;
  // A rank that is not a number sorts last; 0 is a rank, not a missing one.
  const rank = (row: Row) => {
    const value = Number(text(row, "rank") || Number.NaN);
    return Number.isFinite(value) ? value : Number.MAX_SAFE_INTEGER;
  };
  const ranked = [...rows].sort((a, b) => rank(a) - rank(b));
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

/** Every figure here is the model's, so one key says so for all of them. */
function ModelKey({ figures }: { figures: readonly Figure[] }) {
  const drawn = figures.filter((figure) => !figure.oversized);
  const shapes = [
    ...(drawn.some((figure) => figure.kind !== "line") ? (["fill"] as const) : []),
    ...(drawn.some((figure) => figure.kind === "line") ? (["line"] as const) : []),
  ];
  if (shapes.length === 0) return null;
  return (
    <ul className="chart-legend" aria-label="Key" data-figures-key>
      {shapes.map((shape) => (
        <li key={shape} className="chart-provenance">
          <Swatch tone="neutral" shape={shape} origin="model" />
          {shape === "fill" ? "Outlined" : "Dashed, hollow point"}: model-authored, not
          host-verified
        </li>
      ))}
    </ul>
  );
}

export function Figures({
  handoff,
  calculation,
  onPick,
}: {
  handoff: HandoffView;
  /** What the host calculated for this module, said where its figures are. */
  calculation: ReactNode;
  onPick: (pick: FigurePick, opener: HTMLElement) => void;
}) {
  // Once a document, not once a render: pressing a mark re-renders the
  // section, and the figures' cost is the tables' (F327).
  const figures = useMemo(
    () => (handoff.tables_unavailable_reason ? [] : figuresOf(handoff)),
    [handoff],
  );
  // With no figures to head, what the host calculated is a caveat on the
  // module, drawn as one -- not a loose line between its cards (brief 5).
  if (handoff.tables_unavailable_reason) {
    return (
      <div className="calc-caveat">
        <p className="note" data-tables-unavailable={handoff.tables_unavailable_reason}>
          This module&apos;s tables could not be read ({handoff.tables_unavailable_reason}), so it
          shows no figures. Its prose below is unaffected.
        </p>
        {calculation}
      </div>
    );
  }
  // Tables that draw nothing here (a comparator the key figures print) leave
  // no empty Figures heading behind.
  const catalysts = tableOf(handoff.tables, "cp2b.cp_model_catalysts")?.length ?? 0;
  if (figures.length === 0 && catalysts === 0) {
    return <div className="calc-caveat">{calculation}</div>;
  }
  return (
    <section className="figures" aria-labelledby="figures-heading" data-figures>
      <header className="grouphead">
        <h3 id="figures-heading">Figures</h3>
        <ModelKey figures={figures} />
        {calculation}
      </header>
      {figures.length ? (
        <ProvenanceKeyed value={false}>
          <div className="figgrid">
            {figures.map((figure) => (
              <div key={figure.key} className={`fig ${figure.kind}`} data-figure={figure.key}>
                {figure.oversized ? (
                  <p className="note" data-figure-oversized>
                    <b>{figure.title}.</b> {figure.summary}
                  </p>
                ) : (
                  <Chart figure={figure} onPick={onPick} />
                )}
              </div>
            ))}
          </div>
        </ProvenanceKeyed>
      ) : null}
      <Catalysts tables={handoff.tables} />
    </section>
  );
}
