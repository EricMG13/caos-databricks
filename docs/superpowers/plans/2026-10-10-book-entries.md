# Book entries: implementation plan (Plan 3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a case writer adds a completed run to the desk-wide Book with an analyst-stated classification. Entries can be withdrawn with a reason, are flagged when cited sources are withdrawn, and an entry's run becomes readable desk-wide, read-only.

**Architecture:**
- `book_entries` is append-mostly. Its only update is the one-time withdrawal stamp, guarded by a trigger.
- Add and Withdraw are governed, digest-bound case commands on the existing audit chain.
- The Book read reads entries, not Analyses: one query plus one source-liveness query.
- The desk-wide grant is one store predicate, `entry_run(conn, case_id, run_id) -> bool`, consulted only by the read choke points.

**Tech stack:** as in Plan 2.

**Spec:** `docs/superpowers/specs/2026-10-10-book-model-redesign-design.md` (B1–B15).

## Global constraints

- Plan 1 and Plan 2 global constraints apply.
- **Writes never accept the grant:** `commands/_request.py:100-116` and `store/audit.py` `_require_standing` stay member-only.
- **The audit chain is per case** (`audit_events`). Add and Withdraw write to it under new action names. Add the names to `caos/api/events.py:27` `STREAM_NAMES` (checked by `tests/test_event_names.py:59`).
- **Desk-wide reads are not audit-chain events** (the chain is per case and reads write nothing today). Each granted read logs `book_entry_read case=<id> run=<id> user=<id>` with no document text (CLAUDE.md conventions).

---

### Task 1: classification vocabularies and composite rating (pure)

**Agent:** `mx-precise`.

**Files:** create `caos/book/__init__.py` and `caos/book/classification.py`; test `tests/test_book_classification.py`.

**Interfaces:**

```python
GICS_SECTORS: Mapping[str, tuple[str, ...]]   # 11 sectors -> their industry groups (25 total), GICS 2023 names
AGENCIES = ("MOODYS", "SP", "FITCH")
OUTLOOKS = ("STABLE", "POSITIVE", "NEGATIVE", "DEVELOPING", "WATCH_POS", "WATCH_NEG", "WATCH_DEV")
MOODYS_SCALE: tuple[str, ...]   # Aaa Aa1 Aa2 Aa3 A1 A2 A3 Baa1 Baa2 Baa3 Ba1 Ba2 Ba3 B1 B2 B3 Caa1 Caa2 Caa3 Ca C   (21)
SP_FITCH_SCALE: tuple[str, ...] # AAA AA+ AA AA- A+ A A- BBB+ BBB BBB- BB+ BB BB- B+ B B- CCC+ CCC CCC- CC C D (22)
def notch(agency: str, rating: str) -> int          # 1..22; Moody's C maps to 21, Ca to 20, and S&P/Fitch D is 22; unknown -> ValueError
def composite_notch(notches: Sequence[int]) -> int | None   # middle of three, lower (worse = higher number) of two, the single one, None for none
def bucket(n: int | None) -> Literal["IG", "BB", "B", "CCC_AND_BELOW", "NR"]   # IG <= 10 (BBB-), BB 11-13, B 14-16, else CCC_AND_BELOW
def composite_label(n: int | None) -> str           # the S&P/Fitch spelling of the notch, or "NR"
def valid_domicile(code: str) -> bool               # ^[A-Z]{2}$ — ponytail: format only, no country table; upgrade if a bad code ever lands
```

- [ ] **Step 1:** Write the failing tests:
  - `test_middle_of_three_is_the_median_notch`
  - `test_lower_of_two_is_the_worse_rating`
  - `test_buckets_split_at_bbb_minus_bb_minus_and_b_minus`
  - `test_every_scale_entry_has_a_notch`
  - `test_industry_groups_belong_to_their_sector`
  - **Hypothesis:** `test_composite_is_one_of_the_inputs_for_any_ratings`.
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run gates.
- [ ] **Step 5:** Commit: `Book: GICS, rating scales and composite rating`.

---

### Task 2: the `book_entries` store, and the Add and Withdraw commands

**Agent:** `mx-invariants` (digest binding, the one-time withdrawal stamp, and concurrent adds for one issuer).

