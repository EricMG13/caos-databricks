// The run input's command form (N159, D109): the derived CP-2G scope shown
// before the pin, the client's mirror of the server's grammars, and the
// request body the form maps onto `qualifiers` and `objective`.
import {
  EMPTY_COMMAND_FORM,
  NO_COMMAND,
  commandErrors,
  derivedScope,
  runCommand,
} from "@/sections/run/command";

const BOTH = { forecast: true, objective: true };

describe("the derived CP-2G scope (D109)", () => {
  test("derivedScope follows the owner's rule from the reporting period", () => {
    expect(derivedScope("Q2 2026")).toEqual({
      forecast_horizon: "FY2026-FY2028",
      base_period: "Q2 2026 LTM",
    });
    expect(derivedScope("Q2-26")).toEqual({
      forecast_horizon: "FY2026-FY2028",
      base_period: "Q2 2026 LTM",
    });
    expect(derivedScope("Q4 2025")).toEqual({
      forecast_horizon: "FY2026-FY2028",
      base_period: "FY2025",
    });
    expect(derivedScope("FY 2025")).toEqual({
      forecast_horizon: "FY2026-FY2028",
      base_period: "FY2025",
    });
    expect(derivedScope("FY25")).toEqual({
      forecast_horizon: "FY2026-FY2028",
      base_period: "FY2025",
    });
  });

  test("a period the rule cannot read derives nothing", () => {
    for (const period of ["", "2025", "FY2025Q4", "Q5 2026", "FY1899", "H1 2026"]) {
      expect(derivedScope(period)).toBeNull();
    }
  });
});

describe("the command the form sends", () => {
  test("an empty form is no command: qualifiers [] and objective null", () => {
    expect(NO_COMMAND).toEqual({ qualifiers: [], objective: null });
    expect(runCommand(EMPTY_COMMAND_FORM, BOTH)).toEqual({ qualifiers: [], objective: null });
    expect(commandErrors(EMPTY_COMMAND_FORM, BOTH)).toEqual({});
  });

  test("only what the user filled is sent, in the wire's qualifier shape", () => {
    const form = {
      horizon: " FY26-FY28 ",
      base: "",
      cases: "Base/Downside",
      objective: "Size a senior secured position.",
    };
    expect(runCommand(form, BOTH)).toEqual({
      qualifiers: [
        { module_id: "CP-2G", name: "forecast_horizon", value: "FY26-FY28" },
        { module_id: "CP-2G", name: "cases", value: "Base/Downside" },
      ],
      objective: "Size a senior secured position.",
    });
  });

  test("a module the route does not carry is never addressed", () => {
    const form = { horizon: "FY2026-FY2028", base: "FY2025", cases: "Base", objective: "Aim" };
    expect(runCommand(form, { forecast: false, objective: false })).toEqual(NO_COMMAND);
    expect(runCommand(form, { forecast: false, objective: true })).toEqual({
      qualifiers: [],
      objective: "Aim",
    });
    expect(
      commandErrors({ ...form, horizon: "bad" }, { forecast: false, objective: true }),
    ).toEqual({});
  });
});

describe("the client checks what the server checks", () => {
  test("commandErrors names each field the server's grammar would refuse", () => {
    const errors = commandErrors(
      {
        horizon: "FY2028-FY2026",
        base: "Q5 2026 LTM",
        cases: "Base 1",
        objective: "bad [bracket]",
      },
      BOTH,
    );
    expect(Object.keys(errors).sort()).toEqual(["base", "cases", "horizon", "objective"]);
  });

  test("the accepted spellings pass", () => {
    const form = {
      horizon: "FY2026-FY2028",
      base: "Q1 2026 LTM",
      cases: "Base / Downside-case",
      objective: "Is the pack ready for a $50m 5-year loan, 2026.",
    };
    expect(commandErrors(form, BOTH)).toEqual({});
    expect(commandErrors({ ...form, horizon: "FY26-FY28", base: "FY2025" }, BOTH)).toEqual({});
  });

  test("a decomposed accent passes and is sent composed, as the server composes first", () => {
    const decomposed = "Re\u0301sume\u0301 the credit";
    const form = { ...EMPTY_COMMAND_FORM, objective: decomposed };
    expect(commandErrors(form, BOTH)).toEqual({});
    expect(runCommand(form, BOTH).objective).toBe(decomposed.normalize("NFC"));
  });

  test("a value longer than the wire, or over two lines, is refused", () => {
    expect(
      commandErrors({ ...EMPTY_COMMAND_FORM, objective: "a".repeat(1025) }, BOTH),
    ).toHaveProperty("objective");
    expect(commandErrors({ ...EMPTY_COMMAND_FORM, objective: "a\nb" }, BOTH)).toHaveProperty(
      "objective",
    );
    expect(commandErrors({ ...EMPTY_COMMAND_FORM, cases: "a".repeat(65) }, BOTH)).toHaveProperty(
      "cases",
    );
  });
});
