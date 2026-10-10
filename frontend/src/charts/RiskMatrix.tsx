// Events by probability and impact: a grid of the ordinal labels CP-2B step
// 05 declares, Probability (High, Medium, Low, Unknown) top to bottom against
// Impact (Low, Medium, High, Unknown) left to right. Recharts has no grid
// chart, so the grid is drawn here as SVG inside the frame (D61); the frame's
// marks, table twin and provenance rules hold as for every chart. A cell
// holding events is a mark printing its count, the one figure computed here,
// a count of rows; an empty cell is drawn and is not a mark. A label is read
// trimmed and case-insensitive; any other text counts as Unknown and keeps
// its text in the cell's name.
import { ChartFrame, Focus, Reported } from "./ChartFrame";
import { BarShape, HatchPatterns } from "./marks";
import { TICK_SIZE, VALUE_SIZE, textWidth } from "./scale";
import { ORIGIN_WORD } from "./series";
import type { OnSelect, Origin, Plot, PlotKit, RiskEvent, TableTwin } from "./types";

const LEVELS = ["High", "Medium", "Low", "Unknown"] as const;
export type RiskLevel = (typeof LEVELS)[number];
const PROBABILITY: readonly RiskLevel[] = LEVELS;
const IMPACT: readonly RiskLevel[] = ["Low", "Medium", "High", "Unknown"];

/** The ordinal label `written` reads as, trimmed and case-insensitive;
    null for any other text, which counts as Unknown. */
export function riskLevel(written: string): RiskLevel | null {
  const read = written.trim().toLowerCase();
  return LEVELS.find((level) => level.toLowerCase() === read) ?? null;
}

/** The most ids a cell's name or a summary lists; the table twin lists all. */
const MOST_IDS = 10;

/** "E1, E2, …, E10, …and 2 more": at most ten ids, the rest counted. */
export function idList(ids: readonly string[]): string {
  const rest = ids.length - MOST_IDS;
  const listed = ids.slice(0, MOST_IDS).join(", ");
  return rest > 0 ? `${listed}, …and ${rest} more` : listed;
}

const TOP = 20;
const ROW = 44;
const BAND = 36;
const EDGE = 4;
const SIDE = 24;
const LEFT = Math.ceil(textWidth("Probability", TICK_SIZE)) + 12;
const HEIGHT = TOP + 4 * ROW + BAND;

interface MatrixCell {
  key: string;
  probability: RiskLevel;
  impact: RiskLevel;
  /** Its place in the grid, row by row. */
  index: number;
  events: RiskEvent[];
  origin: Origin;
  name: string;
}

/** An event's id, with the text it was counted as Unknown for. */
function idOf(event: RiskEvent): string {
  const unread = (["probability", "impact"] as const).flatMap((axis) => {
    const written = event[axis].trim();
    if (riskLevel(written)) return [];
    return [written ? `${axis} as written: ${written}` : `${axis} not stated`];
  });
  return unread.length ? `${event.label} (${unread.join("; ")})` : event.label;
}

function originOf(events: readonly RiskEvent[]): { origin: Origin; said: string } {
  const host = events.filter((event) => event.origin === "host").length;
  if (host === events.length) return { origin: "host", said: ORIGIN_WORD.host };
  if (host === 0) return { origin: "model", said: ORIGIN_WORD.model };
  // A cell of both is drawn as the model's: no host check stands for it all.
  return {
    origin: "model",
    said: `${host} ${ORIGIN_WORD.host}, ${events.length - host} ${ORIGIN_WORD.model}`,
  };
}

function cellsOf(events: readonly RiskEvent[]): MatrixCell[] {
  const at = (event: RiskEvent, axis: "probability" | "impact") =>
    riskLevel(event[axis]) ?? "Unknown";
  return PROBABILITY.flatMap((probability, row) =>
    IMPACT.map((impact, column) => {
      const held = events.filter(
        (event) => at(event, "probability") === probability && at(event, "impact") === impact,
      );
      const { origin, said } = originOf(held);
      const count = `${held.length} ${held.length === 1 ? "event" : "events"}`;
      return {
        key: `${probability}-${impact}`.toLowerCase(),
        probability,
        impact,
        index: row * IMPACT.length + column,
        events: held,
        origin,
        name: `Probability ${probability}, Impact ${impact}: ${count}, ${idList(held.map(idOf))} (${said})`,
      };
    }),
  );
}

