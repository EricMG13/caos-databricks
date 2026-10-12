"""Add to Book and Withdraw (Plan 3 Task 2; spec B3, B5, B7, B10, B11).

Two case-scoped governed writes, each one unit through `governed`: the case
lock, live standing at commit, the entry row, the receipt and one audit event
on the case's chain (`BOOK_ENTRY_ADDED`, `BOOK_ENTRY_WITHDRAWN`), committed
together or not at all. The floor is `WRITER` on the run's case and a global
role that may write; no desk-wide grant reaches a command.

**Add** checks, in this order and under the case lock:

1. The run is this case's (else `RUN_NOT_FOUND`, as everywhere) and is
   `COMPLETE` with CP-1 accepted, an issuer subject, and a grid the Model
   serves (else `RUN_NOT_COMPLETE_FOR_BOOK`; the grid check is the read's
   own, `model_grid`, so the Book never holds a figure the Model withheld).
2. The request's `snapshot_sha256` is the digest the Model's default view
   serves -- the run's accepted artifacts and every figure the entry will
   store: its pinned deck, currency, unit, book metrics and limitations
   (`entry_figures`) -- recomputed here from the store and the calculator (else
   `COMMAND_EXPECTATION_STALE`): the actor added exactly the figures they
   reviewed (invariant 5), under the calculator that computed them.
3. The classification is valid (`caos.book.classification`): a group of its
   sector, each rating on its agency's scale, an outlook only on a rating
   (else `REQUEST_INVALID`; no input is echoed).
4. The run has no entry yet. A repeat under the same key replays the
   receipt (`run_command`); under another key a live entry is
   `COMMAND_EXPECTATION_STALE`, and a withdrawn one
   `BOOK_ENTRY_ALREADY_WITHDRAWN` -- one entry per run, for good.

The metrics are computed the way the Model section computes them -- the
same Analysis read and `model_grid` with the default add-backs and the
run's pinned deck -- and stored as the read serves them (`book_metrics`),
with the limitations it serves beside them, so the entry is the Model (spec
B10). The read and the model run under the case lock, before check 2,
because the digest binds their output. Two adds
of one run wait for each other at the case lock, so the second sees the
first's entry; `book_entries.run_id` is unique behind that.

**Withdraw** names the entry by id within the path's case (another case's
is `BOOK_ENTRY_NOT_FOUND`), is bound to the entry's snapshot digest (else
`COMMAND_EXPECTATION_STALE`), and stamps the withdrawal once (else
`BOOK_ENTRY_ALREADY_WITHDRAWN`); `OTHER` needs a note. The table's trigger
refuses any other change and every delete.

The entry id is minted in the route, as a revision's is, because the receipt
names it and a replay must answer the body first committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response

from caos.api.commands._request import (
    CommandRequest,
    Key,
    governed,
    json_body,
    require_case_writer,
)
from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RunPath,
    Store,
    parse_uuid,
)
from caos.api.identity import Actor
from caos.api.reads import model as model_read
from caos.api.reads.analysis import AnalysisQuery, read_analysis_without_tables
from caos.api.wire import (
    WITHDRAWAL_NOTE_CHARS,
    AddToBook,
    BookEntryAdded,
    BookEntryWithdrawn,
    WithdrawBookEntry,
)
from caos.blobs import BlobStore
from caos.book.classification import (
    GICS_SECTORS,
    OUTLOOKS,
    ClassificationRefused,
    composite_notch,
    notch,
    valid_domicile,
)
from caos.boundary_text import BoundaryText, visible
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.audit import GovernedAction
from caos.store.book import (
    NOTED_REASON,
    Classification,
    EntrySubject,
    NewEntry,
    Withdrawal,
    accepted_artifacts,
    entry_in_case,
    entry_of_run,
    insert_entry,
    snapshot_sha256,
    withdraw_entry,
)
from caos.store.members import Standing
from caos.store.routes import resolved_route

# The add's statements beyond the Model read's own (Analysis, the live-source
# pin and the deck, which it reads the same way): the receipt lookup, the
# case lock's isolation check and lock, the chain head, live standing, the
# twin lookup, the run's status, its pinned route, its accepted artifacts,
# its entry, the insert, the receipt, the audit event and the chain head.
# The Model's is declared for the longest route a run can pin, so this is
# too. Measured in `tests/test_book_entries.py`.
ADD_FIXED_IO = 14
ADD_IO = ADD_FIXED_IO + model_read.READ_IO
# Standing, the receipt lookup, the case lock's isolation check and lock,
# the chain head, live standing, the twin lookup, the entry (locked), the
# stamp, the receipt, the audit event and the chain head.
WITHDRAW_IO = 12
IO_BUDGET = max(ADD_IO, WITHDRAW_IO)
# The add reads each accepted handoff's artifact and record, as the Model
# does; the withdrawal reads none.
BLOB_BUDGET = model_read.BLOB_BUDGET

# The commands' receipts are recorded under these names.
ADD_TO_BOOK = "ADD_TO_BOOK"
WITHDRAW_BOOK_ENTRY = "WITHDRAW_BOOK_ENTRY"
_CP1 = "CP-1"

router = APIRouter()
Writer = Annotated[Standing, Depends(require_case_writer)]


@dataclass(frozen=True, slots=True)
class Asked:
    """Who asks, under which key, on which case, at what standing: decision
    2's first four dependencies, solved in that order and carried as one."""

    actor: Actor
    key: UUID
    case_id: UUID
    standing: Standing


