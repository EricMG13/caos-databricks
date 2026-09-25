# Design brief — polishing the CAOS workspace

*2026-09-25. For Claude Design. A refine-and-polish pass over the nine-section
workspace as built; not a redesign. The owner edits this before it is sent.*

*Status, later on 2026-09-25: CAOS is desktop only (decisions.md D63). Every
phone and 390px item below is withdrawn; the 320px reflow at 400% zoom stays,
under the a11y matrix. The questions in 9 are answered by D64–D69, and N100, N101 and N105 by D70–D72.*

## 1. The ask

Take the workspace as it stands — shadcn/ui's Nova style on Base UI, light and
dark, Geist, Recharts, the app shell and the five-place module — and make it
read as one finished instrument for credit committee work. Every screen should
look like it was drawn by one hand: the same rhythm between cards, the same
weight for the same kind of fact, the same treatment of an id wherever it
appears, and nothing on the page that reads as a developer's note to
themselves.

Deliver polished screens (light and dark), a delta to the tokens and spacing,
a copy sheet, and component-level specs that name the file each change lands
in. Section 7 says the exact form. Everything in section 3 is settled and is
not up for proposal; section 6 is where the work is.

## 2. What CAOS is and who reads it

CAOS turns governed source documents (10-Ks, credit agreements, earnings
releases) into committee-ready credit conclusions. Sources are admitted into
an immutable source set; a pinned route of CP-* modules runs one node at a
time against delivered evidence; every figure is anchored to a rectangle on a
page; a deliverable is saved, signed, frozen and filed under an audit chain.
The workspace is where an analyst reads the run, reads each module's
conclusion with its figures and its audit, writes the narrative, and where an
approver signs and files.

Three roles read it. The **analyst** writes and runs. The **approver** (a PM
or committee member) reads the conclusion and its evidence, signs an opinion
and files. The **reader** reads and can act on nothing; every control they
cannot use stays on the page, refused, with its reason. All three read dense
pages for a living; the north star in `DESIGN.md` is "a calm, exact workspace"
— dense is allowed, disorganised is not.

The nine sections, in sidebar order, and what each is:

| Section | Route | What it shows |
|---|---|---|
| Directory | `/directory/` | Every case the reader holds standing on; create a case; who holds standing |
| Upload | `/upload/?case=…` | The case's source pack, the immutable set versions, admit and withdraw |
| Analysis | `/analysis/?case=…&tab=<node>` | One module at a time: its conclusion, key figures, charts, reader sections, appendix, audit, as written |
| Book | `/book/` | Accepted CP-CF projections across cases, as one comparison table per period |
| Run | `/run/?case=…` | The resolved route as a canvas of nodes and edges, the gates, attempts, and the run's commands |
| Model | `/model/?case=…` | The accepted CP-CF forecast: its record, limitations, periods |
| Report | `/report/?case=…&run=…&revision=…` | The revisions, the module artifacts they rest on, the narrative editor, and the filing controls |
| Committee | `/committee/?case=…&run=…&revision=…` | The filed deliverable as paper, its signatures, the rendered page and the package |
| Admin | `/admin/` | Unavailable in this deployment; shown as the unavailable state |

## 3. What is fixed

These are owner decisions with evidence in the gates. Design within them; do
not propose replacing them.

**Stack.** shadcn/ui Nova on Base UI (D35), copied into
`frontend/src/components/ui` and owned there. Tailwind 4 with every colour as
a token in `frontend/src/styles/tokens.css` (D37); the workspace's own classes
in `frontend/src/styles/caos.css` (`.pnl` card, `.cp` caption, `.rb` control,
`.tscroll` wide table, `.tabular`) and the chart styles in `charts.css`.
Geist and Geist Mono, bundled (D36). Lucide icons, one stroke weight.
Recharts for every chart (D61). React 19, react-router 7.

