"""Book, `/api/v1/book`: the desk-wide Book, read from its book entries.

Desk-wide (spec B2): any signed-in user reads every issuer, whatever their
standing, because an entry is what a case writer chose to publish to the
desk with Add to Book (`caos.api.commands.book`). One row per issuer key
(spec B1): the issuer's newest live entry by `(analysis_date, added_at,
entry_seq)`, the order `book_entries_live_by_issuer` keeps (spec B4); every
other entry of the issuer, withdrawn ones included, is its history, newest
first (spec B7, B15).

The read computes no figure: an entry serves the subject, the
classification, the metrics and the limitations the command stored, the
composite from the stored notch (`caos.book.classification`), and two facts
the store answers now -- whether the run's deliverable is filed (spec B4)
and whether a source pinned to the run is no longer live (spec B8,
`pinned_live_sources`' predicate). No document-derived text is carried.

Each entry also names what this viewer may do to it (`actions`): Withdraw,
for a WRITER-or-above member of the entry's case whose global role may
write, on a live entry. The member's standing is a scalar subquery of the
same statement, so the read stays one round trip. Advisory; the command
rechecks standing at commit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter
from psycopg import sql

from caos.api.deps import IDENTITY_FIRST, Caller, Store
from caos.api.identity import Actor, GlobalRole
from caos.api.reads.model import FISCAL_YEAR, book_catalogue
from caos.api.wire import (
    BOOK_HISTORY_MAX,
    BOOK_ISSUERS_MAX,
    ActionName,
    BookBody,
    BookDocument,
    BookEntryView,
    BookIssuerView,
    Chrome,
    SectionNote,
    ServedRole,
)
from caos.book.classification import bucket, composite_label
from caos.store import StoreConnection
from caos.store.members import Standing, satisfies

# The store's `now()` and the one query over every entry: constant in the
# issuers and entries served. No blob is read.
IO_BUDGET = 2

router = APIRouter()

_COLUMNS = (
    "entry_id",
    "case_id",
    "run_id",
    "issuer_key",
    "issuer_id",
    "issuer_name",
    "reporting_period",
    "analysis_date",
    "route",
    "sector",
    "industry_group",
    "domicile",
    "moodys",
    "moodys_outlook",
    "sp",
    "sp_outlook",
    "fitch",
    "fitch_outlook",
    "composite_notch",
    "currency",
    "unit",
    "metrics",
    "limitations",
    "snapshot_sha256",
    "added_at",
    "withdrawn_at",
    "withdrawal_reason",
    "withdrawal_note",
)
_SELECTED = sql.SQL(", ").join(
    sql.SQL("r.analysis_date::text")
    if column == "analysis_date"
    else sql.SQL("r.") + sql.Identifier(column)
    for column in _COLUMNS
)
# Each issuer's entries ranked twice: `newest` by B4's order alone, `shown`
# with the live ones first, so `shown = 1` on a live entry is the displayed
# one. The issuers served are those with a live entry, by key, one past the
# bound; of each, the displayed entry and the newest entries up to one past
# the history bound. `filed` and `withdrawn` are set queries the planner runs
# per row served, inside this one round trip: the publication join is
# `reads/reports.py`'s `_revisions`, and the live-member test is
# `caos.store.source_sets.pinned_live_sources`' own predicate, negated.
_QUERY = (
    sql.SQL(
        "WITH ranked AS (SELECT b.*,"
        " row_number() OVER (PARTITION BY issuer_key ORDER BY analysis_date DESC,"
        " added_at DESC, entry_seq DESC) AS newest,"
        " row_number() OVER (PARTITION BY issuer_key ORDER BY withdrawn_at IS NOT NULL,"
        " analysis_date DESC, added_at DESC, entry_seq DESC) AS shown,"
        " count(*) OVER (PARTITION BY issuer_key) AS entries FROM book_entries b),"
        " issuers AS (SELECT issuer_key FROM ranked"
        " WHERE shown = 1 AND withdrawn_at IS NULL ORDER BY issuer_key"
        " LIMIT %(issuers)s)"
        " SELECT "
    )
    + _SELECTED
    + sql.SQL(
        ", r.shown = 1 AS displayed, r.entries,"
        " EXISTS (SELECT 1 FROM deliverable_revisions v JOIN deliverable_publications p"
        " ON p.case_id = v.case_id AND p.revision_id = v.revision_key"
        " WHERE v.case_id = r.case_id AND v.run_id = r.run_id"
        " AND p.filed_at IS NOT NULL) AS filed,"
        " EXISTS (SELECT 1 FROM run_inputs i JOIN source_set_members m"
        " ON (m.case_id, m.version) = (i.case_id, i.source_version)"
        " WHERE i.run_id = r.run_id AND NOT EXISTS (SELECT 1 FROM live_sources s"
        " JOIN source_extractions e ON e.source_id = s.source_id"
        " WHERE (s.case_id, s.source_id) = (m.case_id, m.source_id)"
        " AND (s.document_sha256, e.extractor_identity, e.output_sha256,"
        " e.extraction_sha256) = (m.document_sha256, m.extractor_identity,"
        " m.output_sha256, m.extraction_sha256))) AS sources_withdrawn"
        ", (SELECT m.standing FROM case_members m WHERE m.case_id = r.case_id"
        " AND m.user_id = %(actor)s AND m.revoked_at IS NULL) AS standing"
        " FROM ranked r JOIN issuers USING (issuer_key)"
        " WHERE r.shown = 1 OR r.newest <= %(history)s"
        " ORDER BY r.issuer_key, r.newest"
    )
)


@router.get("/api/v1/book", response_model=BookDocument, dependencies=[IDENTITY_FIRST])
def read_book(actor: Caller, conn: Store) -> BookDocument:
    """`actor` is declared before `conn`: an anonymous request is refused
    before a connection opens, as Directory's read is."""
    [observed_at] = conn.execute("SELECT now()").fetchall()[0]
    issuers, truncated = _issuers(conn, actor)
    return BookDocument(
        chrome=Chrome(
            subject=None,
            served_role=ServedRole(global_role=actor.role, standing=None),
            actions=[],
        ),
        body=BookBody(issuers=issuers, metric_catalogue=list(book_catalogue())),
        observed_at=observed_at,
        observed_empty=not issuers,
        status="partial" if truncated else "complete",
        notes=[SectionNote.LIST_TRUNCATED] if truncated else [],
    )


