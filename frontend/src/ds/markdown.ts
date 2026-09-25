// The model's Markdown, read into the closed element set the host renders it
// as (`caos/deliverable/render.py`, ELEMENTS), and nothing else (D60). This is
// a reader, not a Markdown implementation: its output is plain data that
// `ModelMarkdown.tsx` draws as React elements, so no model-authored character ever
// reaches the page as markup -- a tag, a link or an image stays its own text.
// A construct the host would refuse (`DELIVERABLE_MARKDOWN_UNSUPPORTED`) makes
// the whole read `null`, and the page shows the text as written instead.
//
// It reads no figure: a table's cells stay the strings the model wrote. What
// the page charts comes only from the host's typed tables (D32).

export type Mark = "strong" | "em" | "code";
export type Inline = string | { mark: Mark; children: Inline[] };

export interface MdItem {
  /** The marker as written: `-`, `3.`, `12)`. */
  marker: string;
  ordered: boolean;
  text: string;
  lists: MdList[];
}

export interface MdList {
  ordered: boolean;
  /** An ordered list's first ordinal, when it is not 1. */
  start: number | null;
  /** The ordinals are not a consecutive run (or ordered and unordered items
      share a level): each item's marker is printed as written, never
      renumbered, since a number nobody authored is a fabrication. */
  literal: boolean;
  items: MdItem[];
}

export interface MdTable {
  head: string[];
  rows: string[][];
}

export type Block =
  | { kind: "front"; text: string }
  | { kind: "comment"; text: string }
  | { kind: "code"; info: string; text: string; tail: string }
  | { kind: "rule" }
  | { kind: "heading"; level: number; text: string }
  | { kind: "quote"; text: string }
  | { kind: "list"; list: MdList }
  | { kind: "table"; table: MdTable }
  | { kind: "paragraph"; text: string };

// `render.py`'s patterns. JavaScript has no possessive `\s++`, but each
// `(.*)$` here runs to the end of a newline-free line whatever `\s+` took, so
// nothing backtracks. The `s` flag lets `.` match a CR, as Python's does.
const HEADING = /^(#{1,6})\s+(.*)$/s;
const UNORDERED = /^([-*+])\s+(.*)$/s;
const ORDERED = /^([0-9]{1,3}[.)])\s+(.*)$/s;
const DELIMITER = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/;
const INLINE = /(\*\*|\*|`)/;
// ponytail: four levels, as the host: deeper is refused, not flattened.
const MAX_NESTING = 4;

class Unsupported extends Error {}

const TABLE_ID = /table-id:\s*([^\s]+)/;

/** A `<!-- table-id: -->` comment's id, and whether the comment says nothing
    else; `null` for any other text. Only a bare tag may be drawn as its id: a
    caveat the model wrote beside the tag is its own text, which the reader
    must see as the host's rendering shows it (render.py `_comment`). */
export function tableTag(text: string): { id: string; bare: boolean } | null {
  const id = TABLE_ID.exec(text)?.[1];
  if (id === undefined) return null;
  const rest = text
    .replace(TABLE_ID, "")
    .replace(/<!--|-->/g, "")
    .trim();
  return { id, bare: rest === "" };
}

/** The Markdown as blocks, or `null` where the host would refuse it. */
export function readMarkdown(text: string): Block[] | null {
  const lines = text.split("\n");
  const out: Block[] = [];
  try {
    let index = lines[0]?.trimEnd() === "---" ? frontMatter(lines, out) : 0;
    while (index < lines.length) index = block(lines, index, out);
  } catch (error) {
    if (error instanceof Unsupported) return null;
    throw error;
  }
  return out;
}

function frontMatter(lines: string[], out: Block[]): number {
  for (let end = 1; end < lines.length; end += 1) {
    if (lines[end]!.trimEnd() === "---") {
      out.push({ kind: "front", text: lines.slice(1, end).join("\n") });
      return end + 1;
    }
  }
  throw new Unsupported();
}

function block(lines: string[], index: number, out: Block[]): number {
  const line = lines[index]!;
  if (!line.trim()) return index + 1;
  if (line.trimStart().startsWith("<!--")) return comment(lines, index, out);
  if (line.startsWith("```")) return code(lines, index, out);
  if (["---", "***", "___"].includes(line.trimEnd())) {
    out.push({ kind: "rule" });
    return index + 1;
  }
  const heading = HEADING.exec(line);
  if (heading) {
    out.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
    return index + 1;
  }
  if (line.trimStart().startsWith(">")) return quote(lines, index, out);
  if (item(line)) return list(lines, index, out);
  const next = lines[index + 1];
  if (line.includes("|") && next !== undefined && next.includes("|") && DELIMITER.test(next)) {
    return table(lines, index, out);
  }
  return paragraph(lines, index, out);
}

