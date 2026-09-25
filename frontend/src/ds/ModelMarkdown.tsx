// The model's Markdown drawn as React elements (D60): the blocks `markdown.ts`
// reads, each authored character a text node. Nothing here writes HTML, so
// the page holds under the CSP's Trusted Types whatever the model wrote.
import * as React from "react";
import { createContext, useContext, type ReactNode } from "react";
import { plainHead } from "./format";
import {
  readInline,
  readMarkdown,
  readRefs,
  tableTag,
  type Block,
  type Inline,
  type MdList,
  type MdTable,
  type ModuleRef,
} from "./markdown";

/** How a page draws a module reference (`[CP-1B B2]`) as a way to it. Without
    one -- filed output, which keeps the host renderer's element set -- the
    bracket stays as written. */
export const ModuleRefLink = createContext<((ref: ModuleRef) => ReactNode) | null>(null);

function WithRefs({ text }: { text: string }) {
  const link = useContext(ModuleRefLink);
  if (link === null) return text;
  return readRefs(text).map((piece, index) =>
    typeof piece === "string" ? (
      piece
    ) : (
      <span key={index} className="md-refs" data-refs={piece.text}>
        {piece.refs.map((ref, at) => (
          <React.Fragment key={at}>{link(ref)}</React.Fragment>
        ))}
      </span>
    ),
  );
}

function InlineNodes({ nodes }: { nodes: readonly Inline[] }) {
  return (
    <>
      {nodes.map((node, index) => {
        if (typeof node === "string") return <WithRefs key={index} text={node} />;
        const children = <InlineNodes nodes={node.children} />;
        if (node.mark === "strong") return <strong key={index}>{children}</strong>;
        if (node.mark === "em") return <em key={index}>{children}</em>;
        return <code key={index}>{children}</code>;
      })}
    </>
  );
}

/** One line of model text with its strong, emphasis and code spans. */
export function MdInline({ text }: { text: string }) {
  return <InlineNodes nodes={readInline(text)} />;
}

/** A column head as a reader reads it: an identifier the model wrote
    (`period_id`) in words, its exact name on hover and in As written. */
export function MdHead({ text }: { text: string }) {
  const plain = plainHead(text);
  return plain === null ? <MdInline text={text} /> : <span title={text}>{plain}</span>;
}

// A figure as a column carries it: an optional sign or parenthesis, a
// currency, digits with grouping, a unit. Only the cell's alignment and face
// follow from it; the page never reads the number (D32).
const FIGURE = /^[(−–-]?\s*[$€£]?\s*[0-9][0-9,]*(\.[0-9]+)?\s*(%|x|bps?|pts?|[kmb]n?|mm)?\)?$/i;
const EMPTY = /^(|n\/a|na|—|–|-|none|null)$/i;

function figureColumns(table: MdTable): boolean[] {
  return table.head.map((_, column) => {
    const cells = table.rows.map((row) => row[column] ?? "").filter((cell) => !EMPTY.test(cell));
    return cells.length > 0 && cells.every((cell) => FIGURE.test(cell));
  });
}

// Status words the methodology writes in its registers, as a badge with the
// severity's shape (DESIGN.md: severity is shape and hue). The word is printed
// as written; only its tone is chosen here.
const TONE: Record<string, "ok" | "warn" | "crit"> = {
  pass: "ok",
  passed: "ok",
  ready: "ok",
  calculated: "ok",
  complete: "ok",
  executed: "ok",
  verified: "ok",
  reconciled: "ok",
  warn: "warn",
  warning: "warn",
  partial: "warn",
  restricted: "warn",
  degraded: "warn",
  stale: "warn",
  unresolved: "warn",
  "not calculable": "warn",
  fail: "crit",
  failed: "crit",
  block: "crit",
  blocked: "crit",
  breach: "crit",
};
// Severity-scaled words mean something only under a severity heading: "High"
// confidence is good news, "High" severity is not.
const SEVERITY: Record<string, "ok" | "warn" | "crit" | ""> = {
  low: "",
  medium: "warn",
  moderate: "warn",
  high: "crit",
  critical: "crit",
};
const SEVERITY_HEAD = /severity|materiality|priority|caution/i;

function toneOf(head: string, cell: string): "ok" | "warn" | "crit" | "" | null {
  const word = cell.trim().toLowerCase();
  if (word in TONE) return TONE[word]!;
  if (SEVERITY_HEAD.test(head) && word in SEVERITY) return SEVERITY[word]!;
  return null;
}

const GLYPH = { ok: "ok", warn: "warn", crit: "crit", "": "idle" } as const;

/** One cell: a status word as a badge, anything else as model text. */
export function MdCell({ head, text }: { head: string; text: string }) {
  const tone = toneOf(head, text);
  if (tone === null) return <MdInline text={text} />;
  return (
    <span className={`tag${tone ? ` ${tone}` : ""}`} data-status-word>
      <span className={`glyph ${GLYPH[tone]}`} aria-hidden="true" />
      {text}
    </span>
  );
}