**The production CSP.** `script-src 'self'; style-src 'self'; font-src
'self'` and Trusted Types `'none'`. So: no inline `<style>` element, no
`innerHTML`, no web font, no external image, no library that injects a style
tag at load (Sonner and shadcn's `ChartStyle` were both refused for that).
Styles are classes and CSS custom properties; a value computed at runtime goes
through a `style` prop or a custom property, never a stylesheet string.

**The shell** (D37; `DESIGN.md` "The shell"). Sidebar (collapsible to icons,
a sheet on a phone; case switcher, nine sections with icons, the served role,
Ask and Sign out), sticky header (trigger, the Case › Section trail with the
section as the page's h1, the document's warnings as toned badges, the run's
state, at most three actions with exactly one primary, the theme menu), the
summary card first in the body, then a section's views as pills. Panels are
shadcn cards: radius-xl, a 1px ring, a 44px header with a sentence-case title
and a muted caption.

**The Analysis module's five places** (D60, D62): header, lead (the
conclusion's first sentence set large beside the argument against itself, the
key figures and the caveats), figures, reader sections, depth (one card of
tabs: Appendix · Audit · As written). The model's Markdown is drawn as the
host renderer's closed element set; no figure is ever read from it.

**The named rules** in `DESIGN.md`, all of them, in particular:

- Signal-only colour: primary is ink; hue means status, selection, seniority,
  lineage or a link. Blue (`--info`) is running, selected and focused.
- Severity is shape and hue: success and running a disc, warning a triangle,
  critical a rounded square, idle a flat dot, restricted a ring. Colour alone
  never carries status.
- Numeric truth: financial values, ids, digests, ratings, dates and
  confidence scores are Geist Mono, tabular; figure columns right-aligned.
- Sentence case everywhere; codes verbatim only where quoted as codes
  (`REQUIRED`, `QA_GATE`, refusal codes, ids). Mono is for figures and ids,
  never words.
- Paper (ink on cream) inside filed output and the evidence page only. Never
  in navigation, buttons, panel headers or analytical tables.
- Motion answers the reader: custom ease-out, under 300 ms, transitions not
  keyframes, press at `scale(0.97)`, running states pulse, loading is a
  skeleton. No entrance choreography, no hover flourish.
- A refused control stays visible and refused with its reason named:
  `aria-disabled`, dashed and quiet, never `disabled`, never hidden.
- Command outcomes are said inline beside the control that sent them; no
  toasts.
- One evidence surface: the drawer. No second inspector.
- No emoji in chrome. No all-caps labels. No gradients, glow, glass, pastel
  cards, hero-metric tiles.

**Vocabulary** (`CONTEXT.md`): one term per concept — case, source, source
set, block, citation, module, route, frontier, artifact, snapshot, build,
revision, deliverable, opinion, filing. Node states are the bundle's words:
`COMPLETE · RUNNABLE · RESTRICTED · BLOCKED` (never "degraded", "partial" or
"warning" for a node). Avoid *dashboard*, *AI-powered*, *seamless*,
*leverage* (verb), *insight* (countable), and *user* where analyst, PM,
approver or reader is meant. A gate refuses a synonym in an identifier; the
same discipline holds for copy.

**Accessibility floors** (gates; none may be loosened). axe reports zero
violations across three engines × nine routes and every fixture state × four
viewports (1440×900, 1280×800, 1024×768, 320×640) × both themes. Text 4.5:1
on every surface it sits on, tinted chips included; a field's edge and every
chart hue 3:1; the chart ramp passes the dataviz validator per theme. Every
target at least 24px, every governed control at least 28px. Reflow at 320px
with no sideways page scroll (a wide table scrolls inside its card). Reduced
motion keeps fades only. Nothing reads below 11px.

**The type scale**: 14px body, 13px figures and secondary, 12px labels and
captions, 16–18px headings, 19px/500 for a module's first sentence, chart
ticks 11px and values 12px.

## 4. How to see the current build

```bash
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build:demo
npm --prefix frontend run preview:demo     # http://localhost:4173
```

The demo serves fixtures at the real wire's routes with no backend. The
routes the gates drive are listed in `frontend/scripts/fixture-routes.mjs`;
the ones worth a screen each:

