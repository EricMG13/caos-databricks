// The Book's filtering and sorting (spec B12-B15), pure: no React, no I/O.
// Figures are decimal strings compared exactly as scaled integers, never as
// numbers. A null cell fails a filter and sorts last in either direction; equal
// cells keep the document's order. A MONEY column compares only the rows in
// the view's currency; with no currency chosen a MONEY range filter is inert
// and a MONEY sort leaves the order unchanged (the UI asks for a currency).
import { isDecimal, placesOf, toScaled } from "@/charts/decimal";
import type { BookIssuerView, BookMetricView } from "@/wire/v1";
import {
  MOODYS_SCALE,
  SP_FITCH_SCALE,
  type Agency,
  type Basis,
  type BookView,
  type ColumnKey,
  type Filter,
} from "./view";

export type BookIssuer = BookIssuerView;
type Unit = Pick<BookMetricView, "line_id" | "unit">;

const BASES: readonly Basis[] = ["LTM", "PF_LTM", "BASE_FY1", "DOWNSIDE_FY1"];
const AGENCIES: readonly string[] = ["moodys", "sp", "fitch"];

function scaleOf(agency: Agency): readonly string[] {
  return agency === "moodys" ? MOODYS_SCALE : SP_FITCH_SCALE;
}

/** A metric column's line id (as the metric catalogue spells it) and its own basis, if any. */
export function metricOf(column: ColumnKey, basis: Basis): { lineId: string; basis: Basis } | null {
  const body = column.slice(2);
  const at = body.lastIndexOf("@");
  if (at < 0) return { lineId: body, basis };
  const suffix = body.slice(at + 1);
  const named = BASES.find((candidate) => candidate === suffix);
  return named === undefined ? null : { lineId: body.slice(0, at), basis: named };
}

/** One cell as served: text for an identifier, decimal text for a metric, or null. */
export function cellOf(issuer: BookIssuer, column: ColumnKey, basis: Basis): string | null {
  const entry = issuer.displayed;
  if (column.startsWith("m:")) {
    const metric = metricOf(column, basis);
    if (metric === null) return null;
    return entry.metrics[metric.basis]?.[metric.lineId] ?? null;
  }
  switch (column.slice(3)) {
    case "issuer_name":
      return entry.issuer_name;
    case "reporting_period":
      return entry.reporting_period;
    case "issuer_id":
      return entry.issuer_id;
    case "sector":
      return entry.sector;
    case "industry_group":
      return entry.industry_group;
    case "domicile":
      return entry.domicile;
    case "composite":
      return entry.composite;
    case "composite_bucket":
      return entry.composite_bucket;
    case "moodys":
      return entry.moodys;
    case "moodys_outlook":
      return entry.moodys_outlook;
    case "sp":
      return entry.sp;
    case "sp_outlook":
      return entry.sp_outlook;
    case "fitch":
      return entry.fitch;
    case "fitch_outlook":
      return entry.fitch_outlook;
    case "analysis_date":
      return entry.analysis_date;
    case "route":
      return entry.route;
    case "filed":
      return entry.filed ? "true" : "false";
    case "currency":
      return entry.currency;
    case "unit":
      return entry.unit;
    case "fiscal_year_base_fy1":
      return entry.fiscal_years.BASE_FY1 ?? null;
    case "fiscal_year_downside_fy1":
      return entry.fiscal_years.DOWNSIDE_FY1 ?? null;
    case "case":
      return entry.case_id;
    default:
      return null;
  }
}

function compareDecimal(a: string, b: string): number {
  const places = Math.max(placesOf(a), placesOf(b));
  const [x, y] = [toScaled(a, places), toScaled(b, places)];
  if (x === y) return 0;
  return x < y ? -1 : 1;
}

