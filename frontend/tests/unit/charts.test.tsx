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
  DivergingBarChart,
  LineChart,
  ProvenanceKeyed,
  StackedBarChart,
  WaterfallChart,
  type ChartSeries,
} from "@/charts";
import { fromScaled, placesOf, toScaled } from "@/charts/decimal";
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

describe("every chart form, audited", () => {
  // The tags scripts/a11y-axe.mjs audits the workspace with. Colour contrast
  // needs layout jsdom lacks; the stylesheet's own test below holds it.
  const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
  const audit = async (root: HTMLElement) =>
    (await axe.run(root, { runOnly: { type: "tag", values: TAGS } })).violations.map(
      (violation) => `${violation.id}: ${violation.nodes.length}`,
    );

  test("has no axe violation drawn, or as its table twin", async () => {
    const { container } = render(
      <main>
        <h1>Charts</h1>
        <BarChart
          title="Bars"
          summary="Grouped."
          unit="USD m"
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
        <LineChart
          title="Lines"
          summary="Two series."
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
        <StackedBarChart
          title="Stack"
          summary="Normalised."
          mode="normalised"
          categories={PERIODS}
          series={[REVENUE, EBITDA]}
        />
        <WaterfallChart
          title="Bridge"
          summary="Short of its total."
          steps={[
            { label: "Opening", kind: "total", value: "10", origin: "host" },
            { label: "Step", kind: "delta", value: "-2.5", origin: "model" },
            { label: "Closing", kind: "total", value: "8", origin: "host" },
          ]}
        />
        <DivergingBarChart
          title="Variance"
          summary="Signed."
          categories={PERIODS}
          series={EBITDA}
        />
      </main>,
    );
    expect(await audit(container)).toEqual([]);
    for (const toggle of screen.getAllByRole("button", { name: "Table" })) fireEvent.click(toggle);
    expect(screen.getAllByRole("table")).toHaveLength(5);
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