**Files:**
- Create `caos/store/0051_book_entries.sql`, `caos/store/book.py` and `caos/api/commands/book.py`.
- Modify `caos/store/__init__.py`, `caos/api/wire.py`, `caos/api/app.py`, `caos/api/events.py` (`STREAM_NAMES`: `BOOK_ENTRY_ADDED`, `BOOK_ENTRY_WITHDRAWN`) and `caos/refusals.py` (`RUN_NOT_COMPLETE_FOR_BOOK`, `BOOK_ENTRY_NOT_FOUND`, `BOOK_ENTRY_ALREADY_WITHDRAWN`), plus the `CLEARS` and `_STATUS` entries.
- Tests: `tests/test_book_entries.py` and `tests/test_postgres_races.py` (add one race).

**Schema** (`0051`):
- `book_entries(entry_id uuid pk, case_id uuid fk, run_id uuid fk unique, issuer_key text not null, issuer_id text, issuer_name text, reporting_period text, analysis_date date, route text, sector text not null, industry_group text, domicile text not null, moodys text, moodys_outlook text, sp text, sp_outlook text, fitch text, fitch_outlook text, composite_notch integer, snapshot_sha256 text not null, rate_deck_id uuid, currency text, unit text, metrics jsonb not null, added_by uuid not null, added_at timestamptz not null default now(), withdrawn_at timestamptz, withdrawn_by uuid, withdrawal_reason text, withdrawal_note text)`.
- A CHECK constrains `withdrawal_reason` to `ADDED_IN_ERROR | DATA_ERROR | SUPERSEDED_SOURCES | OTHER` and requires a non-empty note for `OTHER`.
- A trigger allows only an UPDATE that sets the four withdrawal columns from null; DELETE is never allowed.
- Index `(issuer_key, analysis_date desc, added_at desc) where withdrawn_at is null`.
- `issuer_key = upper(trim(issuer_id))`.

**Snapshot digest:** `run_snapshot_sha256(conn, run_id) -> str` is the sha256 of the sorted `"<route_node_id>:<artifact_sha256>"` lines of the run's accepted artifacts, newline-joined. Expose it as `ModelBody.snapshot_sha256` (a wire addition in Plan 2's `ModelBody`; add the field here).

**Add** (`POST /api/v1/cases/{case_id}/runs/{run_id}/book-entry`, `WRITER`+):
- Body: `AddToBook{snapshot_sha256, sector, industry_group|None, domicile, moodys|None, moodys_outlook|None, sp|None, sp_outlook|None, fitch|None, fitch_outlook|None}`.
- **Checks, in order:**
  1. The run belongs to the case and is `COMPLETE` with CP-1 accepted (else `RUN_NOT_COMPLETE_FOR_BOOK`).
  2. `snapshot_sha256` equals the recomputed digest (else `COMMAND_EXPECTATION_STALE`).
  3. The classification is valid per Task 1: an industry group must belong to its sector; each rating must be on its agency's scale; an outlook requires a rating.
  4. The run has no live entry already. A second add is idempotent by key; a different key gets a refusal of `COMMAND_EXPECTATION_STALE`.
