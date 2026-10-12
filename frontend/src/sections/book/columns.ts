// The Book's column vocabulary (spec B12): which identifiers exist, what each
// column is called, and which unit a metric column is read in. Pure.
import type { BookMetricView } from "@/wire/v1";
import { metricOf } from "./filter";
import type { Agency, Basis, ColumnKey, IdentifierKey } from "./view";

export type Unit = Pick<BookMetricView, "line_id" | "label" | "unit">;

export const BASIS_LABELS: Record<Basis, string> = {
  LTM: "LTM",
  PF_LTM: "PF LTM",
  BASE_FY1: "Base FY1",
  DOWNSIDE_FY1: "Downside FY1",
};
export const BASES: readonly Basis[] = ["LTM", "PF_LTM", "BASE_FY1", "DOWNSIDE_FY1"];

export const IDENTIFIER_LABELS: Record<IdentifierKey, string> = {
  issuer_name: "Issuer",
  reporting_period: "Reporting period",
  issuer_id: "Issuer ID",
  sector: "Sector",
  industry_group: "Industry group",
  domicile: "Domicile",
  composite: "Composite",
  composite_bucket: "Composite bucket",
  moodys: "Moody's",
  moodys_outlook: "Moody's outlook",
  sp: "S&P",
  sp_outlook: "S&P outlook",
  fitch: "Fitch",
  fitch_outlook: "Fitch outlook",
  analysis_date: "Analysis date",
  route: "Route",
  filed: "Filed",
  currency: "Currency",
  unit: "Unit",
  fiscal_year_base_fy1: "Fiscal year · Base FY1",
  fiscal_year_downside_fy1: "Fiscal year · Downside FY1",
  case: "Case",
};
export const IDENTIFIERS = Object.keys(IDENTIFIER_LABELS) as IdentifierKey[];

/** The agency a rating column belongs to, or null for any other column. */
export function agencyOf(column: ColumnKey): Agency | null {
  const name = column.slice(3);
  return column.startsWith("id:") && (name === "moodys" || name === "sp" || name === "fitch")
    ? name
    : null;
}

/** A lookup from a metric column to its catalogue entry, built once per catalogue. */
export function unitLookup(units: readonly Unit[]): (column: ColumnKey) => Unit | undefined {
  const byId = new Map(units.map((unit) => [unit.line_id, unit]));
  return (column) => {
    if (!column.startsWith("m:")) return undefined;
    return byId.get(metricOf(column, "LTM")?.lineId ?? "");
  };
}

/** The catalogue entry a metric column reads, or undefined. */
export function unitOf(column: ColumnKey, units: readonly Unit[]): Unit | undefined {
  return unitLookup(units)(column);
}

/** A column's name: "Domicile", "Total revenue" (follows the basis switch), or
    "Total revenue · Base FY1" (pinned to a basis). */
export function columnLabel(column: ColumnKey, units: readonly Unit[]): string {
  if (column.startsWith("id:")) return IDENTIFIER_LABELS[column.slice(3) as IdentifierKey];
  const label = unitOf(column, units)?.label ?? column.slice(2).replace(/@.*$/, "");
  const at = column.lastIndexOf("@");
  return at < 0 ? label : `${label} · ${BASIS_LABELS[column.slice(at + 1) as Basis]}`;
}
