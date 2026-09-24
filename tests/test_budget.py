"""Phase 4: no provider call without a reservation, and every ceiling fails closed.

Invariant 8 (CLAUDE.md): budgets fail closed. Every ceiling refuses the next
operation *before* overspend, and no provider call happens without a reservation
behind it.

`docs/DECISIONS.md` §12 adopts CAOS-Final §21 with this phase: the attempt row is
the call identity, and a retry is a new reservation rather than a reuse of the
old one. That is the price of a provider with no idempotency key, and it is
charged deliberately -- the alternative is a second call believed to be the first.

The reservation commits on its own, before the call. Sharing the acceptance
transaction would mean a crash after the provider completed rolled back the
record of money that was actually spent.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from threading import Event
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from psycopg.pq import TransactionStatus
from test_case_ordering import _blocked, _wait_for_blocking
from test_run_events import RECORD, approved_nodes

from caos.boundary_text import BoundaryText
from caos.graph.route import resolve_route
from caos.pricing import ModelPrice
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, budget, connect
from caos.store.budget import (
    CEILING,
    Reservation,
    remaining,
    reserve,
    reserved_for,
)
from caos.store.cases import lock_case
from caos.store.events import lock_run
from caos.store.runs import (
    Accepted,
    accept_attempt,
    block_run,
    create_case,
    fail_run,
    start_attempt,
    start_run,
)

# The producer an accepted artifact carries.
MODEL = "a-model/for-the-test"
GENERATION = "gen-for-the-test"

# What these fixtures reserve under when the price is not what they are about:
# a real dated price, so a row reads back consistently, and fixed so the amount
# under test is the only thing that varies.
RESERVED_AT = ModelPrice(
    MODEL, Decimal("0.0000001"), Decimal("0.000002"), date(2026, 9, 17)
)

CEILING_FOR_TEST = Decimal("1.00")
HALF = Decimal("0.60")
# Acceptance requires a governed run on the real route (Task17d3a).
NODES = [
    node.route_node_id
    for node in resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION).nodes
]


def _amount(taken: Reservation | None) -> Decimal | None:
    """What a reservation set aside, or None when there is none. Since Task 8.2
    `reserved_for` answers with the price beside the amount; these assertions
    are about the amount, and the price has its own test above."""
    return None if taken is None else taken.amount


def _run_with_ceiling(conn: StoreConnection, case_id: UUID) -> UUID:
    return start_run(conn, case_id, budget_ceiling=CEILING_FOR_TEST)


def test_a_reservation_reduces_what_remains(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")

    reserve(conn, attempt_id, Decimal("0.25"), price=RESERVED_AT)

    assert remaining(conn, run_id) == Decimal("0.75")
    assert _amount(reserved_for(conn, attempt_id)) == Decimal("0.25")


def test_a_reservation_past_the_ceiling_is_refused_before_it_is_taken(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Refuse *before* overspend, not after. A ceiling checked afterwards is an
    invoice, not a budget."""
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    first = start_attempt(conn, run_id, "CP-1")
    reserve(conn, first, HALF, price=RESERVED_AT)
    second = start_attempt(conn, run_id, "CP-2")

    with pytest.raises(Refusal) as caught:
        reserve(conn, second, HALF, price=RESERVED_AT)

    assert caught.value.code is RefusalCode.BUDGET_CEILING_REACHED
    assert remaining(conn, run_id) == CEILING_FOR_TEST - HALF
    assert reserved_for(conn, second) is None, "a refused reservation is not taken"


