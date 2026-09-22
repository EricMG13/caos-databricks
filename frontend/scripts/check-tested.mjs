#!/usr/bin/env node
// Refuse a public TypeScript export that no test names — the TypeScript half of
// scripts/check_tested.py, with the same two scope rules so the two halves
// enforce one thing rather than two.
//
//   *Module-level exports only.* A method is covered through the type that
//   holds it, exactly as check_tested.py covers one through its class.
//   *Runtime exports only.* An `interface` or a `type` is erased before
//   anything runs, so there is no behaviour for a test to assert and no
//   symbol for it to reach; what checks them is `tsc --noEmit` at every use
//   site, on every one, which is stronger than a mention in a test file. This
//   is the exemption check_tested.py's EXEMPT makes for `main`, for the one
//   other kind of export that has nothing to assert.
//   *Components are covered through the section that composes them.* A React
//   component is reached by rendering, not by importing it under its name, so
//   the whole-word rule does not transfer: the unit suite names the section
//   and the workbench drives all nine over every fixture state. Demanding a
//   mention per component would buy shallow render tests, which is worse than
//   the section-level tests that exist. This is check_tested.py's own "a
//   method is covered through the class that holds it", one layer out.
//   *Named is mentioned.* A name is named when the test sources carry it as a
//   whole word — docstrings, comments and imports included. This catches the
//   export no test mentions, not the export whose test asserts nothing, which
//   is the same limit the Python half records in CLAUDE.md's ledger. It is a
//   little looser here for one TypeScript reason: a module specifier carries
//   the module's stem, so an export named exactly after its own file is named
//   by any import of that file. `sev` in `@/ds/sev` is the shape. Worth
//   knowing before reading a clean run as proof.
//   *A section file must be reachable from the entry point.* The rule above
//   has a hole the first three cannot see: a test can name an export whose
//   file nothing in `src/` imports, and the file then lives on to satisfy
//   this gate and for no other reason -- eight components did, for months,
//   behind three such tests. So every file under `src/sections/` must sit on
//   the static import graph walked from `src/main.tsx`; one that only a test
//   reaches, or only another unreachable file reaches, is refused here. Only
//   `src/sections/` is held to it: a `ds/` atom or a `wire/` type may be
//   built ahead of the section that composes it, a section may not.
//
// tests/unit/reachability.test.ts and tests/unit/check-tested.test.ts assert
// the rules where the `typescript` they need is installed; tests/test_gate_scripts.py
// reads EXEMPT and the lint wiring from here.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { resolveGit } from "./git.mjs";

// Resolved on call, not at import: the rules below are pure and a test that
// imports them for those rules should not have to be running from a file URL.
function repo() {
  return resolve(fileURLToPath(new URL("../..", import.meta.url)));
}

// Entry points are exercised by running the file, which names the file rather
// than the symbol — the reason check_tested.py exempts `main`.
export const EXEMPT = new Set(["main", "default"]);

// The names a source file exports at module level.
export function publicExports(source, filename) {
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  const found = [];
  for (const statement of tree.statements) {
    const exported = ts.canHaveModifiers(statement)
      ? (ts.getModifiers(statement) ?? []).some(
          (modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword,
        )
      : false;
    if (!exported) continue;
    for (const name of declaredNames(statement)) {
      if (EXEMPT.has(name) || isComponent(filename, name)) continue;
      found.push({ line: lineOf(tree, statement), name });
    }
  }
  return found;
}

// PascalCase in a `.tsx` file is this repository's component convention
// without exception: see the "covered through the section" rule above.
function isComponent(filename, name) {
  return filename.endsWith(".tsx") && /^[A-Z]/.test(name);
}

function declaredNames(statement) {
  // Erased at compile time: see the "runtime exports only" rule above.
  if (ts.isInterfaceDeclaration(statement) || ts.isTypeAliasDeclaration(statement)) {
    return [];
  }
  if (ts.isVariableStatement(statement)) {
    return statement.declarationList.declarations.flatMap((declaration) =>
      ts.isIdentifier(declaration.name) ? [declaration.name.text] : [],
    );
  }
  return statement.name && ts.isIdentifier(statement.name) ? [statement.name.text] : [];
}

function lineOf(tree, node) {
  return tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
}

// A name is named when it appears as a whole word. Built by scanning rather
// than with `\b${name}\b` so a name carrying a regex metacharacter cannot
// change what is searched for.
export function names(haystack, name) {
  for (let at = haystack.indexOf(name); at !== -1; at = haystack.indexOf(name, at + 1)) {
    if (!isWordChar(haystack[at - 1]) && !isWordChar(haystack[at + name.length])) {
      return true;
    }
  }
  return false;
}

function isWordChar(character) {
  return character !== undefined && /[A-Za-z0-9_$]/.test(character);
}

function tracked(root, patterns) {
  const out = execFileSync(resolveGit(), ["ls-files", "-z", "--", ...patterns], {
    cwd: repo(),
    encoding: "utf8",
  });
  return out
    .split("\0")
    .filter(Boolean)
    .map((file) => resolve(repo(), file))
    .filter((file) => existsSync(file));
}

// Under `--root` the tree is fabricated and git knows nothing about it, so the
// files are walked. The real run reads what git tracks, for the reason
// scripts/tracked.py states: .gitignore already answers "is this ours".
function sources(root) {
  if (root) return walk(join(root, "src"), [".ts", ".tsx"]);
  return tracked(root, ["frontend/src/**/*.ts", "frontend/src/**/*.tsx"]);
}

// Walked from disk, never asked of git -- `check_tested.py` reads its haystack
// with `tests_dir.rglob` for the same reason: a test file written a minute ago
// and not yet staged still covers the export it names, and a gate that said
// otherwise would refuse the change that fixes it.
function testSources(root) {
  return walk(join(root ?? join(repo(), "frontend"), "tests"), [".ts", ".tsx"]);
}

function walk(directory, suffixes) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) return walk(full, suffixes);
    return suffixes.some((suffix) => entry.name.endsWith(suffix)) ? [full] : [];
  });
}

