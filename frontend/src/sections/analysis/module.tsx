// The selected module in the five places every module shares (D60): a header
// of host facts; the model's conclusion-first view beside its key figures and
// caveats; the figures; the reader-facing sections; and one card of tabs --
// Appendix, Audit, As written -- in the same order in every module. The
// model's Markdown is drawn by `ds/ModelMarkdown`, never injected.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { keyFigures, type KeyFigure } from "./figures";
import {
  APPENDIX_GROUPS,
  AUDIT_SECTIONS,
  CONTRARY,
  moduleParts,
  openingOf,
  placeOf,
  shapeOf,
  type Driver,
  type ModuleParts,
  type Opening,
  type Part,
  type Register,
  type Shape,
} from "./parts";
import { formatDecimal } from "@/charts";
import { scopeOf, words } from "@/chrome/compose";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarkdownBlocks, MdCell, MdHead, MdInline, MdTableView } from "@/ds/ModelMarkdown";
import { plainHead, plainName, stamp } from "@/ds/format";
import { readMarkdown, type Block, type MdTable } from "@/ds/markdown";
import type { HandoffView } from "@/wire/v1";

/** Model prose beyond this many characters is shown on request: a handoff may
    carry 25 MB, and drawing all of it at once stalls the page. */
export const PROSE_SHOWN = 20_000;

/** Past this many characters the text is not formatted at all: drawing a
    25 MB handoff as elements stalls the page as surely as printing it did.
    The As written tab shows it, a part at a time. */
const FORMATTED_MAX = 500_000;

/** The module's Markdown read once per handoff, and where each register goes;
    `null` when it is not formatted (too long, or a construct the host would
    refuse). */
export function useModuleParts(handoff: HandoffView) {
  return useMemo(() => {
    if (handoff.model_analysis.length > FORMATTED_MAX) return null;
    const blocks = readMarkdown(handoff.model_analysis);
    if (blocks === null) return null;
    const parts = moduleParts(blocks);
    const placed = parts.registers.map((register) => ({
      register,
      place: placeOf(handoff.module_id, register),
    }));
    // The argument against the view sits beside it, not among the sections.
    const contrary = parts.reader.find((part) => CONTRARY.test(part.title)) ?? null;
    return { parts, placed, contrary };
  }, [handoff.model_analysis, handoff.module_id]);
}

type Read = NonNullable<ReturnType<typeof useModuleParts>>;

/** A register's name: its id, then the words its heading or the schema
    reference gives it. */
function RegisterName({ register }: { register: Register }) {
  return (
    <>
      {register.id ? <span className="id">{register.id}</span> : null}
      <MdHead text={register.title === register.id ? "" : register.title} />
    </>
  );
}

function RegisterTitle({ register }: { register: Register }) {
  return (
    <h4 className="reghead">
      <RegisterName register={register} />
    </h4>
  );
}

// Which column of an evidence-chain register says what: the conclusion, the
// state words, and where it came from. The rest are labelled fields.
const MAIN =
  /credit implication|implication|consequence|credit impact|why it matters|assessment|summary|answer|resolution|credit relevance/i;
const STATE =
  /confidence|severity|materiality|status|priority|direction|verdict|classification|quality|caution/i;
const WHERE = /evidence id|source trace|source|locator|refs?$|trace|citation/i;

/** An evidence-chain register read down, one item a row: what, so what, why,
    on what (the Findings and Triggers shapes). */
