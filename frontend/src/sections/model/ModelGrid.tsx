// The credit workbook as one grid: bands down the side, the periods across in
// column groups, each cell a button that opens its passport. Every figure is
// the server's exact decimal string re-spelled for reading (`grid.ts`).
import { memo, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import type { ModelDocument } from "@/wire/v1";
import {
  columnGroups,
  groupList,
  hiddenLine,
  refinanced,
  shownCell,
  tintOf,
  toggled,
  type ColumnGroup,
  type GridColumn,
  type GroupId,
  type ModelLine,
} from "./grid";

type Body = ModelDocument["body"];

const TERMS = [
  ["reference_rate", "Reference rate"],
  ["spread_or_coupon", "Spread or coupon"],
  ["floor", "Floor"],
  ["maturity", "Maturity"],
  ["amortisation", "Amortisation"],
] as const;

const TINT_CLASS = { pf: "col-pf", base: "col-base", down: "col-down" } as const;

/** One cell: its figure, or the marker for the figure it does not have with the
    reason in its title. */
function ModelCell({ line, entry }: { line: ModelLine; entry: GridColumn }) {
  const shown = shownCell(line, line.cells[entry.index]!);
  return (
    <span className="cellval" data-cell={entry.column.column_id} title={shown.title}>
      {shown.figure ? shown.text : <span className="na">{shown.text}</span>}
    </span>
  );
}

interface Band {
  name: string;
  /** Each shown line, with the debt rank it opens when it is the first of one. */
  lines: { line: ModelLine; heading: string | null }[];
}

/** The lines the grid shows, in the order served, grouped by contiguous band. */
function bandsOf(lines: readonly ModelLine[]): Band[] {
  const bands: Band[] = [];
  let rank: string | null = null;
  for (const line of lines) {
    if (hiddenLine(line)) continue;
    const last = bands.at(-1);
    // A rank heading opens within its own band: the next band starts over.
    if (!last || last.name !== line.band) rank = null;
    const heading = line.rank !== null && line.rank !== rank ? line.rank : null;
    if (line.rank !== null) rank = line.rank;
    if (last && last.name === line.band) last.lines.push({ line, heading });
    else bands.push({ name: line.band, lines: [{ line, heading }] });
  }
  return bands;
}

/** Rank headings, then the line itself. Memoised: its props are the served
    line and the memoised column groups, which a band toggle leaves alone. */
const ModelRows = memo(function ModelRows({
  line,
  heading,
  groups,
  width,
}: {
  line: ModelLine;
  heading: string | null;
  groups: ColumnGroup[];
  width: number;
}) {
  return [
    ...(heading
      ? [
          <tr key="gap" className="gap" aria-hidden="true">
            <td colSpan={width} />
          </tr>,
          <tr key="rank" className="rank">
            <td className="l lab">{heading}</td>
            <td colSpan={width - 1} />
          </tr>,
        ]
      : []),
    <tr key="line" className={`ln ln-${line.kind.toLowerCase()}`} data-line={line.line_id}>
      <th scope="row" className="l lab">
        {line.label}
        {line.unit === "KPI" && line.unit_label ? (
          <span className="ulabel"> {line.unit_label.toLowerCase()}</span>
        ) : null}
      </th>
      {TERMS.map(([key]) => (
        <td key={key} className="l terms" data-term={key}>
          {line.terms ? line.terms[key] : null}
        </td>
      ))}
      {groups.flatMap((group) =>
        group.columns.length === 0
          ? [<td key={group.id} />]
          : group.columns.map((entry) => {
              const classes = [
                "num",
                tintClass(entry.column),
                refinanced(line, line.cells[entry.index]!) ? "cell-refi" : "",
              ];
              return (
                <td key={entry.column.column_id} className={classes.filter(Boolean).join(" ")}>
                  <ModelCell line={line} entry={entry} />
                </td>
              );
            }),
      )}
    </tr>,
  ];
});

function GroupHeads({
  groups,
  collapsed,
  full,
}: {
  groups: ColumnGroup[];
  collapsed: ReadonlySet<GroupId>;
  full: ReadonlySet<GroupId>;
}) {
  const [, setParams] = useSearchParams();
  const write = (name: "mcols" | "mall", value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(name, value);
        else next.delete(name);
        return next;
      },
      { replace: true },
    );
  return (
    <>
      {groups.map((group) => (
        <th
          key={group.id}
          colSpan={Math.max(group.columns.length, 1)}
          className={`grp grp-${group.id}`}
          scope="colgroup"
        >
          <button
            type="button"
            className="grpbtn"
            aria-expanded={!group.collapsed}
            onClick={() => write("mcols", toggled(collapsed, group.id))}
          >
            {group.collapsed ? "▸" : "▾"} {group.label}
            {group.collapsed ? ` (${group.total})` : ""}
          </button>
          {group.recent !== null && group.total > group.recent ? (
            <button
              type="button"
              className="grpbtn more"
              aria-pressed={full.has(group.id)}
              onClick={() => write("mall", toggled(full, group.id))}
            >
              {full.has(group.id) ? "recent" : "all"}
            </button>
          ) : null}
        </th>
      ))}
    </>
  );
}