- **Metrics:** computed in the command from `credit_model()` on the run (default add-backs, the run's pinned deck). For bases LTM, PF-LTM, `BASE:<first three projected FYs>` and `DOWNSIDE:<…>` it stores `{basis: {line_id: decimal-string|null}}` for every `metric:` line plus `revenue`, `adjusted_ebitda`, `total_debt`, `net_debt`, `liquidity`, `fcf`, `ffo`, `cash_closing`, `lease_adjusted_net_debt` and `adjusted_ebitda_margin`.
- **Write:** through `governed`/`run_command` with action `BOOK_ENTRY_ADDED` on the case chain (payload `entry_id` and `snapshot_sha256`). The receipt is `BookEntryAdded{entry_id}`.

**Withdraw** (`POST /api/v1/cases/{case_id}/book-entries/{entry_id}/withdrawal`, `WRITER`+):
- Body: `WithdrawBookEntry{snapshot_sha256, reason, note|None}`, digest-bound to the entry's `snapshot_sha256`.
- An entry already withdrawn is refused with `BOOK_ENTRY_ALREADY_WITHDRAWN`. Action `BOOK_ENTRY_WITHDRAWN`.

- [ ] **Step 1:** Write the failing tests:
  - `test_a_writer_adds_a_complete_run_with_cp1_and_the_entry_stores_its_metrics`
  - `test_a_reader_cannot_add`
  - `test_a_stale_snapshot_digest_is_refused`
  - `test_a_running_or_failed_run_cannot_be_added`
  - `test_an_industry_group_outside_its_sector_is_refused`
  - `test_an_entry_cannot_be_deleted_or_edited_except_withdrawn_once`
  - `test_withdrawal_needs_a_note_for_other`
  - `test_add_and_withdraw_write_the_case_audit_chain`
  - **Race** in `tests/test_postgres_races.py`: `test_two_concurrent_adds_of_one_run_leave_one_entry`.
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement. Regenerate the schema and mirror `commands.ts`; update the command count pin.
- [ ] **Step 4:** Expect PASS. Run the full gates, including the races file.
- [ ] **Step 5:** Commit: `Book entries: add and withdraw, digest-bound, on the case audit chain`.

---

### Task 3: Book read v2 and the source-withdrawn flag

**Agent:** `mx-precise`.

**Files:** rewrite `caos/api/reads/book.py`; modify `caos/api/wire.py` (`BookBody` v2 replaces the case-row shape), `frontend/src/wire/v1/documents.ts` and `schema.json`, `tests/io_measurements.json`, and `tests/test_book_section.py` (rewrite).

**Wire:**

```python
class BookEntryView(BaseModel): entry_id: UUID; case_id: UUID; run_id: UUID; issuer_key: str; issuer_id: str; issuer_name: str
    reporting_period: str; analysis_date: str; route: str; filed: bool; sources_withdrawn: bool
    sector: str; industry_group: str | None; domicile: str
    moodys: str | None; moodys_outlook: str | None; sp: str | None; sp_outlook: str | None; fitch: str | None; fitch_outlook: str | None
    composite: str; composite_bucket: Literal["IG","BB","B","CCC_AND_BELOW","NR"]; composite_notch: int | None
    currency: str | None; unit: str | None; metrics: dict[str, dict[str, DecimalText | None]]
    added_by_name: str | None; added_at: AwareDatetime; withdrawn_at: AwareDatetime | None; withdrawal_reason: str | None; withdrawal_note: str | None
class BookIssuerView(BaseModel): issuer_key: str; displayed: BookEntryView; history: list[BookEntryView]   # history newest first, withdrawn included, displayed excluded
class BookBody(BaseModel): issuers: list[BookIssuerView]; metric_catalogue: list[BookMetricView]   # {line_id, label, unit} for the column chooser, in Model order
```

Bound: issuers ≤ 1000, with `LIST_TRUNCATED` beyond.

**Read** (`GET /api/v1/book`, any signed-in user, spec B2):
- One query over all entries. Rank each issuer's live entries by `(analysis_date desc, added_at desc)`, and use `DISTINCT ON` or a window function for the displayed entry.
- **`filed`:** `EXISTS` a `deliverable_publications.filed_at IS NOT NULL` for the entry's run, via `deliverable_revisions` (`reads/reports.py:352-368` shows the join).
- **`sources_withdrawn`:** true when any source pinned to the run's source set is no longer live. Reuse `pinned_live_sources`' predicate as a set query (one round trip for all entries).
- **`IO_BUDGET`:** a small constant (target ≤ 4), measured and recorded.

- [ ] **Step 1:** Write the failing tests:
  - `test_every_viewer_sees_every_issuer`
  - `test_an_issuers_row_is_its_newest_live_entry_by_analysis_date`
  - `test_a_withdrawn_entry_moves_to_history_and_the_previous_one_displays`
  - `test_the_filed_badge_follows_the_deliverable_publication`
  - `test_a_withdrawn_cited_source_flags_the_entry`
  - `test_the_book_reads_within_its_declared_io_budget`
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run the gates.
- [ ] **Step 5:** Commit: `Book read v2: desk-wide issuers from book entries`.

---

### Task 4: the desk-wide read grant

**Agent:** `mx-invariants`, then an `mx-adversary` review (authorisation change).

**Files:** create `caos/store/book.py`'s `entry_run(conn, case_id, run_id) -> bool` (a live entry exists). Modify the read choke points:
1. `caos/api/deps.py:243-261`: `visible_case` stays member-only. Add `visible_run(...)`, which returns the standing **or** a `BOOK` grant when the run query parameter names a live entry run.
2. `caos/api/reads/analysis.py` and `caos/api/reads/model.py`: accept the grant only when `run` is given and is an entry run. Serve `Chrome.served_role.standing = None` and `actions = []` for a granted read.
3. `caos/api/reads/evidence.py:67-76`: the inline join also accepts an entry run, but only for sources cited by that run's accepted artifacts. Implement "cited" as: the source's `document_sha256` appears in any accepted artifact's citation list of the run. If no stored citation index exists, the run's pinned source set is the bound; record that as a ruling and a `Dn` at PR time.

These stay member-only: Run (`reads/run.py:244-254`), Report and Committee (`reads/reports.py:166`), Deliverable (`reads/deliverable.py:228`), the event stream (`stream.py:319`) and every command.

- [ ] **Step 1:** Write the failing tests:
  - `test_a_non_member_reads_an_entry_runs_analysis_and_model`
  - `test_a_non_member_cannot_read_another_run_of_the_same_case`
  - `test_a_non_member_cannot_read_without_a_run_parameter`
  - `test_a_withdrawn_entry_no_longer_grants`
  - `test_a_non_member_reads_a_cited_source_page_of_the_entry_run_only`
  - `test_a_granted_read_serves_no_actions`
  - `test_run_report_committee_deliverable_and_events_stay_member_only`
  - `test_commands_never_accept_the_grant`
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run the full gates.
- [ ] **Step 5:** Commit: `Book: desk-wide read-only grant for an entry's run`.

---

### Task 5: the Add to Book dialog and the Withdraw control (frontend)

**Agent:** `mx-feature`.

**Files:**
- Create `frontend/src/sections/model/AddToBook.tsx` and `frontend/src/sections/book/WithdrawEntry.tsx`.
- Modify `frontend/src/app/commands.ts` (`addToBook`, `withdrawBookEntry`), `frontend/src/wire/v1/documents.ts` (`ActionName` gains `ADD_TO_BOOK` and `WITHDRAW_BOOK_ENTRY`, mirrored from the backend `ActionName`), and the backend `chrome.actions` for the Model read (offer `ADD_TO_BOOK` to `WRITER`+ when the run is `COMPLETE` with CP-1 and has no live entry).
- Tests: `frontend/tests/unit/add-to-book.test.tsx`.

**Behaviour:**
- The Model header shows **Add to Book** when the action is offered. It opens a Base UI Dialog (`evidence/Overlay.tsx` pattern) holding:
  - a sector `<select>` (required) and an industry-group `<select>` (filtered to the sector, optional);
  - a domicile `<input>` (two letters, upper-cased);
  - for each agency, a rating `<select>` (its own scale, plus "Not rated") and an outlook `<select>`, enabled only when rated.
- The fields are **pre-filled** from the issuer's previous entry. Read it from `GET /api/v1/book` (`issuers[issuer_key].displayed`).
- Validation is inline, per the visual guidance. Confirm uses `ConfirmedControl`'s two-step sentence with the snapshot digest. The outcome is shown inline, then the section refetches.
- **Withdraw** (on the Book row's history disclosure and on the displayed entry, for `WRITER`+ members of that case): a reason `<select>`, plus a note `<textarea>` required for `OTHER`, via `ConfirmedControl`.

- [ ] **Step 1:** Write the failing tests:
  - `pre-fills from the issuer's previous entry`
  - `industry groups follow the chosen sector`
  - `an outlook needs a rating`
  - `confirms with the snapshot digest and posts the classification`
  - `withdraw requires a note for Other`
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run the full frontend gates.
- [ ] **Step 5:** Commit: `Model: Add to Book dialog; Book: withdraw entry`.
