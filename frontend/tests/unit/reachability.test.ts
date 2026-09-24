// The application entry point is the only root. A component under
// `src/sections/` that nothing reachable from `src/main.tsx` imports is dead
// even when a test names it -- the test is what keeps it alive, and the
// untested-definition gate cannot tell that case from a covered one. This is
// the rule `frontend/scripts/check-tested.mjs` enforces in `npm run lint`;
// here it is asserted where the `typescript` it imports is installed.
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import { importGraph, unreachable } from "../../scripts/check-tested.mjs";

const SRC = resolve(process.cwd(), "src");

function components(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(directory, entry.name);
    if (entry.isDirectory()) return components(full);
    return entry.name.endsWith(".tsx") ? [full] : [];
  });
}

test("test_every_component_under_sections_is_reachable_from_main", () => {
  const graph = importGraph(resolve(SRC, "main.tsx"), SRC);
  const unreachable = components(resolve(SRC, "sections"))
    .filter((file) => !graph.has(file))
    .map((file) => relative(SRC, file));
  expect(unreachable).toEqual([]);
});

test("the graph follows `@/` and relative specifiers alike, and stops at a file it cannot resolve", () => {
  const graph = importGraph(resolve(SRC, "main.tsx"), SRC);
  expect(graph.has(resolve(SRC, "app/App.tsx"))).toBe(true);
  expect(graph.has(resolve(SRC, "chrome/AppSidebar.tsx"))).toBe(true);
  expect(graph.has(resolve(SRC, "styles/caos.css"))).toBe(true);
  expect(importGraph(resolve(SRC, "does-not-exist.tsx"), SRC).size).toBe(0);
});

test("a type-only import does not reach: the bundler erases it, so the file ships nothing", () => {
  const root = mkdtempSync(join(tmpdir(), "reach-"));
  mkdirSync(join(root, "sections"), { recursive: true });
  writeFileSync(
    join(root, "sections", "Planted.tsx"),
    "export function Planted() { return null; }\n",
  );
  writeFileSync(join(root, "sections", "Live.tsx"), "export function Live() { return null; }\n");
  writeFileSync(
    join(root, "main.tsx"),
    'import type { Planted } from "@/sections/Planted";\nimport { Live } from "./sections/Live";\nexport { Live };\nexport type { Planted };\n',
  );
  // A types-only module is erased whole, so it is reached by nothing and
  // ships nothing: not a finding.
  writeFileSync(join(root, "sections", "types.ts"), "export interface Shape {\n  id: string;\n}\n");
  const graph = importGraph(join(root, "main.tsx"), root);
  expect(graph.has(join(root, "sections", "Live.tsx"))).toBe(true);
  expect(graph.has(join(root, "sections", "Planted.tsx"))).toBe(false);
  const files = ["Live.tsx", "Planted.tsx", "types.ts"].map((name) => join(root, "sections", name));
  expect(unreachable(files, root)).toEqual([join(root, "sections", "Planted.tsx")]);
  rmSync(root, { recursive: true, force: true });
});

test("a literal dynamic import reaches its chunk; a computed one reaches nothing (N65)", () => {
  const root = mkdtempSync(join(tmpdir(), "reach-"));
  mkdirSync(join(root, "sections"), { recursive: true });
  for (const name of ["Lazy", "Computed"]) {
    writeFileSync(
      join(root, "sections", `${name}.tsx`),
      `export function ${name}() { return null; }\n`,
    );
  }
  writeFileSync(
    join(root, "main.tsx"),
    'const name = "Computed";\n' +
      'export const lazy = () => import("@/sections/Lazy").then((m) => m.Lazy);\n' +
      "export const computed = () => import(`./sections/${name}`);\n",
  );
  const graph = importGraph(join(root, "main.tsx"), root);
  expect(graph.has(join(root, "sections", "Lazy.tsx"))).toBe(true);
  expect(graph.has(join(root, "sections", "Computed.tsx"))).toBe(false);
  rmSync(root, { recursive: true, force: true });
});

// Admin is unavailable in every mode (`src/app/sections.ts`), and on
// 17 September 2026 the owner decided to reduce it and the Book to the shell
// `tests/workbench/chrome.spec.ts` asserts rather than keep implementations
// nothing mounts. Their legacy wire types went with them. The walk above
// cannot see this on its own: an `import type` is erased, so a retired wire
// module is unreachable and still shipped as a file, and a reduction that left
// one importer behind would compile clean. This is what says the deletion was
// complete rather than merely compiling.
// Both spellings of each: `src/wire/index.ts` reached its two by a relative
// specifier, so a list of `@/` paths alone would have read clean over two live
// importers. No other `book` or `admin` wire module exists under `src/`.
// `@/app/ledger` left this list in Task 12.3, which served the Book a v1
// document and gave the snapshot ledger its caller back.
const RETIRED = [
  ["@/wire/book", "./book"],
  ["@/wire/admin", "./admin"],
];

function typescriptSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(directory, entry.name);
    if (entry.isDirectory()) return typescriptSources(full);
    return /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

// `RETIRED` below is a list, and a list only sees what somebody wrote into it.
// The rule beside it is the general form, and it is the graph rather than a
// text match: a raw `source.includes("@/wire/x")` is satisfied by a comment, a
// string literal, or a second orphan naming the first, none of which ships
// anything. The audit that closed the audit remediation found exactly that in
// the first version of this test, and found the walk it was compensating for
// scoped to two directories of eight while its message claimed `src/`.
//
// `unreachable` now walks all of `src/` from `main.tsx`, and `shipsNothing` is
// what makes that safe: a file of pure types is erased whole, so it cannot be
// dead shipped code. Nothing under `src/` is unreachable today.
test("test_no_file_under_src_is_unreachable_from_the_entry_point", () => {
  const files = typescriptSources(SRC);
  expect(unreachable(files, SRC).map((file: string) => relative(SRC, file))).toEqual([]);
});

test("nothing under src/ imports the retired Book and Admin modules", () => {
  const importers = typescriptSources(SRC).flatMap((file) => {
    const source = readFileSync(file, "utf8");
    return RETIRED.filter((spellings) =>
      spellings.some((spelling) => source.includes(`"${spelling}"`)),
    ).map(([module]) => `${relative(SRC, file)} imports ${module}`);
  });
  expect(importers).toEqual([]);
});