function comment(lines: string[], index: number, out: Block[]): number {
  for (let end = index; end < lines.length; end += 1) {
    if (lines[end]!.includes("-->")) {
      out.push({ kind: "comment", text: lines.slice(index, end + 1).join("\n") });
      return end + 1;
    }
  }
  throw new Unsupported();
}

function code(lines: string[], index: number, out: Block[]): number {
  const info = lines[index]!.slice(3).trim();
  for (let end = index + 1; end < lines.length; end += 1) {
    if (lines[end]!.startsWith("```")) {
      const text = lines.slice(index + 1, end).join("\n");
      out.push({ kind: "code", info, text, tail: lines[end]!.slice(3).trim() });
      return end + 1;
    }
  }
  throw new Unsupported();
}

function quote(lines: string[], index: number, out: Block[]): number {
  const held: string[] = [];
  let at = index;
  while (at < lines.length && lines[at]!.trimStart().startsWith(">")) {
    held.push(lines[at]!.trimStart().slice(1).trim());
    at += 1;
  }
  out.push({ kind: "quote", text: held.join(" ") });
  return at;
}

function item(
  line: string,
): { indent: number; ordered: boolean; marker: string; text: string } | null {
  const stripped = line.replace(/^ +/, "");
  const indent = line.length - stripped.length;
  const ordered = ORDERED.exec(stripped);
  if (ordered) return { indent, ordered: true, marker: ordered[1]!, text: ordered[2]! };
  const unordered = UNORDERED.exec(stripped);
  if (unordered) return { indent, ordered: false, marker: unordered[1]!, text: unordered[2]! };
  return null;
}

/** The ordinal after `marker`: `7.` is followed by `8.`. */
function following(marker: string): string {
  const head = marker.slice(0, -1);
  return /^[0-9]+$/.test(head) ? `${Number(head) + 1}${marker.slice(-1)}` : "";
}

function list(lines: string[], index: number, out: Block[]): number {
  // `render.py`'s `_list`, drawn as a tree: each level a list, a deeper level
  // nested in the item before it (the host writes it beside that item).
  const levels: { indent: number; list: MdList }[] = [];
  const expected = new Map<number, string>();
  let at = index;
  while (at < lines.length) {
    const line = lines[at]!;
    const entry = item(line);
    if (!entry || !line.trim()) break;
    while (levels.length && entry.indent < levels.at(-1)!.indent) levels.pop();
    if (!levels.length || entry.indent > levels.at(-1)!.indent) {
      if (levels.length === MAX_NESTING) throw new Unsupported();
      const first = entry.marker.slice(0, -1);
      const opened: MdList = {
        ordered: entry.ordered,
        start: entry.ordered && first !== "1" ? Number(first) : null,
        literal: entry.ordered && String(Number(first)) !== first,
        items: [],
      };
      if (entry.ordered) expected.set(entry.indent, entry.marker);
      const parent = levels.at(-1)?.list.items.at(-1);
      if (parent) parent.lists.push(opened);
      else out.push({ kind: "list", list: opened });
      levels.push({ indent: entry.indent, list: opened });
    }
    const level = levels.at(-1)!;
    if (entry.ordered !== level.list.ordered) level.list.literal = true;
    if (entry.ordered) {
      if (entry.marker !== expected.get(level.indent)) level.list.literal = true;
      expected.set(level.indent, following(entry.marker));
    }
    level.list.items.push({
      marker: entry.marker,
      ordered: entry.ordered,
      text: entry.text,
      lists: [],
    });
    at += 1;
  }
  return at;
}

function cells(line: string): string[] {
  let stripped = line.trim();
  if (stripped.startsWith("|")) stripped = stripped.slice(1);
  if (stripped.endsWith("|")) stripped = stripped.slice(0, -1);
  return stripped.split("|").map((cell) => cell.trim());
}

function table(lines: string[], index: number, out: Block[]): number {
  const head = cells(lines[index]!);
  const rows: string[][] = [];
  let at = index + 2;
  while (at < lines.length && lines[at]!.includes("|") && lines[at]!.trim()) {
    const row = cells(lines[at]!);
    // A row that does not fit its header has no faithful drawing: padding it
    // would invent a cell and dropping one would lose a fact.
    if (row.length !== head.length) throw new Unsupported();
    rows.push(row);
    at += 1;
  }
  out.push({ kind: "table", table: { head, rows } });
  return at;
}