export function ModelGrid({ body }: { body: Body }) {
  const [params] = useSearchParams();
  const mcols = params.get("mcols");
  const mall = params.get("mall");
  const collapsed = useMemo(() => groupList(mcols), [mcols]);
  const full = useMemo(() => groupList(mall), [mall]);
  const [shut, setShut] = useState<ReadonlySet<string>>(new Set());
  const groups = useMemo(
    () => columnGroups(body.columns, collapsed, full),
    [body.columns, collapsed, full],
  );
  const bands = useMemo(() => bandsOf(body.lines), [body.lines]);
  const width =
    1 + TERMS.length + groups.reduce((n, group) => n + Math.max(group.columns.length, 1), 0);
  const toggleBand = (name: string) =>
    setShut((current) => {
      const next = new Set(current);
      if (!next.delete(name)) next.add(name);
      return next;
    });
  return (
    <div className="tscroll model-scroll" tabIndex={0} role="region" aria-label="Model grid">
      <table className="tbl dense pin-first model-grid" data-model-grid>
        <thead>
          <tr className="g">
            <th className="l lab">
              <span className="sr-only">Line</span>
            </th>
            <th colSpan={TERMS.length} className="terms">
              Facility terms
            </th>
            <GroupHeads groups={groups} collapsed={collapsed} full={full} />
          </tr>
          <tr className="p">
            <th scope="col" className="l lab">
              {[body.currency, body.unit?.toLowerCase()].filter(Boolean).join(" ")}
            </th>
            {TERMS.map(([key, label]) => (
              <th key={key} scope="col" className="terms">
                {label}
              </th>
            ))}
            {groups.flatMap((group) =>
              group.columns.length === 0
                ? [<th key={group.id} scope="col" aria-label={`${group.label} collapsed`} />]
                : group.columns.map(({ column }) => (
                    <th key={column.column_id} scope="col" className={tintClass(column)}>
                      {column.label}
                    </th>
                  )),
            )}
          </tr>
        </thead>
        {bands.map((band) => {
          const open = !shut.has(band.name);
          return (
            <tbody key={band.name} data-band={band.name}>
              <tr className="band">
                <td className="l lab">
                  <button
                    type="button"
                    className="bandbtn"
                    aria-expanded={open}
                    onClick={() => toggleBand(band.name)}
                  >
                    {open ? "▾" : "▸"} {band.name}
                  </button>
                </td>
                <td colSpan={width - 1} />
              </tr>
              {open
                ? band.lines.map(({ line, heading }) => (
                    <ModelRows
                      key={line.line_id}
                      line={line}
                      heading={heading}
                      groups={groups}
                      width={width}
                    />
                  ))
                : null}
            </tbody>
          );
        })}
      </table>
    </div>
  );
}

function tintClass(column: GridColumn["column"]): string {
  const tint = tintOf(column);
  return tint ? TINT_CLASS[tint] : "";
}
