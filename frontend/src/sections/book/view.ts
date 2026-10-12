// The Book section's view state (spec B12-B14), pure: no React, no wire import.
// It round-trips through URLSearchParams so a view is a link.
//
// Grammar (every field is percent-encoded, then joined by "|"):
//   basis=<Basis>                      current basis for metric columns
//   col=<ColumnKey>                    repeated, in display order
//   f=range|<col>|<min>|<max>          empty min or max = unbounded; decimals stay strings
//   f=set|<col>|<v1>,<v2>,...          each value encoded, so "," and "|" inside a value are safe
//   f=notch|<agency>|<best>|<worst>
//   sort=<asc|desc>|<col>
//   cur=<currency>
// A range applies to metric columns only. Unknown keys and malformed values are ignored, never thrown on.
// Normalisation: inert filters are dropped (an empty set, a range with both bounds null,
// a notch with an empty label), as are a range whose min exceeds its max (compared exactly),
// a notch with a label off its agency's scale or best worse than worst, and a currency that
// is not three capital letters. Locked columns are re-added and columns de-duplicated.

import { placesOf, toScaled } from "@/charts/decimal";

export type Basis = "LTM" | "PF_LTM" | "BASE_FY1" | "DOWNSIDE_FY1";
export type IdentifierKey =
  | "issuer_name"
  | "reporting_period"
  | "issuer_id"
  | "sector"
  | "industry_group"
  | "domicile"
  | "composite"
  | "composite_bucket"
  | "moodys"
  | "moodys_outlook"
  | "sp"
  | "sp_outlook"
  | "fitch"
  | "fitch_outlook"
  | "analysis_date"
  | "route"
  | "filed"
  | "currency"
  | "unit"
  | "fiscal_year_base_fy1"
  | "fiscal_year_downside_fy1"
  | "case";
export type ColumnKey = `id:${IdentifierKey}` | `m:${string}`;
export type Agency = "moodys" | "sp" | "fitch";
export type Filter =
  | { kind: "range"; column: ColumnKey; min: string | null; max: string | null }
  | { kind: "set"; column: ColumnKey; values: string[] }
  | { kind: "notch"; agency: Agency; best: string; worst: string };
export type BookView = {
  basis: Basis;
  columns: ColumnKey[];
  filters: Filter[];
  sort: { column: ColumnKey; dir: "asc" | "desc" } | null;
  currency: string | null;
};

const BASES: readonly Basis[] = ["LTM", "PF_LTM", "BASE_FY1", "DOWNSIDE_FY1"];
const IDENTIFIERS: readonly IdentifierKey[] = [
  "issuer_name", "reporting_period", "issuer_id", "sector", "industry_group", "domicile",
  "composite", "composite_bucket", "moodys", "moodys_outlook", "sp", "sp_outlook", "fitch",
  "fitch_outlook", "analysis_date", "route", "filed", "currency", "unit", "fiscal_year_base_fy1", "fiscal_year_downside_fy1", "case",
]; // prettier-ignore
const AGENCIES: readonly Agency[] = ["moodys", "sp", "fitch"];
// Rating scales, best first; the labels and order are caos/book/classification.py's.
export const MOODYS_SCALE: readonly string[] = [
  "Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3", "Baa1", "Baa2", "Baa3", "Ba1", "Ba2", "Ba3",
  "B1", "B2", "B3", "Caa1", "Caa2", "Caa3", "Ca", "C",
]; // prettier-ignore
export const SP_FITCH_SCALE: readonly string[] = [
  "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
  "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
]; // prettier-ignore
const CURRENCY = /^[A-Z]{3}$/;
const DECIMAL = /^-?\d+(\.\d+)?$/;

export const LOCKED: readonly ColumnKey[] = ["id:issuer_name", "id:reporting_period"];

export const DEFAULT_VIEW: BookView = {
  basis: "LTM",
  columns: [
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
  ],
  filters: [],
  sort: null,
  currency: null,
};

function isBasis(value: string): value is Basis {
  return (BASES as readonly string[]).includes(value);
}

function isAgency(value: string): value is Agency {
  return (AGENCIES as readonly string[]).includes(value);
}

function asColumn(value: string): ColumnKey | null {
  if (value.startsWith("id:")) {
    return (IDENTIFIERS as readonly string[]).includes(value.slice(3))
      ? (value as ColumnKey)
      : null;
  }
  if (!value.startsWith("m:")) return null;
  const body = value.slice(2);
  const at = body.lastIndexOf("@");
  const id = at < 0 ? body : body.slice(0, at);
  if (id === "") return null;
  if (at >= 0 && !isBasis(body.slice(at + 1))) return null;
  return value as ColumnKey;
}