function compareText(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

function agencyOf(column: ColumnKey): Agency | null {
  const name = column.startsWith("id:") ? column.slice(3) : "";
  return AGENCIES.includes(name) ? (name as Agency) : null;
}

function isMoney(column: ColumnKey, view: BookView, units: readonly Unit[]): boolean {
  if (!column.startsWith("m:")) return false;
  const lineId = metricOf(column, view.basis)?.lineId;
  return units.find((unit) => unit.line_id === lineId)?.unit === "MONEY";
}

/** Whether the figure may be compared: a MONEY cell only in the view's currency. */
function comparable(
  issuer: BookIssuer,
  column: ColumnKey,
  view: BookView,
  units: readonly Unit[],
): boolean {
  return (
    !isMoney(column, view, units) ||
    (view.currency !== null && issuer.displayed.currency === view.currency)
  );
}

function passes(
  issuer: BookIssuer,
  filter: Filter,
  view: BookView,
  units: readonly Unit[],
): boolean {
  if (filter.kind === "notch") {
    const label = cellOf(issuer, `id:${filter.agency}`, view.basis);
    if (label === null) return false;
    const scale = scaleOf(filter.agency);
    const [at, best, worst] = [
      scale.indexOf(label),
      scale.indexOf(filter.best),
      scale.indexOf(filter.worst),
    ];
    return at >= 0 && best >= 0 && worst >= 0 && at >= best && at <= worst;
  }
  if (filter.kind === "set") {
    const cell = cellOf(issuer, filter.column, view.basis);
    return cell !== null && filter.values.includes(cell);
  }
  if (!filter.column.startsWith("m:")) return false;
  if (isMoney(filter.column, view, units) && view.currency === null) return true;
  const cell = cellOf(issuer, filter.column, view.basis);
  // A range is for figures; any other text fails closed rather than reach BigInt.
  if (cell === null || !isDecimal(cell) || !comparable(issuer, filter.column, view, units))
    return false;
  return (
    (filter.min === null || compareDecimal(cell, filter.min) >= 0) &&
    (filter.max === null || compareDecimal(cell, filter.max) <= 0)
  );
}

type SortKey = { kind: "number"; value: number } | { kind: "decimal" | "text"; value: string };

function sortKey(issuer: BookIssuer, column: ColumnKey, view: BookView, units: readonly Unit[]) {
  if (column === "id:composite") {
    const notch = issuer.displayed.composite_notch;
    return notch === null ? null : ({ kind: "number", value: notch } satisfies SortKey);
  }
  if (!comparable(issuer, column, view, units)) return null;
  const cell = cellOf(issuer, column, view.basis);
  if (cell === null) return null;
  const agency = agencyOf(column);
  if (agency !== null) {
    const at = scaleOf(agency).indexOf(cell);
    return at < 0 ? null : ({ kind: "number", value: at } satisfies SortKey);
  }
  const kind = column.startsWith("m:") ? "decimal" : "text";
  return { kind, value: cell } satisfies SortKey;
}

function compareKeys(a: SortKey, b: SortKey): number {
  if (a.kind === "number" && b.kind === "number") return a.value - b.value;
  if (a.kind === "decimal" && b.kind === "decimal") return compareDecimal(a.value, b.value);
  if (a.kind === "text" && b.kind === "text") return compareText(a.value, b.value);
  throw new TypeError("a column holds one kind of key");
}

/** The issuers the view keeps, in the view's order. `units` is the document's metric catalogue. */
export function applyView(
  issuers: BookIssuer[],
  view: BookView,
  units: readonly Unit[],
): BookIssuer[] {
  const kept = issuers.filter((issuer) =>
    view.filters.every((filter) => passes(issuer, filter, view, units)),
  );
  const sort = view.sort;
  if (sort === null || (isMoney(sort.column, view, units) && view.currency === null)) return kept;
  const sign = sort.dir === "asc" ? 1 : -1;
  const keyed = kept.map((issuer, index) => ({
    issuer,
    index,
    key: sortKey(issuer, sort.column, view, units),
  }));
  keyed.sort((a, b) => {
    if (a.key === null || b.key === null) {
      if (a.key === b.key) return a.index - b.index;
      return a.key === null ? 1 : -1;
    }
    return sign * compareKeys(a.key, b.key) || a.index - b.index;
  });
  return keyed.map((item) => item.issuer);
}
