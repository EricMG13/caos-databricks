"""Book entries in the store (Plan 3 Task 2, `0051_book_entries.sql`).

A book entry is a completed run a case writer added to the Book. These are
the statements the Add to Book and Withdraw commands send inside their
governed unit, under the case lock (`caos.api.commands.book`); none of them
commits. The table's own trigger is the second guard: an entry is inserted
live, never deleted, and changed only by its one withdrawal.

The snapshot digest is what an adder reviews and a withdrawal is bound to
(invariant 5). It binds the inputs and the outputs both (fix rounds 1 and
2): the canonical JSON (`caos.digest`) of the run's accepted artifacts as
sorted `"<route_node_id>:<artifact_sha256>"` lines and of every figure the
entry stores (`EntryFigures`: the deck the run pinned, the currency and
unit, the metrics and the limitations). The Model read serves it over the
handoffs and the figures it shows (`caos.api.reads.model.entry_snapshot`)
and the add recomputes it from the store under the case lock, so a figure
that moved -- another view, another calculator -- is a stale digest; and an
entry's stored digest is the digest of its own row.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args
from uuid import UUID

from psycopg.types.json import Jsonb

from caos.digest import canonical_digest
from caos.store import StoreConnection

# The reasons `0051_book_entries.sql`'s CHECK takes, in its order (spec B7);
# a plain alias, so the wire's schema states them inline.
WithdrawalReason = Literal[
    "ADDED_IN_ERROR", "DATA_ERROR", "SUPERSEDED_SOURCES", "OTHER"
]
WITHDRAWAL_REASONS: tuple[str, ...] = get_args(WithdrawalReason)
# The one reason a withdrawal must say more about, in its note.
NOTED_REASON = "OTHER"
# `{basis: {line_id: decimal text or None}}`, as the entry's `metrics` holds it.
type Metrics = Mapping[str, Mapping[str, str | None]]


@dataclass(frozen=True, slots=True)
class EntryFigures:
    """Every figure an entry stores, as the Model's default view serves it:
    the deck the run pinned (whether or not a projection read it), the
    currency and unit, the metrics and the limitations."""

    rate_deck_id: str | None
    currency: str | None
    unit: str | None
    metrics: Metrics
    limitations: tuple[str, ...]


def snapshot_sha256(artifacts: Iterable[tuple[str, str]], figures: EntryFigures) -> str:
    """The digest of `(route_node_id, artifact_sha256)` pairs and the
    figures: canonical JSON, sorted keys, figures as their decimal text.
    Pure."""
    return canonical_digest(
        {
            "artifacts": sorted(f"{node}:{artifact}" for node, artifact in artifacts),
            "rate_deck_id": figures.rate_deck_id,
            "currency": figures.currency,
            "unit": figures.unit,
            "metrics": {basis: dict(lines) for basis, lines in figures.metrics.items()},
            "limitations": list(figures.limitations),
        }
    )


def accepted_artifacts(
    conn: StoreConnection, run_id: UUID
) -> tuple[tuple[str, str], ...]:
    """The run's accepted artifacts as `(route_node_id, artifact_sha256)`.
    One round trip."""
    rows = conn.execute(
        "SELECT route_node_id, artifact_sha256 FROM artifacts WHERE run_id = %s",
        (run_id,),
    ).fetchall()
    return tuple((str(node), str(artifact)) for node, artifact in rows)


@dataclass(frozen=True, slots=True)
class Classification:
    """The analyst-stated classification, already judged valid (spec B5)."""

    sector: str
    industry_group: str | None
    domicile: str
    moodys: str | None
    moodys_outlook: str | None
    sp: str | None
    sp_outlook: str | None
    fitch: str | None
    fitch_outlook: str | None
    composite_notch: int | None


@dataclass(frozen=True, slots=True)
class EntrySubject:
    """The run's pinned subject and route, as the entry records them."""

    issuer_id: str
    issuer_name: str
    reporting_period: str
    analysis_date: str  # ISO date
    route: str  # "<profile_id>/<selection_id>"


