// The chart primitives, rendered: a mark drawn and reachable for every value,
// provenance in the mark, a labelled gap for what is unavailable, the exact
// served string in every name, readout and table cell, the table twin, and a
// bridge's residual wherever its steps fall short of a stated total.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import {
  BarChart,
  BulletChart,
  DivergingBarChart,
  DumbbellChart,
  LineChart,
  ProvenanceKeyed,
  RangeStripChart,
  RiskMatrix,
  ScatterChart,
  StackedBarChart,
  Swatch,
  WaterfallChart,
  idList,
  riskLevel,
  type BulletRow,
  type ChartSeries,
  type DumbbellRow,
  type RangeRow,
  type RiskEvent,
  type ScatterPoint,
} from "@/charts";
import { readDate } from "@/charts/ScatterChart";
import { ChartFrame } from "@/charts/ChartFrame";
import { bandPlot, rowMarker, type BandMarker } from "@/charts/band";
import { DOT } from "@/charts/marks";
import { fromScaled, placesOf, readDatum, toScaled } from "@/charts/decimal";
import { cellOf, said } from "@/charts/series";
import { FALLBACK_WIDTH } from "@/charts/scale";
import { useWidth } from "@/charts/use-width";

const PERIODS = ["Q1 2026", "Q2 2026", "Q3 2026"];
const REVENUE: ChartSeries = {
  key: "revenue",
  label: "Revenue",
  origin: "model",
  data: [
    { value: "3100.5" },
    { value: "3412.0" },
    { value: null, reason: "ZERO_OR_NEGATIVE_DENOMINATOR" },
  ],
};
const EBITDA: ChartSeries = {
  key: "ebitda",
  label: "EBITDA",
  origin: "host",
  data: [{ value: "610.25" }, { value: "702.0" }, { value: "688.75" }],
};

const marks = (root: HTMLElement) => [
  ...root.querySelectorAll<HTMLButtonElement>("button.chart-hit"),
];
/** The plot, not the legend's swatches (which draw marks of their own):
    the picture Recharts draws (D61). */
const plotOf = (root: HTMLElement) =>
  root.querySelector(".chart-plot svg[role='img']") as unknown as HTMLElement;
const rects = (root: HTMLElement) => [
  ...plotOf(root).querySelectorAll<SVGRectElement>("rect.chart-bar"),
];
const numberOf = (element: Element | undefined, name: string) =>
  Number(element?.getAttribute(name));

function bars(extra: Partial<Parameters<typeof BarChart>[0]> = {}) {
  return render(
    <BarChart
      title="Revenue and EBITDA"
      summary="Quarterly, first three quarters of 2026."
      unit="USD m"
      categoryLabel="Period"
      categories={PERIODS}
      series={[REVENUE, EBITDA]}
      {...extra}
    />,
  );
}

