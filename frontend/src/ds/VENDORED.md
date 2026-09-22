# Vendored design-system primitives

Copied from the predecessor frontend, `github.com/EricMG13/Credit-Operating-System`,
local clone `Alpha/Final @ f454c654f`, path `caos/frontend/src/` (`docs/DECISIONS.md` §18).
The blob hash is `git hash-object` of the source file at that commit. Nothing loads the
`_ds_bundle.js` runtime and nothing depends on the private `caos-frontend` package.

| File here           | Source path                          | Blob       | Changes                                                                                                                                                 |
| ------------------- | ------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TextInput.tsx`     | `components/shared/TextInput.tsx`    | `f92efd6d` | `"use client"` dropped                                                                                                                                  |
| `ActionReason.tsx`  | `components/shared/ActionReason.tsx` | `85ad0516` | `"use client"` dropped; `data-*` passes through unchanged                                                                                               |
| `SurfaceState.tsx`  | `components/shared/SurfaceState.tsx` | `eb6f56b8` | kinds are the seven of `IA_SPEC.md` §6 (`empty` → `observed-empty`; `checking`, `not-run` dropped); the glyph is `SeverityMark` (`DESIGN.md` shapes)    |
| `atoms.tsx`         | `components/pipeline/atoms.tsx`      | `66370ae1` | `Tag` only; `Dot`, `Bar`, `ToggleGroup` and `SimControls` are not carried (`docs/design/BRIEF.md`, Run: simulation discarded)                           |
| `use-modal-a11y.ts` | `lib/use-modal-a11y.ts`              | `58d58f47` | the opener is a required argument and focus returns to it; `document.activeElement` is never read (`IA_SPEC.md` §7); only the topmost overlay traps Tab |
| `sev.ts`            | `lib/pipeline/sev.ts`                | `f275bc44` | `isCleared` and `moduleLiveState` dropped (predecessor QA vocabulary)                                                                                   |

Not carried, because no section uses them: `Panel` (sections draw the design project's `.pnl`
markup from `caos.css`), `StatCard`, `SectionHeader`, `StatusGlyph` (`locked`/`held` have no
surface yet), `lib/a11y.ts` (`onActivate`: every clickable row is a real button or link).

Tokens: `src/styles/tokens.css` carries the bound design system's values (`DESIGN.md`),
not the clone's re-tuned `globals.css` values.
