// The figure every chart is, laid out as shadcn's chart card (D61): a caption
// carrying the title and a one-line summary; the chart drawn by Recharts at
// its container's real pixel width, a button over every mark, and a readout
// line for the active mark; then the legend and a "Table" toggle that shows
// the exact data as an accessible table.
//
// The SVG is a picture (`role="img"`, named by the caption), so nothing inside
// it is in the tab order. The marks a reader can reach are native buttons laid
// over it: each mark drawn inside the chart reports its box here (`Reported`),
// and Tab reaches the first, the arrow keys the rest, Enter and Space press
// one; hover and focus show the same readout, and no value is reachable by
// hover alone.
import {
  createContext,
  useCallback,
  useContext,
  useEffectEvent,
  useId,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import { usePlotArea } from "recharts";
import { Swatch } from "./marks";
import { useWidth } from "./use-width";
import type { Box, LegendEntry, MarkHit, OnSelect, Plot, PlotKit, TableTwin, Tone } from "./types";

// WCAG 2.5.8: a target is at least 24 by 24 CSS pixels.
const TARGET = 24;

/** A mark's hit target: its box grown about its centre to at least 24px each
    way, so a thin bar or an 8px point is still easy to press. */
export function hitBox(box: Box): Box {
  const width = Math.max(TARGET, box.width);
  const height = Math.max(TARGET, box.height);
  return {
    x: box.x + (box.width - width) / 2,
    y: box.y + (box.height - height) / 2,
    width,
    height,
  };
}

interface Marks {
  report: (key: string, mark: MarkHit | null) => void;
  marks: ReadonlyMap<string, MarkHit>;
  shown: MarkHit | null;
  pressed: MarkHit | null;
}

const MarksContext = createContext<Marks>({
  report: () => undefined,
  marks: new Map(),
  shown: null,
  pressed: null,
});

/** The marks reported so far, for what is drawn from them (labels, joins). */
export function useMarks(): ReadonlyMap<string, MarkHit> {
  return useContext(MarksContext).marks;
}

const same = (a: MarkHit, b: MarkHit) =>
  a.name === b.name &&
  a.readout === b.readout &&
  a.round === b.round &&
  a.guide === b.guide &&
  a.box.x === b.box.x &&
  a.box.y === b.box.y &&
  a.box.width === b.box.width &&
  a.box.height === b.box.height;

/** Drawn beside a mark inside the chart: tells the frame where the mark is,
    so a button can be laid over it. */
export function Reported({ mark }: { mark: MarkHit }) {
  const { report } = useContext(MarksContext);
  const { key, name, readout, round, guide, box } = mark;
  const tell = useEffectEvent(() => report(key, mark));
  // Only when what the button shows has moved: every report re-renders the
  // frame, and the frame redraws the chart, which would report again.
  useLayoutEffect(() => {
    tell();
  }, [key, name, readout, round, guide, box.x, box.y, box.width, box.height]);
  useLayoutEffect(() => () => report(key, null), [report, key]);
  return null;
}

/** The selected mark, circled or boxed 3px clear of it, and the active mark's
    guide across the plot (a line chart's period). Drawn inside the chart. */
export function Focus() {
  const { shown, pressed } = useContext(MarksContext);
  const area = usePlotArea();
  return (
    <g className="chart-focus">
      {shown?.guide === undefined || !area ? null : (
        <line
          className="chart-guide"
          x1={shown.guide}
          x2={shown.guide}
          y1={area.y}
          y2={area.y + area.height}
        />
      )}
      {pressed ? <Ring mark={pressed} /> : null}
    </g>
  );
}

function Ring({ mark }: { mark: MarkHit }) {
  const { x, y, width, height } = mark.box;
  if (mark.round) {
    return (
      <circle
        className="chart-ring"
        cx={x + width / 2}
        cy={y + height / 2}
        r={Math.max(width, height) / 2 + 3}
      />
    );
  }
  return <rect className="chart-ring" x={x - 3} y={y - 3} width={width + 6} height={height + 6} />;
}

function ChartTable({ title, table }: { title: string; table: TableTwin }) {
  return (
    <div className="chart-table-wrap" role="region" aria-label={`${title}, table`} tabIndex={0}>
      <table className="chart-table">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            {table.head.map((cell, column) => (
              <th key={`${column}`} scope="col">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.key}>
              {row.cells.map((cell, column) =>
                column === 0 ? (
                  <th key={`${column}`} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={`${column}`}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Whether each chart keys its own provenance. A page whose figures share one
    origin draws the key once, above them, and says no here. */
export const ProvenanceKeyed = createContext(true);

const PROVENANCE = {
  fill: ["Solid: host-verified", "Outlined: model-authored, not host-verified"],
  line: [
    "Solid line, filled point: host-verified",
    "Dashed line, hollow point: model-authored, not host-verified",
  ],
} as const;

export function ChartFrame({
  kind,
  title,
  summary,
  note = null,
  legend,
  provenance,
  table,
  plot,
  onSelect,
}: {
  /** Names the chart form on the figure, `data-chart`. */
  kind: string;
  title: string;
  summary: string;
  /** A finding the chart itself made, said beside the summary. */
  note?: string | null;
  legend: readonly LegendEntry[];
  /** Which provenance key the marks need: bars or lines. */
  provenance: "fill" | "line";
  table: TableTwin;
  /** The drawing at a width; called on every render, so it stays pure. */
  plot: (kit: PlotKit) => Plot;
  onSelect?: OnSelect;
}) {
  const uid = useId();
  const { ref, width } = useWidth<HTMLElement>();
  const [tabular, setTabular] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // One Tab stop per chart, the arrow keys between its marks: a module with
  // four charts was otherwise some fifty stops before its prose (review).
  const [anchor, setAnchor] = useState<string | null>(null);
  const [reported, setReported] = useState<ReadonlyMap<string, MarkHit>>(new Map());
  const report = useCallback((key: string, mark: MarkHit | null) => {
    setReported((previous) => {
      const had = previous.get(key);
      if (mark === null ? had === undefined : had !== undefined && same(had, mark)) {
        return previous;
      }
      const next = new Map(previous);
      if (mark === null) next.delete(key);
      else next.set(key, mark);
      return next;
    });
  }, []);

  const named = [`${uid}title`, `${uid}summary`, ...(note ? [`${uid}note`] : [])].join(" ");
  // Drawn once per chart and width: the frame's own state (the active mark,
  // the reported boxes) reaches the chart through context, so a hover or a
  // report never hands Recharts a new chart to lay out again.
  const drawn = useMemo(() => {
    const patternId = (tone: Tone) => `${uid}hatch-${tone}`;
    return plot({
      width,
      hatch: (tone) => `url(#${patternId(tone)})`,
      patternId,
      svg: { role: "img", "aria-labelledby": named },
    });
  }, [plot, width, uid, named]);
  const marks = drawn.order.flatMap((key) => {
    const mark = reported.get(key);
    return mark ? [mark] : [];
  });
  const find = (key: string | null) => (key === null ? null : (reported.get(key) ?? null));
  const pressed = find(selected);
  const shown = find(active) ?? pressed;
  const context = useMemo(
    () => ({ report, marks: reported, shown, pressed }),
    [report, reported, shown, pressed],
  );
  const [hostKey, modelKey] = PROVENANCE[provenance];
  const keyed = useContext(ProvenanceKeyed);
  const roving = marks.some((entry) => entry.key === anchor) ? anchor : marks[0]?.key;

  return (
    <figure ref={ref} className="chart" data-chart={kind}>
      {/* The caption is the figure's first child and holds only what names
          it, so the figure is named by its title and summary, not "Table". */}
      <figcaption className="chart-caption">
        <span id={`${uid}title`} className="chart-title">
          {title}
        </span>
        <span id={`${uid}summary`} className="chart-summary">
          {summary}
        </span>
        {note ? (
          <span id={`${uid}note`} className="chart-note" data-chart-note>
            {note}
          </span>
        ) : null}
      </figcaption>
      {tabular ? (
        <ChartTable title={title} table={table} />
      ) : (
        <MarksContext.Provider value={context}>
          <div className="chart-plot" style={{ height: drawn.height }}>
            {drawn.chart}
            {marks.map((mark, index) => {
              const hit = hitBox(mark.box);
              return (
                <button
                  key={mark.key}
                  type="button"
                  className="chart-hit"
                  data-mark={mark.key}
                  aria-label={mark.name}
                  aria-pressed={mark.key === selected}
                  style={{ left: hit.x, top: hit.y, width: hit.width, height: hit.height }}
                  tabIndex={mark.key === roving ? 0 : -1}
                  onKeyDown={(event) => {
                    const last = marks.length - 1;
                    const step: Record<string, number> = {
                      ArrowRight: index + 1,
                      ArrowDown: index + 1,
                      ArrowLeft: index - 1,
                      ArrowUp: index - 1,
                      Home: 0,
                      End: last,
                    };
                    const target = step[event.key];
                    if (target === undefined) return;
                    event.preventDefault();
                    const next = Math.min(last, Math.max(0, target));
                    const hits =
                      event.currentTarget.parentElement?.querySelectorAll<HTMLElement>(
                        ".chart-hit",
                      );
                    hits?.[next]?.focus();
                  }}
                  onFocus={() => {
                    setActive(mark.key);
                    setAnchor(mark.key);
                  }}
                  onBlur={() => setActive(null)}
                  onMouseEnter={() => setActive(mark.key)}
                  onMouseLeave={() => setActive(null)}
                  onClick={(event) => {
                    setSelected(mark.key);
                    onSelect?.(mark.selection, event.currentTarget);
                  }}
                />
              );
            })}
          </div>
        </MarksContext.Provider>
      )}
      <p className="chart-readout" aria-hidden="true" data-readout>
        {shown ? (shown.readout ?? shown.name) : ""}
      </p>
      {/* shadcn's chart card: what the chart is above it, its key and the
          table toggle below it (D61). */}
      <div className="chart-keys">
        {legend.length || keyed ? (
          <ul className="chart-legend" aria-label="Legend">
            {legend.map((entry) => (
              <li key={entry.key}>
                <Swatch
                  tone={entry.tone}
                  shape={entry.shape}
                  origin={entry.origin === undefined ? "host" : entry.origin}
                />
                {entry.label}
              </li>
            ))}
            {keyed ? (
              <>
                <li className="chart-provenance">
                  <Swatch tone="neutral" shape={provenance} origin="host" />
                  {hostKey}
                </li>
                <li className="chart-provenance">
                  <Swatch tone="neutral" shape={provenance} origin="model" />
                  {modelKey}
                </li>
              </>
            ) : null}
          </ul>
        ) : null}
        <button
          type="button"
          className="chart-toggle"
          aria-pressed={tabular}
          onClick={() => setTabular((on) => !on)}
        >
          Table
        </button>
      </div>
    </figure>
  );
}
