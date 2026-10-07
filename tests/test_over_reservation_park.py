"""R2.6 held by the ledger, not by the park alone (F589).

A Copilot call charged above its reservation is recorded in full, refused
`BUDGET_CHARGE_OVER_RESERVATION`, and its run parks for good. The park is a
separate write from the refusal's explanation: a worker that dies, or a store
that fails, between the two leaves the run claimed and unparked. The next
claim must still start no attempt on that pin -- the pinned per-token price
would reserve the same way and the AI-unit bill overshoot the same way -- so
the ledger itself refuses it, under the run lock, and the reclaim parks the
run with the same code. Turned from the adversarial audit's probes
(`test_p2_park_crash_window.py`, `test_p2b_park_store_fault.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from threading import Event
from uuid import UUID

import psycopg
import pytest
from conftest import tamper
from lite_route_fixtures import RealisticLiteCompletions
from test_model_choice import _pin
from test_runtime import _Run, blobs, bundle, route
from test_worker import CONFIG, queued_run, work_row

from caos.blobs import BlobStore
from caos.copilot import CREDIT_PRICE_ENV
from caos.graph import worker as worker_mod
from caos.graph.route import ResolvedRoute
from caos.graph.worker import module_execution, work_once
from caos.methodology.bundle import Bundle
from caos.pricing import ModelPrice
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.budget import overspent, reserve
from caos.store.outcomes import CallOutcome, record_outcome
from caos.store.runs import start_attempt, start_run
from caos.store.work import stop

__all__ = ["blobs", "bundle", "route"]

COPILOT = "copilot:claude-opus-5.5@high"
PRICE = ModelPrice(
    COPILOT, Decimal("0.000000001"), Decimal("0.00000001"), date(2026, 9, 1)
)
OVER = Decimal("0.5")


def _died(*_args: object, **_kwargs: object) -> bool:
    raise KeyboardInterrupt


def _store_fault(*_args: object, **_kwargs: object) -> bool:
    raise psycopg.OperationalError


@pytest.fixture
def pinned_run(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> _Run:
    """A queued LITE run pinned to a Copilot model, its credit price set."""
    monkeypatch.setenv(CREDIT_PRICE_ENV, "0.01,2026-10-01")
    run = queued_run(case, route, bundle, blobs)
    _pin(run.conn, run.run_id, PRICE)
    return run


@pytest.mark.parametrize("lost", [_died, _store_fault], ids=["died", "store-fault"])
def test_a_park_lost_after_the_refusal_still_pays_the_pin_no_second_time(
    pinned_run: _Run, monkeypatch: pytest.MonkeyPatch, lost: Callable[..., bool]
) -> None:
    run = pinned_run
    providers: list[RealisticLiteCompletions] = []

    def provider_for(price: ModelPrice) -> RealisticLiteCompletions:
        made = RealisticLiteCompletions(
            run.source_id, model=price.model, price=price, charge=OVER
        )
        providers.append(made)
        return made

    execution_for = module_execution(provider_for, PRICE, run.bundle, run.blobs)
    monkeypatch.setattr(worker_mod, "stop", lost)
    try:
        work_once(
            run.conn,
            run.blobs,
            execution_for=execution_for,
            config=CONFIG,
            stopping=Event(),
        )
    except KeyboardInterrupt:
        pass
    run.conn.rollback()
    assert sum(len(p.prompts) for p in providers) == 1
    assert work_row(run.conn, run.run_id)[:2] == ("CLAIMED", None)
    # The lost worker's lease lapses, and another claims the run.
    tamper(
        run.conn,
        "UPDATE run_work SET lease_expires_at = clock_timestamp()"
        " - interval '1 second' WHERE run_id = %s",
        (run.run_id,),
    )
    run.conn.commit()
    monkeypatch.setattr(worker_mod, "stop", stop)
    work_once(
        run.conn,
        run.blobs,
        execution_for=execution_for,
        config=CONFIG,
        stopping=Event(),
    )
    run.conn.rollback()
    assert sum(len(p.prompts) for p in providers) == 1, "the pin was paid twice"
    assert work_row(run.conn, run.run_id)[:2] == (
        "STOPPED",
        "BUDGET_CHARGE_OVER_RESERVATION",
    )
    reservations = run.conn.execute(
        "SELECT count(*) FROM budget_reservations WHERE run_id = %s", (run.run_id,)
    ).fetchone()
    run.conn.rollback()
    assert reservations == (1,)


def _unqueued(case: tuple[StoreConnection, UUID]) -> tuple[StoreConnection, UUID]:
    conn, case_id = case
    run_id = start_run(conn, case_id, budget_ceiling=Decimal(5))
    conn.commit()
    return conn, run_id


def _billed(
    conn: StoreConnection, run_id: UUID, node: str, price: ModelPrice, charge: Decimal
) -> None:
    attempt = start_attempt(conn, run_id, node)
    reserve(conn, attempt, Decimal("0.25"), price=price)
    record_outcome(
        conn,
        attempt_id=attempt,
        outcome=CallOutcome(charge, price.model, f"gen-{node}", None, None),
    )


def test_the_ledger_refuses_any_attempt_on_an_overspent_run(
    case: tuple[StoreConnection, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the park or the explanation say: the bill alone decides, on
    every node of the run, since the price that overshot is the run's pin."""
    monkeypatch.setenv(CREDIT_PRICE_ENV, "0.01,2026-10-01")
    conn, run_id = _unqueued(case)
    assert not overspent(conn, run_id)
    conn.rollback()
    _billed(conn, run_id, "CP-1", PRICE, Decimal("0.25"))
    assert not overspent(conn, run_id), "equal to the reservation is within it"
    conn.rollback()
    _billed(conn, run_id, "CP-2", PRICE, Decimal("0.2500001"))
    assert overspent(conn, run_id)
    conn.rollback()
    for node in ("CP-1", "CP-2", "CP-3"):
        with pytest.raises(Refusal) as refused:
            start_attempt(conn, run_id, node)
        assert refused.value.code is RefusalCode.BUDGET_CHARGE_OVER_RESERVATION
        conn.rollback()
    started = conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s", (run_id,)
    ).fetchone()
    conn.rollback()
    assert started == (2,)


def test_a_token_priced_overrun_never_stops_an_attempt(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A reservation with no credit price keeps the Phase 2 budget exit: its
    overrun spends the run's capacity, and the ceiling decides the rest."""
    conn, run_id = _unqueued(case)
    gateway = ModelPrice(
        "a-model/for-the-test", Decimal(0), Decimal("0.0000001"), PRICE.as_of
    )
    _billed(conn, run_id, "CP-1", gateway, Decimal("0.75"))
    assert not overspent(conn, run_id)
    conn.rollback()
    start_attempt(conn, run_id, "CP-2")