def test_a_reservation_of_exactly_what_remains_is_allowed(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The ceiling is a ceiling, not a wall one short of it."""
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")

    reserve(conn, attempt_id, CEILING_FOR_TEST, price=RESERVED_AT)

    assert remaining(conn, run_id) == Decimal("0")


def test_a_float_reservation_is_refused(case: tuple[StoreConnection, UUID]) -> None:
    """Invariant 7 on the other money path. Binary floating point cannot
    represent a cent, and a ceiling compared against one is not a ceiling."""
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")

    with pytest.raises(Refusal) as caught:
        reserve(conn, attempt_id, 0.25, price=RESERVED_AT)  # type: ignore[arg-type]

    assert caught.value.code is RefusalCode.MONEY_NOT_DECIMAL


def test_a_reservation_for_an_unknown_attempt_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case

    with pytest.raises(Refusal) as caught:
        reserve(conn, uuid4(), Decimal("0.25"), price=RESERVED_AT)

    assert caught.value.code is RefusalCode.ATTEMPT_NOT_FOUND


def test_crash_after_remote_completion_keeps_its_reservation(
    case: tuple[StoreConnection, UUID], empty_database: str
) -> None:
    """The reservation commits before the call, on its own.

    Sharing the acceptance transaction would mean a process that died after the
    provider completed rolled back the record of money that was really spent --
    and the retry would reserve against a ceiling that had forgotten it.
    """
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")
    reserve(conn, attempt_id, HALF, price=RESERVED_AT)

    # The provider completed; the process dies before accepting the artifact.
    with connect(empty_database) as dying:
        dying.execute(
            "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
            " model, generation_id)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            # The producer the real path records; written here too, because the
            # row this simulates is the one a real call would have left.
            (attempt_id, "d" * 64, run_id, case_id, MODEL, GENERATION),
        )
        dying.close()

    with connect(empty_database) as restarted:
        assert _amount(reserved_for(restarted, attempt_id)) == HALF
        assert remaining(restarted, run_id) == CEILING_FOR_TEST - HALF


def test_a_retry_without_provider_idempotency_reserves_again(
    case: tuple[StoreConnection, UUID],
) -> None:
    """`docs/DECISIONS.md` §16: the provider is called with no idempotency key
    and retries are unwanted, so a retry is a new attempt and a new reservation.

    The old one is not released. An indeterminate call may have reached the
    provider and may be billed; releasing its reservation would let the retry
    spend money the run has already committed.
    """
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    first = start_attempt(conn, run_id, "CP-1")
    reserve(conn, first, Decimal("0.30"), price=RESERVED_AT)

    # The call was indeterminate -- PROVIDER_UNAVAILABLE. The node is retried.
    retry = start_attempt(conn, run_id, "CP-1")
    reserve(conn, retry, Decimal("0.30"), price=RESERVED_AT)

    assert first != retry, "a retry is a new attempt row, not a reused one"
    assert _amount(reserved_for(conn, first)) == Decimal("0.30")
    assert remaining(conn, run_id) == Decimal("0.40"), "both reservations stand"


def test_concurrent_reservations_at_the_ceiling_refuse(
    empty_database: str,
) -> None:
    """Two connections, one ceiling. The run row lock is what makes exactly one
    of them right; without it both read the same remaining and both reserve."""
    with connect(empty_database) as setup:
        apply_schema(setup)
        case_id = create_case(setup, BoundaryText.of("Acme 2026 refinancing"))
        run_id = start_run(setup, case_id, budget_ceiling=CEILING_FOR_TEST)
        setup.commit()
        attempts = [start_attempt(setup, run_id, f"CP-{n}") for n in (1, 2)]

    def take(attempt_id: UUID) -> bool:
        with connect(empty_database) as conn:
            try:
                reserve(conn, attempt_id, HALF, price=RESERVED_AT)
            except Refusal as refusal:
                assert refusal.code is RefusalCode.BUDGET_CEILING_REACHED
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(take, attempts))

    assert outcomes == [False, True], "exactly one reservation fits under the ceiling"
    with connect(empty_database) as conn:
        assert remaining(conn, run_id) == CEILING_FOR_TEST - HALF


def test_remaining_of_an_unknown_run_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case

    with pytest.raises(Refusal) as caught:
        remaining(conn, uuid4())

    assert caught.value.code is RefusalCode.RUN_NOT_FOUND


def test_a_run_without_a_stated_ceiling_gets_the_declared_default(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A run with no ceiling at all would be invariant 8 with the number left
    out, so the default is declared beside the code rather than left to a
    caller who may not pass one."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()

    assert remaining(conn, run_id) == CEILING


@pytest.fixture
def money_run(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> tuple[StoreConnection, UUID, UUID]:
    conn, case_id = case
    run = _run_with_ceiling(conn, case_id)
    conn.commit()
    approved_nodes(conn, run, tmp_path)
    return conn, run, start_attempt(conn, run, NODES[0])


def _accept(conn: StoreConnection, attempt: UUID, charge: Decimal) -> None:
    accept_attempt(
        conn,
        attempt_id=attempt,
        accepted=Accepted("b" * 64, charge, MODEL, GENERATION, record_sha256=RECORD),
    )


@pytest.mark.parametrize("entry", ["ceiling", "reserve", "charge"])
@pytest.mark.parametrize(
    "amount",
    [
        True,
        1,
        0.1,
        "0.1",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-0.01"),
        Decimal("1e131072"),
        Decimal("1e-16384"),
        Decimal("0e-16384"),
        Decimal("0e131072"),
        Decimal("1.00e-16383"),
    ],
)
def test_invalid_money_refuses_at_each_store_entrance(
    money_run: tuple[StoreConnection, UUID, UUID], entry: str, amount: object
) -> None:
    """validate_spend guards all three real entrances before arithmetic or writes."""
    conn, run, attempt = money_run
    owner = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert owner is not None
    conn.commit()
    expected = "MONEY_INVALID" if isinstance(amount, Decimal) else "MONEY_NOT_DECIMAL"
    with pytest.raises(Refusal, match=f"^{expected}$"):
        if entry == "ceiling":
            start_run(conn, owner[0], budget_ceiling=amount)  # type: ignore[arg-type]
        elif entry == "reserve":
            reserve(conn, attempt, amount, price=RESERVED_AT)  # type: ignore[arg-type]
        else:
            _accept(conn, attempt, amount)  # type: ignore[arg-type]
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (1,)
    for table in ("budget_reservations", "budget_ledger", "artifacts"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


@pytest.mark.parametrize("value", ["0", "-0.00", "0.2500", "1e131071", "1e-16383"])
def test_native_money_boundaries_round_trip_at_all_entrances(
    case: tuple[StoreConnection, UUID], value: str, tmp_path: Path
) -> None:
    conn, case_id = case
    amount = Decimal(value)
    run = start_run(conn, case_id, budget_ceiling=amount)
    conn.commit()
    approved_nodes(conn, run, tmp_path)
    attempt = start_attempt(conn, run, NODES[0])
    reserve(conn, attempt, amount, price=RESERVED_AT)
    _accept(conn, attempt, amount)
    assert _amount(reserved_for(conn, attempt)) == amount
    assert conn.execute("SELECT amount FROM budget_ledger").fetchone() == (amount,)
    assert conn.execute("SELECT budget_ceiling FROM runs").fetchone() == (amount,)
    assert remaining(conn, run) == 0


@pytest.mark.parametrize(
    ("estimate", "charge", "left"),
    [("0.25", "1.20", "-0.20"), ("0.50", "0.20", "0.50"), ("0", "0", "1")],
)
def test_known_charge_raises_exposure_but_never_releases_a_reservation(
    money_run: tuple[StoreConnection, UUID, UUID], estimate: str, charge: str, left: str
) -> None:
    conn, run, attempt = money_run
    reserve(conn, attempt, Decimal(estimate), price=RESERVED_AT)
    _accept(conn, attempt, Decimal(charge))
    assert remaining(conn, run) == Decimal(left)
    assert _amount(reserved_for(conn, attempt)) == Decimal(estimate)
    next_attempt = start_attempt(conn, run, NODES[1])
    if Decimal(left) < 0:
        with pytest.raises(Refusal, match=r"^BUDGET_CEILING_REACHED$"):
            reserve(conn, next_attempt, Decimal(0), price=RESERVED_AT)
        assert conn.info.transaction_status is TransactionStatus.IDLE
        assert reserved_for(conn, next_attempt) is None
    else:
        reserve(conn, next_attempt, Decimal(left), price=RESERVED_AT)
        assert remaining(conn, run) == 0


def test_mixed_historical_exposure_counts_each_attempt_once(
    money_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run, unresolved = money_run
    reserve(conn, unresolved, Decimal("0.30"), price=RESERVED_AT)
    retry = start_attempt(conn, run, NODES[0])
    reserve(conn, retry, Decimal("0.20"), price=RESERVED_AT)
    _accept(conn, retry, Decimal("0.40"))
    historical = start_attempt(conn, run, NODES[1])
    _accept(conn, historical, Decimal("0.25"))
    start_attempt(conn, run, NODES[2])
    assert remaining(conn, run) == Decimal("0.05")
    assert _amount(reserved_for(conn, unresolved)) == Decimal("0.30")
    assert reserved_for(conn, historical) is None


def test_remaining_is_independent_of_decimal_context(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    run = start_run(
        conn, case_id, budget_ceiling=Decimal("1.000000000000000000000000000001")
    )
    conn.commit()
    approved_nodes(conn, run, tmp_path)
    attempt = start_attempt(conn, run, NODES[0])
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = context.traps[Rounded] = True
        reserve(
            conn,
            attempt,
            Decimal("0.000000000000000000000000000001"),
            price=RESERVED_AT,
        )
        _accept(conn, attempt, Decimal("0.000000000000000000000000000002"))
        assert remaining(conn, run) == Decimal("0.999999999999999999999999999999")


@pytest.mark.parametrize("existing", ["reservation", "charge"])
@pytest.mark.parametrize("amount", ["0.25", "0.30"])
def test_same_attempt_never_authorizes_another_spend(
    money_run: tuple[StoreConnection, UUID, UUID], existing: str, amount: str
) -> None:
    conn, run, attempt = money_run
    if existing == "reservation":
        reserve(conn, attempt, Decimal("0.25"), price=RESERVED_AT)
    else:
        _accept(conn, attempt, Decimal("0.25"))
    with pytest.raises(Refusal, match=r"^BUDGET_ALREADY_RESERVED$"):
        reserve(conn, attempt, Decimal(amount), price=RESERVED_AT)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert remaining(conn, run) == Decimal("0.75")
    taken = reserved_for(conn, attempt)
    assert (taken.amount if taken else None) == (
        Decimal("0.25") if existing == "reservation" else None
    )


@pytest.mark.parametrize("terminal", [block_run, fail_run])
def test_reserve_observes_terminal_transition_after_waiting(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    terminal: Callable[[StoreConnection, UUID], bool],
) -> None:
    conn, run, attempt = money_run
    lock_run(conn, run)
    with connect(empty_database) as other:

        def refused() -> None:
            with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
                reserve(other, attempt, Decimal("0.25"), price=RESERVED_AT)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, refused):
            terminal(conn, run)
    assert reserved_for(conn, attempt) is None


def test_reservation_holds_order_until_commit(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, run, attempt = money_run
    ready, release = Event(), Event()
    original = budget._remaining

    def pause(c: StoreConnection, owner: UUID) -> Decimal:
        result = original(c, owner)
        ready.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(budget, "_remaining", pause)
    with connect(empty_database) as other, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(reserve, conn, attempt, Decimal("0.25"), price=RESERVED_AT)
        try:
            assert ready.wait(3)
            second = pool.submit(block_run, other, run)
            _wait_for_blocking(conn, other)
        finally:
            release.set()
        first.result(timeout=6)
        assert second.result(timeout=6)
    assert _amount(reserved_for(conn, attempt)) == Decimal("0.25")


@pytest.mark.parametrize(
    "failure", ["missing", "owner", "lock", "insert", "commit", "cancel", "broken"]
)
def test_reservation_failure_is_atomic_and_releases_locks(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, run, attempt = money_run
    owner = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert owner is not None
    if failure in {"owner", "lock", "insert"}:
        conn.execute(
            {
                "owner": "ALTER TABLE run_attempts RENAME TO hidden_attempts",
                "lock": "ALTER TABLE cases RENAME TO hidden_cases",
                "insert": "ALTER TABLE budget_reservations ADD CHECK (false)",
            }[failure]
        )
    elif failure == "commit":
        conn.execute(
            "CREATE FUNCTION budget_failure() RETURNS trigger LANGUAGE plpgsql AS $$"
            " BEGIN RAISE EXCEPTION 'private'; END; $$;"
            " CREATE CONSTRAINT TRIGGER budget_failure"
            " AFTER INSERT ON budget_reservations DEFERRABLE INITIALLY DEFERRED"
            " FOR EACH ROW EXECUTE FUNCTION budget_failure()"
        )
    conn.commit()
    if failure in {"cancel", "broken"}:
        execute = psycopg.Connection.execute

        def cancel(
            c: StoreConnection, query: object, *args: object, **kwargs: object
        ) -> object:
            result = execute(c, query, *args, **kwargs)  # type: ignore[arg-type]
            if str(query).startswith("INSERT INTO budget_reservations"):
                if failure == "broken":
                    c.close()
                raise KeyboardInterrupt
            return result

        monkeypatch.setattr(psycopg.Connection, "execute", cancel)
    with pytest.raises(
        KeyboardInterrupt if failure in {"cancel", "broken"} else Refusal
    ) as caught:
        reserve(
            conn,
            uuid4() if failure == "missing" else attempt,
            Decimal("0.25"),
            price=RESERVED_AT,
        )
    if isinstance(caught.value, Refusal):
        assert caught.value.code.value == (
            "ATTEMPT_NOT_FOUND" if failure == "missing" else "STORE_UNAVAILABLE"
        )
    assert conn.closed or conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        if failure != "lock":
            lock_case(other, owner[0])
        assert other.execute("SELECT count(*) FROM budget_reservations").fetchone() == (
            0,
        )


@pytest.mark.parametrize("read", ["remaining", "reserved_for"])
def test_budget_reads_preserve_caller_transaction_on_success_and_error(
    money_run: tuple[StoreConnection, UUID, UUID], read: str
) -> None:
    conn, run, attempt = money_run
    conn.execute("CREATE TABLE caller_work (id integer)")
    reader, key = (remaining, run) if read == "remaining" else (reserved_for, attempt)
    reader(conn, key)
    assert conn.info.transaction_status is TransactionStatus.INTRANS
    conn.execute("ALTER TABLE budget_reservations RENAME TO hidden_reservations")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        reader(conn, key)
    assert conn.info.transaction_status.name == "INERROR"
    conn.rollback()
    assert conn.execute("SELECT to_regclass('caller_work')").fetchone() == (None,)
    assert reserved_for(conn, attempt) is None


def test_validation_respects_transaction_ownership(
    money_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, _run, attempt = money_run
    conn.execute("CREATE TABLE caller_work (id integer)")
    with pytest.raises(Refusal, match=r"^MONEY_INVALID$"):
        start_run(conn, uuid4(), budget_ceiling=Decimal("NaN"))
    assert conn.info.transaction_status is TransactionStatus.INTRANS
    conn.commit()
    conn.execute("INSERT INTO caller_work VALUES (1)")
    with pytest.raises(Refusal, match=r"^MONEY_INVALID$"):
        reserve(conn, attempt, Decimal("NaN"), price=RESERVED_AT)
    assert conn.info.transaction_status.name == "IDLE"
    assert conn.execute("SELECT * FROM caller_work").fetchall() == []


def test_reserve_revalidates_attempt_owner_after_waiting(
    money_run: tuple[StoreConnection, UUID, UUID], empty_database: str
) -> None:
    conn, run, attempt = money_run
    owner = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert owner is not None
    new_run = start_run(conn, owner[0])
    conn.commit()
    lock_case(conn, owner[0])
    with connect(empty_database) as other:

        def refused() -> None:
            with pytest.raises(Refusal, match=r"^ATTEMPT_NOT_FOUND$"):
                reserve(other, attempt, Decimal("0.25"), price=RESERVED_AT)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, refused):
            conn.execute(
                "UPDATE run_attempts SET run_id = %s WHERE attempt_id = %s",
                (new_run, attempt),
            )
    assert reserved_for(conn, attempt) is None


@pytest.mark.parametrize("isolation", ["autocommit", "repeatable read", "serializable"])
def test_reserve_refuses_transaction_modes_that_cannot_order_money(
    money_run: tuple[StoreConnection, UUID, UUID], isolation: str
) -> None:
    conn, _run, attempt = money_run
    if isolation == "autocommit":
        conn.autocommit = True
    else:
        conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        reserve(conn, attempt, Decimal("0.25"), price=RESERVED_AT)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert reserved_for(conn, attempt) is None


def test_concurrent_same_attempt_reserves_only_once(
    money_run: tuple[StoreConnection, UUID, UUID], empty_database: str
) -> None:
    conn, run, attempt = money_run

    def take() -> str:
        with connect(empty_database) as other:
            try:
                reserve(other, attempt, Decimal("0.25"), price=RESERVED_AT)
            except Refusal as refusal:
                assert other.info.transaction_status is TransactionStatus.IDLE
                return refusal.code.value
            return "taken"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(take) for _ in range(2)]
        assert sorted(f.result(timeout=6) for f in futures) == [
            "BUDGET_ALREADY_RESERVED",
            "taken",
        ]
    assert remaining(conn, run) == Decimal("0.75")


@pytest.mark.parametrize("operation", ["reserve", "remaining", "reserved_for"])
def test_budget_closed_connection_failure_is_sanitized(
    money_run: tuple[StoreConnection, UUID, UUID], operation: str
) -> None:
    conn, run, attempt = money_run
    conn.close()
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        if operation == "reserve":
            reserve(conn, attempt, Decimal("0.25"), price=RESERVED_AT)
        else:
            (remaining if operation == "remaining" else reserved_for)(
                conn, run if operation == "remaining" else attempt
            )


def test_a_reservation_records_the_dated_price_that_produced_it(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Completion O09: the row says which price produced the amount (§40).

    The amount alone cannot be read back to a price -- many prices and request
    sizes reach the same number -- so an auditor asking what a run was priced
    at had nothing to read. The four columns are that answer, dated.
    """
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")
    price = ModelPrice(
        MODEL, Decimal("0.0000001"), Decimal("0.000002"), date(2026, 9, 17)
    )

    reserve(conn, attempt_id, Decimal("0.25"), price=price)

    taken = reserved_for(conn, attempt_id)
    assert taken is not None
    assert taken.amount == Decimal("0.25")
    assert taken.price == price, "the price is read back as the host wrote it"
    assert conn.execute(
        "SELECT price_model, price_input, price_output, price_as_of"
        " FROM budget_reservations WHERE attempt_id = %s",
        (attempt_id,),
    ).fetchone() == (
        price.model,
        price.input_per_token,
        price.output_per_token,
        price.as_of,
    )


def test_a_reservation_under_a_nameless_price_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A row whose price names no model would answer the audit with 'legacy'."""
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")
    nameless = ModelPrice("", Decimal("0.1"), Decimal("0.2"), date(2026, 9, 17))

    with pytest.raises(Refusal) as caught:
        reserve(conn, attempt_id, Decimal("0.25"), price=nameless)

    assert caught.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
    assert reserved_for(conn, attempt_id) is None


def test_a_reservation_under_a_non_date_as_of_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    """CF-071: `ModelPrice` is a plain dataclass, so nothing but
    `_validate_price` stops an `as_of` that is not a `date` -- a string, a
    bool, or none at all -- from reaching a row a later audit reads back as
    a date. Untested, this branch had never actually run."""
    conn, case_id = case
    run_id = _run_with_ceiling(conn, case_id)
    conn.commit()
    attempt_id = start_attempt(conn, run_id, "CP-1")
    for bad_as_of in (
        cast(date, "2026-09-17"),
        cast(date, None),
        cast(date, True),
        cast(date, 20260917),
    ):
        undated = ModelPrice("gpt", Decimal("0.1"), Decimal("0.2"), bad_as_of)

        with pytest.raises(Refusal) as caught:
            reserve(conn, attempt_id, Decimal("0.25"), price=undated)

        assert caught.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED, bad_as_of
        assert reserved_for(conn, attempt_id) is None