def _issuers(conn: StoreConnection, actor: Actor) -> tuple[list[BookIssuerView], bool]:
    """Every issuer with a live entry, to the bound, and whether anything
    was cut: an issuer past `BOOK_ISSUERS_MAX`, or history past
    `BOOK_HISTORY_MAX`. One round trip."""
    rows = conn.execute(
        _QUERY,
        {
            "issuers": BOOK_ISSUERS_MAX + 1,
            "history": BOOK_HISTORY_MAX + 1,
            "actor": actor.user_id,
        },
    ).fetchall()
    grouped: dict[str, list[Sequence[Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[_COLUMNS.index("issuer_key")]), []).append(row)
    truncated = len(grouped) > BOOK_ISSUERS_MAX
    issuers = []
    for key, entries in list(grouped.items())[:BOOK_ISSUERS_MAX]:
        issuer, cut = _issuer(key, entries, actor.role)
        issuers.append(issuer)
        truncated = truncated or cut
    return issuers, truncated


def _issuer(
    key: str, rows: list[Sequence[Any]], role: GlobalRole
) -> tuple[BookIssuerView, bool]:
    """The issuer's row from its entries, newest first, and whether its
    history was cut."""
    displayed_at = len(_COLUMNS)
    [displayed] = [row for row in rows if row[displayed_at]]
    history = [_entry(row, role) for row in rows if not row[displayed_at]]
    total = int(rows[0][displayed_at + 1])
    return (
        BookIssuerView(
            issuer_key=key,
            displayed=_entry(displayed, role),
            history=history[:BOOK_HISTORY_MAX],
        ),
        total - 1 > BOOK_HISTORY_MAX,
    )


def _entry(row: Sequence[Any], role: GlobalRole) -> BookEntryView:
    stored = dict(zip(_COLUMNS, row, strict=False))
    filed, withdrawn, standing = row[len(_COLUMNS) + 2 :]
    may_withdraw = (
        stored["withdrawn_at"] is None
        and role is not GlobalRole.READER
        and satisfies(None if standing is None else Standing(standing), Standing.WRITER)
    )
    metrics, years = _bases(stored.pop("metrics"))
    notch = stored["composite_notch"]
    return BookEntryView(
        **stored,
        filed=filed,
        sources_withdrawn=withdrawn,
        actions=[ActionName.WITHDRAW_BOOK_ENTRY] if may_withdraw else [],
        composite=composite_label(notch),
        composite_bucket=bucket(notch),
        metrics=metrics,
        fiscal_years=years,
    )


def _bases(
    stored: Mapping[str, Mapping[str, str | None]],
) -> tuple[dict[str, dict[str, str | None]], dict[str, str]]:
    """The stored metrics with every leaf a figure, and each projected
    basis' fiscal year apart (`book_metrics` stores it among the lines)."""
    metrics: dict[str, dict[str, str | None]] = {}
    years: dict[str, str] = {}
    for basis, lines in stored.items():
        metrics[basis] = {k: v for k, v in lines.items() if k != FISCAL_YEAR}
        year = lines.get(FISCAL_YEAR)
        if year is not None:
            years[basis] = year
    return metrics, years