function matrixPlot(cells: readonly MatrixCell[], kit: PlotKit): Plot {
  const width = (kit.width - LEFT - EDGE) / IMPACT.length;
  const right = LEFT + IMPACT.length * width;
  const bottom = TOP + PROBABILITY.length * ROW;
  const tick = (x: number, y: number, label: string, anchor: "start" | "middle" = "middle") => (
    <text key={`${label}-${x}-${y}`} className="chart-tick" x={x} y={y} textAnchor={anchor}>
      {label}
    </text>
  );
  const held = cells.filter((cell) => cell.events.length);
  const chart = (
    <svg {...kit.svg} className="chart-svg" width={kit.width} height={HEIGHT}>
      <HatchPatterns id={kit.patternId} tones={["series-1"]} />
      {tick(0, TOP - 8, "Probability", "start")}
      {PROBABILITY.map((level, row) => tick(0, TOP + row * ROW + ROW / 2 + 4, level, "start"))}
      {IMPACT.map((level, column) => tick(LEFT + (column + 0.5) * width, bottom + 14, level))}
      {tick(LEFT + (right - LEFT) / 2, bottom + 30, "Impact")}
      <g className="chart-grid">
        {[0, 1, 2, 3, 4].map((n) => (
          <line key={`h${n}`} x1={LEFT} x2={right} y1={TOP + n * ROW} y2={TOP + n * ROW} />
        ))}
        {[0, 1, 2, 3, 4].map((n) => (
          <line key={`v${n}`} x1={LEFT + n * width} x2={LEFT + n * width} y1={TOP} y2={bottom} />
        ))}
      </g>
      {cells.map((cell) => {
        const middle = TOP + Math.floor(cell.index / IMPACT.length) * ROW + ROW / 2;
        const centre = LEFT + ((cell.index % IMPACT.length) + 0.5) * width;
        const box = { x: centre - SIDE, y: middle - SIDE / 2, width: SIDE, height: SIDE };
        return (
          <g key={cell.key} data-cell={cell.key}>
            {cell.events.length ? (
              <>
                <BarShape
                  box={box}
                  tone="series-1"
                  origin={cell.origin}
                  hatch={kit.hatch}
                  mark={cell.key}
                />
                <text
                  className="chart-value"
                  data-count=""
                  x={centre + 6}
                  y={middle + VALUE_SIZE / 2 - 2}
                >
                  {cell.events.length}
                </text>
                <Reported
                  mark={{
                    key: cell.key,
                    name: cell.name,
                    box,
                    selection: {
                      series: `Probability ${cell.probability}`,
                      category: `Impact ${cell.impact}`,
                      index: cell.index,
                      value: `${cell.events.length}`,
                      origin: cell.origin,
                    },
                  }}
                />
              </>
            ) : null}
          </g>
        );
      })}
      <Focus />
    </svg>
  );
  return { height: HEIGHT, chart, order: held.map((cell) => cell.key) };
}

function tableOf(events: readonly RiskEvent[]): TableTwin {
  return {
    head: ["Event ID", "Description", "Probability", "Impact", "P/I Classification"],
    rows: events.map((event) => ({
      key: event.key,
      cells: [
        event.label,
        event.description,
        event.probability,
        event.impact,
        event.classification,
      ],
    })),
  };
}

export function RiskMatrix({
  title,
  summary,
  events,
  onSelect,
}: {
  title: string;
  summary: string;
  /** An event a row, in the order given; the table twin lists each as given. */
  events: readonly RiskEvent[];
  onSelect?: OnSelect;
}) {
  const cells = cellsOf(events);
  return (
    <ChartFrame
      kind="risk-matrix"
      title={title}
      summary={summary}
      legend={[]}
      provenance="fill"
      table={tableOf(events)}
      plot={(kit) => matrixPlot(cells, kit)}
      onSelect={onSelect}
    />
  );
}
