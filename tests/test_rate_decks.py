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
from typing import Any, get_args
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import recorded_statements
from fastapi.testclient import TestClient
from httpx2 import Response

from caos.api import app as app_module
from caos.api.app import app, store_connection
from caos.api.commands import rate_decks as rate_decks_command
from caos.api.commands._request import IDEMPOTENCY_HEADER, REPLAYED_HEADER
from caos.api.commands.rate_decks import require_admin, save_rate_deck
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED, GlobalRole
from caos.api.reads import rate_decks as rate_decks_read
from caos.api.reads.rate_decks import read_latest_rate_deck
from caos.api.wire import (
    RATE_DECK_ROWS_MAX,
    RateDeckRateView,
    RateDeckSaved,
    RateDeckView,
    SaveRateDeck,
)
from caos.boundary_text import BoundaryText
from caos.calculators.credit_model.projection import RateDeck, RateDeckYear
from caos.digest import canonical_digest
from caos.refusals import Refusal, RefusalCode
from caos.store import (
    MIGRATIONS,
    STORE_SCHEMA,
    StoreConnection,
    apply_schema,
    connect,
    rate_decks,
)
from caos.store.rate_decks import (
    DECK_ROWS_MAX,
    REFERENCE_RATES,
    SAVE_LOCK,
    PinnedDeck,
    SavedDeck,
    check_rates,
    deck_for_run,
    latest_deck,
    latest_saved_deck,
    pin_latest_deck,
    rates_digest,
    save_deck,
)
from caos.store.runs import StartedRun, create_case, start_run, started_run

__all__ = ["read_latest_rate_deck", "require_admin", "save_rate_deck"]

PATH = "/api/v1/rate-decks"
LATEST = "/api/v1/rate-decks/latest"
AS_OF = "2026-10-01"
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
BODY = {"as_of": AS_OF, "rates": RATES}
NOT_FOUND = {
    "code": "ENDPOINT_NOT_FOUND",
    "clears": "Use a declared path and method.",
}


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


def _ordered(years: tuple[RateDeckYear, ...]) -> tuple[RateDeckYear, ...]:
    return tuple(sorted(years, key=lambda y: (y.reference_rate, y.fiscal_year_offset)))


@pytest.fixture
def client(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, StoreConnection]]:
    """The real app on the case's connection, served without an edge token,
    so a role above READER is the switched-on role header."""
    conn, _case_id = case
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    app.dependency_overrides[store_connection] = lambda: conn
    try:
        with TestClient(app) as opened:
            yield opened, conn
    finally:
        app.dependency_overrides.clear()


def _save(
    http: TestClient,
    body: object,
    user: UUID,
    role: str = "ADMIN",
    key: UUID | None = None,
) -> Response:
    headers = {
        "x-caos-user": str(user),
        ROLE_HEADER: role,
        IDEMPOTENCY_HEADER: str(key or uuid4()),
    }
    answer: Response = http.post(PATH, headers=headers, json=body)
    return answer


def _latest(http: TestClient, role: str = "READER") -> Response:
    answer: Response = http.get(
        LATEST, headers={"x-caos-user": str(uuid4()), ROLE_HEADER: role}
    )
    return answer


def _decks(conn: StoreConnection) -> tuple[int, int, int]:
    """Rows in the three deck tables, read and released."""
    counts = tuple(
        int(row[0])
        for table in ("rate_decks", "rate_deck_rates", "run_rate_decks")
        for row in [conn.execute(f"SELECT count(*) FROM {table}").fetchone() or (0,)]
    )
    conn.rollback()
    return counts[0], counts[1], counts[2]


