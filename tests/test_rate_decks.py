"""The rate deck: admin-saved, immutable, pinned per run at creation.

A deck is the desk's dated statement of reference rates (`CONTEXT.md`). Three
claims are proven here on a real store:

- only a global ADMIN saves one, and anyone else is answered as an undeclared
  endpoint is;
- a saved deck, its rates and a run's pin are never updated or deleted;
- a run pins the latest deck in the transaction that creates it, and a newer
  save never moves an existing pin.

The two-connection races (saves ordered by commit, twins under one key) are
in `tests/test_postgres_races.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from caos.calculators.credit_model.projection import RateDeckYear
from caos.digest import canonical_digest
from caos.refusals import Refusal
from caos.store import (
    STORE_SCHEMA,
    StoreConnection,
    rate_decks,
)
from caos.store.rate_decks import (
    SAVE_LOCK,
    check_rates,
    rates_digest,
    save_deck,
)
from caos.store.runs import start_run

RATES: list[dict[str, Any]] = [
    {
        "reference_rate": "SOFR",
        "year_offset": 1,
        "base_rate": "0.0380",
        "downside_rate": "0.0450",
    },
    {
        "reference_rate": "SOFR",
        "year_offset": 2,
        "base_rate": "0.0350",
        "downside_rate": "0.0425",
    },
    {
        "reference_rate": "EURIBOR",
        "year_offset": 1,
        "base_rate": "0.0215",
        "downside_rate": "-0.0010",
    },
]


def _years(rates: list[dict[str, Any]] = RATES) -> tuple[RateDeckYear, ...]:
    """The body's rows as Plan 1's projection reads them."""
    return tuple(
        RateDeckYear(
            reference_rate=row["reference_rate"],
            fiscal_year_offset=row["year_offset"],
            base=Decimal(row["base_rate"]),
            downside=Decimal(row["downside_rate"]),
        )
        for row in rates
    )


def _decks(conn: StoreConnection) -> tuple[int, int, int]:
    """Rows in the three deck tables, read and released."""
    counts = tuple(
        int(row[0])
        for table in ("rate_decks", "rate_deck_rates", "run_rate_decks")
        for row in [conn.execute(f"SELECT count(*) FROM {table}").fetchone() or (0,)]
    )
    conn.rollback()
    return counts[0], counts[1], counts[2]


def test_a_deck_is_written_only_under_the_save_lock_with_a_finite_stamp(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The order "latest" reads is assigned under the save lock, so a deck
    inserted without it is refused; and no deck is stamped at infinity."""
    conn, _case_id = case
    digest = rates_digest(_years(RATES[:1]))
    insert = (
        "INSERT INTO rate_decks (deck_id, as_of, saved_by, saved_at, rates_sha256)"
        " VALUES (%s, '2026-09-01', %s, {}, %s)"
    )
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(insert.format("now()"), (uuid4(), uuid4(), digest))
    conn.rollback()
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(insert.format("'infinity'"), (uuid4(), uuid4(), digest))
    conn.rollback()
    # Under the lock, an identity the save did not draw is refused: a deck
    # given a huge `deck_seq` would otherwise stay latest for ever.
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "INSERT INTO rate_decks"
            " (deck_id, deck_seq, as_of, saved_by, saved_at, rates_sha256)"
            " OVERRIDING SYSTEM VALUE"
            " VALUES (%s, 9000000000000000000, '2020-01-01', %s, now(), %s)",
            (uuid4(), uuid4(), digest),
        )
    conn.rollback()
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    save_deck(conn, uuid4(), date(2026, 9, 1), _years(RATES[:1]))
    with pytest.raises(psycopg.errors.RaiseException):
        # Even beside a value this session drew a moment ago.
        conn.execute(
            "INSERT INTO rate_decks"
            " (deck_id, deck_seq, as_of, saved_by, saved_at, rates_sha256)"
            " OVERRIDING SYSTEM VALUE"
            " VALUES (%s, 9000000000000000000, '2020-01-01', %s, now(), %s)",
            (uuid4(), uuid4(), digest),
        )
    conn.rollback()
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    with pytest.raises(psycopg.errors.RaiseException):
        # Nor a deck claiming another transaction saved it.
        conn.execute(
            "INSERT INTO rate_decks"
            " (deck_id, as_of, saved_by, rates_sha256, saved_xact)"
            " VALUES (%s, '2020-01-01', %s, %s, '1'::xid8)",
            (uuid4(), uuid4(), digest),
        )
    conn.rollback()
    # The shared form a run's pin takes is not the save lock.
    conn.execute("SELECT pg_advisory_xact_lock_shared(%s::integer, 0)", (SAVE_LOCK,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(insert.format("now()"), (uuid4(), uuid4(), digest))
    conn.rollback()
    assert _decks(conn) == (0, 0, 0)


def test_the_rates_digest_is_of_the_values_not_their_spelling() -> None:
    """Postgres keeps a rate's scale but not a negative zero's sign: the
    digest reads each figure as its value, so a saved deck reads back equal
    and a changed rate does not."""
    rows = _years()
    assert rates_digest(rows) == rates_digest(tuple(reversed(rows)))
    padded = tuple(
        RateDeckYear(y.reference_rate, y.fiscal_year_offset, y.base * 1, y.downside)
        for y in rows
    )
    assert rates_digest(padded) == rates_digest(rows)
    zero = RateDeckYear("SOFR", 1, Decimal("-0.000"), Decimal("0.10"))
    plain = RateDeckYear("SOFR", 1, Decimal("0"), Decimal("0.1"))
    assert rates_digest((zero,)) == rates_digest((plain,))
    moved = RateDeckYear("SOFR", 1, Decimal("0.0000001"), Decimal("0.1"))
    assert rates_digest((moved,)) != rates_digest((plain,))
    assert len(rates_digest(rows)) == 64
    # The canonical form, pinned: a digest written under one spelling of the
    # form would refuse every deck saved under another.
    assert rates_digest((zero, moved)) == canonical_digest(
        [["SOFR", 1, "0", "0.1"], ["SOFR", 1, "0.0000001", "0.1"]]
    )


def test_a_rate_longer_than_the_wire_carries_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The store holds no rate the wire's 64-character decimal text could not
    carry back: `check_rates` refuses it typed, and the column refuses it."""
    conn, _case_id = case
    long = Decimal("0." + "0" * 70 + "1")
    with pytest.raises(Refusal, match=r"^REQUEST_INVALID$"):
        check_rates((RateDeckYear("SOFR", 1, long, Decimal(0)),))
    widest = Decimal("-0." + "1" * 61)
    assert len(f"{widest:f}") == 64
    check_rates((RateDeckYear("SOFR", 1, widest, Decimal(0)),))
    deck_id = uuid4()
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    conn.execute(
        "INSERT INTO rate_decks (deck_id, as_of, saved_by, rates_sha256)"
        " VALUES (%s, '2026-10-01', %s, %s)",
        (deck_id, uuid4(), "a" * 64),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO rate_deck_rates VALUES (%s, 'SOFR', 1, %s, 0)",
            (deck_id, long),
        )
    conn.rollback()


def test_a_run_inserted_naming_another_transaction_cannot_be_pinned(
    case: tuple[StoreConnection, UUID],
) -> None:
    """`created_xact` is the inserting transaction's or the insert is refused,
    so no run is written claiming a creator it did not have."""
    conn, case_id = case
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "INSERT INTO runs (run_id, case_id, status, budget_ceiling, created_xact)"
            " VALUES (%s, %s, 'RUNNING', 1, '1'::xid8)",
            (uuid4(), case_id),
        )
    conn.rollback()


def test_the_migration_names_the_save_lock_the_store_takes() -> None:
    """`0050_rate_decks.sql` checks the save lock by its number; it must be the
    number `save_deck` takes, or every save is refused."""
    sql = (Path(rate_decks.__file__).parent / "0050_rate_decks.sql").read_text(
        encoding="utf-8"
    )
    assert f"classid = {SAVE_LOCK} AND" in sql
    assert sql.count(str(SAVE_LOCK)) == 2  # the header note and the check


@contextmanager
def _dml_role(conn: StoreConnection) -> Iterator[str]:
    """A role holding only SELECT and INSERT on the deck tables and `runs`
    (and PUBLIC's default TEMP): not the owner, so it can neither disable a
    trigger nor move a sequence -- only shadow a name in its own pg_temp."""
    role = f"caos_dml_{uuid4().hex[:12]}"
    conn.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER")
    conn.execute(f"GRANT USAGE ON SCHEMA {STORE_SCHEMA} TO {role}")
    conn.execute(
        "GRANT SELECT, INSERT ON runs, run_rate_decks, rate_decks, rate_deck_rates"
        f" TO {role}"
    )
    conn.commit()
    try:
        yield role
    finally:
        conn.rollback()
        conn.execute("RESET ROLE")
        conn.execute(f"DROP OWNED BY {role}")
        conn.execute(f"DROP ROLE {role}")
        conn.commit()


def _as(
    conn: StoreConnection,
    role: str,
    statements: list[tuple[str, tuple[object, ...] | None]],
) -> None:
    """Run `statements` as `role` in one transaction; the caller expects the
    last to be refused."""
    conn.execute(f"SET ROLE {role}")
    for query, params in statements:
        conn.execute(query, params)


def test_a_temp_shadow_does_not_let_a_run_claim_another_creator(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    with _dml_role(conn) as role:
        with pytest.raises(psycopg.errors.RaiseException):
            _as(
                conn,
                role,
                [
                    ("CREATE TEMP TABLE runs (run_id uuid) ON COMMIT DROP", None),
                    (
                        f"INSERT INTO {STORE_SCHEMA}.runs"
                        " (run_id, case_id, status, budget_ceiling, created_xact)"
                        " VALUES (%s, %s, 'RUNNING', 1, '1'::xid8)",
                        (uuid4(), case_id),
                    ),
                ],
            )


def test_every_deck_guard_pins_its_search_path(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Each guard resolves names with the catalog first and pg_temp last,
    whatever the calling session's path."""
    conn, _case_id = case
    rows = conn.execute(
        "SELECT p.proname, p.proconfig FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = current_schema() AND p.proname = ANY(%s)",
        (
            [
                "refuse_rate_deck_mutation",
                "refuse_run_creator_change",
                "refuse_run_delete",
                "refuse_rate_deck_unlocked",
                "refuse_rate_after_save",
                "refuse_pin_after_creation",
            ],
        ),
    ).fetchall()
    conn.rollback()
    assert len(rows) == 6
    for name, config in rows:
        assert config == ["search_path=pg_catalog, pg_temp"], name


@pytest.mark.parametrize(
    "statement", ["TRUNCATE runs CASCADE", "TRUNCATE ONLY runs CASCADE"]
)
def test_a_run_cannot_be_truncated(
    case: tuple[StoreConnection, UUID], statement: str
) -> None:
    """TRUNCATE skips the row-level no-delete guard, so `runs` refuses it
    itself, before any cascaded child's own refusal is reached."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="a run is never deleted"):
        conn.execute(statement)
    conn.rollback()
    assert conn.execute(
        "SELECT count(*) FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone() == (1,)
    conn.rollback()
