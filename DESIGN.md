# DESIGN.md — visual language

**North star: a calm, exact workspace for credit committee work.** shadcn/ui's
Nova style on Base UI, in light and dark, with Emil Kowalski's motion. Quiet
surfaces, one type family, figures that line up, and colour only where it
means something. Every number reads as traceable rather than decorative.

Light and dark are both first-class and the reader's system chooses until they
pick (the header's theme menu). Filed output and evidence pages are paper —
ink on cream — in either theme, because they are a different object from the
live surface.

**Desktop only (D63).** CAOS is used at a desk: a PC, a pointer, a keyboard,
a window 1024 px wide or wider. No screen is designed, polished or checked for
a phone or a tablet. A narrow layout remains for one reason: a desktop reader
at 400% zoom sees 320 CSS px, which WCAG 1.4.10 asks to reflow and the a11y
matrix measures (320×640). Below 768 px the sidebar is a sheet and below 640
px a section's views are a native select — reflow for zoom, kept to what
reflow needs, not a phone design.

Rejected outright: marketing dashboards, pastel cards, decorative gradients,
glow, glassmorphism, hero-metric templates, raw terminal dumps, all-caps
labels. Dense is allowed. Disorganised is not.

## Tokens

The theme lives in `frontend/src/styles/tokens.css` (D35–D37): shadcn's
semantic tokens (`--background`, `--foreground`, `--card`, `--popover`,
`--primary`, `--secondary`, `--muted`, `--accent`, `--destructive`,
`--border`, `--input`, `--ring`, `--sidebar-*`, `--radius` 0.625rem) plus the
workspace's own. Each is defined once for light on `:root` and once for dark
in `@variant dark`, which matches `.dark` and a system dark with no pick.

```
status    --success --warning --destructive --info --idle   (text-safe, 4.5:1)
tint      --tint 10% light, 15% dark                          (status washes)
field     --input  3:1 on its card; --field-bg                (WCAG 1.4.11)
seniority --tranche-1l --tranche-2l --tranche-unsec --tranche-sub --tranche-eq
charts    --chart-1..5 --chart-neutral --chart-zero           (per theme)
paper     --paper-bg --paper-ink --paper-rule --paper-cite …  (both themes)
motion    --ease-out cubic-bezier(0.23,1,0.32,1)
          --ease-in-out cubic-bezier(0.77,0,0.175,1)
          --ease-drawer cubic-bezier(0.32,0.72,0,1)
```

Type is Geist and Geist Mono, bundled with the app (D36): `font-src 'self'`
holds and no request goes to a font host. The scale is shadcn's: 14px body,
13px figures and secondary text, 12px labels and captions, 16–18px headings;
chart ticks 11px, chart values 12px, a route node's state line 11px. Nothing
reads below 11px.

## Named rules

**Signal-only colour.** Primary is ink (near black in light, near white in
dark). Hue means status, selection, seniority, lineage or a link — never
decoration. Blue (`--info`) is running, selected and focused.

**Measured, not eyeballed.** Text is 4.5:1 on every surface it sits on,
tinted status chips included; fields and every chart hue 3:1; the chart ramp
passes the dataviz validator per theme. `charts.test.tsx` holds the ramp and
the text tokens to it in both themes, and the a11y matrix scans both.

**Numeric truth.** Financial values, ids, digests, ratings, dates and
confidence scores are Geist Mono and tabular so columns scan and decimals
align; figure columns are right-aligned.

**Severity is shape and hue.** Success and running are a disc, warning a
triangle, critical a rounded square, idle a flat dot, and whatever ran
carrying its limitation forward a ring: a restricted node (F159), and a
module or forecast whose QA is `Restricted`, that states a limitation, or
whose scope is screening only (D71). A warning is what the bundle calls one,
a validation warning. Colour alone never carries status; a badge's tone
always sits beside its word.

**Sentence case.** Labels, buttons, badges, captions and status words are
sentence case, node and attempt states included ("Runnable · frontier",
"Blocked · not accepted"). Codes stay verbatim only where they are quoted as
codes: refusal codes, edge types (`REQUIRED`, `QA_GATE`), ids, and the
bundle's QA and committee statuses ("Passed", "Committee Ready", "Draft
Only"), which are its enumerated values and read as it spells them (D65). A
decision scope reads in words ("full scope", "screening only"). Mono is for
figures, ids, digests and times, never for words.

**Paper is for filed output and evidence pages only.** Ink on cream inside the
deliverable and the evidence page render. It must not leak into navigation,
buttons, panel headers or analytical tables.

**Motion answers the reader, and marks live state.** Custom ease-out, under
300 ms: buttons press to `scale(0.97)`, menus and tooltips grow from their
trigger (origin-aware), the drawer slides with the drawer curve, the sidebar
collapses in 200 ms. Transitions, not keyframes, so every motion can be
interrupted; the first tooltip waits 400 ms and the next ones are instant.
Running states pulse; loading shows skeletons. No entrance choreography, no
hover flourish. Reduced motion keeps fades only.

**One evidence surface.** The evidence drawer (a sheet). What a surface rests
on is counted where it is read and opens in the drawer; there is no second
inspector.

**Model text is formatted, never injected.** The model's Markdown is drawn as
the host renderer's closed element set in React elements (D60): headings,
paragraphs at 72ch, lists, tables whose figure columns are mono and right
aligned, status words as badges with their shape. Its exact text is always one
tab away ("As written"), and nothing it says reaches the page as markup.

## The shell

A shadcn app shell (D37), inset variant:

- **Sidebar** — collapsible to icons (⌘/Ctrl-B), a sheet at zoomed widths. The case
  switcher heads it (the directory's read, asked for when it opens); then the
  nine sections with their icons, each named with its count and state (a
  section this deployment does not serve says "Unavailable" in the link); the
  section-local group where a document has one; the served role, read-only;
  and Ask and Sign out, refused and visible. It is the only `nav`.
- **Header** — sticky: the sidebar trigger, the trail (the case's issuer, then
  the section as the page's h1, where focus lands after a navigation), then the
  document's warnings as toned badges, the run's state as mark and word, at
  most three actions with exactly one primary, and the theme menu. The trail is
  not a second navigation landmark.
- **Summary** — the first card of the body, drawn only over a document: the
  verdict (severity mark, conclusion, what blocks it), revision and approval
  where the document says them, one headline figure with what it counts
  ("6/10 modules complete") unless the conclusion already states it, then
  Change, Impact, Next step and Evidence. A cell with nothing to say is not
  drawn; never "—".
- **Views** — a section's own views are pills under the summary (the active
  one filled), wrapping to a second row rather than scrolling out of sight —
  the 2026-09-23 critique's rule that every view stays in sight, which is why
  they are not shadcn's line tabs, whose underline cannot survive a wrap;
  arrows move and select; a native select at zoomed widths. Never navigation
  between sections.

A section with no document says its state in the header badge and in the
region (shadcn's empty pattern: mark, title, sentence, the one action that
helps), and draws no summary.

Panels are shadcn cards (`.pnl`): radius-xl, a 1px ring, a 44px header with a
sentence-case title and a muted caption. A larger shadow means the object
floats above the workflow (menus, the drawer, the passport). A table wider
than its card scrolls inside it and fades at the edge it continues past; the
page never scrolls sideways. Counts by state are one badge per state, each
with its mark.

## Analysis

The route's modules are the section's views, in route order, each with its
QA state as shape and hue; the address names the one shown
(`?tab=<route node>`), and the section opens on its conclusion (the last
module that reasons, never the CP-CF calculator). Past eight views the tabs
are one row of module codes that stays under the header, each name on hover
and to a screen reader; with a view open, the section's summary is one line
and its brief opens on request. The module fills the width,
in the five places every module shares (D60), so a reader finds the same
thing in the same place in every module:

1. **Header** — name first, code second, QA state; one line of host facts
   (committee status, confidence, limitations, accepted, route node) and a
   count of what the run rests on that opens it in the evidence drawer.
2. **Lead** — the model's conclusion-first view and its drivers, beside the
   module's argument against itself (when it heads one), the key figures
   (host-typed tables only) and the caveats (the host's facts,
   then the audit's gap and conflict counts; a passing QA is the header's
   tag, not a caveat). With nothing to set beside it, the view takes the
   width. Prose runs about 65 characters a line, notes about 72. The view's
   first sentence is set large (19px, 500) with the rest of its paragraph
   quieter beneath; drivers written as a bold-led list are key points,
   numbered, each support clamped to three lines with "Read in full". A
   bracketed module reference is a small mono chip linking to that module
   and register (D62).
3. **Figures** — one chart card per host-typed table, under one header that
   carries the only provenance key and what the host calculated; a chart
   that would repeat the key figures is not drawn. A pressed mark is said in
   the card below them.
4. **Reader sections** — the model's risks, catalysts and triggers; a list of
   labelled items reads as columns.
5. **Depth** — one card of tabs, Appendix · Audit · As written, whose choice
   holds from module to module. The appendix is an index, grouped by what
   the registers are: each a line of id, name (the schema reference's, for a
   tagged table) and row count, opened in place one at a time, eight rows
   first. A module with no appendix register opens on Audit. Column heads
   the model wrote as identifiers read in words, the identifier on hover and
   in As written. The Audit tab is always host-verified citations, what the run rests
   on, then the model's audit summary, evidence trace, source registry, gaps
   and conflicts, and QA validation.

At zoomed widths the lead stacks: view, key figures, caveats.

## Charts

Drawn by Recharts (D61), shadcn/ui's chart primitive, in this app's marks
and nice ticks; laid out as shadcn's chart card (title and summary, the chart,
then the legend and the Table toggle). shadcn's `ChartStyle` is not used: it
injects a style element the CSP refuses. Nothing writes `innerHTML`, so every
chart holds under the production CSP.

- **Provenance is drawn in the mark.** Host-verified figures are solid;
  model-authored ones are outlined and hatched (a model line is dashed with
  hollow points). A value the document does not carry is a gap marked n/a with
  its reason, never zero and never interpolated. A bridge that does not
  reconcile draws its unexplained residual in the critical hue and says so.
- **Figures are printed as served.** Labels, names and table twins print the
  API's exact decimals; sums are exact; a float only places a mark.
- **Every chart is a figure:** a title, one plain summary line, and a table
  twin behind a Table toggle. A chart keys its own provenance unless the
  page keys it once for all its figures (`ProvenanceKeyed`, Analysis). Every mark is a button named for its series,
  category, value and origin; pressing it says the mark below the figures.
- **Colour:** `--chart-1..5` per theme, the tranche tokens for seniority,
  `--chart-neutral` for stated totals; a sixth series is neutral, never a
  recycled hue.
- No gradients, shadows, glow or rounded bar ends; bars start at zero; no dual
  axes. The route canvas alone carries a faint dot grid.

## Rules with teeth

- A refused control stays **visible and refused, with its reason named**:
  `aria-disabled`, never `disabled`, dashed and quiet, its plain reason beside
  or under it. Hiding it teaches the wrong model of the system.
- Every ready conclusion carries observation time, origin, method, approval and
  freshness.
- A private 404 and an absent route share one neutral wording:
  "Unavailable or not permitted."
- Dialog openers are passed explicitly, never inferred from
  `document.activeElement` — WebKit does not focus a button on click.
- Command outcomes are said inline beside the control that sent them and
  announced; no toasts (D35).
- No emoji in product chrome; icons are Lucide, one stroke weight.

## Reference

shadcn/ui (Nova, Base UI): https://ui.shadcn.com — motion: Emil Kowalski's
design-engineering notes, https://emilkowal.ski