def _asked(actor: Caller, key: Key, standing: Writer, case_id: CasePath) -> Asked:
    return Asked(actor, key, case_id, standing)


@dataclass(frozen=True, slots=True)
class Stores:
    """The request's store connection, blob store and bundle."""

    conn: StoreConnection
    blobs: BlobStore
    bundle: Bundle


def _stores(conn: Store, blobs: Blobs, bundle: Methodology) -> Stores:
    return Stores(conn, blobs, bundle)


def _entry_path(entry_id: str) -> UUID:
    """The path's entry id, or the answer an entry nobody may act on gets."""
    return parse_uuid(entry_id, RefusalCode.BOOK_ENTRY_NOT_FOUND)


ByWriter = Annotated[Asked, Depends(_asked)]
EntryPath = Annotated[UUID, Depends(_entry_path)]


@dataclass(frozen=True, slots=True)
class _Add:
    """One add: who asked, the run, the request and the entry it mints."""

    asked: Asked
    run_id: UUID
    body: AddToBook
    stores: Stores
    entry_id: UUID


@router.post(
    "/api/v1/cases/{case_id}/runs/{run_id}/book-entry",
    status_code=201,
    dependencies=[IDENTITY_FIRST],
)
def add_to_book(
    asked: ByWriter,
    run_id: RunPath,
    body: Annotated[AddToBook, Depends(json_body(AddToBook))],
    stores: Annotated[Stores, Depends(_stores)],
) -> Response:
    """Add the run to the Book, bound to the snapshot the actor reviewed."""
    add = _Add(asked, run_id, body, stores, uuid4())
    return governed(
        stores.conn,
        scope=asked.case_id,
        key=asked.key,
        request=CommandRequest(
            ADD_TO_BOOK, asked.case_id, run_id, None, body.model_dump(mode="json")
        ),
        action=GovernedAction(
            case_id=asked.case_id,
            actor_id=asked.actor.user_id,
            action="BOOK_ENTRY_ADDED",
            requires=Standing.WRITER,
            payload={
                "entry_id": str(add.entry_id),
                "snapshot_sha256": body.snapshot_sha256,
            },
        ),
        write=lambda unit: _add(unit, add),
        model=BookEntryAdded,
    )


def _add(unit: StoreConnection, add: _Add) -> tuple[int, BookEntryAdded]:
    """The add's checks in their order, then the entry, in the unit."""
    case_id, run_id = add.asked.case_id, add.run_id
    route, artifacts = _addable(unit, case_id, run_id)
    subject, served = _modelled(unit, add, route)
    figures = model_read.entry_figures(served)
    if snapshot_sha256(artifacts, figures) != add.body.snapshot_sha256:
        raise Refusal(RefusalCode.COMMAND_EXPECTATION_STALE)
    classification = _classification(add.body)
    existing = entry_of_run(unit, run_id)
    if existing is not None and existing.withdrawn:
        raise Refusal(RefusalCode.BOOK_ENTRY_ALREADY_WITHDRAWN)
    if existing is not None:
        raise Refusal(RefusalCode.COMMAND_EXPECTATION_STALE)
    insert_entry(
        unit,
        NewEntry(
            entry_id=add.entry_id,
            case_id=case_id,
            run_id=run_id,
            subject=subject,
            classification=classification,
            snapshot_sha256=add.body.snapshot_sha256,
            figures=figures,
            added_by=add.asked.actor.user_id,
        ),
    )
    return 201, BookEntryAdded(entry_id=add.entry_id)


