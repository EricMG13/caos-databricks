// The figure every chart is: a caption carrying the title and a one-line
// summary, the legend, the SVG drawn at its container's real pixel width, a
// button over every mark, a readout line for the active mark, and a "Table"
// toggle that shows the exact data as an accessible table instead.
//
// The SVG is a picture (`role="img"`, named by the caption), so nothing inside
// it is focusable. The marks a reader can reach are native buttons laid over
// it, as RouteGraph lays its nodes over its edges: Tab reaches each, Enter
// and Space press it, hover and focus show the same readout, and no value is
// reachable by hover alone.
import { useId, useState } from "react";
import { HatchPatterns, Swatch } from "./marks";
import { useWidth } from "./use-width";
import type { Box, Hatch, LegendEntry, MarkHit, OnSelect, Plot, TableTwin, Tone } from "./types";

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

/** The selected mark, circled or boxed in the accent 3px clear of it. */
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
  plot: (width: number, hatch: Hatch) => Plot;
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

  const patternId = (tone: Tone) => `${uid}hatch-${tone}`;
  const drawn = plot(width, (tone) => `url(#${patternId(tone)})`);
  const find = (key: string | null) => drawn.marks.find((mark) => mark.key === key) ?? null;
  const pressed = find(selected);
  const shown = find(active) ?? pressed;
  const named = [`${uid}title`, `${uid}summary`, ...(note ? [`${uid}note`] : [])].join(" ");
  const [hostKey, modelKey] = PROVENANCE[provenance];

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
      <div className="chart-keys">
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
          <li className="chart-provenance">
            <Swatch tone="neutral" shape={provenance} origin="host" />
            {hostKey}
          </li>
          <li className="chart-provenance">
            <Swatch tone="neutral" shape={provenance} origin="model" />
            {modelKey}
          </li>
        </ul>
        <button
          type="button"
          className="chart-toggle"
          aria-pressed={tabular}
          onClick={() => setTabular((on) => !on)}
        >
          Table
        </button>
      </div>
      {tabular ? (
        <ChartTable title={title} table={table} />
      ) : (
        <div className="chart-plot" style={{ height: drawn.height }}>
          <svg
            className="chart-svg"
            role="img"
            aria-labelledby={named}
            width={width}
            height={drawn.height}
          >
            <HatchPatterns id={patternId} tones={drawn.hatched} />
            {drawn.body}
            {shown?.guide === undefined ? null : (
              <line
                className="chart-guide"
                x1={shown.guide}
                x2={shown.guide}
                y1={drawn.area.y}
                y2={drawn.area.y + drawn.area.height}
              />
            )}
            {pressed ? <Ring mark={pressed} /> : null}
          </svg>
          {drawn.marks.map((mark, index) => {
            const hit = hitBox(mark.box);
            const roving = drawn.marks.some((entry) => entry.key === anchor)
              ? anchor
              : drawn.marks[0]?.key;
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
                  const last = drawn.marks.length - 1;
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
                    event.currentTarget.parentElement?.querySelectorAll<HTMLElement>(".chart-hit");
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
      )}
      <p className="chart-readout" aria-hidden="true" data-readout>
        {shown ? (shown.readout ?? shown.name) : ""}
      </p>
    </figure>
  );
}
