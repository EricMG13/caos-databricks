# Vendored design-system code

## shadcn/ui (D35)

`src/components/ui/*` and `src/hooks/use-mobile.ts` were copied in by the shadcn CLI
4.21.0, style `base-nova` (Base UI primitives, the Nova preset), MIT licence, and are
owned here: edit them like any other source. `components.json` records the style for the
next `npx shadcn@4.21.0 add`. The variants the CLI's `shadcn/tailwind.css` declares for
Base UI's state attributes (`data-open`, `data-closed`, `data-checked`, `data-selected`,
`data-disabled`, `data-active`, `data-horizontal`, `data-vertical`) and its `no-scrollbar`
utility are vendored into `src/styles/tokens.css`; the `shadcn` package itself is not a
dependency.

Changes from the CLI's output:

| File                | Change                                                                                                                                                                                                                                                           |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `button.tsx`        | press is `scale(0.97)` with named transition properties (no `transition-all`); a refused (`aria-disabled`) button is dashed and quiet and keeps its pointer; `destructive` is solid (ink on red, above 5:1 in both themes, where Nova's tint measured 3.1-4.4:1) |
| `badge.tsx`         | `success`, `warning` and `info` tones beside `destructive`; `badgeVariants` not exported                                                                                                                                                                         |
| `sidebar.tsx`       | open state in localStorage (`caos.sidebar`), never a cookie; `SidebarInset` is a div; `ease-out`; `SidebarMenuSkeleton` dropped (a random width in render)                                                                                                       |
| `use-mobile.ts`     | `useSyncExternalStore` on the media query, so the first render is right and a page without `matchMedia` is a desktop                                                                                                                                             |
| `tooltip.tsx`       | a 400 ms first delay; transitions on Base UI's starting and ending styles, instant within a group (`data-instant`)                                                                                                                                               |
| `dropdown-menu.tsx` | transitions on Base UI's starting and ending styles, origin-aware, a faster exit                                                                                                                                                                                 |
| `sheet.tsx`         | the drawer curve (`ease-drawer`)                                                                                                                                                                                                                                 |
| `skeleton.tsx`      | no pulse under reduced motion                                                                                                                                                                                                                                    |
| `tabs.tsx`          | `tabsListVariants` not exported                                                                                                                                                                                                                                  |
| everything          | formatted by the repository's Prettier                                                                                                                                                                                                                           |

## The predecessor's primitives

Copied from the predecessor frontend, `github.com/EricMG13/Credit-Operating-System`,
local clone `Alpha/Final @ f454c654f`, path `caos/frontend/src/`.
The blob hash is `git hash-object` of the source file at that commit. Nothing loads the
`_ds_bundle.js` runtime and nothing depends on the private `caos-frontend` package.

| File here          | Source path                          | Blob       | Changes                                                                                                                                                                                                         |
| ------------------ | ------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ActionReason.tsx` | `components/shared/ActionReason.tsx` | `85ad0516` | `"use client"` dropped; `data-*` passes through unchanged; `reasonTitle` carries the pointer's fuller detail (the code) while the reason stays the plain sentence; the control is shadcn's `Button` (D35)       |
| `SurfaceState.tsx` | `components/shared/SurfaceState.tsx` | `eb6f56b8` | kinds are the seven region states (`empty` → `observed-empty`; `checking`, `not-run` dropped) plus `choose`, a case section waiting on the reader's selection; the glyph is `SeverityMark` (`DESIGN.md` shapes) |
| `atoms.tsx`        | `components/pipeline/atoms.tsx`      | `66370ae1` | `Tag` only, now a shadcn `Badge` in the severity's tone (D35); `Dot`, `Bar`, `ToggleGroup` and `SimControls` are not carried (the legacy design brief's Run: simulation discarded)                              |

`TextInput.tsx` (now shadcn's `Input`) and `sev.ts` (now the badge's tones) were removed
with D35, and `use-modal-a11y.ts` with N64: the evidence overlays are Base UI's Dialog
(`evidence/Overlay.tsx`), told to return focus to the opener it is passed. Not carried, because no section uses them: `Panel` (sections draw `.pnl` from
`caos.css`, styled as shadcn's card), `StatCard`, `SectionHeader`, `StatusGlyph`
(`locked`/`held` have no surface yet), `lib/a11y.ts` (`onActivate`: every clickable row is a
real button or link).

Tokens: `src/styles/tokens.css` carries the theme's values (`DESIGN.md`, D37).