/** A model table, scrolling inside its card when wider than it. */
export function MdTableView({ table, label }: { table: MdTable; label: string }) {
  const figures = figureColumns(table);
  const align = (column: number) => (figures[column] ? undefined : "l");
  return (
    <div className="tscroll" tabIndex={0} role="region" aria-label={label}>
      <table className="tbl md-table">
        <thead>
          <tr>
            {table.head.map((cell, column) => (
              <th key={column} scope="col" className={align(column)}>
                <MdHead text={cell} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) => (
                <td key={column} className={align(column)}>
                  <MdCell head={table.head[column] ?? ""} text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListView({ list }: { list: MdList }) {
  const items = list.items.map((entry, index) => (
    <li key={index} data-marker={list.literal ? entry.marker : undefined}>
      {list.literal ? (
        <span className="md-marker" aria-hidden="true">
          {entry.ordered ? entry.marker : "•"}
        </span>
      ) : null}
      <MdInline text={entry.text} />
      {entry.lists.map((nested, at) => (
        <ListView key={at} list={nested} />
      ))}
    </li>
  ));
  if (!list.ordered) return <ul className={list.literal ? "md-literal" : undefined}>{items}</ul>;
  return (
    <ol
      className={list.literal ? "md-literal" : undefined}
      start={list.literal ? undefined : (list.start ?? undefined)}
    >
      {items}
    </ol>
  );
}

/** Heading levels for a run of authored headings under a container heading
    of level `base`: the authored levels keep their order but close up (a
    document of `####` under a card's h3 starts at h4), and none steps more
    than one below the heading before it. The authored level stays on the
    element as `data-level`. */
function headingLevels(blocks: readonly Block[], base: number): Map<number, number> {
  const authored = [
    ...new Set(blocks.flatMap((b) => (b.kind === "heading" ? [b.level] : []))),
  ].sort((a, b) => a - b);
  const levels = new Map<number, number>();
  let previous = base;
  blocks.forEach((entry, index) => {
    if (entry.kind !== "heading") return;
    const ranked = base + 1 + authored.indexOf(entry.level);
    const level = Math.min(6, ranked, previous + 1);
    levels.set(index, level);
    previous = level;
  });
  return levels;
}

/** Each table's place among the tables, from 1: it names the table's region. */
function tableNumbers(blocks: readonly Block[]): Map<number, number> {
  const numbers = new Map<number, number>();
  blocks.forEach((entry, index) => {
    if (entry.kind === "table") numbers.set(index, numbers.size + 1);
  });
  return numbers;
}

/** A run of blocks as the page draws them. `label` names each table's scroll
    region; `base` is the heading level of the card they sit in. */
export function MarkdownBlocks({
  blocks,
  base,
  label,
}: {
  blocks: readonly Block[];
  base: number;
  label: string;
}) {
  const levels = headingLevels(blocks, base);
  const numbers = tableNumbers(blocks);
  const drawn: ReactNode[] = blocks.map((entry, index) => {
    switch (entry.kind) {
      case "heading": {
        const Tag = `h${levels.get(index) ?? Math.min(6, base + 1)}` as "h4";
        return (
          <Tag key={index} data-level={entry.level}>
            <MdInline text={entry.text} />
          </Tag>
        );
      }
      case "paragraph":
        return (
          <p key={index}>
            <MdInline text={entry.text} />
          </p>
        );
      case "list":
        return <ListView key={index} list={entry.list} />;
      case "quote":
        return (
          <blockquote key={index}>
            <MdInline text={entry.text} />
          </blockquote>
        );
      case "table":
        return (
          <MdTableView
            key={index}
            table={entry.table}
            label={`${label}, table ${numbers.get(index)}`}
          />
        );
      case "code":
        return (
          <figure key={index} className="md-code">
            {entry.info ? <figcaption>{entry.info}</figcaption> : null}
            <pre>
              <code>{entry.text}</code>
            </pre>
            {entry.tail ? <figcaption>{entry.tail}</figcaption> : null}
          </figure>
        );
      case "comment": {
        // A bare table tag labels the table under it by its id; any other
        // comment, a tag with the model's caveat beside it included, is shown
        // as the characters written, never dropped (render.py `_comment`).
        const tag = tableTag(entry.text);
        return (
          <p key={index} className="md-comment" data-table-id={tag?.id}>
            {tag?.bare ? tag.id : entry.text}
          </p>
        );
      }
      case "front":
        return (
          <pre key={index} className="md-front">
            {entry.text}
          </pre>
        );
      default:
        return <hr key={index} />;
    }
  });
  return <>{drawn}</>;
}

/** A whole Markdown text, formatted; where the host would refuse it, the text
    as written with the reason, so nothing the model wrote is hidden. */
export function Markdown({ text, base, label }: { text: string; base: number; label: string }) {
  const blocks = readMarkdown(text);
  if (blocks === null) {
    return (
      <div className="md" data-markdown="as-written">
        <p className="note">
          This text uses a construct the page does not format (an unclosed block, a table row that
          does not fit its header, or lists nested past four levels), so it is shown as written.
        </p>
        <pre className="model-text">{text}</pre>
      </div>
    );
  }
  return (
    <div className="md" data-markdown="formatted">
      <MarkdownBlocks blocks={blocks} base={base} label={label} />
    </div>
  );
}