def test_an_admin_saves_a_deck_and_it_reads_back_as_latest(
    client: tuple[TestClient, StoreConnection],
    capsys: pytest.CaptureFixture[str],
) -> None:
    http, conn = client
    admin, key = uuid4(), uuid4()

    with recorded_statements(conn) as saving:
        answer = _save(http, BODY, admin, key=key)

    assert answer.status_code == 201, answer.text
    assert answer.headers.get(REPLAYED_HEADER) is None
    deck_id = RateDeckSaved.model_validate(answer.json()).deck_id
    assert len(saving) == rate_decks_command.SAVE_IO
    assert rate_decks_command.SAVE_IO == rate_decks_command.IO_BUDGET
    # The one log line names the deck and its size, never a rate.
    logged = capsys.readouterr().err
    assert f"rate_deck_saved deck_id={deck_id} rows=3" in logged
    assert "0.0380" not in logged and "SOFR" not in logged

    with recorded_statements(conn) as reading:
        shown = _latest(http)
    assert shown.status_code == 200, shown.text
    assert len(reading) == rate_decks_read.IO_BUDGET == 1
    view = RateDeckView.model_validate(shown.json())
    assert (view.deck_id, view.as_of) == (deck_id, AS_OF)
    assert view.rates == [
        RateDeckRateView.model_validate(row)
        for row in sorted(RATES, key=lambda r: (r["reference_rate"], r["year_offset"]))
    ]

    # The store reads it back as Plan 1's `RateDeck`: Decimal, never float.
    deck = latest_deck(conn)
    assert deck == RateDeck(str(deck_id), AS_OF, _ordered(_years()))
    assert all(type(year.base) is Decimal for year in deck.years)
    saved = latest_saved_deck(conn)
    assert isinstance(saved, SavedDeck)
    assert saved.deck == deck and saved.saved_at == view.saved_at
    conn.rollback()

    # The same key and body replays the receipt and writes nothing; a
    # different body under it is the idempotency conflict.
    with recorded_statements(conn) as replaying:
        again = _save(http, BODY, admin, key=key)
    assert again.status_code == 201
    assert again.headers.get(REPLAYED_HEADER) == "true"
    assert again.json() == answer.json()
    assert len(replaying) == rate_decks_command.REPLAY_IO
    changed = {**BODY, "as_of": "2026-10-02"}
    reused = _save(http, changed, admin, key=key)
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert _decks(conn) == (1, 3, 0)
    assert "rate_deck_saved" not in capsys.readouterr().err