describe("a bar chart", () => {
  test("draws a bar per value, a labelled gap per unavailable one, and a button per mark", () => {
    const { container } = bars();
    expect(rects(container)).toHaveLength(5);
    const gap = container.querySelector("[data-gap]");
    expect(gap).not.toBeNull();
    expect(within(gap as HTMLElement).getByText("n/a")).toBeInTheDocument();
    expect(marks(container)).toHaveLength(6);
    expect(
      screen.getByRole("button", { name: "Revenue, Q2 2026: 3,412.0 USD m (model-authored)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Revenue, Q3 2026: n/a (ZERO_OR_NEGATIVE_DENOMINATOR)" }),
    ).toBeInTheDocument();
    // The label on the bar is the served string, grouped: never a float's rendering.
    const label = within(plotOf(container)).getByText("3,412.0");
    expect(label).toHaveClass("chart-value");
    // Placed past the bar's end as Recharts drew the bar (`useMarks`, D61).
    const bar = container.querySelector('rect[data-mark="revenue:1"]')!;
    expect(numberOf(label, "y")).toBeLessThan(numberOf(bar, "y"));
  });

  test("is a figure: a captioned picture, drawn at real pixels and never scaled", () => {
    const { container } = bars();
    const caption = container.querySelector("figure > figcaption");
    expect(caption).toHaveTextContent("Revenue and EBITDA");
    expect(caption).toHaveTextContent("Quarterly, first three quarters of 2026.");
    // The caption holds only what names the figure; the toggle sits outside it.
    expect(caption?.querySelector("button")).toBeNull();
    expect(caption).not.toHaveTextContent("Table");
    const picture = screen.getByRole("img", {
      name: "Revenue and EBITDA Quarterly, first three quarters of 2026.",
    });
    // Drawn at its real pixels: the viewBox is the drawing's own size, so
    // nothing is scaled and the text stays at the type floors.
    expect(picture).toHaveAttribute("width", String(FALLBACK_WIDTH));
    expect(picture.getAttribute("viewBox")).toBe(
      `0 0 ${FALLBACK_WIDTH} ${picture.getAttribute("height")}`,
    );
    // Nothing inside the picture is in the tab order: the marks are the
    // buttons over it (Recharts' own layers carry tabindex -1, out of it).
    expect(picture.querySelector("[tabindex]:not([tabindex='-1']), button, a")).toBeNull();
    expect(container.querySelector("style")).toBeNull();
    expect(container.querySelector(".chart-zero")).not.toBeNull();
  });

  test("draws provenance in the mark: the host solid, the model outlined and hatched", () => {
    const { container } = bars();
    const host = container.querySelector('rect[data-mark="ebitda:0"]');
    expect(host).toHaveClass("chart-host", "chart-tone-series-2");
    expect(host).not.toHaveAttribute("fill");
    const model = container.querySelector('rect[data-mark="revenue:0"]');
    expect(model).toHaveClass("chart-outline", "chart-tone-series-1");
    const fill = model?.getAttribute("fill") ?? "";
    expect(fill).toMatch(/^url\(#.+\)$/);
    expect(container.querySelector(`pattern[id="${fill.slice(5, -1)}"]`)).not.toBeNull();
    expect(screen.getByText("Solid: host-verified")).toBeInTheDocument();
    expect(screen.getByText("Outlined: model-authored, not host-verified")).toBeInTheDocument();
    // Two series: a legend names both, beside the provenance key.
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Revenue")).toBeInTheDocument();
    expect(within(legend).getByText("EBITDA")).toBeInTheDocument();
  });

  test("a page that keys provenance once turns each chart's own key off", () => {
    render(
      <ProvenanceKeyed value={false}>
        <BarChart
          title="Revenue and EBITDA"
          summary="Quarterly."
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
      </ProvenanceKeyed>,
    );
    expect(screen.queryByText("Solid: host-verified")).toBeNull();
    // The series legend stays: it says which colour is which, not who wrote it.
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Revenue")).toBeInTheDocument();
  });

  test("stands up or runs along: value is height upright and width sideways", () => {
    const upright = rects(bars({ series: [EBITDA] }).container);
    expect(new Set(upright.map((rect) => numberOf(rect, "width"))).size).toBe(1);
    const tall = upright.map((rect) => numberOf(rect, "height"));
    expect(tall[1]).toBeGreaterThan(tall[2] ?? Infinity);
    expect(tall[2]).toBeGreaterThan(tall[0] ?? Infinity);

    const sideways = rects(bars({ series: [EBITDA], orientation: "horizontal" }).container);
    expect(new Set(sideways.map((rect) => numberOf(rect, "height"))).size).toBe(1);
    const long = sideways.map((rect) => numberOf(rect, "width"));
    expect(long[1]).toBeGreaterThan(long[2] ?? Infinity);
    expect(long[2]).toBeGreaterThan(long[0] ?? Infinity);
  });

  test("has a table twin of the exact data, one toggle away", () => {
    bars();
    const toggle = screen.getByRole("button", { name: "Table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("img")).toBeNull();
    const table = screen.getByRole("table", { name: "Revenue and EBITDA" });
    const cells = within(table)
      .getAllByRole("row")
      .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent));
    expect(cells).toEqual([
      ["Period", "Revenue, USD m (model-authored)", "EBITDA, USD m (host-verified)"],
      ["Q1 2026", "3,100.5", "610.25"],
      ["Q2 2026", "3,412.0", "702.0"],
      ["Q3 2026", "n/a: ZERO_OR_NEGATIVE_DENOMINATOR", "688.75"],
    ]);
    expect(within(table).getAllByRole("rowheader")).toHaveLength(3);
    fireEvent.click(toggle);
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  test("selects from the keyboard: a native button Tab reaches and Enter or Space presses", () => {
    const onSelect = vi.fn();
    const { container } = bars({ onSelect });
    const readout = container.querySelector("[data-readout]");
    const mark = screen.getByRole("button", {
      name: "EBITDA, Q2 2026: 702.0 USD m (host-verified)",
    });
    // Enter and Space activate a native button as a click; jsdom does not
    // synthesise that click, so the press below is the click they fire.
    expect(mark.tagName).toBe("BUTTON");
    expect(mark).toHaveAttribute("type", "button");
    // One Tab stop per chart: the first mark, until another is focused; the
    // arrow keys move between marks in reading order.
    expect(marks(container).map((button) => button.tabIndex)).toEqual([0, -1, -1, -1, -1, -1]);
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowRight" });
    expect(document.activeElement).toBe(marks(container)[1]);
    expect(marks(container)[1]!.tabIndex).toBe(0);
    fireEvent.keyDown(marks(container)[1]!, { key: "End" });
    expect(document.activeElement).toBe(marks(container).at(-1));
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(document.activeElement).toBe(marks(container)[0]);
    // Reading order: category by category, and series by series within one.
    expect(marks(container).map((button) => button.dataset.mark)).toEqual([
      "revenue:0",
      "ebitda:0",
      "revenue:1",
      "ebitda:1",
      "revenue:2",
      "ebitda:2",
    ]);
    act(() => mark.focus());
    expect(document.activeElement).toBe(mark);
    expect(readout).toHaveTextContent("EBITDA, Q2 2026: 702.0 USD m (host-verified)");
    fireEvent.click(mark);
    expect(onSelect).toHaveBeenCalledWith(
      { series: "ebitda", category: "Q2 2026", index: 1, value: "702.0", origin: "host" },
      mark,
    );
    expect(mark).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector(".chart-ring")).not.toBeNull();
    // The readout keeps the selection when focus leaves, and hover shows what focus does.
    act(() => mark.blur());
    expect(readout).toHaveTextContent("702.0");
    const other = screen.getByRole("button", { name: /^Revenue, Q1 2026/ });
    fireEvent.mouseEnter(other);
    expect(readout).toHaveTextContent("Revenue, Q1 2026: 3,100.5 USD m (model-authored)");
    fireEvent.mouseLeave(other);
    expect(readout).toHaveTextContent("702.0");
  });

  test("keeps every target at least 24px, however thin its bar", () => {
    const { container } = bars();
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

describe("a line chart", () => {
  const series: ChartSeries[] = [
    {
      key: "revenue",
      label: "Revenue",
      origin: "host",
      data: [
        { value: "10" },
        { value: "12" },
        { value: null, reason: "NOT_DISCLOSED" },
        { value: "15" },
      ],
    },
    {
      key: "forecast",
      label: "Forecast",
      origin: "model",
      data: [{ value: "9.5" }, { value: "11.25" }, { value: "13" }, { value: "14.5" }],
    },
  ];
  const quarters = ["Q1", "Q2", "Q3", "Q4"];

  test("breaks at a missing value and never draws one in", () => {
    const { container } = render(
      <LineChart
        title="Revenue"
        summary="Actual and forecast."
        unit="USD m"
        categories={quarters}
        series={series}
      />,
    );
    const d = container.querySelector('path[data-series="revenue"]')?.getAttribute("d") ?? "";
    const runs = d.split("M").filter(Boolean);
    // Q1-Q2 is one run; Q4 stands alone. Nothing joins Q2 to Q4 across the gap.
    expect(runs).toHaveLength(2);
    expect(runs[0]).toContain("L");
    expect(runs[1]).not.toContain("L");
    expect(plotOf(container).querySelectorAll("circle.chart-point")).toHaveLength(7);
    expect(container.querySelectorAll("[data-gap]")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Revenue, Q3: n/a (NOT_DISCLOSED)" }),
    ).toBeInTheDocument();
  });

  test("dashes the model's line and hollows its points", () => {
    const { container } = render(
      <LineChart
        title="Revenue"
        summary="Actual and forecast."
        categories={quarters}
        series={series}
      />,
    );
    expect(container.querySelector('path[data-series="forecast"]')).toHaveClass("chart-dashed");
    expect(container.querySelector('path[data-series="revenue"]')).not.toHaveClass("chart-dashed");
    expect(container.querySelector('circle[data-mark="forecast:0"]')).toHaveClass("chart-hollow");
    expect(container.querySelector('circle[data-mark="revenue:0"]')).not.toHaveClass(
      "chart-hollow",
    );
    expect(
      screen.getByText("Dashed line, hollow point: model-authored, not host-verified"),
    ).toBeInTheDocument();
  });

  test("reads out every series at the period a point stands on", () => {
    const { container } = render(
      <LineChart
        title="Revenue"
        summary="Actual and forecast."
        unit="USD m"
        categories={quarters}
        series={series}
      />,
    );
    act(() => screen.getByRole("button", { name: /^Forecast, Q3/ }).focus());
    expect(container.querySelector("[data-readout]")).toHaveTextContent(
      "Q3: Revenue n/a (NOT_DISCLOSED); Forecast 13 USD m (model-authored)",
    );
    expect(container.querySelector(".chart-guide")).not.toBeNull();
  });
});

describe("a stacked bar chart", () => {
  const segments: ChartSeries[] = [
    { key: "retail", label: "Retail", origin: "host", data: [{ value: "1200.0" }] },
    { key: "wholesale", label: "Wholesale", origin: "host", data: [{ value: "800.5" }] },
    { key: "online", label: "Online", origin: "model", data: [{ value: "450.25" }] },
  ];

  test("normalised, prints shares that sum to exactly 100.0 and fills to 100%", () => {
    // Rounded one by one, these shares would print 49.0 + 32.7 + 18.4 = 100.1.
    const naive = ["1200.0", "800.5", "450.25"].map((value) =>
      ((Number(value) / 2450.75) * 100).toFixed(1),
    );
    expect(naive).toEqual(["49.0", "32.7", "18.4"]);
    const { container } = render(
      <StackedBarChart
        mode="normalised"
        title="Segment mix"
        summary="FY2025 revenue by segment."
        unit="USD m"
        categories={["FY2025"]}
        series={segments}
      />,
    );
    const shares = marks(container).map(
      (button) =>
        /, ([\d.]+)% of the whole/.exec(button.getAttribute("aria-label") ?? "")?.[1] ?? "",
    );
    expect(shares).toEqual(["49.0", "32.6", "18.4"]);
    const places = Math.max(...shares.map(placesOf));
    const total = shares.reduce((sum, share) => sum + toScaled(share, places), 0n);
    expect(fromScaled(total, places)).toBe("100.0");
    // The stack's top meets the 100% gridline; the top segment is the model's,
    // whose outlined edge is drawn half its 1.5px stroke inside the mark's box.
    const gridlines = [...container.querySelectorAll("line.chart-grid")].map((line) =>
      numberOf(line, "y1"),
    );
    const top = Math.min(...rects(container).map((rect) => numberOf(rect, "y")));
    expect(top - Math.min(...gridlines)).toBe(0.75);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  test("absolute, hangs a negative below zero and prints each stack's exact total", () => {
    const { container } = render(
      <StackedBarChart
        title="Debt stack"
        summary="FY2025 by seniority."
        unit="USD m"
        categories={["FY2025"]}
        series={[
          {
            key: "1l",
            label: "First lien",
            origin: "host",
            color: "tranche-1l",
            data: [{ value: "10.5" }],
          },
          {
            key: "2l",
            label: "Second lien",
            origin: "host",
            color: "tranche-2l",
            data: [{ value: "4.25" }],
          },
          {
            key: "cash",
            label: "Cash",
            origin: "host",
            color: "tranche-eq",
            data: [{ value: "-1.75" }],
          },
        ]}
      />,
    );
    expect(container.querySelector('rect[data-mark="1l:0"]')).toHaveClass("chart-tone-tranche-1l");
    expect(within(plotOf(container)).getByText("13.00")).toBeInTheDocument();
    const zero = numberOf(container.querySelector(".chart-zero") ?? undefined, "y1");
    const cash = container.querySelector('rect[data-mark="cash:0"]') ?? undefined;
    expect(numberOf(cash, "y")).toBeGreaterThanOrEqual(zero);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("columnheader", { name: "Total, USD m" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "13.00" })).toBeInTheDocument();
  });
});

test("a count's table twin heads its columns as computed, as its marks are named", () => {
  render(
    <StackedBarChart
      title="Issues"
      summary="Counted."
      unit="issues"
      unitOne="issue"
      computed="a count of the model's rows"
      categories={["CP-5"]}
      series={[{ key: "high", label: "High", origin: "model", data: [{ value: "2" }] }]}
    />,
  );
  expect(screen.getByRole("button", { name: /High, CP-5: 2 issues/ })).toHaveAccessibleName(
    "High, CP-5: 2 issues (a count of the model's rows)",
  );
  fireEvent.click(screen.getByRole("button", { name: "Table" }));
  expect(
    screen.getByRole("columnheader", { name: "High, issues (a count of the model's rows)" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: /model-authored/ })).toBeNull();
});

test("two unavailable segments of one stack are marked apart, never over each other", () => {
  const { container } = render(
    <StackedBarChart
      title="Mix"
      summary="Two segments unavailable."
      categories={["FY2025"]}
      series={[
        { key: "a", label: "A", origin: "host", data: [{ value: "5" }] },
        { key: "b", label: "B", origin: "host", data: [{ value: null, reason: "NOT_SERVED" }] },
        { key: "c", label: "C", origin: "host", data: [{ value: null, reason: "NOT_SERVED" }] },
      ]}
    />,
  );
  const ticks = [...plotOf(container).querySelectorAll("[data-gap] line")].map((line) =>
    numberOf(line, "y1"),
  );
  expect(ticks).toHaveLength(2);
  expect(new Set(ticks).size).toBe(2);
});

describe("a waterfall chart", () => {
  test("draws an Unreconciled residual, exact, where the steps fall short of a total", () => {
    const { container } = render(
      <WaterfallChart
        title="Adjusted EBITDA bridge"
        summary="FY2025, reported to adjusted."
        unit="USD m"
        steps={[
          { label: "Reported EBITDA", kind: "total", value: "100.0", origin: "host" },
          { label: "Restructuring", kind: "delta", value: "12.5", origin: "model" },
          { label: "FX", kind: "delta", value: "-3.25", origin: "host" },
          { label: "Adjusted EBITDA", kind: "total", value: "110.00", origin: "model" },
        ]}
      />,
    );
    const note = "Does not reconcile: +0.75 USD m unexplained before Adjusted EBITDA.";
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(
      `Adjusted EBITDA bridge FY2025, reported to adjusted. ${note}`,
    );
    const residual = container.querySelector('rect[data-origin="residual"]');
    expect(residual).toHaveClass("chart-tone-residual");
    expect(
      screen.getByRole("button", {
        name: "Unreconciled before Adjusted EBITDA: +0.75 USD m, the stated total less the running level: computed here, not served",
      }),
    ).toBeInTheDocument();
    const svg = plotOf(container);
    expect(within(svg).getByText("+0.75")).toHaveClass("chart-alarm");
    expect(within(svg).getByText("-3.25")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Restructuring: +12.5 USD m, running level 112.50 (model-authored)",
      }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("line.chart-connector")).toHaveLength(4);
  });

  test("closes 0.1 + 0.2 on a stated 0.3 with no residual", () => {
    const { container } = render(
      <WaterfallChart
        title="Bridge"
        summary="Closes exactly."
        steps={[
          { label: "Opening", kind: "total", value: "0", origin: "host" },
          { label: "Price", kind: "delta", value: "0.1", origin: "host" },
          { label: "Volume", kind: "delta", value: "0.2", origin: "host" },
          { label: "Closing", kind: "total", value: "0.3", origin: "host" },
        ]}
      />,
    );
    expect(container.querySelector("[data-chart-note]")).toBeNull();
    expect(container.querySelector('rect[data-origin="residual"]')).toBeNull();
    expect(rects(container)).toHaveLength(4);
  });

  test("a step's colour says its status, and the status word is in its name and its row", () => {
    const { container } = render(
      <WaterfallChart
        title="Quality bridge"
        summary="Reported to adjusted."
        steps={[
          { key: "0", label: "Reported", kind: "total", value: "50", origin: "model" },
          {
            key: "1",
            label: "Restructuring",
            kind: "delta",
            value: "4",
            origin: "model",
            color: "series-3",
            status: "Challenged",
          },
          {
            key: "2",
            label: "Synergies",
            kind: "delta",
            value: "6",
            origin: "model",
            color: "negative",
            status: "Rejected",
          },
          { key: "3", label: "Adjusted", kind: "total", value: "60", origin: "model" },
        ]}
        statuses={[
          { color: "series-3", label: "Challenged" },
          { color: "negative", label: "Rejected" },
        ]}
      />,
    );
    // The colour overrides the pole's: a rejected increase is not green.
    const tones = rects(container).map((rect) => rect.getAttribute("class"));
    expect(tones[1]).toContain("chart-tone-series-3");
    expect(tones[2]).toContain("chart-tone-negative");
    expect(tones[2]).not.toContain("chart-tone-positive");
    expect(
      screen.getByRole("button", {
        name: "Synergies: +6, running level 60, Rejected (model-authored)",
      }),
    ).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Challenged")).toBeInTheDocument();
    expect(within(legend).getByText("Rejected")).toBeInTheDocument();
    expect(within(legend).queryByText("Increase")).toBeNull();
    expect(within(legend).queryByText("Decrease")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const rows = within(screen.getByRole("table"))
      .getAllByRole("row")
      .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent));
    expect(rows[0]).toEqual(["Step", "Kind", "Amount", "Running level", "Status", "Origin"]);
    expect(rows[2]).toEqual([
      "Restructuring",
      "change",
      "+4",
      "54",
      "Challenged",
      "model-authored",
    ]);
    expect(rows[1]).toEqual(["Reported", "stated total", "50", "50", "", "model-authored"]);
  });

  test("a step's note follows its amount in its name and its row", () => {
    render(
      <WaterfallChart
        title="Liquidity bridge"
        summary="Beginning to ending."
        steps={[
          { label: "Beginning", kind: "total", value: "50", origin: "model" },
          {
            label: "Cash interest",
            kind: "delta",
            value: "-5",
            origin: "model",
            note: "served 5, a use the method subtracts",
          },
        ]}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: "Cash interest: -5 (served 5, a use the method subtracts), running level 45 (model-authored)",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect([...(rows[2] as HTMLTableRowElement).cells].map((cell) => cell.textContent)).toEqual([
      "Cash interest",
      "change",
      "-5 (served 5, a use the method subtracts)",
      "45",
      "model-authored",
    ]);
  });

  test("a step of no known status keeps its pole, and the legend keeps the poles for it", () => {
    const { container } = render(
      <WaterfallChart
        title="Quality bridge"
        summary="Reported to adjusted."
        steps={[
          { label: "Reported", kind: "total", value: "50", origin: "model" },
          { label: "Other", kind: "delta", value: "-2", origin: "model", status: "Pending" },
        ]}
        statuses={[]}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Other: -2, running level 48, Pending (model-authored)" }),
    ).toBeInTheDocument();
    expect(rects(container)[1]).toHaveClass("chart-tone-negative");
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Decrease")).toBeInTheDocument();
  });

  test("an uncoloured change with no value is a gap, not a pole: the legend keeps no poles", () => {
    render(
      <WaterfallChart
        title="Quality bridge"
        summary="Reported to adjusted."
        steps={[
          { label: "Reported", kind: "total", value: "50", origin: "model" },
          {
            label: "Savings",
            kind: "delta",
            value: "3",
            origin: "model",
            color: "series-3",
            status: "Challenged",
          },
          {
            label: "Other",
            kind: "delta",
            value: null,
            reason: "Not quantified",
            origin: "model",
            status: "Pending",
          },
        ]}
        statuses={[{ color: "series-3", label: "Challenged" }]}
      />,
    );
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Challenged")).toBeInTheDocument();
    expect(within(legend).queryByText("Increase")).toBeNull();
    expect(within(legend).queryByText("Decrease")).toBeNull();
  });
});

describe("a diverging bar chart", () => {
  test("wraps a long category name to two lines rather than cutting it (brief 6.4)", () => {
    const { container } = render(
      <DivergingBarChart
        title="Add-backs to EBITDA"
        summary="Net +11 USD m across 2 add-backs."
        unit="USD m"
        categoryLabel="Add-back"
        categories={["Share-based compensation and related payroll taxes", "Other"]}
        series={{
          key: "addback",
          label: "Add-back",
          origin: "model",
          data: [{ value: "27" }, { value: "-6" }],
        }}
      />,
    );
    const ticks = [...plotOf(container).querySelectorAll("text.chart-tick")];
    const wrapped = ticks.find((tick) => tick.querySelectorAll("tspan").length === 2);
    expect(wrapped).toBeDefined();
    expect(wrapped!.textContent).not.toContain("…");
    expect([...wrapped!.querySelectorAll("tspan")].map((line) => line.textContent)).toEqual([
      "Share-based compensation and",
      "related payroll taxes",
    ]);
  });

  test("carries the sign in position, pole and every label", () => {
    const { container } = render(
      <DivergingBarChart
        title="Actual less model"
        summary="FY2025 variance by line item."
        unit="USD m"
        categoryLabel="Line item"
        categories={["Revenue", "EBITDA", "Capex"]}
        series={{
          key: "variance",
          label: "Actual less model",
          origin: "host",
          data: [{ value: "12.5" }, { value: "-3.25" }, { value: "0.0" }],
        }}
      />,
    );
    expect(container.querySelector('rect[data-mark="variance:0"]')).toHaveClass(
      "chart-tone-positive",
    );
    expect(container.querySelector('rect[data-mark="variance:1"]')).toHaveClass(
      "chart-tone-negative",
    );
    expect(container.querySelector('rect[data-mark="variance:2"]')).toHaveClass(
      "chart-tone-neutral",
    );
    const svg = plotOf(container);
    expect(within(svg).getByText("+12.5")).toBeInTheDocument();
    expect(within(svg).getByText("-3.25")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Actual less model, EBITDA: -3.25 USD m (host-verified)",
      }),
    ).toBeInTheDocument();
    const zero = numberOf(container.querySelector(".chart-zero") ?? undefined, "x1");
    const below = container.querySelector('rect[data-mark="variance:1"]') ?? undefined;
    expect(numberOf(below, "x") + numberOf(below, "width")).toBeCloseTo(zero);
  });
});

// Made-up tests and values: no real issuer's figures (N191).
const TESTS: BulletRow[] = [
  {
    key: "lev",
    label: "Net leverage",
    direction: "max",
    threshold: { value: "4.50" },
    current: { value: "3.25" },
    headroom: { value: "1.25" },
    origin: "model",
  },
  {
    key: "icr",
    label: "Interest cover",
    direction: "min",
    threshold: { value: "2.00" },
    current: { value: null, reason: "NOT_DISCLOSED" },
    headroom: { value: null, reason: "NOT_DISCLOSED" },
    origin: "host",
  },
  {
    key: "fcc",
    label: "Fixed charge cover",
    direction: null,
    threshold: { value: null, reason: "PACKED_CELL" },
    current: { value: "1.8" },
    headroom: { value: "-0.20" },
    origin: "host",
  },
];

function bullets(extra: Partial<Parameters<typeof BulletChart>[0]> = {}) {
  return render(
    <BulletChart
      title="Covenant headroom"
      summary="Three tests against their thresholds."
      unit="x"
      rows={TESTS}
      {...extra}
    />,
  );
}

describe("a bullet chart", () => {
  test("names each mark with its row, both values, the headroom as served and its origin", () => {
    const { container } = bullets();
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Net leverage: current basis 3.25 x against a ceiling of 4.50 x, headroom 1.25 (model-authored)",
      "Net leverage: ceiling 4.50 x against a current basis of 3.25 x, headroom 1.25 (model-authored)",
      "Interest cover: current basis n/a (NOT_DISCLOSED) against a floor of 2.00 x, headroom n/a (NOT_DISCLOSED) (host-verified)",
      "Interest cover: floor 2.00 x against a current basis of n/a (NOT_DISCLOSED), headroom n/a (NOT_DISCLOSED) (host-verified)",
      "Fixed charge cover: current basis 1.8 x against a threshold of n/a (PACKED_CELL), headroom -0.20 (host-verified)",
      "Fixed charge cover: threshold n/a (PACKED_CELL) against a current basis of 1.8 x, headroom -0.20 (host-verified)",
    ]);
    // The readout says what the name says, headroom included.
    act(() => marks(container)[1]!.focus());
    expect(container.querySelector("[data-readout]")).toHaveTextContent(
      "Net leverage: ceiling 4.50 x against a current basis of 3.25 x, headroom 1.25 (model-authored)",
    );
    // Each row is labelled with its direction.
    const ticks = [...plotOf(container).querySelectorAll("text.chart-tick")].map((tick) => {
      const lines = [...tick.querySelectorAll("tspan")].map((line) => line.textContent);
      return lines.length ? lines.join(" ") : tick.textContent;
    });
    expect(ticks).toEqual(
      expect.arrayContaining([
        "Net leverage, ceiling",
        "Interest cover, floor",
        "Fixed charge cover, direction not stated",
      ]),
    );
    expect(container.querySelector("figure")).toHaveAttribute("data-chart", "bullet");
  });

  test("draws the current basis as a bar from zero and the threshold as a rule across its row", () => {
    const { container } = bullets();
    const bar = container.querySelector('rect[data-mark="lev:current"]');
    // The model's bar is outlined and hatched; the model's rule is dashed.
    expect(bar).toHaveClass("chart-outline", "chart-tone-series-1");
    const rule = container.querySelector('line[data-mark="lev:threshold"]');
    expect(rule).toHaveClass("chart-rule", "chart-tone-neutral", "chart-dashed");
    expect(rule).toHaveAttribute("data-origin", "model");
    const host = container.querySelector('line[data-mark="icr:threshold"]');
    expect(host).toHaveClass("chart-rule");
    expect(host).not.toHaveClass("chart-dashed");
    expect(host).toHaveAttribute("data-origin", "host");
    // Across the row: perpendicular to the value axis, standing past its bar.
    expect(numberOf(rule ?? undefined, "x1")).toBe(numberOf(rule ?? undefined, "x2"));
    const top = numberOf(rule ?? undefined, "y1");
    const foot = numberOf(rule ?? undefined, "y2");
    // The bar is thinner than its rule, which reads at least 4px past each
    // side of it (the model's outline is inset a further 0.75px).
    expect(numberOf(bar ?? undefined, "y") - top).toBeGreaterThanOrEqual(4);
    expect(
      foot - numberOf(bar ?? undefined, "y") - numberOf(bar ?? undefined, "height"),
    ).toBeGreaterThanOrEqual(4);
    // The rule stands at 4.50 past the bar's end at 3.25, the bar from zero.
    const zero = numberOf(container.querySelector(".chart-zero") ?? undefined, "x1");
    // The model's outlined edge is drawn half its 1.5px stroke inside the box.
    expect(numberOf(bar ?? undefined, "x") - 0.75).toBeCloseTo(zero);
    expect(numberOf(rule ?? undefined, "x1")).toBeGreaterThan(
      numberOf(bar ?? undefined, "x") + numberOf(bar ?? undefined, "width"),
    );
    // The bar's exact value labels it; headroom is never drawn.
    const svg = plotOf(container);
    expect(within(svg).getByText("3.25")).toHaveClass("chart-value");
    expect(within(svg).queryByText("1.25")).toBeNull();
    expect(rects(container)).toHaveLength(2);
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Current basis")).toBeInTheDocument();
    expect(within(legend).getByText("Threshold")).toBeInTheDocument();
    // The threshold is keyed as the rule it is: no point on it.
    const key = within(legend).getByText("Threshold");
    expect(key.querySelector("line.chart-rule")).not.toBeNull();
    expect(key.querySelector("circle")).toBeNull();
  });

  test("leaves out a value label the rule would cross: the name still says it", () => {
    const { container } = bullets({
      rows: [{ ...TESTS[0]!, current: { value: "4.40" }, headroom: { value: "0.10" } }],
    });
    expect(within(plotOf(container)).queryByText("4.40")).toBeNull();
    expect(
      screen.getByRole("button", { name: /^Net leverage: current basis 4\.40 x/ }),
    ).toBeInTheDocument();
  });

  test("marks an unavailable current basis or threshold n/a in its row, with its reason", () => {
    const { container } = bullets();
    const gaps = [...container.querySelectorAll<SVGGElement>("[data-gap]")];
    expect(gaps.map((gap) => gap.dataset.mark)).toEqual(["icr:current", "fcc:threshold"]);
    for (const gap of gaps)
      expect(within(gap as unknown as HTMLElement).getByText("n/a")).toBeInTheDocument();
    // Neither is drawn as a zero: no bar for the one, no rule for the other.
    expect(container.querySelector('rect[data-mark="icr:current"]')).toBeNull();
    expect(container.querySelector('line[data-mark="fcc:threshold"]')).toBeNull();
    // A row with both unavailable marks the two apart, never one over the other.
    const both = render(
      <BulletChart
        title="Both"
        summary="Nothing served."
        rows={[
          {
            key: "dscr",
            label: "Debt service cover",
            direction: "min",
            threshold: { value: null, reason: "NOT_SERVED" },
            current: { value: null, reason: "NOT_SERVED" },
            headroom: { value: null, reason: "NOT_SERVED" },
            origin: "host",
          },
        ]}
      />,
    ).container;
    const ticks = [...plotOf(both).querySelectorAll("[data-gap] line")].map((line) =>
      numberOf(line, "x1"),
    );
    expect(ticks).toHaveLength(2);
    expect(new Set(ticks).size).toBe(2);
  });

  test("has a table twin of the rows as served, headroom included", () => {
    bullets();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table", { name: "Covenant headroom" });
    const cells = within(table)
      .getAllByRole("row")
      .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent));
    expect(cells).toEqual([
      ["Test", "Direction", "Threshold, x", "Current basis, x", "Headroom, x", "Origin"],
      ["Net leverage", "ceiling", "4.50", "3.25", "1.25", "model-authored"],
      [
        "Interest cover",
        "floor",
        "2.00",
        "n/a: NOT_DISCLOSED",
        "n/a: NOT_DISCLOSED",
        "host-verified",
      ],
      [
        "Fixed charge cover",
        "direction not stated",
        "n/a: PACKED_CELL",
        "1.8",
        "-0.20",
        "host-verified",
      ],
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    bullets({ categoryLabel: "Trigger", unit: undefined });
    fireEvent.click(screen.getAllByRole("button", { name: "Table" })[1]!);
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Trigger", "Direction", "Threshold", "Current basis", "Headroom", "Origin"]);
  });

  test("takes the bar, then the rule, row by row, from the keyboard; every target 24px", () => {
    const onSelect = vi.fn();
    const { container } = bullets({ onSelect });
    expect(marks(container).map((button) => button.dataset.mark)).toEqual([
      "lev:current",
      "lev:threshold",
      "icr:current",
      "icr:threshold",
      "fcc:current",
      "fcc:threshold",
    ]);
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marks(container)[1]);
    fireEvent.keyDown(marks(container)[1]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marks(container)[2]);
    fireEvent.click(marks(container)[1]!);
    expect(onSelect).toHaveBeenCalledWith(
      { series: "threshold", category: "Net leverage", index: 0, value: "4.50", origin: "model" },
      marks(container)[1],
    );
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

describe("a band chart's markers", () => {
  test("rowMarker names a row's value for its part and keeps its own origin over its row's", () => {
    const row = { key: "lev", label: "Net leverage", origin: "model" as const };
    const value = readDatum({ value: "3.25", origin: "host" });
    expect(
      rowMarker(row, 2, "median", "median", value, "x", { tone: "neutral", shape: "rule" }),
    ).toEqual({
      key: "lev:median",
      category: 2,
      at: 3.25,
      tone: "neutral",
      shape: "rule",
      origin: "host",
      gap: false,
      name: "Net leverage: median 3.25 x (host-verified)",
      selection: {
        series: "median",
        category: "Net leverage",
        index: 2,
        value: "3.25",
        origin: "host",
      },
    });
    const gap = rowMarker(
      row,
      0,
      "to",
      "Realized",
      readDatum({ value: null, reason: "NOT_REPORTED" }),
      "%",
      {
        tone: "series-1",
        shape: "dot",
      },
    );
    expect([gap.gap, gap.at, gap.origin, gap.name]).toEqual([
      true,
      0,
      "model",
      "Net leverage: Realized n/a (NOT_REPORTED) (model-authored)",
    ]);
  });

  // A dot marker, as the range strip and the dumbbell will draw one.
  const dot = (origin: "host" | "model", at: number, gap = false): BandMarker => ({
    key: `dot-${origin}`,
    category: origin === "host" ? 0 : 1,
    at,
    tone: "series-3",
    origin,
    gap,
    shape: "dot",
    name: `Dot, ${origin}`,
    selection: { series: "dot", category: origin, index: 0, value: null, origin },
  });
  const plot = (markers: readonly BandMarker[]) =>
    render(
      <ChartFrame
        kind="markers"
        title="Markers"
        summary="Dots."
        legend={[]}
        provenance="line"
        table={{ head: ["Row"], rows: [] }}
        plot={(kit) =>
          bandPlot(
            { orientation: "horizontal", categories: ["A", "B"], slots: 1, bars: [], markers },
            kit,
          )
        }
      />,
    ).container;

  test("draws a dot filled for the host and hollow for the model, its target 24px and round", () => {
    const container = plot([dot("host", 3), dot("model", 7)]);
    const host = container.querySelector('circle[data-mark="dot-host"]');
    const model = container.querySelector('circle[data-mark="dot-model"]');
    expect(host).toHaveClass("chart-point", "chart-tone-series-3");
    expect(host).not.toHaveClass("chart-hollow");
    expect(model).toHaveClass("chart-point", "chart-hollow");
    expect(numberOf(host ?? undefined, "r")).toBe(DOT);
    // The marker counts in the value axis: 7 lies inside the plot, past 3.
    expect(numberOf(model ?? undefined, "cx")).toBeGreaterThan(numberOf(host ?? undefined, "cx"));
    expect(numberOf(model ?? undefined, "cx")).toBeLessThanOrEqual(FALLBACK_WIDTH - 8);
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Dot, host",
      "Dot, model",
    ]);
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
    fireEvent.click(marks(container)[0]!);
    expect(container.querySelector("circle.chart-ring")).not.toBeNull();
  });

  test("an unavailable marker is a labelled gap, and its value never sets the axis", () => {
    const container = plot([dot("host", 3), dot("model", 1000, true)]);
    expect(container.querySelector('circle[data-mark="dot-model"]')).toBeNull();
    expect(container.querySelector('[data-gap][data-mark="dot-model"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: "Dot, model" })).toBeInTheDocument();
    const ticks = [...plotOf(container).querySelectorAll("text.chart-tick")].map(
      (tick) => tick.textContent,
    );
    expect(ticks).not.toContain("1,000");
  });
});

// Made-up peer ranges: one row per metric, every statistic declared.
const PEERS: RangeRow[] = [
  {
    key: "ev",
    label: "EV / EBITDA",
    min: { value: "5.0" },
    q1: { value: "6.25" },
    median: { value: "7.5", origin: "model" },
    q3: { value: "8.75" },
    max: { value: "11.0" },
    marker: { value: "9.1" },
    origin: "host",
  },
  {
    key: "lev",
    label: "Net leverage",
    min: { value: "2.0" },
    q1: { value: null, reason: "NOT_DISCLOSED" },
    median: { value: "3.5" },
    q3: { value: "4.0" },
    max: { value: "5.25" },
    marker: { value: null, reason: "PEER_ONLY" },
    origin: "model",
  },
];
// Made-up implied values by method: no quartiles declared, one median absent.
const METHODS: RangeRow[] = [
  {
    key: "trading",
    label: "Trading multiples",
    min: { value: "800" },
    median: { value: "950" },
    max: { value: "1100" },
    marker: { value: "990" },
    origin: "host",
  },
  {
    key: "deals",
    label: "Precedent deals",
    min: { value: "900" },
    max: { value: "1250.5" },
    marker: { value: "1000" },
    origin: "model",
  },
];

function strips(extra: Partial<Parameters<typeof RangeStripChart>[0]> = {}) {
  return render(
    <RangeStripChart
      title="Peer ranges"
      summary="The borrower against its peers."
      unit="x"
      rows={PEERS}
      {...extra}
    />,
  );
}

describe("a range strip", () => {
  test("names each mark with its metric, statistic, exact value and unit, and origin", () => {
    const { container } = strips();
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "EV / EBITDA: interquartile range 6.25 x to 8.75 x (host-verified)",
      "EV / EBITDA: min 5.0 x (host-verified)",
      "EV / EBITDA: median 7.5 x (model-authored)",
      "EV / EBITDA: max 11.0 x (host-verified)",
      "EV / EBITDA: Borrower 9.1 x (host-verified)",
      "Net leverage: interquartile range n/a (Q1: NOT_DISCLOSED) (model-authored)",
      "Net leverage: min 2.0 x (model-authored)",
      "Net leverage: median 3.5 x (model-authored)",
      "Net leverage: max 5.25 x (model-authored)",
      "Net leverage: Borrower n/a (PEER_ONLY) (model-authored)",
    ]);
    expect(container.querySelector("figure")).toHaveAttribute("data-chart", "range");
  });

  test("floats the interquartile bar from Q1 to Q3, rules min, median and max, dots the marker", () => {
    const { container } = strips();
    const bar = container.querySelector('rect[data-mark="ev:iqr"]');
    expect(bar).toHaveClass("chart-host", "chart-tone-series-1");
    // An interval, not a magnitude: it starts at Q1, clear of zero, and the
    // axis still holds zero.
    const zero = numberOf(container.querySelector(".chart-zero") ?? undefined, "x1");
    const at = (key: string) =>
      numberOf(container.querySelector(`[data-mark="${key}"]`) ?? undefined, "x1");
    const left = numberOf(bar ?? undefined, "x");
    const right = left + numberOf(bar ?? undefined, "width");
    expect(left).toBeGreaterThan(zero + 1);
    expect(at("ev:min")).toBeLessThan(left);
    expect(at("ev:median")).toBeGreaterThan(left);
    expect(at("ev:median")).toBeLessThan(right);
    expect(at("ev:max")).toBeGreaterThan(right);
    // Each statistic a rule in neutral, dashed where the model authored it.
    for (const key of ["ev:min", "ev:max"]) {
      const rule = container.querySelector(`line[data-mark="${key}"]`);
      expect(rule).toHaveClass("chart-rule", "chart-tone-neutral");
      expect(rule).not.toHaveClass("chart-dashed");
    }
    expect(container.querySelector('line[data-mark="ev:median"]')).toHaveClass("chart-dashed");
    expect(container.querySelector('line[data-mark="lev:min"]')).toHaveClass("chart-dashed");
    // The marker a dot in series-3, filled for the host.
    const dot = container.querySelector('circle[data-mark="ev:marker"]');
    expect(dot).toHaveClass("chart-point", "chart-tone-series-3");
    expect(dot).not.toHaveClass("chart-hollow");
    // A thin line from min to max at the row's centre, under the bar, and
    // never a button.
    const span = container.querySelector('line[data-span="0"]');
    expect(span).toHaveClass("chart-span");
    expect(numberOf(span ?? undefined, "x1")).toBeCloseTo(at("ev:min"));
    expect(numberOf(span ?? undefined, "x2")).toBeCloseTo(at("ev:max"));
    expect(numberOf(span ?? undefined, "y1")).toBe(numberOf(span ?? undefined, "y2"));
    expect(numberOf(span ?? undefined, "y1")).toBeCloseTo(numberOf(dot ?? undefined, "cy"));
    expect(span!.compareDocumentPosition(bar!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(marks(container)).toHaveLength(10);
    // A bar sharing its band with markers is thinner than the rule, which
    // reads past it by 4px each side.
    const rule = container.querySelector('line[data-mark="ev:min"]');
    const top = numberOf(bar ?? undefined, "y");
    const foot = top + numberOf(bar ?? undefined, "height");
    expect(top - numberOf(rule ?? undefined, "y1")).toBeCloseTo(4);
    expect(numberOf(rule ?? undefined, "y2") - foot).toBeCloseTo(4);
    // The bar wears its quartiles' origin: host-verified ends in a model row
    // draw it solid, and either end the model's draws it outlined.
    const ends = (q1: "host" | "model", q3: "host" | "model") =>
      strips({
        rows: [
          { ...PEERS[1]!, q1: { value: "2.5", origin: q1 }, q3: { value: "4.0", origin: q3 } },
        ],
      }).container.querySelector('rect[data-mark="lev:iqr"]');
    expect(ends("host", "host")).toHaveClass("chart-host");
    expect(ends("host", "model")).toHaveClass("chart-outline");
  });

  test("marks an unavailable quartile or marker n/a in its row, with its reason", () => {
    const { container } = strips();
    const gaps = [...container.querySelectorAll<SVGGElement>("[data-gap]")];
    expect(gaps.map((gap) => gap.dataset.mark)).toEqual(["lev:iqr", "lev:marker"]);
    for (const gap of gaps)
      expect(within(gap as unknown as HTMLElement).getByText("n/a")).toBeInTheDocument();
    expect(container.querySelector('rect[data-mark="lev:iqr"]')).toBeNull();
    expect(container.querySelector('circle[data-mark="lev:marker"]')).toBeNull();
    // The two gaps in one row stand apart.
    const ticks = gaps.map((gap) => numberOf(gap.querySelector("line") ?? undefined, "x1"));
    expect(new Set(ticks).size).toBe(2);
    // Both ends unavailable: each end's reason is said.
    strips({
      rows: [
        {
          ...PEERS[0]!,
          q1: { value: null, reason: "NOT_DISCLOSED" },
          q3: { value: null, reason: "PACKED_CELL" },
        },
      ],
    });
    expect(
      screen.getByRole("button", {
        name: "EV / EBITDA: interquartile range n/a (Q1: NOT_DISCLOSED; Q3: PACKED_CELL) (host-verified)",
      }),
    ).toBeInTheDocument();
  });

  test("draws nothing for a statistic its register does not declare", () => {
    const { container } = strips({ rows: METHODS, markerLabel: "Implied EV", unit: "USD m" });
    // No quartiles: no bar and no gap for one.
    expect(rects(container)).toHaveLength(0);
    expect(container.querySelector("[data-gap]")).toBeNull();
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Trading multiples: min 800 USD m (host-verified)",
      "Trading multiples: median 950 USD m (host-verified)",
      "Trading multiples: max 1,100 USD m (host-verified)",
      "Trading multiples: Implied EV 990 USD m (host-verified)",
      "Precedent deals: min 900 USD m (model-authored)",
      "Precedent deals: max 1,250.5 USD m (model-authored)",
      "Precedent deals: Implied EV 1,000 USD m (model-authored)",
    ]);
    expect(container.querySelector('circle[data-mark="deals:marker"]')).toHaveClass("chart-hollow");
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).queryByText("Interquartile range")).toBeNull();
    expect(within(legend).getByText("Implied EV").querySelector("circle")).not.toBeNull();
  });

  test("draws a row that declares one quartile as a gap naming the end it does not serve", () => {
    const { q3: _undeclared, ...one } = PEERS[0]!;
    const { container } = strips({ rows: [one] });
    expect(container.querySelector('rect[data-mark="ev:iqr"]')).toBeNull();
    expect(container.querySelector('[data-gap][data-mark="ev:iqr"]')).not.toBeNull();
    expect(
      screen.getByRole("button", {
        name: "EV / EBITDA: interquartile range n/a (Q3: Not served) (host-verified)",
      }),
    ).toBeInTheDocument();
  });

  test("has a table twin of the rows as served, columns no row carries left out", () => {
    strips();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const cellsOf = (table: HTMLElement) =>
      within(table)
        .getAllByRole("row")
        .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent));
    expect(cellsOf(screen.getByRole("table", { name: "Peer ranges" }))).toEqual([
      ["Metric", "Min", "Q1", "Median", "Q3", "Max", "Borrower", "Origin"],
      [
        "EV / EBITDA",
        "5.0",
        "6.25",
        "7.5 (model-authored)",
        "8.75",
        "11.0",
        "9.1",
        "host-verified",
      ],
      [
        "Net leverage",
        "2.0",
        "n/a: NOT_DISCLOSED",
        "3.5",
        "4.0",
        "5.25",
        "n/a: PEER_ONLY",
        "model-authored",
      ],
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    strips({
      title: "Implied EV",
      rows: METHODS,
      markerLabel: "Implied EV",
      categoryLabel: "Method",
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Table" })[1]!);
    expect(cellsOf(screen.getByRole("table", { name: "Implied EV" }))).toEqual([
      ["Method", "Min", "Median", "Max", "Implied EV", "Origin"],
      ["Trading multiples", "800", "950", "1,100", "990", "host-verified"],
      ["Precedent deals", "900", "", "1,250.5", "1,000", "model-authored"],
    ]);
  });

  test("keys its marks in their own forms", () => {
    strips();
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Interquartile range").querySelector("rect")).not.toBeNull();
    const rule = within(legend).getByText("Min, median, max");
    expect(rule.querySelector("line.chart-rule")).not.toBeNull();
    expect(rule.querySelector("circle")).toBeNull();
    const dot = within(legend).getByText("Borrower");
    expect(dot.querySelector("circle.chart-point")).not.toBeNull();
    expect(dot.querySelector("line")).toBeNull();
  });

  test("takes the bar, then min, median, max and the marker, row by row; every target 24px", () => {
    const onSelect = vi.fn();
    const { container } = strips({ onSelect });
    expect(marks(container).map((button) => button.dataset.mark)).toEqual([
      "ev:iqr",
      "ev:min",
      "ev:median",
      "ev:max",
      "ev:marker",
      "lev:iqr",
      "lev:min",
      "lev:median",
      "lev:max",
      "lev:marker",
    ]);
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marks(container)[1]);
    fireEvent.click(marks(container)[0]!);
    expect(onSelect).toHaveBeenCalledWith(
      {
        series: "interquartile",
        category: "EV / EBITDA",
        index: 0,
        value: null,
        interval: { from: "6.25", to: "8.75" },
        origin: "host",
      },
      marks(container)[0],
    );
    fireEvent.click(marks(container)[4]!);
    expect(onSelect).toHaveBeenLastCalledWith(
      { series: "marker", category: "EV / EBITDA", index: 0, value: "9.1", origin: "host" },
      marks(container)[4],
    );
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

// Made-up expected and realised values: one realised value host-verified,
// one unavailable.
const OUTCOMES: DumbbellRow[] = [
  {
    key: "growth",
    label: "Revenue growth",
    from: { value: "4.0" },
    to: { value: "2.5", origin: "host" },
    origin: "model",
  },
  {
    key: "margin",
    label: "EBITDA margin",
    from: { value: "18.0" },
    to: { value: null, reason: "NOT_REPORTED" },
    origin: "model",
  },
];

function dumbbells(extra: Partial<Parameters<typeof DumbbellChart>[0]> = {}) {
  return render(
    <DumbbellChart
      title="Expected against realised"
      summary="Each metric's expected value against its realised one."
      unit="%"
      rows={OUTCOMES}
      fromLabel="Expected"
      toLabel="Realized"
      {...extra}
    />,
  );
}

describe("a dumbbell", () => {
  test("names each end with its metric, which end, exact value and unit, and origin", () => {
    const { container } = dumbbells();
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Revenue growth: Expected 4.0 % (model-authored)",
      "Revenue growth: Realized 2.5 % (host-verified)",
      "EBITDA margin: Expected 18.0 % (model-authored)",
      "EBITDA margin: Realized n/a (NOT_REPORTED) (model-authored)",
    ]);
    expect(container.querySelector("figure")).toHaveAttribute("data-chart", "dumbbell");
  });

  test("dots each end, the first neutral and the second series-1, joined by a thin line", () => {
    const { container } = dumbbells();
    const from = container.querySelector('circle[data-mark="growth:from"]');
    const to = container.querySelector('circle[data-mark="growth:to"]');
    expect(from).toHaveClass("chart-point", "chart-tone-neutral", "chart-hollow");
    expect(to).toHaveClass("chart-point", "chart-tone-series-1");
    expect(to).not.toHaveClass("chart-hollow");
    expect(rects(container)).toHaveLength(0);
    const span = container.querySelector('line[data-span="0"]');
    expect(span).toHaveClass("chart-span");
    expect(numberOf(span ?? undefined, "x1")).toBeCloseTo(numberOf(from ?? undefined, "cx"));
    expect(numberOf(span ?? undefined, "x2")).toBeCloseTo(numberOf(to ?? undefined, "cx"));
    expect(numberOf(span ?? undefined, "y1")).toBeCloseTo(numberOf(from ?? undefined, "cy"));
    expect(span!.compareDocumentPosition(from!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // One end unavailable: a gap with its reason, and no line.
    expect(container.querySelector('line[data-span="1"]')).toBeNull();
    expect(container.querySelector('circle[data-mark="margin:to"]')).toBeNull();
    const gap = container.querySelector<SVGGElement>('[data-gap][data-mark="margin:to"]');
    expect(within(gap as unknown as HTMLElement).getByText("n/a")).toBeInTheDocument();
    expect(container.querySelector('circle[data-mark="margin:from"]')).not.toBeNull();
  });

  test("has a table twin of both ends as served, and keys its two dots", () => {
    dumbbells({ categoryLabel: "Outcome" });
    // Its marks are dots: the provenance key names a hollow dot, not a line.
    expect(screen.getByText("Hollow dot: model-authored, not host-verified")).toBeInTheDocument();
    expect(screen.queryByText(/^Dashed line/)).toBeNull();
    const legend = screen.getByRole("list", { name: "Legend" });
    for (const [label, tone] of [
      ["Expected", "chart-tone-neutral"],
      ["Realized", "chart-tone-series-1"],
    ] as const) {
      const swatch = within(legend).getByText(label).querySelector("svg.chart-swatch");
      expect(swatch).toHaveClass(tone);
      expect(swatch?.querySelector("circle.chart-point")).not.toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table", { name: "Expected against realised" });
    expect(
      within(table)
        .getAllByRole("row")
        .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent)),
    ).toEqual([
      ["Outcome", "Expected", "Realized", "Origin"],
      ["Revenue growth", "4.0", "2.5 (host-verified)", "model-authored"],
      ["EBITDA margin", "18.0", "n/a: NOT_REPORTED", "model-authored"],
    ]);
  });

  test("sets two equal ends apart across their row, the first above, both seen and reached", () => {
    const { container } = dumbbells({
      rows: [
        ...OUTCOMES,
        {
          key: "flat",
          label: "Net leverage",
          from: { value: "3.0" },
          to: { value: "3.00" },
          origin: "model",
        },
      ],
    });
    const from = container.querySelector('circle[data-mark="flat:from"]') ?? undefined;
    const to = container.querySelector('circle[data-mark="flat:to"]') ?? undefined;
    expect(numberOf(from, "cx")).toBeCloseTo(numberOf(to, "cx"));
    expect(numberOf(to, "cy") - numberOf(from, "cy")).toBeGreaterThan(2 * DOT);
    const [high, low] = ["flat:from", "flat:to"].map((key) =>
      marks(container).find((button) => button.dataset.mark === key),
    );
    expect(parseFloat(low!.style.top) - parseFloat(high!.style.top)).toBeGreaterThan(2 * DOT);
    // A short line across the row joins the two, so they read as one row's.
    const join = container.querySelector('line[data-span="2"]') ?? undefined;
    expect([numberOf(join, "x1"), numberOf(join, "x2")]).toEqual([
      numberOf(from, "cx"),
      numberOf(to, "cx"),
    ]);
    expect([numberOf(join, "y1"), numberOf(join, "y2")]).toEqual([
      numberOf(from, "cy"),
      numberOf(to, "cy"),
    ]);
    // Ends apart in value keep the row's centre.
    expect(
      numberOf(container.querySelector('circle[data-mark="growth:from"]') ?? undefined, "cy"),
    ).toBeCloseTo(
      numberOf(container.querySelector('circle[data-mark="growth:to"]') ?? undefined, "cy"),
    );
  });

  test("takes each row's two ends in turn; every target 24px", () => {
    const onSelect = vi.fn();
    const { container } = dumbbells({ onSelect });
    expect(marks(container).map((button) => button.dataset.mark)).toEqual([
      "growth:from",
      "growth:to",
      "margin:from",
      "margin:to",
    ]);
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marks(container)[1]);
    fireEvent.click(marks(container)[1]!);
    expect(onSelect).toHaveBeenCalledWith(
      { series: "to", category: "Revenue growth", index: 0, value: "2.5", origin: "host" },
      marks(container)[1],
    );
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

// Securities against their maturities, made up: three placed, one with a
// date no reader should guess, one with a day its month lacks, one unquoted.
const CURVE: ScatterPoint[] = [
  {
    key: "a",
    label: "Note A",
    at: "2031-06-15",
    value: { value: "412.5" },
    group: "Senior",
    origin: "model",
  },
  {
    key: "b",
    label: "Note B",
    at: "2029-03",
    value: { value: "275" },
    group: "Sub",
    origin: "host",
  },
  {
    key: "c",
    label: "Note C",
    at: "2033",
    value: { value: "-12.25" },
    group: "Senior",
    origin: "model",
  },
  {
    key: "d",
    label: "Note D",
    at: "03/04/2031",
    value: { value: "300" },
    group: "Senior",
    origin: "model",
  },
  {
    key: "e",
    label: "Note E",
    at: "2030-02-30",
    value: { value: "100" },
    group: "Sub",
    origin: "model",
  },
  {
    key: "f",
    label: "Note F",
    at: "2032-01-01",
    value: { value: null, reason: "Not quoted" },
    group: "Senior",
    origin: "model",
  },
];

function scatter(extra: Partial<Parameters<typeof ScatterChart>[0]> = {}) {
  return render(
    <ScatterChart
      title="Spread against maturity"
      summary="Each security's spread at its maturity."
      unit="bps"
      points={CURVE}
      xLabel="Maturity"
      pointLabel="Security"
      valueLabel="Spread"
      groupLabel="Seniority"
      {...extra}
    />,
  );
}

const pointAt = (root: HTMLElement, key: string) =>
  plotOf(root).querySelector<SVGCircleElement>(`circle[data-mark="${key}"]`);
const xTicks = (root: HTMLElement) =>
  [...plotOf(root).querySelectorAll(".recharts-xAxis-tick-labels .chart-tick")].map(
    (tick) => tick.textContent,
  );

describe("a scatter chart", () => {
  test("reads only an ISO date, a month or a year, never a date it would have to guess", () => {
    expect(readDate("2031-06-15")).toBe(Date.UTC(2031, 5, 15));
    expect(readDate("2031-06")).toBe(Date.UTC(2031, 5, 1));
    expect(readDate("2031")).toBe(Date.UTC(2031, 0, 1));
    for (const unread of ["03/04/2031", "2031-13", "2031-02-29", "31-06-15", "2031-6-15", ""]) {
      expect(readDate(unread)).toBeNull();
    }
    expect(readDate("2032-02-29")).toBe(Date.UTC(2032, 1, 29));
  });

  test("names each placed point for its security, group, date, exact value and origin, by date", () => {
    const { container } = scatter();
    expect(container.querySelector("figure")).toHaveAttribute("data-chart", "scatter");
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Note B, Sub, Maturity 2029-03: 275 bps (host-verified)",
      "Note A, Senior, Maturity 2031-06-15: 412.5 bps (model-authored)",
      "Note C, Senior, Maturity 2033: -12.25 bps (model-authored)",
    ]);
    expect(plotOf(container).querySelectorAll("circle.chart-point")).toHaveLength(3);
  });

  test("places each point by its date's time, on a value axis holding zero", () => {
    const { container } = scatter();
    const [a, b, c] = ["a", "b", "c"].map((key) => numberOf(pointAt(container, key)!, "cx"));
    const share =
      (Date.UTC(2031, 5, 15) - Date.UTC(2029, 2, 1)) /
      (Date.UTC(2033, 0, 1) - Date.UTC(2029, 2, 1));
    expect((a! - b!) / (c! - b!)).toBeCloseTo(share, 5);
    const zero = numberOf(plotOf(container).querySelector(".chart-zero") ?? undefined, "y1");
    expect(numberOf(pointAt(container, "c")!, "cy")).toBeGreaterThan(zero);
    expect(numberOf(pointAt(container, "b")!, "cy")).toBeLessThan(zero);
    expect(xTicks(container)).toEqual(["2029", "2030", "2031", "2032", "2033", "2034"]);
  });

  test("labels years only, thinned to what fits", () => {
    const { container } = scatter({
      points: [
        { key: "p", label: "P", at: "2000", value: { value: "1" }, group: "G", origin: "model" },
        {
          key: "q",
          label: "Q",
          at: "2099-12-31",
          value: { value: "2" },
          group: "G",
          origin: "model",
        },
      ],
    });
    expect(xTicks(container)).toEqual(Array.from({ length: 11 }, (_, n) => `${2000 + 10 * n}`));
  });

  test("colours points by group as they first appear, neutral past the fifth; the model's hollow", () => {
    const { container } = scatter();
    expect(pointAt(container, "a")).toHaveClass("chart-tone-series-1", "chart-hollow");
    expect(pointAt(container, "b")).toHaveClass("chart-tone-series-2");
    expect(pointAt(container, "b")).not.toHaveClass("chart-hollow");
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Sub").querySelector("svg.chart-swatch")).toHaveClass(
      "chart-tone-series-2",
    );
    const six = Array.from({ length: 6 }, (_, n): ScatterPoint => ({
      key: `${n}`,
      label: `S${n}`,
      at: `${2030 + n}`,
      value: { value: "1" },
      group: `G${n}`,
      origin: "host",
    }));
    const many = scatter({ points: six, title: "Six" }).container;
    expect(pointAt(many, "4")).toHaveClass("chart-tone-series-5");
    expect(pointAt(many, "5")).toHaveClass("chart-tone-neutral");
  });

  test("lists what it could not place with its reason in the table, and counts it in the caption", () => {
    const { container } = scatter();
    expect(container.querySelector("[data-chart-note]")).toHaveTextContent(
      "3 of 6 points not placed; the table lists each with its reason.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table", { name: "Spread against maturity" });
    expect(
      within(table)
        .getAllByRole("row")
        .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent)),
    ).toEqual([
      ["Security", "Maturity", "Spread, bps", "Seniority", "Origin", "Not placed"],
      ["Note B", "2029-03", "275", "Sub", "host-verified", ""],
      ["Note A", "2031-06-15", "412.5", "Senior", "model-authored", ""],
      ["Note C", "2033", "-12.25", "Senior", "model-authored", ""],
      [
        "Note D",
        "03/04/2031",
        "300",
        "Senior",
        "model-authored",
        "No readable date (YYYY-MM-DD, YYYY-MM or YYYY)",
      ],
      [
        "Note E",
        "2030-02-30",
        "100",
        "Sub",
        "model-authored",
        "No readable date (YYYY-MM-DD, YYYY-MM or YYYY)",
      ],
      ["Note F", "2032-01-01", "n/a: Not quoted", "Senior", "model-authored", "No value"],
    ]);
  });

  test("counts a value too large to place as not placed, with its reason", () => {
    const huge = `1${"0".repeat(400)}`;
    const { container } = scatter({
      points: [
        ...CURVE.slice(0, 3),
        {
          key: "g",
          label: "Note G",
          at: "2030",
          value: { value: huge },
          group: "Sub",
          origin: "host",
        },
      ],
    });
    expect(marks(container)).toHaveLength(3);
    expect(container.querySelector("[data-chart-note]")).toHaveTextContent(
      /^1 of 4 points not placed/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const row = screen.getByRole("row", { name: /Note G/ });
    expect([...(row as HTMLTableRowElement).cells].at(-1)?.textContent).toBe(
      "Value too large in magnitude to place",
    );
  });

  test("a point whose figure says why it has no one date gives that as its reason", () => {
    scatter({ points: [{ ...CURVE[0]!, at: "", unread: "stated twice: 2031, 2032" }] });
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const row = screen.getByRole("row", { name: /Note A/ }) as HTMLTableRowElement;
    expect([...row.cells].at(-1)?.textContent).toBe("stated twice: 2031, 2032");
  });

  test("keys its groups in the order their colours were given, not by date; a hollow dot is the model's", () => {
    scatter({
      points: [
        { key: "p", label: "P", at: "2035", value: { value: "1" }, group: "Late", origin: "model" },
        { key: "q", label: "Q", at: "2030", value: { value: "2" }, group: "Early", origin: "host" },
      ],
    });
    const legend = screen.getByRole("list", { name: "Legend" });
    const groups = [...legend.querySelectorAll("li:not(.chart-provenance)")];
    expect(groups.map((item) => item.textContent)).toEqual(["Late", "Early"]);
    expect(within(legend).getByText("Hollow dot: model-authored, not host-verified")).toBeTruthy();
  });

  test("colours and keys only the groups of placed points", () => {
    const { container } = scatter({
      points: [
        {
          key: "x",
          label: "X",
          at: "2030",
          value: { value: null, reason: "NA" },
          group: "Ghost",
          origin: "host",
        },
        { key: "y", label: "Y", at: "2031", value: { value: "1" }, group: "Real", origin: "host" },
        { key: "z", label: "Z", at: "2032", value: { value: "2" }, group: "Also", origin: "host" },
      ],
    });
    expect(pointAt(container, "y")).toHaveClass("chart-tone-series-1");
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).queryByText("Ghost")).toBeNull();
    expect(within(legend).getByText("Real")).toBeInTheDocument();
  });

  test("holds zero on its value axis when every value is negative", () => {
    const { container } = scatter({
      points: [
        { key: "m", label: "M", at: "2030", value: { value: "-5" }, group: "G", origin: "host" },
        { key: "n", label: "N", at: "2031", value: { value: "-10" }, group: "G", origin: "host" },
      ],
    });
    const zero = numberOf(plotOf(container).querySelector(".chart-zero") ?? undefined, "y1");
    for (const key of ["m", "n"]) {
      expect(numberOf(pointAt(container, key)!, "cy")).toBeGreaterThan(zero);
    }
    const ticks = [
      ...plotOf(container).querySelectorAll(".recharts-yAxis-tick-labels .chart-tick"),
    ];
    expect(ticks.map((tick) => tick.textContent)).toContain("0");
  });

  test("one point of one not placed is said in the singular", () => {
    const { container } = scatter({ points: CURVE.slice(3, 4), title: "One" });
    expect(container.querySelector("[data-chart-note]")).toHaveTextContent(
      "1 of 1 point not placed; the table lists each with its reason.",
    );
  });

  test("with nothing placed, labels no year and reaches no point", () => {
    const { container } = scatter({ points: CURVE.slice(3), title: "None placed" });
    expect(xTicks(container)).toEqual([]);
    expect(marks(container)).toHaveLength(0);
    expect(container.querySelector("[data-chart-note]")).toHaveTextContent(/^3 of 3 points/);
  });

  test("takes its points in date order by the arrow keys; every target 24px", () => {
    const onSelect = vi.fn();
    const { container } = scatter({ onSelect });
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowRight" });
    expect(document.activeElement).toBe(marks(container)[1]);
    fireEvent.click(marks(container)[1]!);
    expect(onSelect).toHaveBeenCalledWith(
      { series: "Senior", category: "Note A", index: 0, value: "412.5", origin: "model" },
      marks(container)[1],
    );
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

// Made-up events: two High/High, one host-verified beside a model's in one
// cell, and texts the ordinal labels do not read.
const EVENTS: RiskEvent[] = [
  ["e1", "E-01", "Refinancing slips", "High", "High", "Critical"],
  ["e2", "E-02", "Covenant reset", " high ", "HIGH", "Critical"],
  ["e3", "E-03", "Supplier exit", "Medium", "Low", "Watch"],
  ["e4", "E-04", "Tariff change", "Likely", "High", "High"],
  ["e5", "E-05", "Litigation", "Low", "", "Low"],
  ["e6", "E-06", "Rate reset", "medium", "low", "Watch"],
].map(([key, label, description, probability, impact, classification]) => ({
  key: key!,
  label: label!,
  description: description!,
  probability: probability!,
  impact: impact!,
  classification: classification!,
  origin: key === "e3" ? "host" : "model",
}));

function matrix(extra: Partial<Parameters<typeof RiskMatrix>[0]> = {}) {
  return render(
    <RiskMatrix
      title="Probability and impact"
      summary="2 events High/High."
      events={EVENTS}
      {...extra}
    />,
  );
}

const cellAt = (root: HTMLElement, key: string) =>
  plotOf(root).querySelector(`[data-cell="${key}"]`);

describe("a risk matrix", () => {
  test("reads the four ordinal labels trimmed and case-insensitive, nothing else", () => {
    expect([" high ", "MEDIUM", "Low", "unknown"].map(riskLevel)).toEqual([
      "High",
      "Medium",
      "Low",
      "Unknown",
    ]);
    for (const other of ["Likely", "", "Med", "High/Medium"]) expect(riskLevel(other)).toBeNull();
  });

  test("a mark a cell holding events, in reading order, named with both labels, its count and ids", () => {
    const { container } = matrix();
    expect(container.querySelector("figure")).toHaveAttribute("data-chart", "risk-matrix");
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Probability High, Impact High: 2 events, E-01, E-02 (a count of the model's rows)",
      "Probability Medium, Impact Low: 2 events, E-03, E-06 (a count of rows: 1 host-verified, 1 model-authored)",
      "Probability Low, Impact Unknown: 1 event, E-05 (impact not stated) (a count of the model's rows)",
      "Probability Unknown, Impact High: 1 event, E-04 (probability as written: Likely) (a count of the model's rows)",
    ]);
    expect(cellAt(container, "high-high")?.querySelector("[data-count]")).toHaveTextContent("2");
    expect(cellAt(container, "unknown-high")?.querySelector("[data-count]")).toHaveTextContent("1");
  });

  test("draws all sixteen cells, an empty one with no mark and no count", () => {
    const { container } = matrix();
    const cells = [...plotOf(container).querySelectorAll("[data-cell]")];
    expect(cells.map((cell) => cell.getAttribute("data-cell"))).toEqual(
      ["high", "medium", "low", "unknown"].flatMap((p) =>
        ["low", "medium", "high", "unknown"].map((i) => `${p}-${i}`),
      ),
    );
    expect(cellAt(container, "low-low")?.querySelector("[data-mark], [data-count]")).toBeNull();
    const ticks = [...plotOf(container).querySelectorAll(".chart-tick")].map((t) => t.textContent);
    expect(ticks).toEqual([
      "Probability",
      "High",
      "Medium",
      "Low",
      "Unknown",
      "Low",
      "Medium",
      "High",
      "Unknown",
      "Impact",
    ]);
    expect(plotOf(container).querySelectorAll(".chart-grid line")).toHaveLength(10);
  });

  test("a cell of the model's events is outlined and hatched; of the host's alone, solid", () => {
    const host = matrix({ events: EVENTS.filter((event) => event.key === "e3") }).container;
    expect(cellAt(host, "medium-low")?.querySelector("rect[data-mark]")).toHaveClass("chart-host");
    const { container } = matrix({ title: "Mixed" });
    const mixed = cellAt(container, "medium-low")?.querySelector("rect[data-mark]");
    expect(mixed).toHaveClass("chart-outline");
    expect(mixed?.getAttribute("fill")).toMatch(/^url\(#/);
  });

  test("its table twin lists each event as given, label texts the ordinal labels do not read included", () => {
    matrix();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table", { name: "Probability and impact" });
    const rows = within(table)
      .getAllByRole("row")
      .map((row) => [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent));
    expect(rows.slice(0, 3)).toEqual([
      ["Event ID", "Description", "Probability", "Impact", "P/I Classification"],
      ["E-01", "Refinancing slips", "High", "High", "Critical"],
      ["E-02", "Covenant reset", " high ", "HIGH", "Critical"],
    ]);
    expect(rows).toHaveLength(7);
  });

  test("names at most ten ids a cell, the rest counted and left to the table", () => {
    const twelve = Array.from({ length: 12 }, (_, n) => ({
      ...EVENTS[0]!,
      key: `k${n}`,
      label: `E${n + 1}`,
    }));
    const { container } = matrix({ events: twelve });
    expect(marks(container).map((button) => button.getAttribute("aria-label"))).toEqual([
      "Probability High, Impact High: 12 events, E1, E2, E3, E4, E5, E6, E7, E8, E9, E10, …and 2 more (a count of the model's rows)",
    ]);
    expect(idList(["A", "B"])).toBe("A, B");
  });

  test("a cell's hit box is its inner area, so pressing its printed count presses the cell", () => {
    const { container } = matrix();
    const across = [...plotOf(container).querySelectorAll(".chart-grid line")].slice(5);
    const width = numberOf(across[1], "x1") - numberOf(across[0], "x1");
    const button = marks(container)[0]!;
    const [left, wide] = [parseFloat(button.style.left), parseFloat(button.style.width)];
    expect([wide, parseFloat(button.style.height)]).toEqual([Math.max(24, width - 8), 44 - 8]);
    const count = numberOf(
      cellAt(container, "high-high")?.querySelector("[data-count]") ?? undefined,
      "x",
    );
    expect(count > left && count + 8 < left + wide).toBe(true);
  });

  test("takes its cells by the arrow keys; every target 24px; a press hands the cell over", () => {
    const onSelect = vi.fn();
    const { container } = matrix({ onSelect });
    act(() => marks(container)[0]!.focus());
    fireEvent.keyDown(marks(container)[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marks(container)[1]);
    fireEvent.click(marks(container)[3]!);
    expect(onSelect).toHaveBeenCalledWith(
      {
        series: "Probability Unknown",
        category: "Impact High",
        index: 14,
        value: "1",
        origin: "model",
      },
      marks(container)[3],
    );
    for (const button of marks(container)) {
      expect(parseFloat(button.style.width)).toBeGreaterThanOrEqual(24);
      expect(parseFloat(button.style.height)).toBeGreaterThanOrEqual(24);
    }
  });
});

describe("a value read for a name or a table cell", () => {
  test("said prints it with its unit or n/a and why; cellOf names an origin only where it differs", () => {
    expect(said(readDatum({ value: "1234.5" }), "x")).toBe("1,234.5 x");
    expect(said(readDatum({ value: "-2" }), undefined)).toBe("-2");
    expect(said(readDatum({ value: null, reason: "NOT_DISCLOSED" }), "x")).toBe(
      "n/a (NOT_DISCLOSED)",
    );
    // A statistic the register does not declare is an empty cell, not n/a.
    expect(cellOf(undefined, "model")).toBe("");
    expect(cellOf(readDatum({ value: null, reason: "PEER_ONLY" }), "model")).toBe("n/a: PEER_ONLY");
    expect(cellOf(readDatum({ value: "2500.5", origin: "host" }), "model")).toBe(
      "2,500.5 (host-verified)",
    );
    expect(cellOf(readDatum({ value: "2.5", origin: "model" }), "model")).toBe("2.5");
    expect(cellOf(readDatum({ value: "2.5" }), "host")).toBe("2.5");
  });
});

describe("a legend swatch", () => {
  test("draws a rule dashed for the model and solid for the host, a dot hollow or filled", () => {
    const swatch = (shape: "rule" | "dot", origin: "host" | "model") =>
      render(<Swatch tone="neutral" shape={shape} origin={origin} />).container;
    expect(swatch("rule", "host").querySelector("line")).toHaveClass("chart-rule");
    expect(swatch("rule", "host").querySelector("line")).not.toHaveClass("chart-dashed");
    expect(swatch("rule", "model").querySelector("line")).toHaveClass("chart-rule", "chart-dashed");
    expect(swatch("rule", "model").querySelector("circle")).toBeNull();
    expect(swatch("dot", "host").querySelector("circle")).not.toHaveClass("chart-hollow");
    expect(swatch("dot", "model").querySelector("circle")).toHaveClass(
      "chart-point",
      "chart-hollow",
    );
    expect(swatch("dot", "model").querySelector("line")).toBeNull();
  });
});

describe("every chart form, audited", () => {
  // The tags scripts/a11y-axe.mjs audits the workspace with. Colour contrast
  // needs layout jsdom lacks; the stylesheet's own test below holds it.
  const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
  const audit = async (root: HTMLElement) =>
    (await axe.run(root, { runOnly: { type: "tag", values: TAGS } })).violations.map(
      (violation) => `${violation.id}: ${violation.nodes.length}`,
    );

  // One test per form, so no audit nears the 5 s test timeout as forms are added.
  const FORMS: readonly (readonly [string, () => React.ReactElement])[] = [
    [
      "bar chart",
      () => (
        <BarChart
          title="Bars"
          summary="Grouped."
          unit="USD m"
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
      ),
    ],
    [
      "line chart",
      () => (
        <LineChart
          title="Lines"
          summary="Two series."
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
      ),
    ],
    [
      "stacked bar chart",
      () => (
        <StackedBarChart
          title="Stack"
          summary="Normalised."
          mode="normalised"
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
      ),
    ],
    [
      "waterfall chart",
      () => (
        <WaterfallChart
          title="Bridge"
          summary="Short of its total."
          steps={[
            { label: "Opening", kind: "total", value: "10", origin: "host" },
            { label: "Step", kind: "delta", value: "-2.5", origin: "model" },
            { label: "Closing", kind: "total", value: "8", origin: "host" },
          ]}
        />
      ),
    ],
    [
      "diverging bar chart",
      () => (
        <DivergingBarChart
          title="Variance"
          summary="Signed."
          categories={PERIODS}
          series={EBITDA}
        />
      ),
    ],
    [
      "bullet chart",
      () => <BulletChart title="Headroom" summary="Against thresholds." unit="x" rows={TESTS} />,
    ],
    [
      "range strip",
      () => <RangeStripChart title="Ranges" summary="Against peers." unit="x" rows={PEERS} />,
    ],
    [
      "dumbbell",
      () => (
        <DumbbellChart
          title="Outcomes"
          summary="Expected against realised."
          unit="%"
          rows={OUTCOMES}
          fromLabel="Expected"
          toLabel="Realized"
        />
      ),
    ],
    [
      "risk matrix",
      () => <RiskMatrix title="Matrix" summary="By probability and impact." events={EVENTS} />,
    ],
    [
      "scatter",
      () => (
        <ScatterChart title="Curve" summary="Against maturity." points={CURVE} xLabel="Maturity" />
      ),
    ],
  ];

  test.each(FORMS)("has no axe violation in a %s, drawn or as its table twin", async (_, chart) => {
    const { container } = render(
      <main>
        <h1>Charts</h1>
        {chart()}
      </main>,
    );
    expect(await audit(container)).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(await audit(container)).toEqual([]);
  });
});

describe("drawn at the container's width", () => {
  function Probe() {
    const { ref, width } = useWidth<HTMLDivElement>(300);
    return <div ref={ref}>{width}</div>;
  }

  test("with nothing to measure with, a chart draws at the fallback width", () => {
    expect(typeof ResizeObserver).toBe("undefined");
    render(<Probe />);
    expect(screen.getByText("300")).toBeInTheDocument();
  });

  test("a measured width redraws the SVG at that many whole pixels", () => {
    let report: ResizeObserverCallback = () => undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          report = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    const { container } = bars();
    const svg = () => container.querySelector(".chart-plot svg[role='img']");
    expect(svg()).toHaveAttribute("width", String(FALLBACK_WIDTH));
    act(() =>
      report([{ contentRect: { width: 480.6 } } as ResizeObserverEntry], {} as ResizeObserver),
    );
    expect(svg()).toHaveAttribute("width", "480");
    vi.unstubAllGlobals();
  });
});

describe("the chart stylesheet", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles/charts.css"), "utf8");
  const tokens = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");
  // Each theme's own values: light on :root, dark in its `@variant dark` block.
  const [light = "", dark = ""] = tokens.split("@variant dark");
  /** A token's colour as linear sRGB, from its hex or oklch() value. */
  const colour = (source: string, name: string): number[] => {
    const value = new RegExp(`--${name}:\\s*([^;]+);`).exec(source)?.[1]?.trim() ?? "";
    const hexed = /^#([0-9a-f]{6})$/i.exec(value);
    if (hexed) {
      return [0, 2, 4].map((at) => {
        const channel = parseInt(hexed[1]!.slice(at, at + 2), 16) / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
    }
    const [l = 0, c = 0, h = 0] = (/^oklch\(([^)]*)\)$/.exec(value)?.[1] ?? "")
      .split(/\s+/)
      .map(Number);
    const a = c * Math.cos((h * Math.PI) / 180);
    const b = c * Math.sin((h * Math.PI) / 180);
    const [L, M, S] = [
      l + 0.3963377774 * a + 0.2158037573 * b,
      l - 0.1055613458 * a - 0.0638541728 * b,
      l - 0.0894841775 * a - 1.291485548 * b,
    ].map((v) => v ** 3) as [number, number, number];
    return [
      4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
      -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
      -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
    ].map((v) => Math.min(1, Math.max(0, v)));
  };
  const luminance = ([r = 0, g = 0, b = 0]: number[]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const contrast = (x: number[], y: number[]) => {
    const [high = 0, low = 0] = [luminance(x), luminance(y)].sort((p, q) => q - p);
    return (high + 0.05) / (low + 0.05);
  };

  test("sets no chart text below 11px: ticks 11px, values 12px, titles 14px", () => {
    const sizes = [...css.matchAll(/(?:font-size:\s*|font:[^;]*?\s)(\d+(?:\.\d+)?)(px|rem)/g)].map(
      (match) => Number(match[1]) * (match[2] === "rem" ? 16 : 1),
    );
    expect(sizes.length).toBeGreaterThan(5);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);
    expect(css).toMatch(/\.chart-title\s*\{[^}]*font-size: 0\.875rem/);
  });

  test("holds every mark hue at 3:1 against the card and every text at 4.5:1, in both themes", () => {
    for (const theme of [light, dark]) {
      const card = colour(theme, "card");
      for (const name of [
        "chart-1",
        "chart-2",
        "chart-3",
        "chart-4",
        "chart-5",
        "chart-neutral",
        "chart-zero",
      ]) {
        expect(contrast(colour(theme, name), card), name).toBeGreaterThanOrEqual(3);
      }
      for (const name of ["muted-foreground", "foreground", "destructive", "info"]) {
        expect(contrast(colour(theme, name), card), name).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
