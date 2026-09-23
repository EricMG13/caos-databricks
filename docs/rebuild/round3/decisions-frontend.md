# Frontend adversarial-review findings, FE-1 to FE-12

One paragraph per finding. Every one was checked against the code before it was
patched; all twelve were confirmed, and none was declined.

**FE-1 — FIXED — the guard now sits where two presses in one frame can both see
it.** `useCommand.run` (`frontend/src/sections/run/controls.tsx`) takes an
in-flight ref, read and written in the same synchronous step as the send, so a
second activation while the first is still open sends nothing and answers
`null`; every caller was narrowed to `outcome?.kind`. The visible half is a
`busy` prop carried from `RefusedControl` to `ActionReason`, which renders the
control `aria-disabled` and `aria-busy` while it waits and, because the busy
text is the only thing that changed, lets the fixed `aria-label` step aside so
the control is named "Creating…" rather than "Create run" (this is also the
`aria-label`-override half of FE-6). Tests:
`test_a_second_press_while_a_command_is_in_flight_sends_nothing` (three clicks
inside one `act`, which is the batch a render-time `pending` cannot see) and
`test_a_busy_control_is_aria_disabled_and_named_by_its_busy_text`.

**FE-2 — FIXED — a refetch that does not answer no longer throws away the
document or the draft under it.** `adopt` in `frontend/src/app/Workspace.tsx`
keeps the displayed document when the refetch carries none, records it as
`interrupted`, and replaces at once only for `unavailable` — a 404 or standing
lost, which is the safety case. The workspace renders a polite `NotLive`
banner (`frontend/src/states/PageAlert.tsx`) naming the typed code, and because
the mount key does not move, an unsaved committee narrative survives. Tests:
`test_a_failed_refetch_keeps_the_displayed_document_and_marks_it_not_live`,
`test_a_refused_refetch_names_its_code_and_does_not_replace_the_document` and
`test_an_unsaved_draft_survives_a_refetch_that_did_not_answer`.

**FE-3 — FIXED — a refused reconnect is waited out, not the end of the tail.**
`openTail` (`frontend/src/app/sse.ts`) reopens a CLOSED source on a backoff of
1 s doubling to a 60 s ceiling, or the server's own `Retry-After` where the
refusal carried one; `onRefused` now answers with a decision, and the workspace
computes it from the document read, stopping only when that read says the case
is gone. `fetchSection` carries `retryAfterSeconds` on a refusal
(`frontend/src/app/transport.ts`, via the new `retryAfterOf`), and the
workspace shows and announces a "Live updates paused" `NotLive` banner while
the tail is down. Tests: `test_a_refused_reconnect_reopens_the_tail_after_the_backoff`,
`test_a_refused_reconnect_waits_the_servers_retry_after`,
`test_a_case_that_is_gone_stops_the_tail_for_good`,
`test_the_reconnect_wait_doubles_from_a_second_to_a_minute_and_honours_retry_after`,
`test_a_refusals_retry_after_is_carried_in_seconds_or_not_at_all` and
`test_a_refused_tail_says_live_updates_are_paused_and_reopens`.

**FE-4 — FIXED — the page says which view it is, and focus follows the
reader.** `Workspace` is no longer keyed on the section in
`frontend/src/app/App.tsx`, so the rail — the only navigation — outlives a
navigation and the activated link keeps its place; the evidence surface keeps
the old behaviour through a `key` on its own provider. `frontend/src/app/heading.ts`
holds `pageTitle` and `focusSectionHeading`, the one place focus lands; the
workspace sets `document.title` per section and case, and focuses the section
heading (now `tabIndex={-1}`) whenever the request key changes and after
RELOAD. `useModalA11y` restores focus to an opener only while
`opener.isConnected`. Tests: `test_the_page_title_names_the_section_and_the_case`,
`test_a_navigation_moves_focus_to_the_section_heading` and
`test_focus_is_not_handed_to_an_opener_that_has_left_the_page`.

**FE-5 — FIXED — the workspace reflows at 320 CSS px, and the gate now
measures it.** `overflow-x: hidden` came off `html, body, #root`
(`frontend/src/styles/tokens.css`); the register, the source pack and the
book's tables sit in a `.tscroll` wrapper that is a named, keyboard-reachable
region, and the Model's period body became one too. `.tscroll` carries
`contain: paint`, which is what actually stops a table's intrinsic width
widening the document's own scroll range; the brief's four cells stack below
640 px; and the book cells and each form's primary action are 24 px targets.
`VIEWPORTS` in `frontend/scripts/fixture-routes.mjs` gained `320x640`, so the
matrix is 240 entries. The a11y gate passes: 240/240, 0 violations, 0 layout
failures.

