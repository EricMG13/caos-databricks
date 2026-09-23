# DESIGN.md — visual language

**North star: the committee terminal.** A refined institutional terminal for
buy-side credit analysts. Calm enough for committee work, live enough for desk
posture, exact enough that every number reads as traceable rather than
decorative.

Dark, dense, single mode. Filed output inverts to paper — ink on
cream — because filed output is a different object from the live surface.

Rejected outright: friendly consumer SaaS, marketing dashboards, pastel cards,
decorative gradients, glow, glassmorphism, raw terminal dumps. Dense is allowed.
Disorganised is not.

## Tokens

Bound design system: **CAOS (caos-frontend)**. The bundle declares `--caos-*`
but **not** `--font-sans|mono|display` — the app declares those, or every
`font:` shorthand using one is invalid at computed-value time and silently
falls back to 16px.

```
--caos-bg #0a0a0f   --caos-panel #12121a   --caos-elevated #1a1a24
--caos-border #262633   --caos-text #e6e6ef   --caos-muted #8a8a9a
--caos-accent #4f8cff
--caos-success #22c55e   --caos-warning #f5a524   --caos-critical #ef4444
--caos-idle #3f3f46   --field-edge #63636f (3:1 on panel; a field's edge)
--tranche-1l #2dd4bf  --tranche-2l #4f8cff  --tranche-unsec #f5a524
--tranche-sub #a855f7  --tranche-eq #64748b
```

Type scale: `3xs 10` `2xs 10` `xs 11` `sm 11` `md 12` `lg 12.5` `xl 13`
`2xl 14` `metric 18` `hero 24`. Body text is 12px.

**Type floors.** Labels and captions are never below 10px, tabular mono data
never below 11px, body and prose never below 12px. Density comes from fewer,
better-chosen things, not from smaller text (raised from an 8px floor after
the 2026-09-23 critique).

## Named rules

**Signal-only colour.** Accent and semantic colours mean action, selection,
status, seniority or lineage. Never decoration.

**Numeric truth.** Financial values, ids, ratings, dates and confidence scores
are mono and tabular so columns scan and decimals align.

**Severity is shape and hue.** Success and running are a disc, warning a
triangle, critical a rounded square, idle a flat dot. Colour alone never carries
status.

**Paper is for filed output only.** Ink on cream inside the deliverable. It
must not leak into navigation, buttons, panel headers or
analytical tables.

**Motion only for live state.** No entrance animation, no hover flourish.
Reduced motion is honoured.

**One evidence surface.** The context drawer and the per-surface evidence rail.
There is no second inspector.

## Chrome

Four bands, in order, on every section: ribbon → decision brief
(CHANGE · IMPACT · ACTION · EVIDENCE + one headline figure) → tabs →
verdict strip. Then the rail, the body, and a right column that is always about
the selected thing, never a second menu.

**Bands say only what the document supports.** Every cell is composed from the
section's own body facts (run status, open gates, the conclusion module's
committee status, withdrawn citations, revision state). A cell with nothing to
say is not drawn, a brief with nothing to say is no band, and the ribbon names
the issuer, not the case id. Never "—", never "No action is offered", never the
section's own name as the headline figure. The verdict wash is flat, not a
gradient.

Panels: hairline border, 6–10px radius, one faint resting shadow, a 29–30px
sentence-case header. A larger shadow means the object floats above the
workflow.

The ribbon carries at most three actions and exactly one primary.

## Analysis

The legacy desk's three panes, on this frame. The route's modules are the
section's tabs, in route order, each with its QA state as shape and hue; the
address names the one shown (`?tab=<route node>`), and the section opens on
its conclusion (the last module that reasons, never the CP-CF calculator). The
body is the evidence rail (what the run rests on: each cited document once,
its pages and citation count, withdrawn marked; then the module's own source
facts), the module (name first, code second; status, limitations, figures,
the model's prose as text at 72ch, the host-calculation note), and the right
column, which is always the selected thing's provenance. Pending nodes follow.
The decision lives in the bands, not in a third pane.

## Charts

Drawn by React as SVG; `d3-scale` and `d3-shape` do the maths only (D33).
Nothing writes `innerHTML`, so every chart holds under the production CSP.

- **Provenance is drawn in the mark.** Host-verified figures are solid;
  model-authored ones are outlined and hatched (a model line is dashed with
  hollow points). A value the document does not carry is a gap marked n/a
  with its reason, never zero and never interpolated. A bridge that does not
  reconcile draws its unexplained residual in the critical hue and says so.
- **Figures are printed as served.** Labels, names and table twins print the
  API's exact decimals; sums are exact; a float only places a mark.
- **Every chart is a figure:** a title, one plain summary line, and a table
  twin behind a Table toggle. Every mark is a button named for its series,
  category, value and origin; pressing it fills the right column.
- **Colour:** `--chart-series-1..5` (validated on the panel), the tranche
  tokens for seniority, `--chart-neutral` for stated totals; a sixth series is
  neutral, never a recycled hue.
- **Type at the floors:** ticks 10px and values 11px mono tabular, titles 12px.
- No motion, gradients, shadows, glow or rounded bar ends; bars start at zero;
  no dual axes.

## Rules with teeth

- A refused control stays **visible and refused, with its reason named**.
  Hiding it teaches the wrong model of the system.
- Every ready conclusion carries observation time, origin, method, approval and
  freshness.
- A private 404 and an absent route share one neutral wording:
  "Unavailable or not permitted."
- Dialog openers are passed explicitly, never inferred from
  `document.activeElement` — WebKit does not focus a button on click.
- No web font. No emoji in product chrome.

## Reference

Design source: https://claude.ai/design/p/69d37748-8595-4309-9b06-bc5f9529a29c