function ItemRows({ table }: { table: MdTable }) {
  const main = table.head.findIndex((head, column) => column > 0 && MAIN.test(head));
  const role = (head: string, column: number) =>
    column === 0
      ? "title"
      : column === main
        ? "main"
        : STATE.test(head)
          ? "state"
          : WHERE.test(head)
            ? "where"
            : "field";
  const columns = (row: readonly string[], wanted: string) =>
    row.flatMap((cell, column) =>
      role(table.head[column]!, column) === wanted && cell ? [{ cell, column }] : [],
    );
  return (
    <ol className="items">
      {table.rows.map((row, index) => {
        const fields = columns(row, "field");
        const where = columns(row, "where");
        return (
          <li key={index}>
            <div className="ih">
              <span>
                <MdInline text={row[0] ?? ""} />
              </span>
              {columns(row, "state").map(({ cell, column }) => (
                <span key={column} className="st">
                  <MdCell head={table.head[column]!} text={cell} />
                </span>
              ))}
            </div>
            {main > 0 && row[main] ? (
              <p className="im">
                <MdInline text={row[main]!} />
              </p>
            ) : null}
            {fields.length ? (
              <dl>
                {fields.map(({ cell, column }) => (
                  <div key={column}>
                    <dt>
                      <MdHead text={table.head[column]!} />
                    </dt>
                    <dd>
                      <MdInline text={cell} />
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {where.length ? (
              <p className="iw">
                {where.map(({ cell, column }) => (
                  <span key={column}>
                    <MdInline text={cell} />
                  </span>
                ))}
              </p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

const WHEN = /date|window|timing|period|milestone/i;

/** A dated register read down time, as CP-2B's catalysts are. */
function DatedRows({ table }: { table: MdTable }) {
  const when = Math.max(
    0,
    table.head.findIndex((head) => WHEN.test(head)),
  );
  const what = table.head.findIndex((_, column) => column !== when && column > 0);
  return (
    <ol className="dated">
      {table.rows.map((row, index) => (
        <li key={index}>
          <span className="when">
            <MdInline text={row[when] || "Undated"} />
          </span>
          <span className="what">
            <b>
              <MdInline text={row[what] ?? row[0] ?? ""} />
            </b>
            {row
              .map((cell, column) => ({ cell, column }))
              .filter(({ column, cell }) => column !== when && column !== what && cell)
              .map(({ cell, column }) => (
                <span key={column} className="more">
                  <MdCell head={table.head[column]!} text={cell} />
                </span>
              ))}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** A register's table in the form its shape reads best in. */
function RegisterBody({ table, shape, label }: { table: MdTable; shape: Shape; label: string }) {
  if (shape === "findings" || shape === "triggers" || shape === "debate") {
    return <ItemRows table={table} />;
  }
  if (shape === "timeline") return <DatedRows table={table} />;
  return <MdTableView table={table} label={label} />;
}

function RegisterNotes({ register, label }: { register: Register; label: string }) {
  return register.notes.length ? (
    <div className="md">
      <MarkdownBlocks blocks={register.notes} base={4} label={label} />
    </div>
  ) : null;
}

/** One register, titled, whole. */
function RegisterView({ register, label }: { register: Register; label: string }) {
  return (
    <section
      className="reg"
      data-register={register.id ?? register.title}
      data-shape={register.shape}
    >
      <RegisterTitle register={register} />
      <RegisterNotes register={register} label={label} />
      <RegisterBody table={register.table} shape={register.shape} label={label} />
    </section>
  );
}

/** An opened register shows this many rows first: enough to read what it
    is, not a page of it. */
const ROWS_FIRST = 8;

const rowsSaid = (count: number) =>
  `${count.toLocaleString("en-US")} ${count === 1 ? "row" : "rows"}`;

/** An appendix register once opened: its notes and its first rows, the rest
    on request. */
function OpenRegister({ register, label, id }: { register: Register; label: string; id: string }) {
  const [all, setAll] = useState(false);
  const { table } = register;
  const cut = !all && table.rows.length > ROWS_FIRST;
  return (
    <div
      id={id}
      className="reg"
      data-register={register.id ?? register.title}
      data-shape={register.shape}
    >
      <RegisterNotes register={register} label={label} />
      <RegisterBody
        table={cut ? { ...table, rows: table.rows.slice(0, ROWS_FIRST) } : table}
        shape={register.shape}
        label={label}
      />
      {cut ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-register-rest
          onClick={() => setAll(true)}
        >
          Show all {rowsSaid(table.rows.length)}
        </Button>
      ) : null}
    </div>
  );
}

/** The appendix as an index: each register a line -- id, name, how many rows
    -- that opens in place, one at a time, so the tab is a list of what the
    module registered rather than every row of it. */
function RegisterIndex({
  registers,
  label,
  open,
  onOpen,
}: {
  registers: readonly { register: Register; key: string }[];
  label: string;
  open: string | null;
  onOpen: (key: string | null) => void;
}) {
  const uid = useId();
  return (
    <ul className="regindex">
      {registers.map(({ register, key }, index) => {
        const shown = open === key;
        // By position: a title can hold spaces, and `aria-controls` is a list.
        const panel = `${uid}register-${index}`;
        return (
          <li key={key} data-register-entry={register.id ?? register.title}>
            <h4>
              <button
                type="button"
                aria-expanded={shown}
                aria-controls={shown ? panel : undefined}
                data-register-open
                onClick={() => onOpen(shown ? null : key)}
              >
                <span className="nm">
                  <RegisterName register={register} />
                </span>
                <span className="n">{rowsSaid(register.table.rows.length)}</span>
                <span className="chev" aria-hidden="true" />
              </button>
            </h4>
            {shown ? (
              <OpenRegister
                register={register}
                label={`${label}, ${register.id ?? register.title}`}
                id={panel}
              />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Registers({ registers, label }: { registers: readonly Register[]; label: string }) {
  return (
    <div className="regs">
      {registers.map((register, index) => (
        <RegisterView
          key={`${register.id ?? register.title}-${index}`}
          register={register}
          label={`${label}, ${register.id ?? register.title}`}
        />
      ))}
    </div>
  );
}

// ---- the header's facts ----

export function ModuleFacts({
  handoff,
  subject,
  documents,
}: {
  handoff: HandoffView;
  subject: string | null;
  documents: ReactNode;
}) {
  return (
    <ul className="modfacts">
      {subject ? <li data-subject>{subject}</li> : null}
      <li data-committee-status>
        {handoff.committee_status} · {scopeOf(handoff.decision_scope)}
      </li>
      <li>
        Confidence{" "}
        <span data-confidence>
          <b className="mono">{handoff.confidence_score}</b> · {words(handoff.confidence_band)}
        </span>
      </li>
      {/* How many; the caveats name each. */}
      <li data-limitation-flags>
        Limitations <b>{handoff.limitation_flags.length || "none"}</b>
      </li>
      <li>
        Accepted <time dateTime={handoff.accepted_at}>{stamp(handoff.accepted_at)}</time>
      </li>
      <li className="mono" title={handoff.artifact_sha256} data-route-node>
        {handoff.route_node_id}
      </li>
      <li>{documents}</li>
    </ul>
  );
}

// ---- the lead: the view, its key figures, its caveats ----

function KeyFigures({ figures }: { figures: readonly KeyFigure[] }) {
  return (
    <section className="pnl" data-key-figures aria-labelledby="key-figures-heading">
      <header>
        <h3 id="key-figures-heading">Key figures</h3>
        <span className="cp model">model-authored, as served</span>
      </header>
      <ul className="stats">
        {figures.map((figure) => {
          const change = figure.change.value;
          const direction =
            change === null
              ? "none"
              : change.startsWith("-")
                ? "down"
                : /[1-9]/.test(change)
                  ? "up"
                  : "flat";
          return (
            <li key={figure.key} data-key-figure={figure.key}>
              <span className="k">{figure.label}</span>
              <span className="v">{figure.value}</span>
              <span className="d">
                <span className="delta" data-direction={direction}>
                  {change === null
                    ? (figure.change.reason ?? "n/a")
                    : `${formatDecimal(change, true)}%`}
                </span>
                {figure.reference === null ? null : <span>from {figure.reference}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

interface Caveat {
  key: string;
  /** The identifier a limitation flag was served as; its words are `text`. */
  flag?: string;
  title: string;
  text: string;
  origin: string;
}

function caveatsOf(handoff: HandoffView, read: Read | null, screening: string): Caveat[] {
  const out: Caveat[] = [];
  const host = "host-verified";
  if (handoff.screening_only)
    out.push({
      key: "screening",
      title: "Screening only.",
      text: screening,
      origin: host,
    });
  for (const [index, flag] of handoff.limitation_flags.entries()) {
    out.push({
      key: `limit-${index}`,
      title: "Limitation.",
      text: plainName(flag),
      flag,
      origin: host,
    });
  }
  if (handoff.validation_warnings.length) {
    out.push({
      key: "warnings",
      title: "Validation warnings.",
      text: handoff.validation_warnings.map((warning) => plainHead(warning) ?? warning).join("; "),
      origin: host,
    });
  }
  for (const [index, fact] of handoff.source_facts.entries()) {
    if (fact.withdrawn_at === null) continue;
    out.push({
      key: `withdrawn-${index}`,
      title: "Source withdrawn.",
      text: `${fact.filename} p.${fact.page}, withdrawn ${stamp(fact.withdrawn_at)}; the citation stays so the conclusion stays explicable.`,
      origin: host,
    });
  }
  for (const [shape, one, many] of [
    ["gaps", "gap", "gaps"],
    ["conflicts", "conflict", "conflicts"],
  ] as const) {
    const tables = [
      ...(read?.placed ?? [])
        .filter(({ register }) => register.shape === shape)
        .map(({ register }) => ({ name: register.id ?? register.title, table: register.table })),
      ...(
        read?.parts.audit.find((part) => part.title === "Gaps and conflicts")?.blocks ?? []
      ).flatMap((block) =>
        block.kind === "table" && shapeOf("", block.table.head) === shape
          ? [{ name: "Gaps and conflicts", table: block.table }]
          : [],
      ),
    ];
    const count = tables.reduce((sum, { table }) => sum + table.rows.length, 0);
    if (!count) continue;
    out.push({
      key: shape,
      title: `${count} ${count === 1 ? one : many}.`,
      text: `In the Audit tab, under Gaps and conflicts.`,
      origin: `model-authored · ${[...new Set(tables.map(({ name }) => name))].join(", ")}`,
    });
  }
  // A pass is the header's QA tag; only a QA state that qualifies the view is
  // a caveat.
  if (handoff.qa_status !== "Passed") {
    out.push({
      key: "qa",
      title: `QA ${handoff.qa_status}.`,
      text: "Read the module's limitations before relying on it.",
      origin: host,
    });
  }
  return out;
}

function Caveats({ caveats }: { caveats: readonly Caveat[] }) {
  return (
    <section className="pnl" data-caveats aria-labelledby="caveats-heading">
      <header>
        <h3 id="caveats-heading">Caveats</h3>
        <span className="cp">what qualifies the view</span>
      </header>
      <ul className="caveats">
        {caveats.map((caveat) => (
          <li
            key={caveat.key}
            data-caveat={caveat.key}
            data-screening-only={caveat.key === "screening" || undefined}
            data-validation-warnings={caveat.key === "warnings" || undefined}
          >
            <span className="glyph warn" aria-hidden="true" />
            <span>
              <b>{caveat.title}</b>{" "}
              {caveat.flag ? (
                <span title={caveat.flag} data-limitation-flag={caveat.flag}>
                  {caveat.text}
                </span>
              ) : (
                caveat.text
              )}
              <span className="src">{caveat.origin}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A driver's support past this many characters (about three lines at the
    view's measure) is shown in part until the reader asks for the rest. */
const SUPPORT_SHOWN = 300;

function KeyPoint({ driver, index }: { driver: Driver; index: number }) {
  const [all, setAll] = useState(false);
  const long = driver.support.length > SUPPORT_SHOWN;
  return (
    <li data-key-point>
      <span className="n" aria-hidden="true">
        {index + 1}
      </span>
      <div>
        <p className="claim">
          <MdInline text={driver.claim} />
        </p>
        {driver.support ? (
          <p className="support" data-clamped={(long && !all) || undefined}>
            <MdInline text={driver.support} />
          </p>
        ) : null}
        {long ? (
          <button
            type="button"
            className="more"
            aria-expanded={all}
            onClick={() => setAll((open) => !open)}
          >
            {all ? "Show less" : "Read in full"}
          </button>
        ) : null}
      </div>
    </li>
  );
}

/** The opening in the canon's order: its first sentence large, the rest of
    its paragraph, then its decision drivers as key points. */
function OpeningView({ opening }: { opening: Opening }) {
  return (
    <>
      {opening.lede || opening.continuation ? (
        <div className="thesis" data-opening>
          {opening.lede ? (
            <p className="lede">
              <MdInline text={opening.lede} />
            </p>
          ) : null}
          {/* Without a lede the paragraph is plain text, not the quiet rest of one. */}
          {opening.continuation ? (
            <p className={opening.lede ? "cont" : undefined}>
              <MdInline text={opening.continuation} />
            </p>
          ) : null}
        </div>
      ) : null}
      {opening.drivers ? (
        <section className="keypoints" data-key-points aria-labelledby="key-points-heading">
          <h4 id="key-points-heading">Key points</h4>
          {opening.drivers.intro ? (
            <p className="intro">
              <MdInline text={opening.drivers.intro} />
            </p>
          ) : null}
          <ol>
            {opening.drivers.items.map((driver, index) => (
              <KeyPoint key={index} driver={driver} index={index} />
            ))}
          </ol>
        </section>
      ) : null}
      {opening.rest.length ? (
        <MarkdownBlocks blocks={opening.rest} base={3} label="Analysis" />
      ) : null}
    </>
  );
}

/** The module's argument against its own view, beside the view, in the same
    place in every module that writes one. */
function Contrary({ part }: { part: Part }) {
  return (
    <section className="pnl contrary" data-contrary aria-labelledby="contrary-heading">
      <header>
        <h3 id="contrary-heading">
          <MdInline text={part.title} />
        </h3>
        <span className="cp model">the case against the view</span>
      </header>
      <div className="pb md">
        <MarkdownBlocks blocks={part.blocks} base={3} label={part.title} />
      </div>
    </section>
  );
}

export function Lead({
  handoff,
  read,
  screening,
}: {
  handoff: HandoffView;
  read: Read | null;
  screening: string;
}) {
  const figures = useMemo(
    () => (handoff.tables_unavailable_reason ? [] : keyFigures(handoff.tables)),
    [handoff],
  );
  const caveats = caveatsOf(handoff, read, screening);
  const lead = read?.parts.lead ?? null;
  const opening = useMemo(() => (lead ? openingOf(lead) : null), [lead]);
  const contrary = read?.contrary ?? null;
  const leading = (read?.placed ?? [])
    .filter(({ place }) => place === "lead")
    .map(({ register }) => register);
  const side = figures.length > 0 || caveats.length > 0 || contrary !== null;
  return (
    <div className="lead" data-solo={side ? undefined : true}>
      <section className="pnl view" data-model-analysis aria-labelledby="view-heading">
        <header>
          <h3 id="view-heading">{lead?.title ? <MdInline text={lead.title} /> : "Analysis"}</h3>
          <span className="cp model">model-authored, not host-verified</span>
        </header>
        <div className="pb md">
          {read === null ? (
            <p className="note" data-markdown="as-written">
              {handoff.model_analysis.length > FORMATTED_MAX
                ? `This module's text runs to ${handoff.model_analysis.length.toLocaleString("en-US")} characters, more than the page formats.`
                : "This module's text uses a construct the page does not format (an unclosed block, a table row that does not fit its header, or lists nested past four levels)."}{" "}
              The As written tab shows it as written.
            </p>
          ) : opening && lead!.blocks.length ? (
            <OpeningView opening={opening} />
          ) : (
            <p className="note">This module wrote no opening view before its registers.</p>
          )}
          {leading.length ? <Registers registers={leading} label="Analysis" /> : null}
        </div>
      </section>
      {side ? (
        <div className="side">
          {contrary ? <Contrary part={contrary} /> : null}
          {figures.length ? <KeyFigures figures={figures} /> : null}
          {caveats.length ? <Caveats caveats={caveats} /> : null}
        </div>
      ) : null}
    </div>
  );
}

// ---- the reader-facing sections after the view ----

/** A section that is one list whose every item opens with a bold label reads
    as columns, one item each; any other section as written. */
function asColumns(blocks: readonly Block[]): { label: string; text: string }[] | null {
  if (blocks.length !== 1 || blocks[0]!.kind !== "list") return null;
  const items = blocks[0]!.list.items;
  if (items.length < 2 || items.length > 4) return null;
  const labelled = items.map((item) => /^\*\*(.+?)\*\*\s*(.*)$/s.exec(item.text));
  if (labelled.some((match) => match === null)) return null;
  return labelled.map((match) => ({ label: match![1]!.replace(/[.:]$/, ""), text: match![2]! }));
}

export function ReaderParts({ parts }: { parts: readonly Part[] }) {
  return (
    <>
      {parts.map((part, index) => {
        const columns = asColumns(part.blocks);
        const title = part.title || "Notes";
        return (
          <section key={`${title}-${index}`} className="pnl reader" data-reader-part={title}>
            <header>
              <h3>
                <MdInline text={title} />
              </h3>
              <span className="cp model">model-authored</span>
            </header>
            {columns ? (
              <div className="cols">
                {columns.map((column) => (
                  <div key={column.label}>
                    <h4>
                      <MdInline text={column.label} />
                    </h4>
                    <p>
                      <MdInline text={column.text} />
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="pb md">
                <MarkdownBlocks blocks={part.blocks} base={3} label={title} />
              </div>
            )}
          </section>
        );
      })}
    </>
  );
}

// ---- depth: Appendix, Audit, As written ----

function AsWritten({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const cut = !all && text.length > PROSE_SHOWN;
  return (
    <>
      <pre className="model-text written" data-as-written>
        {cut ? text.slice(0, PROSE_SHOWN) : text}
      </pre>
      {cut ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-prose-rest
          onClick={() => setAll(true)}
        >
          Show the remaining {(text.length - PROSE_SHOWN).toLocaleString("en-US")} characters
        </Button>
      ) : null}
    </>
  );
}

/** The register an address names (`#register-B2`); `null` for none, and for
    an address that does not decode -- a hand-typed `%E0%A4` is no register. */
export function registerOfHash(hash: string): string | null {
  const encoded = /^#register-(.+)$/.exec(hash)?.[1];
  if (encoded === undefined) return null;
  try {
    return decodeURIComponent(encoded);
  } catch {
    return null;
  }
}

/** The three tabs; the section holds which is open, so a reader moving
    between modules stays on the tab they were reading. */
export type DepthTab = "appendix" | "audit" | "written";

export function Depth({
  handoff,
  read,
  tab,
  onTab,
  sourceFacts,
  documents,
}: {
  handoff: HandoffView;
  read: Read | null;
  tab: DepthTab;
  onTab: (tab: DepthTab) => void;
  /** The host-verified citations, first in the Audit tab. */
  sourceFacts: ReactNode;
  /** What the run rests on, second. */
  documents: ReactNode;
}) {
  const parts: ModuleParts | null = read?.parts ?? null;
  const appendix = (read?.placed ?? [])
    .filter(({ place }) => place === "appendix")
    .map(({ register }) => register);
  const inAudit = (name: string) =>
    (read?.placed ?? []).filter(({ place }) => place === name).map(({ register }) => register);
  const issues = (read?.placed ?? [])
    .filter(({ register }) => register.shape === "gaps" || register.shape === "conflicts")
    .reduce((sum, { register }) => sum + register.table.rows.length, 0);
  const keyed = appendix.map((register, index) => ({
    register,
    key: `${index}-${register.id ?? register.title}`,
  }));
  // A reference to one of this module's registers (`#register-B2`, from a
  // `[CP-1B B2]` elsewhere) opens it; otherwise the appendix opens closed.
  const { hash } = useLocation();
  const wanted = registerOfHash(hash);
  const target = wanted === null ? undefined : keyed.find(({ register }) => register.id === wanted);
  // One register open at a time; the module's own key, so a reader moving to
  // another module finds its appendix closed.
  const [open, setOpen] = useState<string | null>(target?.key ?? null);
  // A module with no appendix register opens on its audit: an empty tab is
  // not where a reader should land, and its count already says it is empty.
  // Asked for, it opens and says so.
  const [asked, setAsked] = useState(false);
  const shown = tab === "appendix" && appendix.length === 0 && !asked ? "audit" : tab;
  // Following a reference: the appendix, then the register, once.
  const followed = useRef(false);
  const targetId = target?.register.id;
  useEffect(() => {
    if (targetId === undefined || followed.current) return;
    if (shown !== "appendix") {
      onTab("appendix");
      return;
    }
    followed.current = true;
    [...document.querySelectorAll<HTMLElement>("[data-register-entry]")]
      .find((entry) => entry.dataset.registerEntry === targetId)
      ?.scrollIntoView?.({ block: "center" });
  }, [targetId, shown, onTab]);
  return (
    <section className="pnl depth" data-depth aria-label="Appendix, audit and the module's text">
      <Tabs
        value={shown}
        onValueChange={(next) => {
          setAsked(next === "appendix");
          onTab(next as DepthTab);
        }}
      >
        <header>
          <TabsList>
            <TabsTrigger value="appendix" data-depth-tab="appendix">
              Appendix <span className="count">{appendix.length}</span>
            </TabsTrigger>
            <TabsTrigger value="audit" data-depth-tab="audit">
              Audit
              {issues ? (
                <span className="count">
                  <span className="glyph warn" aria-hidden="true" /> {issues}
                </span>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="written" data-depth-tab="written">
              As written
            </TabsTrigger>
          </TabsList>
        </header>
        <TabsContent value="appendix" className="pb depthpanel" data-depth-panel="appendix">
          {appendix.length === 0 ? (
            <p className="note">This module&apos;s text carries no appendix register.</p>
          ) : null}
          {APPENDIX_GROUPS.map((group) => {
            const members = keyed.filter(({ register }) => group.shapes.includes(register.shape));
            return members.length ? (
              <section key={group.name} className="group" data-appendix-group={group.name}>
                <h3>
                  {group.name} <span className="cp">{members.length}</span>
                </h3>
                <RegisterIndex
                  registers={members}
                  label={group.name}
                  open={open}
                  onOpen={setOpen}
                />
              </section>
            ) : null;
          })}
        </TabsContent>
        <TabsContent value="audit" className="pb depthpanel" data-depth-panel="audit">
          <section className="group" data-audit-part="Source facts">
            <h3>
              Source facts <span className="cp">host-verified citations</span>
            </h3>
            {sourceFacts}
          </section>
          <section className="group" data-audit-part="Documents">
            <h3>
              What this run rests on <span className="cp">host-verified</span>
            </h3>
            {documents}
          </section>
          {AUDIT_SECTIONS.map((name) => {
            const written = parts?.audit.find((part) => part.title === name)?.blocks ?? [];
            const registers = inAudit(name);
            return written.length || registers.length ? (
              <section key={name} className="group" data-audit-part={name}>
                <h3>
                  {name} <span className="cp">model-authored</span>
                </h3>
                {written.length ? (
                  <div className="md">
                    <MarkdownBlocks blocks={written} base={3} label={name} />
                  </div>
                ) : null}
                {registers.length ? <Registers registers={registers} label={name} /> : null}
              </section>
            ) : null;
          })}
          {parts?.front ? (
            <section className="group" data-audit-part="Front matter">
              <h3>
                Front matter <span className="cp">host-owned, as written</span>
              </h3>
              <pre className="md-front">{parts.front}</pre>
            </section>
          ) : null}
        </TabsContent>
        <TabsContent value="written" className="pb depthpanel" data-depth-panel="written">
          <AsWritten text={handoff.model_analysis} />
        </TabsContent>
      </Tabs>
    </section>
  );
}