// A bare specifier is a package, which is never a file of ours; a `@/` one is
// rooted at `src` (tsconfig `paths`); a relative one at the importer. The
// extension is tried the way the bundler tries it, an index file last.
function resolveSpecifier(importer, specifier, src) {
  let base;
  if (specifier.startsWith("@/")) base = join(src, specifier.slice(2));
  else if (specifier.startsWith(".")) base = resolve(dirname(importer), specifier);
  else return null;
  const candidates = [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ];
  for (const candidate of candidates) {
    try {
      if (statSync(candidate).isFile()) return candidate;
    } catch {
      // not this spelling; try the next
    }
  }
  return null;
}

// Every file the static import graph reaches from `entry`, `entry` included
// -- `import` and `export ... from`, never `import type` or `export type`:
// the bundler erases a type-only import, so a file only a type reaches ships
// nothing and is exactly what this rule is for. A specifier that resolves to
// nothing is left to `tsc`, which refuses it with a better message. Only
// TypeScript files are parsed; a stylesheet or JSON file is reached and
// stops there.
export function importGraph(entry, src) {
  const reached = new Set();
  const pending = [resolve(entry)];
  while (pending.length) {
    const file = pending.pop();
    if (reached.has(file) || !existsSync(file)) continue;
    reached.add(file);
    if (!/\.tsx?$/.test(file)) continue;
    const tree = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
    );
    for (const statement of tree.statements) {
      const specifier =
        (ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)) &&
        statement.moduleSpecifier;
      if (!specifier || !ts.isStringLiteral(specifier)) continue;
      const typeOnly = ts.isImportDeclaration(statement)
        ? (statement.importClause?.isTypeOnly ?? false)
        : statement.isTypeOnly;
      if (typeOnly) continue;
      const target = resolveSpecifier(file, specifier.text, src);
      if (target) pending.push(target);
    }
  }
  return reached;
}

// A file that declares only interfaces, type aliases and type-only imports or
// re-exports is erased whole: it ships nothing, so it cannot be dead shipped
// code, and `tsc` checks it at every use site (the "runtime exports only"
// rule above, applied to a whole file). `run/types.ts` is the shape.
export function shipsNothing(source, filename) {
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  return tree.statements.every(
    (statement) =>
      ts.isInterfaceDeclaration(statement) ||
      ts.isTypeAliasDeclaration(statement) ||
      (ts.isImportDeclaration(statement) && (statement.importClause?.isTypeOnly ?? false)) ||
      (ts.isExportDeclaration(statement) && statement.isTypeOnly),
  );
}

// Every file the entry point cannot reach: the "reachable from the entry
// point" rule above, over the files the export scan already holds.
//
// This was scoped to `src/sections/` until the audit that closed the audit
// remediation measured it: two directories of eight, 27 of 66 files, and a
// message that claimed `src/` while inspecting one folder. The three wire
// modules that wave deleted were exactly the class it could not see, because a
// wire module is not a component. `shipsNothing` is what makes the wider scope
// safe -- a file of pure types is erased whole and so cannot be dead shipped
// code, which is why widening flags nothing that was already honest.
export function unreachable(files, src) {
  const reached = importGraph(join(src, "main.tsx"), src);
  return files.filter(
    (file) => !reached.has(file) && !shipsNothing(readFileSync(file, "utf8"), file),
  );
}

function main(argv) {
  const at = argv.indexOf("--root");
  const root = at === -1 ? null : argv[at + 1];

  const files = sources(root);
  if (files.length === 0) {
    console.error("scanned no files; a scan that scanned nothing is a failure");
    return 2;
  }
  const haystack = testSources(root)
    .map((file) => readFileSync(file, "utf8"))
    .join("\n");

  const found = [];
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    for (const { line, name } of publicExports(source, file)) {
      if (!names(haystack, name)) {
        found.push(`${file}:${line}: '${name}' has no test naming it`);
      }
    }
  }
  const src = root ? join(root, "src") : join(repo(), "frontend", "src");
  for (const file of unreachable(files, src)) {
    found.push(`${file}: unreachable from src/main.tsx; nothing in src/ imports it`);
  }
  for (const line of found) console.log(line);
  console.error(`tested: ${files.length} files, ${found.length} findings`);
  return found.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