def test_with_no_deck_the_latest_is_null(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, conn = client
    shown = _latest(http)
    assert shown.status_code == 200
    assert shown.json() is None
    assert latest_deck(conn) is None
    assert latest_saved_deck(conn) is None


@pytest.mark.parametrize("role", ["ANALYST", "READER"])
def test_a_non_admin_save_is_refused_as_not_found(
    client: tuple[TestClient, StoreConnection], role: str
) -> None:
    http, conn = client
    answer = _save(http, BODY, uuid4(), role=role)
    assert (answer.status_code, answer.json()) == (404, NOT_FOUND)
    # Refused before the key, the body and the store: no key, no body.
    bare = http.post(PATH, headers={"x-caos-user": str(uuid4()), ROLE_HEADER: role})
    assert (bare.status_code, bare.json()) == (404, NOT_FOUND)
    assert _decks(conn) == (0, 0, 0)
    # Anonymous is 401 before anything else.
    assert http.post(PATH, json=BODY).status_code == 401
    assert http.get(LATEST).status_code == 401


def test_require_admin_compares_by_rank() -> None:
    from caos.api.identity import Actor

    admin = Actor(uuid4(), GlobalRole.ADMIN)
    assert require_admin(admin) is admin
    for role in (GlobalRole.ANALYST, GlobalRole.READER):
        with pytest.raises(Refusal, match=r"^ENDPOINT_NOT_FOUND$"):
            require_admin(Actor(uuid4(), role))


def test_a_saved_deck_cannot_be_updated_or_deleted(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    run_id = start_run(conn, case_id)
    conn.commit()
    attempts = [
        "UPDATE rate_decks SET as_of = '2026-01-01'",
        "DELETE FROM rate_decks",
        "TRUNCATE rate_decks CASCADE",
        "UPDATE rate_deck_rates SET base_rate = 0.5",
        "DELETE FROM rate_deck_rates",
        "TRUNCATE rate_deck_rates",
        "UPDATE run_rate_decks SET deck_id = deck_id",
        "DELETE FROM run_rate_decks",
        "TRUNCATE run_rate_decks",
    ]
    for statement in attempts:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(statement)
        conn.rollback()
    pinned = deck_for_run(conn, run_id)
    assert pinned is not None and pinned.deck_id == str(deck_id)
    assert _decks(conn) == (1, 3, 1)


def test_a_run_pins_the_latest_deck_at_creation_and_keeps_it_after_a_newer_save(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    first = save_deck(conn, uuid4(), date(2026, 9, 1), _years())
    conn.commit()
    run_id = start_run(conn, case_id)
    conn.commit()
    newer_rates = [{**RATES[0], "base_rate": "0.0400"}]
    second = save_deck(conn, uuid4(), date(2026, 10, 1), _years(newer_rates))
    conn.commit()

    kept = deck_for_run(conn, run_id)
    assert kept == RateDeck(str(first), "2026-09-01", _ordered(_years()))
    latest = latest_deck(conn)
    assert latest is not None and latest.deck_id == str(second)
    later = start_run(conn, case_id)
    conn.commit()
    pinned = deck_for_run(conn, later)
    assert pinned == RateDeck(str(second), "2026-10-01", _years(newer_rates))
    assert _decks(conn) == (2, 4, 2)


def test_the_pin_is_written_in_the_run_creating_transaction(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A run rolled back takes its pin with it: the pin is never a second
    unit that could survive or miss the run."""
    conn, case_id = case
    save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    run_id = start_run(conn, case_id)
    assert deck_for_run(conn, run_id) is not None
    conn.rollback()
    # The run is gone, and its pin with it.
    with pytest.raises(Refusal, match=r"^RUN_NOT_FOUND$"):
        deck_for_run(conn, run_id)
    conn.rollback()
    assert _decks(conn) == (1, 3, 0)


def test_a_run_created_with_no_deck_pins_none(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    assert deck_for_run(conn, run_id) is None
    assert _decks(conn) == (0, 0, 0)
    # `pin_latest_deck` with no deck inserts nothing and names nothing.
    assert pin_latest_deck(conn, run_id) is None
    assert _decks(conn) == (0, 0, 0)


def test_a_run_started_on_a_store_before_rate_decks_still_starts(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The populated-upgrade suites start runs on a migration prefix; a store
    without the deck tables starts an ordinary run, pins nothing, and says so
    in one line (a documented fail-open is a logged one)."""
    import caos.store as store

    names = [name for name, _sql in MIGRATIONS]
    before = names.index("0050_rate_decks")
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", MIGRATIONS[:before])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("before decks"))
        run_id = start_run(conn, case_id)
        conn.commit()
        logged = capsys.readouterr().err
        assert f"rate_deck_pin_skipped run={run_id} reason=no_table\n" in logged
        apply_schema(conn)
        conn.commit()
        assert deck_for_run(conn, run_id) is None


def test_duplicate_rate_rows_are_refused(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, conn = client
    rows = [RATES[0], {**RATES[0], "base_rate": "0.0400"}]
    answer = _save(http, {**BODY, "rates": rows}, uuid4())
    assert (answer.status_code, answer.json()["code"]) == (400, "REQUEST_INVALID")
    with pytest.raises(Refusal, match=r"^REQUEST_INVALID$"):
        save_deck(conn, uuid4(), date(2026, 10, 1), _years(rows))
    conn.rollback()
    assert _decks(conn) == (0, 0, 0)


@pytest.mark.parametrize(
    "rates",
    [
        [],
        [{**RATES[0], "base_rate": "1"}],
        [{**RATES[0], "downside_rate": "-1"}],
        [{**RATES[0], "base_rate": "1.5"}],
        [{**RATES[0], "year_offset": 0}],
        [{**RATES[0], "year_offset": 6}],
    ],
    ids=["empty", "base-one", "downside-minus-one", "base-over", "offset-0", "off-6"],
)
def test_a_deck_outside_its_bounds_is_refused_before_any_write(
    client: tuple[TestClient, StoreConnection], rates: list[dict[str, Any]]
) -> None:
    http, conn = client
    answer = _save(http, {**BODY, "rates": rates}, uuid4())
    assert (answer.status_code, answer.json()["code"]) == (400, "REQUEST_INVALID")
    assert _decks(conn) == (0, 0, 0)


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "rates": [RATES[0]] * (DECK_ROWS_MAX + 1)},
        {**BODY, "rates": [{**RATES[0], "reference_rate": "LIBOR"}]},
        {**BODY, "rates": [{**RATES[0], "base_rate": 0.038}]},
        {**BODY, "rates": [{**RATES[0], "base_rate": "3.8e-2"}]},
        {**BODY, "as_of": "2026-02-30"},
        {**BODY, "as_of": "01/10/2026"},
        {**BODY, "saved_by": str(uuid4())},
    ],
    ids=["21-rows", "libor", "float", "exponent", "no-such-day", "not-iso", "actor"],
)
def test_a_body_the_wire_does_not_declare_is_refused(
    client: tuple[TestClient, StoreConnection], body: dict[str, Any]
) -> None:
    http, conn = client
    answer = _save(http, body, uuid4())
    assert (answer.status_code, answer.json()["code"]) == (400, "REQUEST_INVALID")
    assert _decks(conn) == (0, 0, 0)
    with pytest.raises(ValueError, match="validation error"):
        SaveRateDeck.model_validate(body)


def test_check_rates_states_every_bound() -> None:
    check_rates(_years())
    full = tuple(
        RateDeckYear(rate, offset, Decimal("0.01"), Decimal("0.02"))
        for rate in ("SOFR", "TERM_SOFR", "EURIBOR", "SONIA")
        for offset in range(1, 6)
    )
    assert len(full) == DECK_ROWS_MAX == RATE_DECK_ROWS_MAX
    # The wire's closed set is the store's.
    declared = RateDeckRateView.model_fields["reference_rate"].annotation
    assert set(get_args(declared)) == REFERENCE_RATES
    check_rates(full)
    near = RateDeckYear("SONIA", 5, Decimal("0.9999"), Decimal("-0.9999"))
    check_rates((near,))
    for bad in (
        (),
        (*full, RateDeckYear("SOFR", 1, Decimal(0), Decimal(0))),
        (RateDeckYear("LIBOR", 1, Decimal(0), Decimal(0)),),
        (RateDeckYear("SOFR", 0, Decimal(0), Decimal(0)),),
        (RateDeckYear("SOFR", 6, Decimal(0), Decimal(0)),),
        (RateDeckYear("SOFR", 1, Decimal(1), Decimal(0)),),
        (RateDeckYear("SOFR", 1, Decimal(0), Decimal(-1)),),
        (RateDeckYear("SOFR", 1, Decimal("NaN"), Decimal(0)),),
        (RateDeckYear("SOFR", 1, Decimal(0), Decimal("-Infinity")),),
    ):
        with pytest.raises(Refusal) as refused:
            check_rates(bad)
        assert refused.value.code is RefusalCode.REQUEST_INVALID


def test_latest_is_the_last_deck_saved_whatever_its_clock_says(
    case: tuple[StoreConnection, UUID],
) -> None:
    """ "Latest" is the identity the save lock hands out, not the clock: a deck
    stamped a day ahead (a clock stepped back since) is still not the latest
    once another deck is saved after it. `saved_at` is for display."""
    conn, _case_id = case
    ahead = uuid4()
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    conn.execute(
        "INSERT INTO rate_decks (deck_id, as_of, saved_by, saved_at, rates_sha256)"
        " VALUES (%s, '2026-09-01', %s, now() + interval '1 day', %s)",
        (ahead, uuid4(), rates_digest(_years(RATES[:1]))),
    )
    conn.execute(
        "INSERT INTO rate_deck_rates VALUES (%s, 'SOFR', 1, 0.0380, 0.0450)", (ahead,)
    )
    conn.commit()
    saved = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    latest = latest_deck(conn)
    assert latest is not None and latest.deck_id == str(saved)


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


def test_a_saved_deck_cannot_gain_a_rate(case: tuple[StoreConnection, UUID]) -> None:
    """A deck's rates are written in the deck's own transaction or never: a
    later insert, an upsert or a merge into a saved deck is refused, so the
    deck a run pinned reads the same for ever."""
    conn, case_id = case
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    run_id = start_run(conn, case_id)
    conn.commit()
    attempts = [
        "INSERT INTO rate_deck_rates VALUES (%(d)s, 'SONIA', 3, 0.09, 0.09)",
        "INSERT INTO rate_deck_rates VALUES (%(d)s, 'SOFR', 1, 0.5, 0.5)"
        " ON CONFLICT (deck_id, reference_rate, year_offset)"
        " DO UPDATE SET base_rate = 0.5",
        "MERGE INTO rate_deck_rates r USING (SELECT %(d)s::uuid AS d) s"
        " ON r.deck_id = s.d WHEN MATCHED THEN UPDATE SET base_rate = 0.6",
    ]
    for statement in attempts:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(statement, {"d": deck_id})
        conn.rollback()
    pinned = deck_for_run(conn, run_id)
    assert pinned is not None and pinned.years == _ordered(_years())


def test_a_run_is_pinned_only_in_the_transaction_that_creates_it(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A run created with no deck stays deck-less: a pin inserted after its
    creation -- even in a transaction that has since touched the run row --
    is refused, as is re-pinning a run that has one."""
    conn, case_id = case
    bare = start_run(conn, case_id)
    conn.commit()
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    pinned = start_run(conn, case_id)
    conn.commit()
    back_pin = "INSERT INTO run_rate_decks VALUES (%s, %s)"
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(back_pin, (bare, deck_id))
    conn.rollback()
    conn.execute("UPDATE runs SET status = status WHERE run_id = %s", (bare,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(back_pin, (bare, deck_id))
    conn.rollback()
    # Rewriting the run's own timestamps does not make a later transaction its
    # creator: the creating transaction is a write-once id, not a clock.
    conn.execute("UPDATE runs SET created_at = now() WHERE run_id = %s", (bare,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(back_pin, (bare, deck_id))
    conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "UPDATE runs SET created_xact = pg_current_xact_id() WHERE run_id = %s",
            (bare,),
        )
    conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            back_pin + " ON CONFLICT (run_id) DO UPDATE SET deck_id = EXCLUDED.deck_id",
            (pinned, deck_id),
        )
    conn.rollback()
    assert deck_for_run(conn, bare) is None
    assert _decks(conn) == (1, 3, 1)


def test_a_deck_whose_rates_no_longer_match_its_digest_is_refused_on_read(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """Every read checks the rates against the digest written at save: rates
    changed behind the triggers (an owner disabling them) fail closed with a
    typed refusal, never a silently different deck."""
    http, conn = client
    case_id = conn.execute("SELECT case_id FROM cases").fetchone()
    assert case_id is not None
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    run_id = start_run(conn, case_id[0])
    conn.commit()
    conn.execute("ALTER TABLE rate_deck_rates DISABLE TRIGGER rate_deck_rate_immutable")
    conn.execute(
        "UPDATE rate_deck_rates SET base_rate = 0.0390 WHERE deck_id = %s"
        " AND reference_rate = 'SOFR' AND year_offset = 1",
        (deck_id,),
    )
    conn.execute("ALTER TABLE rate_deck_rates ENABLE TRIGGER rate_deck_rate_immutable")
    conn.commit()
    with pytest.raises(Refusal, match=r"^ARTIFACT_RECORD_MISMATCH$"):
        latest_deck(conn)
    conn.rollback()
    with pytest.raises(Refusal, match=r"^ARTIFACT_RECORD_MISMATCH$"):
        deck_for_run(conn, run_id)
    conn.rollback()
    shown = _latest(http)
    assert (shown.status_code, shown.json()["code"]) == (
        500,
        "ARTIFACT_RECORD_MISMATCH",
    )


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


def test_a_deck_with_a_negative_zero_reads_back_intact(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case
    rows = (RateDeckYear("SONIA", 2, Decimal("-0.000"), Decimal("0.05000")),)
    save_deck(conn, uuid4(), date(2026, 10, 1), rows)
    conn.commit()
    latest = latest_deck(conn)
    assert latest is not None
    assert latest.years == (
        RateDeckYear("SONIA", 2, Decimal("0.000"), Decimal("0.05000")),
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


def test_an_unknown_run_has_no_deck_to_read(case: tuple[StoreConnection, UUID]) -> None:
    conn, _case_id = case
    with pytest.raises(Refusal, match=r"^RUN_NOT_FOUND$"):
        deck_for_run(conn, uuid4())


def test_started_run_names_the_deck_it_pinned(
    case: tuple[StoreConnection, UUID],
) -> None:
    """What the run-creating command binds into its audit payload: the deck
    and the digest of its rates, or nothing when there was no deck."""
    conn, case_id = case
    bare = started_run(conn, case_id)
    assert bare.deck is None and isinstance(bare, StartedRun)
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    run = started_run(conn, case_id)
    assert run.deck == PinnedDeck(deck_id, rates_digest(_years()))
    stored = conn.execute(
        "SELECT rates_sha256 FROM rate_decks WHERE deck_id = %s", (deck_id,)
    ).fetchone()
    assert stored == (rates_digest(_years()),)
    conn.rollback()


def test_a_run_created_inside_a_savepoint_pins_the_latest_deck(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The creating transaction is the top-level one, so a run started (or a
    deck saved) inside a savepoint is pinned and read as any other."""
    conn, case_id = case
    conn.execute("SELECT 1")
    with conn.transaction():
        deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    conn.execute("SELECT 1")
    with conn.transaction():
        run_id = start_run(conn, case_id)
    conn.commit()
    pinned = deck_for_run(conn, run_id)
    assert pinned is not None and pinned.deck_id == str(deck_id)


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


def test_a_temp_runs_table_does_not_let_a_run_be_pinned_late(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The pin guard reads the real `runs`, whatever a session shadows in its
    own temporary schema (searched first for an unqualified name)."""
    conn, case_id = case
    bare = start_run(conn, case_id)
    conn.commit()
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    with _dml_role(conn) as role:
        with pytest.raises(psycopg.errors.RaiseException):
            _as(
                conn,
                role,
                [
                    (
                        "CREATE TEMP TABLE runs (run_id uuid, created_xact xid8)"
                        " ON COMMIT DROP",
                        None,
                    ),
                    (
                        "INSERT INTO pg_temp.runs VALUES (%s, pg_current_xact_id())",
                        (bare,),
                    ),
                    ("INSERT INTO run_rate_decks VALUES (%s, %s)", (bare, deck_id)),
                ],
            )
    assert deck_for_run(conn, bare) is None


def test_a_temp_rate_decks_table_does_not_let_a_deck_gain_a_rate(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    with _dml_role(conn) as role:
        with pytest.raises(psycopg.errors.RaiseException):
            _as(
                conn,
                role,
                [
                    (
                        "CREATE TEMP TABLE rate_decks (deck_id uuid, saved_xact xid8)"
                        " ON COMMIT DROP",
                        None,
                    ),
                    (
                        "INSERT INTO pg_temp.rate_decks"
                        " VALUES (%s, pg_current_xact_id())",
                        (deck_id,),
                    ),
                    (
                        f"INSERT INTO {STORE_SCHEMA}.rate_deck_rates"
                        " VALUES (%s, 'SONIA', 3, 0.09, 0.09)",
                        (deck_id,),
                    ),
                ],
            )
    latest = latest_deck(conn)
    assert latest is not None and latest.years == _ordered(_years())


def test_a_temp_pg_locks_and_sequence_do_not_let_a_deck_jump_the_queue(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The deck guard reads the catalog's own `pg_locks` and the real
    identity sequence: a temporary view faking the save lock and a temporary
    table drawing a huge identity are both ignored."""
    conn, _case_id = case
    save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    rogue = uuid4()
    with _dml_role(conn) as role:
        with pytest.raises(psycopg.errors.RaiseException):
            _as(
                conn,
                role,
                [
                    (
                        "CREATE TEMP VIEW pg_locks AS SELECT 'advisory'::text AS"
                        " locktype, pg_backend_pid() AS pid, true AS granted,"
                        f" {SAVE_LOCK}::oid AS classid, 0::oid AS objid,"
                        " 2::int2 AS objsubid, 'ExclusiveLock'::text AS mode",
                        None,
                    ),
                    (
                        "CREATE TEMP TABLE rate_decks (deck_seq bigint GENERATED"
                        " ALWAYS AS IDENTITY (START 9000000000000000001),"
                        " deck_id uuid, saved_xact xid8)",
                        None,
                    ),
                    (
                        "INSERT INTO pg_temp.rate_decks (deck_id, saved_xact)"
                        " VALUES (%s, pg_current_xact_id())",
                        (rogue,),
                    ),
                    (
                        f"INSERT INTO {STORE_SCHEMA}.rate_decks"
                        " (deck_id, deck_seq, as_of, saved_by, saved_at, rates_sha256)"
                        " OVERRIDING SYSTEM VALUE"
                        " VALUES (%s, 9000000000000000001, '2020-01-01', %s,"
                        " now(), %s)",
                        (rogue, uuid4(), rates_digest(_years())),
                    ),
                ],
            )
    latest = latest_deck(conn)
    assert latest is not None and latest.deck_id != str(rogue)


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


def test_a_rewound_deck_sequence_cannot_put_a_save_behind_the_latest(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Even the owner moving the identity sequence back cannot make a new
    save draw an identity at or below the latest: the save is refused rather
    than written where it would never be the latest."""
    conn, _case_id = case
    save_deck(conn, uuid4(), date(2026, 9, 1), _years())
    conn.commit()
    save_deck(conn, uuid4(), date(2026, 9, 2), _years())
    conn.rollback()  # a gap: the rolled-back save drew an identity
    latest = save_deck(conn, uuid4(), date(2026, 9, 3), _years())
    conn.commit()
    conn.execute("SELECT setval(pg_get_serial_sequence('rate_decks', 'deck_seq'), 1)")
    conn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.rollback()
    found = latest_deck(conn)
    assert found is not None and found.deck_id == str(latest)


def test_a_run_cannot_be_deleted(case: tuple[StoreConnection, UUID]) -> None:
    """A run deleted and re-inserted would be created again, by a later
    transaction that could then pin it: no run is deleted."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM runs WHERE run_id = %s", (run_id,))
    conn.rollback()
    assert deck_for_run(conn, run_id) is None


@pytest.mark.parametrize(
    "move",
    [
        "UPDATE runs SET run_id = %s WHERE run_id = %s",
        "INSERT INTO runs (run_id, case_id, status, budget_ceiling)"
        " VALUES (%s, %s, 'RUNNING', 1)"
        " ON CONFLICT (run_id) DO UPDATE SET run_id = %s",
    ],
)
def test_a_run_s_id_never_changes(
    case: tuple[StoreConnection, UUID], move: str
) -> None:
    """A run moved aside under a new id would free its old id for a run
    created again, by a later transaction that could then pin it: the old
    id names the same run for ever, by UPDATE or by an upsert's UPDATE."""
    conn, case_id = case
    bare = start_run(conn, case_id)
    conn.commit()
    deck_id = save_deck(conn, uuid4(), date(2026, 10, 1), _years())
    conn.commit()
    conn.execute("UPDATE runs SET run_id = run_id WHERE run_id = %s", (bare,))
    conn.rollback()  # writing the same id is no change, and is accepted
    with _dml_role(conn) as role:
        conn.execute(f"GRANT UPDATE ON runs TO {role}")
        conn.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="identity"):
            _as(
                conn,
                role,
                [
                    (
                        move,
                        (uuid4(), bare)
                        if move.startswith("UPDATE")
                        else (bare, case_id, uuid4()),
                    ),
                    (
                        "INSERT INTO runs (run_id, case_id, status, budget_ceiling)"
                        " VALUES (%s, %s, 'RUNNING', 1)",
                        (bare, case_id),
                    ),
                    ("INSERT INTO run_rate_decks VALUES (%s, %s)", (bare, deck_id)),
                ],
            )
    assert deck_for_run(conn, bare) is None
    assert conn.execute(
        "SELECT count(*) FROM runs WHERE run_id = %s", (bare,)
    ).fetchone() == (1,)
    conn.rollback()


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


def test_a_temp_pg_settings_does_not_move_the_callers_lock_bound(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The pin reads the bound in force from the catalog's `pg_settings`, so
    a temporary view of that name cannot make it put back a different one."""
    conn, case_id = case
    conn.execute("SET LOCAL lock_timeout = '250ms'")
    conn.execute(
        "CREATE TEMP VIEW pg_settings AS"
        " SELECT 'lock_timeout'::text AS name, '1'::text AS setting"
    )
    start_run(conn, case_id)
    assert conn.execute("SELECT current_setting('lock_timeout')").fetchone() == (
        "250ms",
    )
    conn.rollback()
