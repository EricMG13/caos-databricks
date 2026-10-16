// The run input's command (N159, D109): what the workspace may state above the
// evidence, mapped onto the existing `PinRunInput` wire -- CP-2G's
// `forecast_horizon`, `base_period` and `cases` as `qualifiers`, and CP-0's
// `objective`. The server (`caos/methodology/qualifiers.py`) is the authority:
// this mirrors its grammars so a value it would refuse is named before the
// pin, and anything else it refuses comes back as a typed refusal.

export const FORECAST_MODULE = "CP-2G";

/** What the form holds; an empty string is "not stated". */
export interface CommandForm {
  horizon: string;
  base: string;
  cases: string;
  objective: string;
}

/** The modules the pinned route carries; a command for a module the route
    does not carry is refused by the server, so it is never offered. */
export interface CommandRoute {
  forecast: boolean;
  objective: boolean;
}

/** The two request fields the form owns. */
export interface RunCommand {
  qualifiers: { module_id: string; name: string; value: string }[];
  objective: string | null;
}

export const EMPTY_COMMAND_FORM: CommandForm = { horizon: "", base: "", cases: "", objective: "" };
export const NO_COMMAND: RunCommand = { qualifiers: [], objective: null };

export type CommandErrors = Partial<Record<keyof CommandForm, string>>;

const TEXT_BYTES = 1024;
const PERIOD = /^(?:FY ?|Q([1-4])[ -])(\d{4}|\d{2})$/;
const FY_RANGE = /^FY(\d{4})-FY(\d{4})$/;
const FY_SHORT_RANGE = /^FY(\d{2})-FY(\d{2})$/;
const BASE = /^(?:Q[1-4] \d{4} LTM|FY\d{4})$/;
const CASES = /^[A-Za-z/ -]{1,64}$/;
// Letters, digits, the ASCII space and this punctuation (the server's closed
// allow-list for the one free-text value).
const OBJECTIVE = /^[\p{L}\p{N}.,;:'"\-\u2013\u2014/&%$ ]+$/u;

/** CP-2G's forecast scope by the owner's rule (D109) from the latest reporting
    period, or null when the rule cannot read it. After Q1 to Q3 of year Y the
    horizon is FY(Y) to FY(Y+2) on the LTM to that quarter; after Q4 or a
    fiscal year Y it is FY(Y+1) to FY(Y+3) on that fiscal year. */
export function derivedScope(
  reportingPeriod: string,
): { forecast_horizon: string; base_period: string } | null {
  const matched = PERIOD.exec(reportingPeriod);
  if (matched === null) return null;
  const digits = matched[2]!;
  const year = digits.length === 2 ? 2000 + Number(digits) : Number(digits);
  if (year < 1900 || year > 2999) return null;
  const quarter = matched[1];
  if (quarter !== undefined && quarter !== "4") {
    return { forecast_horizon: `FY${year}-FY${year + 2}`, base_period: `Q${quarter} ${year} LTM` };
  }
  return { forecast_horizon: `FY${year + 1}-FY${year + 3}`, base_period: `FY${year}` };
}

function validHorizon(value: string): boolean {
  const matched = FY_RANGE.exec(value) ?? FY_SHORT_RANGE.exec(value);
  return matched !== null && matched[1]! <= matched[2]!;
}

function oneLine(value: string): boolean {
  return (
    !/[\r\n\u2028\u2029\t]/.test(value) &&
    value === value.normalize("NFC") &&
    new TextEncoder().encode(value).length <= TEXT_BYTES
  );
}

/** The wording the form shows for a value the server's grammar refuses. */
export function commandErrors(form: CommandForm, route: CommandRoute): CommandErrors {
  const errors: CommandErrors = {};
  const check = (
    key: keyof CommandForm,
    offered: boolean,
    ok: (value: string) => boolean,
    message: string,
  ) => {
    const value = form[key].trim();
    if (offered && value !== "" && !(oneLine(value) && ok(value))) errors[key] = message;
  };
  check(
    "horizon",
    route.forecast,
    validHorizon,
    "Write the horizon as a range of fiscal years that does not end before it starts, such as FY2026-FY2028.",
  );
  check(
    "base",
    route.forecast,
    (value) => BASE.test(value),
    "Write the base period as a fiscal year or a quarter's last twelve months, such as FY2025 or Q2 2026 LTM.",
  );
  check(
    "cases",
    route.forecast,
    (value) => CASES.test(value),
    "Cases take letters, spaces, hyphens and slashes only, up to 64 characters.",
  );
  check(
    "objective",
    route.objective,
    (value) => OBJECTIVE.test(value),
    "The objective takes letters, digits and plain punctuation (. , ; : - / & % $ and quotes) on one line, up to 1,024 bytes; no brackets.",
  );
  return errors;
}

/** The request fields for `form`: only what the user stated, only for a module
    the route carries. An empty form is `NO_COMMAND` (`qualifiers: []`,
    `objective: null`), so the host derives the scope as it always has. */
export function runCommand(form: CommandForm, route: CommandRoute): RunCommand {
  const qualifiers: RunCommand["qualifiers"] = [];
  if (route.forecast) {
    const stated: [string, string][] = [
      ["forecast_horizon", form.horizon],
      ["base_period", form.base],
      ["cases", form.cases],
    ];
    for (const [name, raw] of stated) {
      const value = raw.trim();
      if (value !== "") qualifiers.push({ module_id: FORECAST_MODULE, name, value });
    }
  }
  const objective = route.objective ? form.objective.trim() : "";
  return { qualifiers, objective: objective === "" ? null : objective };
}
