#!/usr/bin/env node
// Refuse a TypeScript identifier that spells a CONTEXT.md term by one of its
// synonyms — the TypeScript half of scripts/check_vocabulary.py, with the same
// word rules (camelCase split, plural fold, `ready_set` as a substring).
// Only identifiers are examined: declaration names, object and JSX property
// names, import/export aliases, relative module specifiers and the file stem.
// Never prose, string literals or JSX text. tests/test_vocabulary_rules.py
// asserts ENFORCED below equals the Python gate's.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { resolveGit } from "./git.mjs";

export const ENFORCED = [
  "deal",
  "corpus",
  "chunk",
  "fragment",
  "passage",
  "footnote",
  "pipeline",
  "workflow",
  "ready_set",
  "benchmark",
  "golden_set",
];

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

// Lower-to-upper and acronym-to-word transitions, found by hand rather than a
// lookbehind+lookahead regex — SonarQube flags that shape as super-linear
// (javascript:S8786) though it holds no quantifier to backtrack on; a
// char-code scan reads the same and draws no such flag.
function isLowerOrDigit(code) {
  return (code >= 97 && code <= 122) || (code >= 48 && code <= 57); // a-z, 0-9
}
function isUpper(code) {
  return code >= 65 && code <= 90; // A-Z
}
function isLower(code) {
  return code >= 97 && code <= 122; // a-z
}

export function normalise(phrase) {
  let spaced = "";
  for (let i = 0; i < phrase.length; i += 1) {
    const code = phrase.charCodeAt(i);
    const previous = i > 0 ? phrase.charCodeAt(i - 1) : -1;
    const next = i + 1 < phrase.length ? phrase.charCodeAt(i + 1) : -1;
    // A run of capitals ("HTTP") followed by a capitalised word ("Response")
    // never crossed a lower-to-upper boundary, so "HTTPResponse" stayed one
    // token and a banned word spelled after an acronym went unenforced.
    const acronymThenWord = isUpper(code) && isUpper(previous) && isLower(next);
    if (i > 0 && isUpper(code) && (isLowerOrDigit(previous) || acronymThenWord)) {
      spaced += "_";
    }
    spaced += phrase[i];
  }
  return trimUnderscores(spaced.toLowerCase().replace(/[^a-z0-9]+/g, "_"));
}

// Leading/trailing "_" trimmed by hand rather than `/^_+|_+$/` — the same
// anchor-adjacent-quantifier shape already replaced above and in
// sections.ts/ReportSection.tsx (javascript/typescript:S8786).
function trimUnderscores(value) {
  let start = 0;
  let end = value.length;
  while (start < end && value[start] === "_") start += 1;
  while (end > start && value[end - 1] === "_") end -= 1;
  return value.slice(start, end);
}

/** Synonym token → the term it displaces, from CONTEXT.md's Domain table. */
export function bannedTerms(contextMd) {
  const banned = {};
  for (const line of contextMd.split("\n")) {
    const cells = line
      .trim()
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim());
    if (cells.length !== 3 || !cells[0].startsWith("**")) continue;
    const term = cells[0].replace(/\*/g, "");
    for (const phrase of cells[2].split(",")) {
      const token = normalise(phrase);
      if (token) banned[token] = term;
    }
  }
  return banned;
}

function nameOf(node) {
  if (node && (ts.isIdentifier(node) || ts.isPrivateIdentifier(node))) return node.text;
  if (node && ts.isJsxNamespacedName(node)) return `${node.namespace.text}_${node.name.text}`;
  return null; // a quoted key or a computed name is not an identifier
}

const DECLARATIONS = [
  ts.isVariableDeclaration,
  ts.isFunctionDeclaration,
  ts.isClassDeclaration,
  ts.isInterfaceDeclaration,
  ts.isTypeAliasDeclaration,
  ts.isEnumDeclaration,
  ts.isEnumMember,
  ts.isParameter,
  ts.isPropertySignature,
  ts.isPropertyDeclaration,
  ts.isMethodDeclaration,
  ts.isMethodSignature,
  ts.isPropertyAssignment,
  ts.isShorthandPropertyAssignment,
  ts.isBindingElement,
  ts.isImportSpecifier,
  ts.isExportSpecifier,
  ts.isNamespaceImport,
  ts.isImportClause,
  ts.isTypeParameterDeclaration,
  ts.isJsxAttribute,
  ts.isGetAccessorDeclaration,
  ts.isSetAccessorDeclaration,
  ts.isFunctionExpression,
  ts.isClassExpression,
  ts.isModuleDeclaration,
];

/** Every name a source file defines, with its line. */
export function identifiers(source) {
  const found = [];
  const lineOf = (node) => source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
  const visit = (node) => {
    if (DECLARATIONS.some((is) => is(node))) {
      const name = nameOf(node.name);
      if (name) found.push([lineOf(node.name), name]);
    }
    // `obj.workflow = 1` defines a name as surely as a declaration does.
    if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isPropertyAccessExpression(node.left)
    ) {
      found.push([lineOf(node.left.name), node.left.name.text]);
    }
    if (ts.isLabeledStatement(node)) found.push([lineOf(node.label), node.label.text]);
    const specifier =
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier;
    if (specifier && ts.isStringLiteral(specifier) && /^[.@]/.test(specifier.text)) {
      found.push([lineOf(node), basename(specifier.text)]);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

export function violations(path, text, banned) {
  const kind = path.endsWith("x")
    ? ts.ScriptKind.TSX
    : path.endsWith(".mjs")
      ? ts.ScriptKind.JS
      : ts.ScriptKind.TS;
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind);
  const stem = basename(path).replace(/(\.(test|spec))?\.(tsx?|mjs)$/, "");
  const named = [[1, stem], ...identifiers(source)];
  const lines = [];
  for (const [line, name] of named) {
    const normalised = normalise(name);
    const words = new Set(normalised.split("_"));
    for (const word of [...words]) if (word.endsWith("s")) words.add(word.slice(0, -1));
    for (const token of ENFORCED) {
      const hit = token.includes("_") ? normalised.includes(token) : words.has(token);
      if (hit) lines.push(`${path}:${line}: '${name}' says '${token}'; use '${banned[token]}'`);
    }
  }
  return lines;
}

function trackedTypeScript() {
  const out = execFileSync(
    resolveGit(),
    [
      "ls-files",
      "-z",
      "--",
      "frontend/*.ts",
      "frontend/**/*.ts",
      "frontend/**/*.tsx",
      "frontend/**/*.mjs",
    ],
    {
      cwd: REPO,
      encoding: "utf8",
    },
  );
  // A tracked file can be absent mid-rebase or after an unstaged delete; what is
  // not there is not scanned, and scan_floors-style counting still sees the rest.
  return out
    .split("\0")
    .filter(Boolean)
    .filter((file) => existsSync(resolve(REPO, file)));
}

function main() {
  const banned = bannedTerms(readFileSync(resolve(REPO, "CONTEXT.md"), "utf8"));
  const missing = ENFORCED.filter((token) => !(token in banned));
  if (missing.length) {
    console.error(`CONTEXT.md no longer lists: ${missing.join(", ")}`);
    return 2;
  }
  const files = trackedTypeScript();
  if (files.length === 0) {
    console.error("scanned no files; a scan that scanned nothing is a failure");
    return 2;
  }
  const found = files.flatMap((file) =>
    violations(file, readFileSync(resolve(REPO, file), "utf8"), banned),
  );
  for (const line of found) console.log(line);
  console.error(`vocabulary: ${files.length} files, ${found.length} findings`);
  return found.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