function paragraph(lines: string[], index: number, out: Block[]): number {
  const held: string[] = [];
  let at = index;
  while (at < lines.length && lines[at]!.trim()) {
    const line = lines[at]!;
    if (held.length && (HEADING.test(line) || item(line))) break;
    if (line.startsWith("```") || line.trimStart().startsWith("<!--")) break;
    held.push(line.trim());
    at += 1;
  }
  out.push({ kind: "paragraph", text: held.join(" ") });
  return at;
}

const TAGS: Record<string, Mark> = { "**": "strong", "*": "em", "`": "code" };

/** Strong, emphasis and code spans; every other character as itself. A
    delimiter counts only where Markdown's flanking rule says so (`2 * 3` is
    arithmetic), a code span's contents are literal, delimiters close in the
    order they opened, and a run that never pairs leaves the whole text
    literal -- `render.py`'s `_inline`, rule for rule. */
export function readInline(text: string): Inline[] {
  const pieces = text.split(INLINE);
  const marks: string[] = [];
  const frames: Inline[][] = [[]];
  const put = (node: Inline) => {
    const top = frames.at(-1)!;
    const last = top.at(-1);
    if (typeof node === "string" && typeof last === "string") top[top.length - 1] = last + node;
    else if (node !== "") top.push(node);
  };
  pieces.forEach((piece, position) => {
    if (position % 2 === 0) return put(piece); // split alternates text and delimiter
    if (marks.at(-1) === "`" && piece !== "`") return put(piece);
    const mark = TAGS[piece]!;
    const before = pieces[position - 1]!;
    const after = pieces[position + 1]!;
    if (marks.includes(piece)) {
      if (marks.at(-1) === piece && (mark === "code" || (before && !/\s/.test(before.at(-1)!)))) {
        marks.pop();
        const children = frames.pop()!;
        return put({ mark, children });
      }
      return put(piece);
    }
    if (mark === "code" || (after && !/\s/.test(after[0]!))) {
      marks.push(piece);
      frames.push([]);
      return undefined;
    }
    return put(piece);
  });
  return marks.length ? [text] : frames[0]!;
}

// ---- module references ----

/** One module a bracketed reference names: `[CP-1B B2/B5]` names CP-1B's
    registers B2 and B5; `[CP-2A calc]` names CP-2A with a note. */
export interface ModuleRef {
  module: string;
  register: string | null;
  note: string | null;
}

export type RefPiece = string | { text: string; refs: ModuleRef[] };

const REF = /\[(CP-[^[\]\n]{1,100})\]/g;
const REF_MODULE = /^(CP-(?:\d+[A-Z]?|[A-Z][A-Z0-9]*))(?:\s+(.+))?$/;
const REF_REGISTER = /^[A-Z]{1,3}\d+[A-Z]?(?:\.[0-9A-Z]+)*(?:[–-][A-Z0-9.]+)?$/;

/** The references in a bracket's content, or `null` when any part of it is
    not one (a file name, "external: …"), so the bracket stays as written. */
function refsIn(content: string): ModuleRef[] | null {
  const refs: ModuleRef[] = [];
  let current: string | null = null;
  for (const segment of content.split(/\s*[/;,]\s*/)) {
    const part = segment.trim();
    const named = REF_MODULE.exec(part);
    if (named) {
      const module = named[1]!;
      current = module;
      const rest = named[2]?.trim() ?? "";
      const tokens = rest ? rest.split(/\s+/) : [];
      if (tokens.length && tokens.every((token) => REF_REGISTER.test(token))) {
        refs.push(...tokens.map((register) => ({ module, register, note: null })));
      } else {
        refs.push({ module, register: null, note: rest || null });
      }
    } else if (current !== null && REF_REGISTER.test(part)) {
      refs.push({ module: current, register: part, note: null });
    } else {
      return null;
    }
  }
  return refs.length ? refs : null;
}

/** A line of model text with its module references picked out, the rest
    exactly as written. */
export function readRefs(text: string): RefPiece[] {
  const out: RefPiece[] = [];
  let at = 0;
  for (const match of text.matchAll(REF)) {
    const refs = refsIn(match[1]!);
    if (refs === null) continue;
    if (match.index > at) out.push(text.slice(at, match.index));
    out.push({ text: match[0], refs });
    at = match.index + match[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}
