"""A paid call remains a fact when analytical acceptance cannot commit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import reserve_at as reserve
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_budget import money_run as _money_run
from test_case_ordering import _blocked
from test_store_schema import _records

from caos.refusals import Refusal
from caos.store import RunStatus, StoreConnection, connect, outcomes, runs
from caos.store.budget import remaining, reserved_for
from caos.store.events import events_of, lock_run

ACCEPTED = runs.Accepted(
    "a" * 64, Decimal("0.25"), "test/model", "generation", record_sha256="c" * 64
)
OUTCOME_EVENT = "CALL_OUTCOME_RECORDED"
money_run = _money_run


@pytest.mark.parametrize("limit", [256, 512])
@pytest.mark.parametrize(
    "value", ["a", "A0._:/@+-", "", "_bad", "bad\n", "é", {}, True]
)
def test_producer_identifier_retains_the_exact_storage_grammar(
    limit: int, value: object
) -> None:
    expected = value if value in ("a", "A0._:/@+-") else None
    assert outcomes.producer_identifier(value, limit=limit) == expected
    assert outcomes.producer_identifier("x" * limit, limit=limit) == "x" * limit
    assert outcomes.producer_identifier("x" * (limit + 1), limit=limit) is None


def _outcome(**changes: object) -> outcomes.CallOutcome:
    return replace(
        outcomes.CallOutcome(ACCEPTED.charge, ACCEPTED.model, ACCEPTED.generation_id),
        **changes,  # type: ignore[arg-type]
    )


def _counts(conn: StoreConnection) -> tuple[int, ...]:
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        for table in ("call_outcomes", "budget_ledger", "artifacts")
    )


def test_acceptance_requires_known_charge(
    money_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, _run, attempt = money_run
    accepted = replace(ACCEPTED, charge=None)  # type: ignore[arg-type]
    with pytest.raises(Refusal, match=r"^MONEY_NOT_DECIMAL$"):
        runs.accept_attempt(conn, attempt_id=attempt, accepted=accepted)
    assert _counts(conn) == (0, 0, 0)


@pytest.mark.parametrize("terminal", [runs.block_run, fail_run])
def test_late_outcome_is_durable_without_analytical_acceptance(
    money_run: tuple[StoreConnection, UUID, UUID],
    terminal: Callable[[StoreConnection, UUID], bool],
) -> None:
    conn, run, attempt = money_run
    terminal(conn, run)
    assert not runs.accept_attempt(conn, attempt_id=attempt, accepted=ACCEPTED)
    before = _records(conn)
    assert not runs.accept_attempt(conn, attempt_id=attempt, accepted=ACCEPTED)
    assert _records(conn) == before
    assert _counts(conn) == (1, 1, 0)
    assert [e.name for e in events_of(conn, run)] == [
        "ROUTE_PINNED",
        "INPUT_PINNED",
        "ATTEMPT_STARTED",
        "RUN_" + runs.run_status(conn, run).value,
        OUTCOME_EVENT,
    ]


def test_record_outcome_keeps_unknown_exposure_and_known_overrun(
    money_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run, attempt = money_run
    reserve(conn, attempt, Decimal("0.30"))
    unknown = _outcome(charge=None, model=None, generation_id=None)
    assert outcomes.record_outcome(conn, attempt_id=attempt, outcome=unknown)
    assert not outcomes.record_outcome(conn, attempt_id=attempt, outcome=unknown)
    assert _counts(conn) == (1, 0, 0)
    taken = reserved_for(conn, attempt)
    assert taken is not None and taken.amount == Decimal("0.30")
    assert remaining(conn, run) == Decimal("0.70")
    other = runs.start_attempt(conn, run, "CP-2")
    reserve(conn, other, Decimal("0.10"))
    assert outcomes.record_outcome(
        conn, attempt_id=other, outcome=_outcome(charge=Decimal("2"))
    )
    assert remaining(conn, run) == Decimal("-1.30")
    assert _counts(conn) == (2, 1, 0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("charge", Decimal("0.26")),
        ("charge", None),
        ("model", "other/model"),
        ("generation_id", "other-generation"),
        ("diagnostic_sha256", "b" * 64),
    ],
)
def test_conflicting_outcome_preserves_every_original_record(
    money_run: tuple[StoreConnection, UUID, UUID], field: str, value: object
) -> None:
    conn, _run, attempt = money_run
    assert outcomes.record_outcome(conn, attempt_id=attempt, outcome=_outcome())
    before = _records(conn)
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
        outcomes.record_outcome(
            conn, attempt_id=attempt, outcome=_outcome(**{field: value})
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert _records(conn) == before


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("model", "", "CALL_OUTCOME_INVALID"),
        ("model", {}, "CALL_OUTCOME_INVALID"),
        ("model", "a" * 257, "CALL_OUTCOME_INVALID"),
        ("generation_id", "a\n", "CALL_OUTCOME_INVALID"),
        ("generation_id", "a" * 513, "CALL_OUTCOME_INVALID"),
        ("diagnostic_sha256", "A" * 64, "CALL_OUTCOME_INVALID"),
        ("charge", True, "MONEY_NOT_DECIMAL"),
        ("charge", "0.1", "MONEY_NOT_DECIMAL"),
        ("charge", Decimal("NaN"), "MONEY_INVALID"),
        ("charge", Decimal("-1"), "MONEY_INVALID"),
    ],
)
def test_outcome_metadata_and_money_refuse_before_any_write(
    money_run: tuple[StoreConnection, UUID, UUID], field: str, value: object, code: str
) -> None:
    conn, _run, attempt = money_run
    with pytest.raises(Refusal, match=f"^{code}$"):
        outcomes.record_outcome(
            conn, attempt_id=attempt, outcome=_outcome(**{field: value})
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert _counts(conn) == (0, 0, 0)


@pytest.mark.parametrize(
    "failure", ["outcome", "ledger", "event", "commit", "cancel", "broken"]
)
def test_outcome_failure_rolls_back_owned_unit_and_releases_locks(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, run, attempt = money_run
    if failure in {"outcome", "ledger", "event"}:
        conn.execute(
            "ALTER TABLE "
            + {
                "outcome": "call_outcomes ADD CHECK (false)",
                "ledger": "budget_ledger ADD CHECK (false)",
                "event": "run_events ADD CHECK (name <> 'CALL_OUTCOME_RECORDED')",
            }[failure]
        )
    elif failure == "commit":
        conn.execute(
            "CREATE FUNCTION outcome_failure() RETURNS trigger LANGUAGE plpgsql AS $$"
            " BEGIN RAISE EXCEPTION 'private'; END; $$;"
            " CREATE CONSTRAINT TRIGGER outcome_failure AFTER INSERT ON call_outcomes"
            " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " EXECUTE FUNCTION outcome_failure()"
        )
    conn.commit()
    if failure in {"cancel", "broken"}:
        commit = psycopg.Connection.commit

        def cancel(c: StoreConnection) -> None:
            if failure == "broken":
                c.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(psycopg.Connection, "commit", cancel)
    with pytest.raises(
        KeyboardInterrupt if failure in {"cancel", "broken"} else Refusal
    ):
        outcomes.record_outcome(conn, attempt_id=attempt, outcome=_outcome())
    if failure in {"cancel", "broken"}:
        monkeypatch.setattr(psycopg.Connection, "commit", commit)
    assert conn.closed or conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_run(other, run)
        assert _counts(other) == (0, 0, 0)
        assert [e.name for e in events_of(other, run)] == [
            "ROUTE_PINNED",
            "INPUT_PINNED",
            "ATTEMPT_STARTED",
        ]


@pytest.mark.parametrize("failure", ["artifact", "event", "digest", "conflict"])
def test_analytical_failure_cannot_rollback_an_independent_bill(
    money_run: tuple[StoreConnection, UUID, UUID],
    failure: str,
) -> None:
    conn, run, attempt = money_run
    accepted = ACCEPTED
    if failure in {"artifact", "event"}:
        conn.execute(
            "ALTER TABLE "
            + (
                "artifacts ADD CHECK (false)"
                if failure == "artifact"
                else "run_events ADD CHECK (name <> 'ATTEMPT_ACCEPTED')"
            )
        )
        conn.commit()
    elif failure == "digest":
        accepted = replace(accepted, artifact_sha256="private-invalid")
    else:
        runs.accept_attempt(conn, attempt_id=attempt, accepted=accepted)
        fail_run(conn, run)
        accepted = replace(accepted, artifact_sha256="c" * 64)
    with pytest.raises(Refusal):
        runs.accept_attempt(conn, attempt_id=attempt, accepted=accepted)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert _counts(conn) == (1, 1, int(failure == "conflict"))
    names = [e.name for e in events_of(conn, run)]
    assert names.count(OUTCOME_EVENT) == 1
    assert names.count("ATTEMPT_ACCEPTED") == int(failure == "conflict")


@pytest.mark.parametrize("conflict", [False, True])
def test_same_attempt_outcomes_and_acceptance_serialize(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    conflict: bool,
) -> None:
    conn, run, attempt = money_run
    accepted = replace(ACCEPTED, diagnostic_sha256="d" * 64)
    lock_run(conn, run)
    with connect(empty_database) as other:

        def waiting() -> None:
            if conflict:
                with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
                    outcomes.record_outcome(
                        other,
                        attempt_id=attempt,
                        outcome=_outcome(charge=Decimal("0.26")),
                    )
            else:
                assert runs.accept_attempt(other, attempt_id=attempt, accepted=accepted)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, waiting):
            assert outcomes.record_outcome(
                conn,
                attempt_id=attempt,
                outcome=_outcome(diagnostic_sha256=accepted.diagnostic_sha256),
            )
    assert _counts(conn) == (1, 1, int(not conflict))
    assert [e.name for e in events_of(conn, run)].count(OUTCOME_EVENT) == 1


def test_acceptance_rechecks_termination_after_outcome_commit(
    money_run: tuple[StoreConnection, UUID, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, run, attempt = money_run
    record = outcomes.record_outcome

    def end(
        c: StoreConnection, *, attempt_id: UUID, outcome: outcomes.CallOutcome
    ) -> bool:
        result = record(c, attempt_id=attempt_id, outcome=outcome)
        with connect(empty_database) as other:
            other.execute("SET lock_timeout = '1s'")
            fail_run(other, run)
        return result

    monkeypatch.setattr(runs, "record_outcome", end)
    assert not runs.accept_attempt(conn, attempt_id=attempt, accepted=ACCEPTED)
    assert _counts(conn) == (1, 1, 0)
    assert runs.run_status(conn, run) is RunStatus.FAILED


@pytest.mark.parametrize("table", ["call_outcomes", "budget_ledger"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
def test_call_outcomes_and_ledger_are_natively_immutable(
    money_run: tuple[StoreConnection, UUID, UUID],
    table: str,
    verb: str,
) -> None:
    conn, _run, attempt = money_run
    outcomes.record_outcome(conn, attempt_id=attempt, outcome=_outcome())
    before = _records(conn)
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            {
                "UPDATE": f"UPDATE {table} SET run_id = run_id",
                "DELETE": f"DELETE FROM {table}",
                "TRUNCATE": f"TRUNCATE {table} CASCADE",
            }[verb]
        )
    conn.rollback()
    assert _records(conn) == before


@pytest.mark.parametrize(
    "fault", ["owner", "missing", "charge", "different-charge", "model", "digest"]
)
def test_outcome_native_keys_and_bounds_refuse_existing_unrelated_records(
    money_run: tuple[StoreConnection, UUID, UUID],
    fault: str,
) -> None:
    conn, run, attempt = money_run
    owner = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert owner is not None
    other = runs.start_run(conn, owner[0])
    conn.commit()
    charged = runs.start_attempt(conn, run, "CP-2")
    conn.execute(
        "INSERT INTO budget_ledger (attempt_id,run_id,amount) VALUES (%s,%s,0.1)",
        (charged, run),
    )
    conn.commit()
    before = _records(conn)
    values: list[object] = [attempt, run, None, "model", None]
    index, value = {
        "owner": (1, other),
        "missing": (0, uuid4()),
        "charge": (2, attempt),
        "different-charge": (2, charged),
        "model": (3, "unsafe\n"),
        "digest": (4, "bad"),
    }[fault]
    values[index] = value
    with pytest.raises(psycopg.IntegrityError):
        conn.execute(
            "INSERT INTO call_outcomes"
            " (attempt_id,run_id,charged_attempt_id,model,diagnostic_sha256)"
            " VALUES (%s,%s,%s,%s,%s)",
            values,
        )
    conn.rollback()
    assert _records(conn) == before


@pytest.mark.parametrize("legacy", ["exact", "ledger", "artifact", "conflict"])
def test_legacy_acceptance_replay_never_invents_an_outcome(
    money_run: tuple[StoreConnection, UUID, UUID],
    legacy: str,
) -> None:
    conn, run, attempt = money_run
    # A pre-0012 artifact carries no record; its replay names none either.
    accepted = replace(ACCEPTED, model="legacy model", record_sha256=None)
    if legacy != "artifact":
        conn.execute(
            "INSERT INTO budget_ledger (attempt_id,run_id,amount) VALUES (%s,%s,%s)",
            (attempt, run, accepted.charge),
        )
    if legacy != "ledger":
        conn.execute(
            "INSERT INTO artifacts (attempt_id,run_id,case_id,artifact_sha256,"
            " model,generation_id)"
            " SELECT %s,run_id,case_id,%s,%s,%s FROM runs WHERE run_id=%s",
            (
                attempt,
                accepted.artifact_sha256,
                accepted.model,
                accepted.generation_id,
                run,
            ),
        )
    conn.commit()
    before = _records(conn)
    if legacy == "exact":
        assert not runs.accept_attempt(conn, attempt_id=attempt, accepted=accepted)
    else:
        with pytest.raises(Refusal, match=r"^CALL_OUTCOME_LEGACY$"):
            runs.accept_attempt(
                conn,
                attempt_id=attempt,
                accepted=replace(accepted, charge=Decimal("0.26")),
            )
    assert _records(conn) == before
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_LEGACY$"):
        outcomes.record_outcome(conn, attempt_id=attempt, outcome=_outcome())
    assert _records(conn) == before