| Screen | Route |
|---|---|
| Directory | `/directory/` and `/directory/?fixture=observed-empty` |
| Upload | `/upload/?case=ff1fbf5a-e56f-4f84-a983-2f5a507675f0` (`&fixture=acts` for the offered commands) |
| Analysis, conclusion | `/analysis/?case=00000000-0000-4000-8000-000000000001` |
| Analysis, a module with figures | `…&tab=rn-cp-1` (six charts, five appendix registers), `…&tab=rn-cp-1b`, `…&tab=rn-cp-2g` |
| Analysis states | `…&fixture=partial`, `stale`, `offline`, `unavailable`, `error` |
| Run, mid-route | `/run/?case=00000000-0000-4000-8000-000000000001` |
| Run, at a gate | `…&fixture=gate`; `…&fixture=acts` for every command |
| Book | `/book/` |
| Model | `/model/?case=00000000-0000-4000-8000-000000000001` |
| Report | `/report/?case=00000000-0000-4000-8000-000000000001&run=00000000-0000-4000-8000-0000000000b2&revision=00000000-0000-4000-8000-0000000000c3` (`&fixture=acts` for the filing controls) |
| Committee | same query on `/committee/` |
| Admin, unavailable | `/admin/` |
| Absent route | `/nothing/` |

Two things about the fixtures. The Directory, Upload, Run and Analysis
fixtures are realistic (a Carvana case with real-shaped registers and
figures); design against those. The Report, Committee, Book and Model
fixtures are synthetic — "Acme Credit", digests of repeated letters, ids of
repeated digits — and Report and Committee carry hostile strings (`<img
onerror…>`) on purpose, to prove nothing reaches the page as markup. Do not
design around the hostile text; assume a real narrative of three to six
paragraphs with two or three citation chips, and real 64-character digests.

The theme menu is in the header; the system's choice holds until a pick.
`⌘/Ctrl-B` collapses the sidebar. The demo's top banner ("Read-only
demonstration…") exists only in demo mode.

## 5. The current build, screen by screen

What is on each screen today and what wants polish. Each finding is
observable in the demo at 1440×900 unless a viewport is named.

### Directory

The summary reads "4 cases." with a flat dot, then Change / Next step /
Evidence. The register is a table (truncated case id in mono, title, created,
standing, live sources, latest run as a state badge over two mono lines, an
"Open case" link). Below it a Create case field and button, a disclosure that
says "Available means the command would answer, not that it will succeed",
and a Case access card of one disclosure per case.

- The "Latest run" cell stacks a badge and two mono lines; rows run to 78px
  for one line of content. Set the badge and the route code on one line and
  drop the row to a single rhythm.
- "your standing: approver" in the access rows is lowercase where the table
  says "Approver". One casing.
- The disclosure sentence about "Available" is a note to the builder, placed
  in the primary flow. Either say it once as a caption on the field, or not
  on the page.
- The summary's verdict "4 cases." is a count with a full stop; the headline
  figure slot to the right is empty. Decide the grammar of a verdict that is
  only a count (see 6.7).

### Upload

