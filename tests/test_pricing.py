"""F06: a reservation is priced from the configured model, conservatively.

Each call's reservation covers that call: the bytes the provider will be sent
as input tokens -- a token is at least one byte, so the bound holds -- and the
output cap as output tokens (Task 8.2, §38). `worst_case`, the same arithmetic
at `MAX_REQUEST_BYTES`, stays as the run's admission check.
Runtime-driven cases run the canonical LITE route (Task 3.1 slice e-2).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from conftest import reserve_at
from test_runtime import _approved_run, blobs, bundle, route

from caos.blobs import BlobStore
from caos.graph.route import ResolvedRoute
from caos.graph.runtime import Execution, run_route
from caos.methodology.bundle import Bundle
from caos.pricing import ModelPrice, price_from_environment, priced_request, worst_case
from caos.provider import MAX_COMPLETION_TOKENS, MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.budget import ceiling_of, remaining, reserved_for
from caos.store.outcomes import execution_reads
from caos.store.runs import run_status, start_attempt

__all__ = ["blobs", "bundle", "route"]

MODEL = "a-model/for-the-test"
PRICE = ModelPrice(MODEL, Decimal("0.0000001"), Decimal("0.000002"), date(2026, 9, 13))


def test_worst_case_covers_the_request_and_completion_ceilings() -> None:
    assert worst_case(PRICE) == (
        Decimal("0.0000001") * MAX_REQUEST_BYTES
        + Decimal("0.000002") * MAX_COMPLETION_TOKENS
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("input_per_token", Decimal("NaN"), RefusalCode.MONEY_INVALID),
        ("output_per_token", Decimal("-0.1"), RefusalCode.MONEY_INVALID),
        ("output_per_token", 0.1, RefusalCode.MONEY_NOT_DECIMAL),
        ("input_per_token", True, RefusalCode.MONEY_NOT_DECIMAL),
        ("model", "", RefusalCode.PROVIDER_NOT_CONFIGURED),
        ("input_per_token", Decimal("0." + "1" * 1200), RefusalCode.MONEY_INVALID),
    ],
)
def test_invalid_prices_refuse(field: str, value: object, code: RefusalCode) -> None:
    with pytest.raises(Refusal) as caught:
        worst_case(replace(PRICE, **{field: value}))  # type: ignore[arg-type]
    assert caught.value.code is code


@pytest.mark.parametrize(
    "request_bytes,code",
    [
        (1.5, RefusalCode.MONEY_NOT_DECIMAL),
        (True, RefusalCode.MONEY_NOT_DECIMAL),
        (-1, RefusalCode.MONEY_INVALID),
        (MAX_REQUEST_BYTES + 1, RefusalCode.CONTEXT_OVER_CEILING),
    ],
)
def test_priced_request_refuses_a_malformed_or_oversized_byte_count(
    request_bytes: object, code: RefusalCode
) -> None:
    """N68: `worst_case` only ever calls this at exactly `MAX_REQUEST_BYTES`,
    which never exercises `priced_request`'s own guards on the count a direct
    caller supplies."""
    with pytest.raises(Refusal) as caught:
        priced_request(PRICE, request_bytes)  # type: ignore[arg-type]
    assert caught.value.code is code


def test_price_from_environment_refuses_a_price_for_another_model() -> None:
    """N68: `caos.models.from_environment` names the endpoint twice -- once as
    the model `price_from_environment` must match, once again to build the
    provider -- so a `CAOS_MODEL_PRICE` for some other endpoint is refused
    here, before either the provider or its own later, redundant check."""
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        price_from_environment(
            "databricks-claude-opus-5", "other-model,0.000005,0.000025,2026-09-22"
        )


def test_a_free_price_refuses_rather_than_reserving_nothing() -> None:
    free = replace(PRICE, input_per_token=Decimal(0), output_per_token=Decimal(0))
    with pytest.raises(Refusal, match=r"^MONEY_INVALID$"):
        worst_case(free)


def test_a_price_for_another_model_refuses_before_any_attempt(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    provider = run.provider()
    with pytest.raises(Refusal) as caught:
        run_route(
            conn,
            blobs,
            run_id=run.run_id,
            route=route,
            execution=Execution(provider, replace(PRICE, model="other/model"), bundle),
        )
    assert caught.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
    assert provider.calls == []
    assert provider.answers.prompts == []
    assert conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s", (run.run_id,)
    ).fetchone() == (0,)


def test_an_overrun_charge_stops_the_next_node_before_its_call(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """A charge above the reservation consumes capacity (Phase 2 budget exit)."""
    conn, case_id = case
    small = ModelPrice(
        MODEL, Decimal(0), Decimal("0.10") / MAX_COMPLETION_TOKENS, PRICE.as_of
    )
    run = _approved_run(conn, case_id, route, bundle, blobs, ceiling=Decimal("1.05"))
    provider = run.provider(charge=Decimal("1.00"))
    with pytest.raises(Refusal) as caught:
        run_route(
            conn,
            blobs,
            run_id=run.run_id,
            route=route,
            execution=Execution(provider, small, bundle),
        )
    assert caught.value.code is RefusalCode.BUDGET_CEILING_REACHED
    assert provider.calls == ["CP-0"]
    assert len(provider.answers.prompts) == 1
    assert conn.execute(
        "SELECT amount FROM budget_ledger WHERE run_id = %s", (run.run_id,)
    ).fetchall() == [(Decimal("1.00"),)]


def test_a_run_ceiling_below_one_worst_case_still_refuses_before_any_attempt(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """Task 8.2 prices each reservation on its own request, so the ceiling is
    no longer met by the first reservation. `worst_case` stays as the run's
    admission check: a run that could not afford one call at the price's worst
    case is refused before an attempt row exists, spending nothing.
    """
    conn, case_id = case
    run = _approved_run(
        conn, case_id, route, bundle, blobs, ceiling=worst_case(PRICE) - Decimal("0.01")
    )
    provider = run.provider()

    with pytest.raises(Refusal) as caught:
        run_route(
            conn,
            blobs,
            run_id=run.run_id,
            route=route,
            execution=Execution(provider, PRICE, bundle),
        )

    assert caught.value.code is RefusalCode.BUDGET_CEILING_REACHED
    assert provider.calls == [] and provider.answers.prompts == []
    assert conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s", (run.run_id,)
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*) FROM budget_reservations WHERE run_id = %s", (run.run_id,)
    ).fetchone() == (0,)


def test_a_reservation_is_priced_on_the_request_not_on_the_byte_ceiling(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """What Task 8.2 replaces `worst_case` per call with (completion O09).

    `PRICE` charges for input, so the byte ceiling and the request diverge:
    each reservation is the priced cost of the bytes the provider was sent,
    strictly below one worst case, and carries the dated price that produced it.
    """
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    provider = run.provider()
    run_route(
        conn,
        blobs,
        run_id=run.run_id,
        route=route,
        execution=Execution(provider, PRICE, bundle),
    )
    attempts = [
        row[0]
        for row in conn.execute(
            "SELECT attempt_id FROM run_attempts WHERE run_id = %s", (run.run_id,)
        ).fetchall()
    ]
    taken = [reserved_for(conn, attempt) for attempt in attempts]

    assert len(attempts) == len(provider.calls) == len(route.nodes)
    assert all(row is not None for row in taken)
    assert {row.price for row in taken if row is not None} == {PRICE}
    assert sorted(row.amount for row in taken if row is not None) == sorted(
        priced_request(
            PRICE, len(provider.answers.request_bytes(prompt, json_object=True))
        )
        for prompt in provider.answers.prompts
    )
    assert all(
        row is not None and Decimal(0) < row.amount < worst_case(PRICE) for row in taken
    )


def test_a_run_that_spent_past_one_worst_case_still_resumes(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """The admission check reads the run's ceiling, not what is left of it.

    Before Task 8.2 every reservation was a worst case, so "remaining below one
    worst case" and "ceiling below one worst case" refused the same runs. Priced
    reservations separate them: a run may legitimately spend to within one worst
    case of its ceiling and still afford its remaining nodes. Reading the
    remainder here refused exactly that run the next time `run_route` was
    entered -- which is every resume, and every retry after one -- so a run that
    finished when it ran continuously could not finish after a crash, with money
    left and nothing wrong. Invariant 6 is "resume from accepted attempts, never
    restart", and a guard for invariant 8 was breaking it.

    What refuses an operation the run can no longer pay for is `reserve`, under
    the run row lock. This refuses a run that could never have afforded one
    full-sized call, which is a property of the ceiling and does not move.

    Found by the Task 8.2 acceptance review, which reproduced it on the LITE
    fixture; this is the same failure at the guard rather than through a crash.
    """
    conn, case_id = case
    # A price whose worst case is dominated by the request rather than by the
    # completion cap, so that a priced request is a small fraction of a worst
    # case -- which is the gap Task 8.2 stopped paying for, and the only shape in
    # which "spent past one worst case, still affords its nodes" can exist. Under
    # `PRICE` the output cap alone is 55.6 % of a worst case, so three nodes cost
    # more than one and this test's shape -- one lump past a worst case, then all
    # three nodes -- cannot arise. The underlying situation can: two nodes paid
    # and one left is 0.556 of a worst case at any price. At about $3 and $15 per
    # million tokens the cap is 24 % of a $4.13 worst case, so a $5 LITE run that
    # has paid two nodes has less than one worst case left and its last node is
    # affordable -- which is the real run the old guard refused on resume. The
    # price here reproduces that ratio; `PRICE` is the artefact, not this.
    price = replace(PRICE, output_per_token=Decimal("0.0000000001"))
    run = _approved_run(
        conn, case_id, route, bundle, blobs, ceiling=worst_case(price) * 2
    )
    attempt = start_attempt(conn, run.run_id, route.nodes[0].route_node_id)
    # Spent past the point where one worst case is left, as a priced run can be.
    reserve_at(conn, attempt, worst_case(price) + Decimal("0.01"))
    conn.commit()
    with execution_reads(conn):
        left = remaining(conn, run.run_id)
        # The two readings this fix separates: what the run may still spend, and
        # what it was ever allowed to spend. `ceiling_of` is the second and does
        # not move as the run pays for its nodes.
        assert ceiling_of(conn, run.run_id) == worst_case(price) * 2
    assert left < worst_case(price), "the state this refused on"
    assert left > worst_case(price) / 2, "and the money is genuinely there"

    # The run is entered again, as a resume or a retry enters it.
    run_route(
        conn,
        blobs,
        run_id=run.run_id,
        route=route,
        execution=Execution(run.provider(), price, bundle),
    )

    # The point is that admission did not refuse. The run then finishes, which
    # says the money was there all along: `reserve` priced each node and none
    # of them needed a worst case.
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE


def test_bills_at_compares_the_whole_price_a_provider_states() -> None:
    """CF-089: the reservation is priced at the run's price and the charge at
    the provider's own, so the two must be one price -- model, rates and date
    -- not only one model. A provider that states no price (one that reports
    money) is still held to the model."""
    from types import SimpleNamespace

    from caos.pricing import bills_at

    assert bills_at(SimpleNamespace(model=MODEL, price=PRICE), PRICE)
    assert bills_at(SimpleNamespace(model=MODEL), PRICE)
    assert bills_at(SimpleNamespace(model=MODEL, price=None), PRICE)
    for moved in (
        replace(PRICE, input_per_token=Decimal("0.0000002")),
        replace(PRICE, output_per_token=Decimal("0.000001")),
        replace(PRICE, as_of=date(2026, 9, 12)),
    ):
        assert not bills_at(SimpleNamespace(model=MODEL, price=moved), PRICE)
    assert not bills_at(SimpleNamespace(model="another-model", price=PRICE), PRICE)
    assert not bills_at(SimpleNamespace(), PRICE)
    # The same rate spelled with another exponent is the same price.
    same = replace(PRICE, output_per_token=Decimal("0.0000020"))
    assert bills_at(SimpleNamespace(model=MODEL, price=same), PRICE)