**FE-6 — FIXED — a screen reader is told what changed.** A persistent polite
live region per section (`frontend/src/states/Announcer.tsx`, mounted inside
the workspace's `<main>`); `CommandOutcome` announces a success into it and
gives the success note `role="status"`; `RunSection` announces every run-status
transition, terminal states included; the pending state is exposed through
`aria-busy` and the `aria-label` that steps aside (FE-1). Tests:
`test_the_section_carries_one_persistent_polite_live_region`,
`test_a_command_success_is_announced_and_carries_role_status` and
`test_a_run_status_transition_is_announced`.

**FE-7 — FIXED — six irreversible acts ask once more.** A new
`ConfirmedControl` (`frontend/src/controls/ConfirmedControl.tsx`) renders an
inline second step naming the act, what it acts on and the short form of the
digest it binds; Confirm takes focus when the step opens, and Cancel or Escape
puts focus back on the opener. It is placed on sign, freeze and file
(`FilingControls`), withdraw (`WithdrawSource`), revoke (`CaseAccess`) and
cancel run (`controls.tsx`). The four section tests that drove those acts with
one press were updated to confirm. Tests:
`test_a_single_activation_sends_nothing_until_it_is_confirmed`,
`test_the_confirm_step_takes_focus_and_cancel_gives_it_back` and
`test_escape_closes_the_confirm_step_and_returns_focus_to_the_opener`.

**FE-8 / AR-19 — FIXED — an answer that settles nothing keeps the key.** The
intent is now kept until an answer settles it, which is a validated receipt or
a typed refusal and nothing else (`settles` in `controls.tsx`): a proxy's HTML
504, a 5xx with no refusal body and a 201 whose body was lost in transfer all
become `RESPONSE_INVALID` and all keep the same `Idempotency-Key`. The note
says so, in place of a bare code. Test:
`test_an_unreadable_answer_keeps_the_key_so_a_retry_cannot_write_twice`, with
`a settled answer draws a fresh key for the next press` for the other side.

**FE-9 — FIXED — the first open of the tail is a resync too.** `openTail`'s
`onReconnect` became `onOpen` and fires on every open, the first included, so
an event landing between the document read and the stream's head is not lost
until the next reconnect; the one-flight rule coalesces the read it doubles.
Tests: `test_every_open_refetches_the_visible_documents_the_first_included` and
the updated `test_a_reconnect_refetches_the_visible_documents`.

**FE-10 — FIXED — the note goes when the view catches up.** `useRunRefetch`
clears `failed` in the same render-phase adjustment that adopts a fresh
`initial`. Test: `test_a_fresh_document_clears_the_could_not_be_refreshed_note`.

**FE-11 — FIXED — no tab list where there are no tabs.** `SectionTabs` renders
the `role="tablist"` only when the document declares tabs; when it does, each
tab carries `aria-controls`, and the new `SectionPanel` renders the
`role="tabpanel"` region it names, labelled by that tab. Test:
`test_no_tablist_is_rendered_when_the_document_declares_no_tabs`.

**FE-12 — FIXED — landmarks are named for what they are about, and the rail
reads its own state.** Each Report artifact's two regions are named by their
`route_node_id`, so N artifacts give 2N distinct names; a rail entry's
`aria-label` now carries its count and its one-line state, which the strip rail
at 1024 px and below hides visually and which the old name-only label withheld
entirely; the section-local list is a `role="group"`. Tests:
`test_each_artifact_region_is_named_by_the_route_node_it_is_about` and
`test_a_rail_entry_reads_its_count_and_state_not_only_its_name`.

## Notes

- The wire (`frontend/src/wire/v1/*`) was not changed. `RegionStatus.error` in
  `frontend/src/app/transport.ts` gained an optional `retryAfterSeconds`, which
  is an app-level status, not a wire field, and is set only where the response
  carried the header.
- No dependency was added, and no suppression (`eslint-disable`, `@ts-ignore`,
  `ts-expect-error`) was introduced.
- `frontend/a11y-results/matrix.json` is the gate's own output and now records
  the 240-entry matrix.