// decodeURIComponent throws URIError on a bad escape; that is the one expected failure, answered with null.
function decode(part: string): string | null {
  try {
    return decodeURIComponent(part);
  } catch (error) {
    if (error instanceof URIError) return null;
    throw error;
  }
}

const enc = encodeURIComponent;

function encodeFilter(filter: Filter): string {
  if (filter.kind === "range") {
    return ["range", enc(filter.column), enc(filter.min ?? ""), enc(filter.max ?? "")].join("|");
  }
  if (filter.kind === "set") {
    return ["set", enc(filter.column), filter.values.map(enc).join(",")].join("|");
  }
  return ["notch", filter.agency, enc(filter.best), enc(filter.worst)].join("|");
}

function decodeBound(raw: string): string | null | undefined {
  if (raw === "") return null;
  return DECIMAL.test(raw) ? raw : undefined;
}

function decodeFilter(raw: string): Filter | null {
  const parts = raw.split("|");
  if (parts.length > 4) return null;
  const [kind = "", first = "", second = "", third = ""] = parts;
  if (kind === "range") {
    const column = decode(first);
    const min = decode(second);
    const max = decode(third);
    const key = column === null ? null : asColumn(column);
    if (key === null || !key.startsWith("m:") || min === null || max === null) return null;
    const lo = decodeBound(min);
    const hi = decodeBound(max);
    if (lo === undefined || hi === undefined || (lo === null && hi === null)) return null;
    if (lo !== null && hi !== null) {
      const places = Math.max(placesOf(lo), placesOf(hi));
      if (toScaled(lo, places) > toScaled(hi, places)) return null;
    }
    return { kind, column: key, min: lo, max: hi };
  }
  if (kind === "set" && third === "") {
    const column = decode(first);
    const key = column === null ? null : asColumn(column);
    if (key === null || second === "") return null;
    const values: string[] = [];
    for (const piece of second.split(",")) {
      const value = decode(piece);
      if (value === null) return null;
      values.push(value);
    }
    return { kind, column: key, values };
  }
  if (kind === "notch") {
    const best = decode(second);
    const worst = decode(third);
    if (!isAgency(first) || !best || !worst) return null;
    const scale = first === "moodys" ? MOODYS_SCALE : SP_FITCH_SCALE;
    const bestAt = scale.indexOf(best);
    const worstAt = scale.indexOf(worst);
    if (bestAt < 0 || worstAt < 0 || bestAt > worstAt) return null;
    return { kind, agency: first, best, worst };
  }
  return null;
}

function withLocked(columns: ColumnKey[]): ColumnKey[] {
  return [...new Set<ColumnKey>([...LOCKED, ...columns])];
}

export function toParams(view: BookView): URLSearchParams {
  const params = new URLSearchParams();
  params.set("basis", view.basis);
  for (const column of withLocked(view.columns)) params.append("col", column);
  for (const filter of view.filters) params.append("f", encodeFilter(filter));
  if (view.sort) params.set("sort", `${view.sort.dir}|${enc(view.sort.column)}`);
  if (view.currency) params.set("cur", view.currency);
  return params;
}

export function fromParams(params: URLSearchParams): BookView {
  const basis = params.get("basis") ?? "";
  const columns: ColumnKey[] = [];
  for (const value of params.getAll("col")) {
    const column = asColumn(value);
    if (column !== null) columns.push(column);
  }
  const filters: Filter[] = [];
  for (const value of params.getAll("f")) {
    const filter = decodeFilter(value);
    if (filter !== null) filters.push(filter);
  }
  let sort: BookView["sort"] = null;
  const sortParts = (params.get("sort") ?? "").split("|");
  const [dir, rawColumn] = sortParts;
  const sortColumn = rawColumn === undefined ? null : decode(rawColumn);
  const column = sortColumn === null ? null : asColumn(sortColumn);
  if ((dir === "asc" || dir === "desc") && sortParts.length <= 2 && column) {
    sort = { column, dir };
  }
  const currency = params.get("cur") ?? "";
  return {
    basis: isBasis(basis) ? basis : DEFAULT_VIEW.basis,
    columns: params.has("col") ? withLocked(columns) : [...DEFAULT_VIEW.columns],
    filters,
    sort,
    currency: CURRENCY.test(currency) ? currency : null,
  };
}
