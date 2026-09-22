// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  bannedTerms,
  identifiers,
  normalise,
  violations,
} from "../../scripts/check-vocabulary.mjs";
import ts from "typescript";

const CONTEXT = readFileSync(
  fileURLToPath(new URL("../../../CONTEXT.md", import.meta.url)),
  "utf8",
);
const BANNED = bannedTerms(CONTEXT);

function names(text: string): string[] {
  return identifiers(
    ts.createSourceFile("m.tsx", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX),
  ).map(([, name]: [number, string]) => name);
}

describe("the TypeScript vocabulary gate", () => {
  test("reads camel case as words and folds plurals", () => {
    expect(normalise("loadDealChunks")).toBe("load_deal_chunks");
    const found = violations("m.ts", "function loadDealChunks() {}\n", BANNED);
    expect(found.map((line: string) => line.split("use ")[1])).toEqual(["'case'", "'block'"]);
  });

  test("ignores prose, string literals and JSX text", () => {
    const found = violations(
      "m.tsx",
      'const DOC = "the deal chunk";\nexport const view = <p title="pipeline">workflow</p>;\n',
      BANNED,
    );
    expect(found).toEqual([]);
    expect(names('const DOC = "the deal chunk";')).toEqual(["DOC"]);
  });

  test("examines declarations, properties, aliases, bindings and relative specifiers", () => {
    const text = [
      'import chunker from "./chunker";',
      'import { y as fragmentReader } from "./x";',
      "interface Row { footnote: string }",
      "const { passage } = row;",
      "const o = { corpus: 1 };",
      'const view = <div data-workflow="x" />;',
    ].join("\n");
    expect(names(text)).toEqual(
      expect.arrayContaining([
        "chunker",
        "chunker",
        "fragmentReader",
        "footnote",
        "passage",
        "corpus",
        "data-workflow",
      ]),
    );
    // `chunker` is not `chunk`: whole words and their plural only, as in the Python gate.
    expect(violations("m.tsx", text, BANNED)).toHaveLength(5);
  });

  test("reads attribute stores, accessors, labels and namespaced JSX names", () => {
    const text = [
      "obj.workflow = 1;",
      "class C { get pipeline() { return 1; } }",
      "const view = <svg xlink:chunk='x' />;",
    ].join("\n");
    expect(names(text)).toEqual(expect.arrayContaining(["workflow", "pipeline", "xlink_chunk"]));
    expect(violations("m.mjs", "export const deal = 1;\n", BANNED)).toHaveLength(1);
  });

  test("reads the file stem and the ready_set substring", () => {
    expect(violations("deal_store.ts", "export const x = 1;\n", BANNED)[0]).toContain("'case'");
    expect(violations("m.ts", "const readySet = [];\n", BANNED)[0]).toContain("'frontier'");
  });
});
