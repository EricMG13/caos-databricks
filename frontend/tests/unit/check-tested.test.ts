// The untested-definition gate's own rules, asserted where the `typescript` it
// imports is installed. The Python half asserts the *agreement* between the two
// by reading this file's EXEMPT (tests/test_gate_scripts.py); the CI `test` job
// never runs `npm ci`, so driving this gate from there would assert whether
// node_modules happened to be present.
import { EXEMPT, names, publicExports } from "../../scripts/check-tested.mjs";

const at = (source: string, file = "m.ts") => publicExports(source, file).map((e) => e.name);

describe("what the gate counts as a public export", () => {
  test("module-level functions, classes and consts, exported only", () => {
    expect(
      at(
        [
          "export function shown(): void {}",
          "function hidden(): void {}",
          "export class Shown {}",
          "export const value = 1;",
          "const unexported = 2;",
        ].join("\n"),
      ),
    ).toEqual(["shown", "Shown", "value"]);
  });

  test("a method is covered through the class that holds it", () => {
    // The Python half's rule, kept: `check_tested.py` sees module-level
    // definitions only and covers a method through its class.
    expect(at("export class Ledger {\n  append(): void {}\n}")).toEqual(["Ledger"]);
  });

  test("an interface and a type alias are erased, so neither is asked for", () => {
    // `tsc --noEmit` checks them at every use site, which is stronger than a
    // mention in a test file.
    expect(at("export interface Chrome {\n  rail: string;\n}\nexport type Grade = 'A';")).toEqual(
      [],
    );
  });

  test("a component is covered through the section that composes it", () => {
    // PascalCase in a .tsx file, and only there: the same name in a .ts file
    // is an ordinary export and is asked for.
    expect(at("export function RouteGraph(): null {\n  return null;\n}", "m.tsx")).toEqual([]);
    expect(at("export function severityOf(): number {\n  return 1;\n}", "m.tsx")).toEqual([
      "severityOf",
    ]);
    expect(at("export class Ledger {}", "m.ts")).toEqual(["Ledger"]);
  });

  test("`main` is exempt, because running a script names the file not the symbol", () => {
    expect(EXEMPT.has("main")).toBe(true);
    expect(at("export function main(): void {}")).toEqual([]);
  });

  test("several declarations in one export statement are each asked for", () => {
    expect(at("export const first = 1,\n  second = 2;")).toEqual(["first", "second"]);
  });
});

describe("what the gate counts as a test naming an export", () => {
  test("a whole word, and never one buried in a longer one", () => {
    expect(names("it('run', () => run())", "run")).toBe(true);
    // Adjacent punctuation is a boundary, so an import names it.
    expect(names("import { run } from '@/x';", "run")).toBe(true);
    expect(names("the runner runs", "run")).toBe(false);
    expect(names("prerun", "run")).toBe(false);
    // `$` is a word character in an identifier.
    expect(names("run$", "run")).toBe(false);
    expect(names("", "run")).toBe(false);
  });
});