def _addable(
    conn: StoreConnection, case_id: UUID, run_id: UUID
) -> tuple[ResolvedRoute, tuple[tuple[str, str], ...]]:
    """The run's pinned route and accepted artifacts, if the run is this
    case's, `COMPLETE`, and has CP-1 accepted."""
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = %s AND case_id = %s",
        (run_id, case_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    if row[0] != RunStatus.COMPLETE.value:
        raise Refusal(RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    route = resolved_route(conn, run_id)
    artifacts = accepted_artifacts(conn, run_id)
    accepted = {node for node, _artifact in artifacts}
    if route is None or not any(
        node.module_id == _CP1 and node.route_node_id in accepted
        for node in route.nodes
    ):
        raise Refusal(RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    return route, artifacts


def _modelled(
    unit: StoreConnection, add: _Add, route: ResolvedRoute
) -> tuple[EntrySubject, model_read.ServedModel]:
    """The run's subject and the model its Model serves, read the Model
    section's way (`exclude_unrealised` off, the pinned deck). A run with no
    issuer subject cannot join a Book keyed by issuer (spec B1), nor one the
    Model serves no grid for (`model_grid`: CP-1 tables unreadable, a grid
    past its bounds)."""
    asked, stores = add.asked, add.stores
    body = read_analysis_without_tables(
        AnalysisQuery(
            asked.actor,
            asked.case_id,
            add.run_id,
            asked.standing,
            unit,
            stores.blobs,
            stores.bundle,
        )
    ).body
    accepted = model_read.accepted_cp1(body)
    subject = body.subject
    if accepted is None or subject is None or not subject.issuer_id.strip():
        raise Refusal(RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    model_read.require_live_sources(unit, body)
    grid = model_read.model_grid(
        unit, stores.bundle, accepted, exclude_unrealised=False
    )
    if isinstance(grid, model_read.NoGrid):
        raise Refusal(RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    return EntrySubject(
        issuer_id=subject.issuer_id,
        issuer_name=subject.issuer_name,
        reporting_period=subject.reporting_period,
        analysis_date=subject.analysis_date,
        route=f"{route.profile_id}/{route.selection_id}",
    ), grid


def _classification(body: AddToBook) -> Classification:
    """The analyst's classification, judged; `REQUEST_INVALID` otherwise."""
    groups = GICS_SECTORS.get(body.sector)
    if (
        groups is None
        or (body.industry_group is not None and body.industry_group not in groups)
        or not valid_domicile(body.domicile)
    ):
        raise Refusal(RefusalCode.REQUEST_INVALID)
    notches = [
        _rated("MOODYS", body.moodys, body.moodys_outlook),
        _rated("SP", body.sp, body.sp_outlook),
        _rated("FITCH", body.fitch, body.fitch_outlook),
    ]
    return Classification(
        sector=body.sector,
        industry_group=body.industry_group,
        domicile=body.domicile,
        moodys=body.moodys,
        moodys_outlook=body.moodys_outlook,
        sp=body.sp,
        sp_outlook=body.sp_outlook,
        fitch=body.fitch,
        fitch_outlook=body.fitch_outlook,
        composite_notch=composite_notch([n for n in notches if n is not None]),
    )


def _rated(agency: str, rating: str | None, outlook: str | None) -> int | None:
    """The rating's notch on the agency's scale, None unrated; an outlook
    must be one of `OUTLOOKS`, on a rating."""
    if outlook is not None and (rating is None or outlook not in OUTLOOKS):
        raise Refusal(RefusalCode.REQUEST_INVALID)
    if rating is None:
        return None
    try:
        return notch(agency, rating)
    except ClassificationRefused:
        raise Refusal(RefusalCode.REQUEST_INVALID) from None


@router.post(
    "/api/v1/cases/{case_id}/book-entries/{entry_id}/withdrawal",
    dependencies=[IDENTITY_FIRST],
)
def withdraw_book_entry(
    asked: ByWriter,
    entry_id: EntryPath,
    body: Annotated[WithdrawBookEntry, Depends(json_body(WithdrawBookEntry))],
    conn: Store,
) -> Response:
    """Withdraw the entry, bound to its snapshot; never delete it."""
    withdrawal = Withdrawal(entry_id, asked.actor.user_id, body.reason, _note(body))

    def write(unit: StoreConnection) -> tuple[int, BookEntryWithdrawn]:
        state = entry_in_case(unit, asked.case_id, entry_id)
        if state is None:
            raise Refusal(RefusalCode.BOOK_ENTRY_NOT_FOUND)
        if state.snapshot_sha256 != body.snapshot_sha256:
            raise Refusal(RefusalCode.COMMAND_EXPECTATION_STALE)
        if state.withdrawn or not withdraw_entry(unit, withdrawal):
            raise Refusal(RefusalCode.BOOK_ENTRY_ALREADY_WITHDRAWN)
        return 200, BookEntryWithdrawn(entry_id=entry_id)

    return governed(
        conn,
        scope=asked.case_id,
        key=asked.key,
        request=CommandRequest(
            WITHDRAW_BOOK_ENTRY,
            asked.case_id,
            None,
            str(entry_id),
            body.model_dump(mode="json"),
        ),
        action=GovernedAction(
            case_id=asked.case_id,
            actor_id=asked.actor.user_id,
            action="BOOK_ENTRY_WITHDRAWN",
            requires=Standing.WRITER,
            payload={
                "entry_id": str(entry_id),
                "snapshot_sha256": body.snapshot_sha256,
                "reason": body.reason,
            },
        ),
        write=write,
        model=BookEntryWithdrawn,
    )


def _note(body: WithdrawBookEntry) -> str | None:
    """The note past the boundary; one with nothing a reader can see in it
    (white space, zero-width characters: `visible`) is none, and `OTHER`
    without one is `REQUEST_INVALID` (fix round 1, L3)."""
    note = None if body.note is None or not visible(body.note).strip() else body.note
    if note is None and body.reason == NOTED_REASON:
        raise Refusal(RefusalCode.REQUEST_INVALID)
    return (
        None
        if note is None
        else BoundaryText.of(note, limit=WITHDRAWAL_NOTE_CHARS).value
    )