@dataclass(frozen=True, slots=True)
class NewEntry:
    """One entry to insert: who, which run, what it says and its metrics."""

    entry_id: UUID
    case_id: UUID
    run_id: UUID
    subject: EntrySubject
    classification: Classification
    snapshot_sha256: str
    figures: EntryFigures  # what `snapshot_sha256` binds, stored as bound
    added_by: UUID


def insert_entry(conn: StoreConnection, entry: NewEntry) -> None:
    """Insert `entry`, live, in the caller's unit. `issuer_key` is the
    store's `upper(trim(issuer_id))`, the spelling its CHECK holds."""
    subject, stated, figures = entry.subject, entry.classification, entry.figures
    deck = figures.rate_deck_id
    conn.execute(
        "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key,"
        " issuer_id, issuer_name, reporting_period, analysis_date, route, sector,"
        " industry_group, domicile, moodys, moodys_outlook, sp, sp_outlook, fitch,"
        " fitch_outlook, composite_notch, snapshot_sha256, rate_deck_id, currency,"
        " unit, metrics, limitations, added_by) VALUES (%s, %s, %s,"
        " upper(trim(%s)), %s, %s, %s, %s::date, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            entry.entry_id,
            entry.case_id,
            entry.run_id,
            subject.issuer_id,
            subject.issuer_id,
            subject.issuer_name,
            subject.reporting_period,
            subject.analysis_date,
            subject.route,
            stated.sector,
            stated.industry_group,
            stated.domicile,
            stated.moodys,
            stated.moodys_outlook,
            stated.sp,
            stated.sp_outlook,
            stated.fitch,
            stated.fitch_outlook,
            stated.composite_notch,
            entry.snapshot_sha256,
            None if deck is None else UUID(deck),
            figures.currency,
            figures.unit,
            Jsonb({basis: dict(lines) for basis, lines in figures.metrics.items()}),
            list(figures.limitations),
            entry.added_by,
        ),
    )


@dataclass(frozen=True, slots=True)
class EntryState:
    """What a command checks of an existing entry: its digest, and whether
    it is withdrawn."""

    entry_id: UUID
    snapshot_sha256: str
    withdrawn: bool


def _state(row: tuple[object, ...] | None) -> EntryState | None:
    if row is None:
        return None
    entry_id, digest, withdrawn = row
    return EntryState(UUID(str(entry_id)), str(digest), bool(withdrawn))


def entry_of_run(conn: StoreConnection, run_id: UUID) -> EntryState | None:
    """The run's one entry, live or withdrawn, or None. One round trip."""
    return _state(
        conn.execute(
            "SELECT entry_id, snapshot_sha256, withdrawn_at IS NOT NULL"
            " FROM book_entries WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    )


def entry_in_case(
    conn: StoreConnection, case_id: UUID, entry_id: UUID
) -> EntryState | None:
    """The case's entry `entry_id`, locked for its withdrawal, or None for an
    entry of another case or none at all. One round trip."""
    return _state(
        conn.execute(
            "SELECT entry_id, snapshot_sha256, withdrawn_at IS NOT NULL"
            " FROM book_entries WHERE entry_id = %s AND case_id = %s FOR UPDATE",
            (entry_id, case_id),
        ).fetchone()
    )


@dataclass(frozen=True, slots=True)
class Withdrawal:
    """One withdrawal: the entry, who withdrew it, why, and the note."""

    entry_id: UUID
    withdrawn_by: UUID
    reason: WithdrawalReason
    note: str | None


def withdraw_entry(conn: StoreConnection, withdrawal: Withdrawal) -> bool:
    """Stamp the entry's withdrawal, in the caller's unit; False when it was
    already withdrawn (nothing is written). One round trip."""
    cursor = conn.execute(
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = %s, withdrawal_note = %s"
        " WHERE entry_id = %s AND withdrawn_at IS NULL",
        (
            withdrawal.withdrawn_by,
            withdrawal.reason,
            withdrawal.note,
            withdrawal.entry_id,
        ),
    )
    return cursor.rowcount == 1