The summary says "1 withdrawn source stay cited where they were used." with
"5 sources admitted" as the headline figure; the Source pack badge says
"6 sources · 1 withdrawn". The pack is a native file input ("Choose Files /
No file chosen"), a refused Admit with "Not offered on this page yet." under
it, a second line "Withdraw: Not offered on this page yet.", then the table
(filename, digest, admitted, extractor identity), which scrolls inside the
card and fades at the right edge. Set versions is a card on the right, each
version a bare number over "6 sources · 0b582ff0c768".

- The plural is wrong ("1 … stay … they"); the count and the badge disagree
  in what they count (admitted vs rows). Fix the copy in `chrome/compose.ts`
  and say what the 5 and the 6 are.
- The native file input is the only unstyled control in the product. Draw it
  as a shadcn control (a button that opens the picker, the chosen names as
  chips) without changing that it is an `<input type=file>`.
- Two refused-reason lines sit one over the other. One reason for the pack's
  commands (6.3).
- The fade cuts the "Extractor identity" column head mid-word at 1440. The
  fade is the rule; the cut head is the problem (6.5). A version reads as a
  bare "4"; give it its word ("Version 4" or "v4").

### Analysis

The strongest screen and the one most readers will live in. The summary is
one line (mark, verdict, approval, "12/12 modules accepted", Brief). Twelve
view pills carry the module codes in mono with their QA mark. A module's
header is its name, its code, its Passed tag, a line of host facts, and the
"4 documents · 4 citations · 1 withdrawn ›" chip that opens the drawer. The
lead card sets the first sentence at 19px; CP-1 shows key points, a code line
and a subheading beneath. The figures row shows six chart cards in three
columns with a provenance key. The depth card holds Appendix · Audit · As
written. A "Route complete" card closes the page.

- The chart cards in a row are different heights (a three-item legend vs
  none), so their "Table" toggles float at different heights. Give a row one
  height and pin legend and toggle to the card's foot (6.4).
- The figures header wraps the provenance key against the right-hand note
  ("Deterministic calculations: none performed by the host…"); on the
  conclusion module that same note floats between two cards as an orphan
  line. Give it a home: a caveat, or the figures header, in every module.
- The diverging bar's category labels are cut ("Share-based compe…", "Change
  in fair va…") at 11px mono. Wider label column or two-line labels.
- A module served without a name shows only its code as its name (CP-7 in
  the demo). Show the code as the name and nothing beside it, not a name
  slot with a code in it.
- The host-facts line runs label and value pairs inline with mixed weights;
  at 390px it wraps into a run-on. Consider a definition list on the phone.
- The Audit tab lists sources as long underscore filenames in bold sans;
  they read heavier than the page's headings. Filenames are ids: mono,
  regular weight, and let the page and citation count carry the weight.
- The closing card's badge "0" says nothing on its own ("Route complete · the
  run ended COMPLETE · 0"). Name what the count counts, or drop it when zero.
- The pill row: past eight views the codes stay in one row, as the rule
  wants; check the active pill's fill has the 3:1 edge it needs in dark.

### Run

A canvas of stage columns with node cards (code, state with its mark, the
edge that placed it), edges drawn as lines by type, a QA_GATE diamond, and a
legend of five edge types. To the right, Selected node, Attempts, Run and
Gates cards. Below, "Act on this run": Subject (a form), Source set, Research
plan, Work (Start · Retry · Cancel), Create run.

- The canvas opens scrolled so that the selected node (CP-0, in the rail) is
  off-screen to the left while CP-6 wears an amber ring for "awaiting the
  gate". Selection is blue by rule; the gate is the amber edge. Make the
  selected node visibly selected and scrolled into view, and let the gate's
  amber sit on the edge and the diamond, not on a node's ring.
- Edges cross the canvas diagonally through other columns (CP-4 → CP-7 runs
  under CP-5). Route them orthogonally in the gutters, or bend at the
  column's edge.
- "Stage 100" for CP-CF is the bundle's number for the host extension; on a
  canvas it reads as a mistake. Say "Extension" or place CP-CF after the last
  stage without a number.
- The legend's five items wrap to two lines and fall below the fold at 900px.
  A compact legend, or the edge types keyed in a popover from one control.
- The empty canvas (route not pinned) draws 350px of dot grid with one
  sentence in it and the full legend under it. Use the empty pattern: mark,
  title, sentence, the one action; no grid, no legend.
- "displayed and latest are named separately" in the Runs caption is a note
  to the builder. Caption the card with what it is; say the distinction in a
  tooltip on the row's "Displayed · latest" tag if it needs saying.
- The Run card wraps a UUID across two lines, right-aligned. Ids do not wrap
  (6.1).
- Under "Act on this run", with every command refused, "Not offered on this
  page yet." appears six times. One reason per card (6.3).
- Node cards truncate their edge text ("accepted · CONDITIONAL rn-cp-1 …");
  the card is 150px wide. Either the node card is a code and a state, with
  the placing edge in the rail, or it is wide enough to say it.

### Book

The summary ("Partial · 3 credits.") is followed by a dashed alert that says
Partial again ("Rendered with warning status."), then a Basis card of three
mono codes and a bold-led paragraph of explanation, then one table per period
with a centred caption above the header row, a "Not served" chip in each
cell of a blocked credit, and the table cut at "Capital expen…".

- State is said three times: header badge, summary mark and word, alert.
  Once (6.2).
- The explanatory paragraph inside a data card is documentation. A caption
  on the card or a line in the summary's Evidence cell; not a paragraph among
  the figures.
- The centred table caption is the only centred text in the product.
  Left-align it as the card's caption.
- A cell that is "Not served" in every column of a row is one fact about the
  row; say it once in the row's first cell and dim the rest, rather than six
  chips.

### Model

The summary, an Accepted forecast card of label/value rows — the accepted
time, two full 64-character digests, QA, units, perimeter — then Limitations
and Validation warnings as bold-led lines, then a Periods table. Half the
viewport is empty below.

- The two full digests span the card and set its width; every other value on
  the card is short. Truncate with the full value one hover and one copy away
  (6.1).
- Bold-led lines ("Limitations. LIMITED_HISTORY") are a third label style on
  one card, after the label/value rows and the caption. One label style per
  card.
- The summary mark is a warning triangle for an accepted forecast whose only
  fact is a stated limitation. Check the severity mapping: a limitation the
  bundle carries forward is RESTRICTED's ring, not a warning.

### Report

The summary, a "Saved report" card of four full ids and digests, the
Revisions table, one card per module artifact (two full digests, a scope, a
Formatted / As written segmented control, the text), then Filing: a textarea,
two lines of helper text, a citation select with Insert figure, and a row of
four buttons — Save revision (primary), Sign opinion, Freeze deliverable,
File deliverable — then the Narrative card.

- Save → sign → freeze → file is the product's peak moment and it is a row
  of four equal buttons. Draw it as the sequence it is: the step the revision
  is at, the steps done, the step offered, the steps refused with their
  reason. One primary at a time.
- The helper text under the textarea is two sentences of rules ("Type prose
  only. Every figure goes in through the citation picker…"). Keep the rule,
  set it as a caption, and let the refusal at save carry the detail.
- The digests (6.1). The artifact card's segmented control sits inside a
  card whose header already carries the module's tag; see if the control
  reads better in the card's header row.

### Committee

The paper: cream, a title, "Filed" as a rotated outlined stamp, the
narrative with a citation chip, signed / frozen / filed by, the payload line.
Under it two links (Open the rendered page · Download the package). Then the
same artifact cards as Report.

- This is the best moment in the product; keep it. Polish: the stamp overlaps
  the id line at the top right; the paper's left edge aligns with the cards
  above but its right edge stops at 735px, leaving a ragged column — either a
  fixed page width centred in the body, or the paper's own margin rule.
- The two links under the paper are the deliverable's actions; consider them
  as the header's actions for this section (at most three, one primary) so
  they are where every other section's actions are.
- The artifact cards below the paper repeat Report. If Committee is the
  approver's page, the cards are the audit and can open closed.

### Admin and the absent route

The unavailable state draws a dashed card with a warning triangle, the word
"Unavailable", and the sentence "Unavailable or not permitted." — title and
sentence say the same thing. The empty pattern is mark, title, one sentence,
one action; here the sentence should add something (what to do) or the title
should go.

### The chrome, everywhere

- The sidebar's foot has Ask and Sign out as permanently refused dashed
  buttons with no reason visible. A refused control names its reason; two
  dashed buttons in the chrome of every page read as unfinished. Make the
  reason reachable (a tooltip is fine) and quiet the dashes in the sidebar.
- The case switcher truncates "Carvana Co. (NYSE: …" at the sidebar's width
  and shows "Case 00000000" beneath. Show the ticker or the short id, not a
  cut title; the full title is in the trail.
- The demo banner is a full-width warning wash; in dark it is a yellow-olive
  band over every page. It is demo-only, so it may stay loud, but it should
  not set the page's first impression for a design review — a thin line in
  the header's colour with the text in `--warning` would say the same.
- The header's state badge duplicates the summary's mark and word on every
  section (see 6.2). Decide which one is the state's home when the summary is
  in view; the badge earns its place once the summary has scrolled away.
- At ≥1440 the body runs edge to edge; the summary card's cells sit 280px
  apart with 20-character contents. Consider a reading width for the summary
  and the lead (the module's prose already stops at 65ch) while tables and
  the canvas keep the width.

## 6. Cross-cutting polish targets, in priority order

**6.1 Ids and digests: one rule.** Today a case id reads `ff1fbf5a…75f0` in
Directory, a run id wraps across two lines in Run, and a sha256 prints all 64
characters in Model, Report and Committee. Specify one `Digest` treatment:
mono, the first 8 and last 4 with an ellipsis, the full value as the
accessible name and on hover, one click to copy with an inline "Copied" that
fades (no toast). Where the full value is the point — the paper's payload
line, the As-written tab — print it whole, wrapped at the card's width with
`overflow-wrap: anywhere`. Name where each applies.

**6.2 One home for state.** A section's state appears in the header badge,
the summary's mark and word, and (Book, Run at a gate) a dashed alert under
the summary. Specify: the summary is the state's home while it is in view;
the header badge carries it once the summary scrolls out (or always on a
phone, where the summary is below the fold); the dashed alert is only for a
warning the summary cannot carry (a refusal code with a reason line). Show
the rule on Book and on Run at its gate.

**6.3 Refused controls: reason once per group.** `RefusedControl` prints
"Not offered on this page yet." under each control. With three refused
controls in one card that is three identical lines. Specify a grouped form:
the controls dashed as today, one reason line for the card when every reason
is the same, per-control lines only when they differ. Keep every reason
reachable from its control for a screen reader.

**6.4 Chart card rhythm.** In a row of chart cards: equal heights, the plot
area sharing one baseline, legend and Table toggle pinned to the foot, the
summary line clamped to two lines with the rest in the card's tooltip or the
table twin. Category axis labels get a measured column (up to ~18 characters)
or wrap to two lines; never an ellipsis inside a category name. The
provenance key is set once in the figures header, left, with the host's
calculation note as a caption beneath it, not beside it.

**6.5 Wide tables.** A table wider than its card scrolls inside it and fades
at the continuing edge; that stays. What changes: the column head is never
cut mid-word — the fade begins after the last fully visible column, and the
table's first column is sticky so a row keeps its name while scrolling.
Specify a column priority per table (which columns give way first at 1024
and 320) for the case register, the source pack, Book, and the appendix
registers, until the row-at-a-time form (N95) is chosen.

**6.6 The route canvas.** Selection is a blue ring and the selected node is
scrolled into view on load; the gate's amber lives on the edge and its
diamond only. Edges run orthogonally in the column gutters. Stage labels are
"Stage n" for the bundle's stages and a word for the host extension. The
legend is compact and one row at 1280, or a keyed popover. The empty canvas
uses the empty pattern, no grid.

**6.7 The summary card's grammar.** The verdict is a sentence fragment
today ("4 cases.", "Filed.", "Accepted CP-CF projection.", "1 withdrawn
source stay cited where they were used."). Specify the grammar of the verdict
line in three cases: a state with a subject ("In progress · CP-6 at its
gate"), a count only, and a warning. Say when the headline figure is drawn
and when the verdict already states it. Fix the agreement in every
`compose.ts` string on the way.

**6.8 Captions are subtitles, notes are notes.** A card caption (`.cp`)
names what the card is ("One issuer engagement per row"). Today it also
carries builder notes ("displayed and latest are named separately",
"Available means the command would answer…"). Specify: captions describe;
anything that explains a rule is a tooltip on the thing it explains, or is
not on the page.

**6.9 Label styles per card.** Cards mix label/value rows, bold-led lines
("Limitations. LIMITED_HISTORY"), and caption pairs. One label style per
card, and at most two on a page.

**6.10 Forms.** The file input as a shadcn control; the Subject form's grid
(three fields then one) on a 4px rhythm with consistent label spacing; the
narrative textarea and its citation row as one composed control.

**6.11 Filing as a sequence.** Specify the stepper (6 Report above): four
steps, the current step's control primary, done steps with their time and
signer, refused steps dashed with the reason, all inline, no modal beyond the
existing confirm step.

**6.12 Dark parity.** For every change, both themes: the tinted selected row
in Run, the active pill's edge, chart neutrals against `--card`, the paper
(which stays cream in dark) and its drop shadow on a dark body, the demo
banner.

**6.13 Phone.** *Withdrawn: desktop only (D63).* At 390px: the banner wraps to two lines; the summary stacks
its cells with the headline figure between them; the host-facts line runs on.
Show Analysis (a module with figures), Run and Directory at 390 in dark.

## 7. Deliverables and their form

1. **Screens.** For each of the nine sections, the polished screen at
   1440×900 in light and dark, on the realistic fixture where one exists;
   Analysis on `rn-cp-1` and on the conclusion; Run mid-route and at its
   gate; Report with the filing controls offered. Analysis, Run and Directory
   also at 390 in dark. Each screen annotated with the rule each change
   serves (a section-6 number or a `DESIGN.md` rule).
2. **Token and spacing delta.** Only changes to values in
   `frontend/src/styles/tokens.css` (and additions, named in shadcn's
   pattern), each new or changed colour with its measured contrast on every
   surface it sits on in both themes. A spacing spec on the 4px grid: card
   padding, header height, row heights for the register, the source pack and
   an appendix register, the gap between cards, the summary's cell gap.
3. **Copy sheet.** Every string changed: before, after, the file
   (`frontend/src/chrome/compose.ts`, `controls/RefusedControl.tsx`,
   `sections/directory/NewCase.tsx`, `sections/run/RunSection.tsx`, …). Copy
   is sentence case and uses `CONTEXT.md`'s words.
4. **Component specs**, each one page: `Digest`; the state-once rule
   (header badge, summary, alert); the grouped refused control; the chart
   card foot; the wide table's sticky column and column priority; the route
   canvas's selection and edge routing; the filing stepper; the file input.
   Each names the file it changes and the test that names it (every public
   definition is named by a test; `frontend/tests/unit/*.test.tsx`).
5. **A change list** in priority order that the owner can hand to a build
   session as tasks, each small enough to land as one PR that keeps every
   gate green.

Acceptance for anything in the list: it lands as edits to the files above
(no new stylesheet, no new dependency without a `Dn` entry in
`docs/rebuild/decisions.md`; stdlib, then an already-pinned dependency, then
new code); both themes; axe zero across the matrix; contrast measured, not
eyeballed; every refused control still visible with its reason; no
`innerHTML`, no inline style element; vocabulary clean; and nothing below
11px.

## 8. Out of scope

- New data on the wire: the heading-labelled registers as typed tables
  (N94), module names served from the bundle catalog (N61), a structured
  narrative editor in place of the textarea (N90).
- The row-at-a-time register (N95): propose the form in one screen if you
  have a view, but it is the owner's pick, not this pass.
- Bundle splitting and load performance (N91).
- Any change to what a section shows, the order of the nine sections, the
  route resolution, the evidence drawer's contract, or the paper rule.
- Brand: the "C" mark, the name, a logo, illustrations, marketing surfaces.
- Anything `DESIGN.md` rejects outright.

## 9. Questions for the owner before the pass starts

1. A reading width for the summary and the lead at ≥1440, or edge to edge as
   today?
2. "Committee Ready" is the bundle's committee status, printed as text in
   Title Case among sentence-case words. Is it quoted as a code (keep) or
   read as a word (sentence case)?
3. The digest treatment: 8…4 with copy, or 12 characters as the Upload table
   prints them?
4. The header's state badge when the summary is in view: keep both, or badge
   only once the summary scrolls away?
5. The demo banner: leave loud, or the thin form?
6. Committee's two links: header actions, or under the paper as today?

## Reading list

`DESIGN.md` (the whole of it), `CONTEXT.md`, `docs/rebuild/decisions.md`
D35–D37 and D60–D62, `docs/rebuild/next.md` N90–N95,
`frontend/src/styles/tokens.css`, `caos.css`, `charts.css`,
`frontend/src/chrome/` (the shell), `frontend/src/sections/analysis/module.tsx`
(the five places), `frontend/src/charts/ChartFrame.tsx` (the chart card),
`frontend/scripts/fixture-routes.mjs` (every route the gates drive).
