"""F468: a run is started on one approved model and executes on it or not at all.

The deployment approves its models (`CAOS_MODEL_PRICE` and
`CAOS_MODEL_CHOICES`), a new run is pinned to one of them at its dated price,
and the worker builds each run's provider from that pin -- so a redeploy that
changes the configured model no longer moves a running run onto another.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from threading import Event
from uuid import UUID

import psycopg
import pytest
from command_fixtures import command_client
from conftest import SUITE_CONTEXT_TOKENS, tamper
from lite_route_fixtures import RealisticLiteCompletions
from test_runtime import RUN_AT, blobs, bundle, route
from test_worker import CONFIG, count, queued_run, work_row

from caos.api.commands.runs import started_on
from caos.blobs import BlobStore
from caos.graph.route import ResolvedRoute
from caos.graph.worker import approved, module_execution, work_once
from caos.methodology.bundle import Bundle
from caos.pricing import (
    CHOICES_SEPARATOR,
    ENDPOINT_ENV,
    MAX_MODEL_CHOICES,
    MODEL_CHOICES_ENV,
    MODEL_PRICE_ENV,
    REASONING_EFFORT_ENV,
    ModelPrice,
    model_choices,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.budget import price_of
from caos.store.runs import run_status, start_run

__all__ = ["blobs", "bundle", "command_client", "route"]

OPUS = "claude-opus-5-5,0.000005,0.000025,2026-09-22"
SONNET = "claude-sonnet-5-5,0.000003,0.000015,2026-09-22"
LUNA = "gpt-6-luna,0.0000001,0.0000005,2026-09-22"


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opus configured, Sonnet and Luna approved beside it."""
    monkeypatch.setenv(ENDPOINT_ENV, "claude-opus-5-5")
    monkeypatch.setenv(MODEL_PRICE_ENV, OPUS)
    monkeypatch.setenv(MODEL_CHOICES_ENV, CHOICES_SEPARATOR.join((SONNET, LUNA)))
    monkeypatch.delenv(REASONING_EFFORT_ENV, raising=False)


def test_the_configured_model_comes_first_then_each_approved_one(
    deployed: None,
) -> None:
    choices = model_choices()
    assert list(choices) == ["claude-opus-5-5", "claude-sonnet-5-5", "gpt-6-luna"]
    assert choices["claude-sonnet-5-5"] == ModelPrice(
        "claude-sonnet-5-5",
        Decimal("0.000003"),
        Decimal("0.000015"),
        date(2026, 9, 22),
    )


def test_with_no_choices_listed_the_configured_model_is_the_only_one(
    deployed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for listed in ("", f"{OPUS};", f"{OPUS};;"):
        # The bundle's own form, the configured price first (D75).
        monkeypatch.setenv(MODEL_CHOICES_ENV, listed)
        assert list(model_choices()) == ["claude-opus-5-5"]
    monkeypatch.delenv(MODEL_CHOICES_ENV)
    assert list(model_choices()) == ["claude-opus-5-5"]
    monkeypatch.setenv(MODEL_CHOICES_ENV, f"{OPUS};{LUNA}")
    assert list(model_choices()) == ["claude-opus-5-5", "gpt-6-luna"]


@pytest.mark.parametrize(
    "listed",
    [
        "claude-opus-5-5,0.000006,0.000025,2026-09-22",  # the configured, repriced
        f"{SONNET};{SONNET}",  # an approved model priced twice
        f"{SONNET};{SONNET.replace('0.000003', '0.000004')}",  # priced two ways
        "claude-sonnet-5-5,0,0.000015,2026-09-22",  # a free rate
        "claude-sonnet-5-5,0.000003,0.000015,2999-01-01",  # a price not yet in force
        "claude-sonnet-5-5,0.000003,0.000015",  # no date
        CHOICES_SEPARATOR.join(
            f"model-{n},0.000001,0.000002,2026-09-22" for n in range(MAX_MODEL_CHOICES)
        ),  # one past the bound, with the configured model
    ],
)
def test_a_list_that_cannot_be_read_whole_refuses_every_model(
    deployed: None, monkeypatch: pytest.MonkeyPatch, listed: str
) -> None:
    monkeypatch.setenv(MODEL_CHOICES_ENV, listed)
    with pytest.raises(Refusal) as refused:
        model_choices()
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_a_reasoning_effort_is_refused_before_any_price_is_read(
    deployed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REASONING_EFFORT_ENV, "high")
    with pytest.raises(Refusal) as refused:
        model_choices()
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_a_run_keeps_the_price_it_was_started_on_and_it_is_written_once(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    sonnet = replace(RUN_AT, model="claude-sonnet-5-5")
    pinned = start_run(conn, case_id, price=sonnet)
    unpinned = start_run(conn, case_id)
    conn.commit()
    assert price_of(conn, pinned) == sonnet
    assert price_of(conn, unpinned) is None
    for run_id in (pinned, unpinned):
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(
                "UPDATE runs SET price_model = 'gpt-6-luna' WHERE run_id = %s",
                (run_id,),
            )
        conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        start_run(conn, case_id, price=replace(sonnet, input_per_token=Decimal(-1)))
    conn.rollback()


def test_started_on_names_the_pin_a_create_gets(
    deployed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert started_on("gpt-6-luna") == model_choices()["gpt-6-luna"]
    assert started_on(None) == model_choices()["claude-opus-5-5"]
    with pytest.raises(Refusal) as refused:
        started_on("glm-5-3")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
    monkeypatch.delenv(MODEL_PRICE_ENV)
    assert started_on(None) is None


def _pin(conn: StoreConnection, run_id: UUID, price: ModelPrice) -> None:
    """The price `start_run` would have written: the fixture starts its runs
    unpinned, and the columns refuse a later write, so it is set as a
    replica would set it."""
    tamper(
        conn,
        "UPDATE runs SET price_model = %s, price_input = %s, price_output = %s,"
        " price_as_of = %s WHERE run_id = %s",
        (
            price.model,
            price.input_per_token,
            price.output_per_token,
            price.as_of,
            run_id,
        ),
    )
    conn.commit()


def test_the_worker_executes_a_run_on_its_pinned_model_at_its_pinned_price(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    declare_context: Callable[[str, int | None], None],
) -> None:
    # The pinned model's context, declared for this endpoint name (D116).
    declare_context("gpt-6-luna", SUITE_CONTEXT_TOKENS)
    run = queued_run(case, route, bundle, blobs)
    luna = replace(RUN_AT, model="gpt-6-luna", as_of=date(2026, 9, 1))
    _pin(run.conn, run.run_id, luna)
    asked: list[ModelPrice] = []

    def provider_for(price: ModelPrice) -> RealisticLiteCompletions:
        asked.append(price)
        return RealisticLiteCompletions(run.source_id, model=price.model, price=price)

    work_once(
        run.conn,
        run.blobs,
        execution_for=module_execution(provider_for, RUN_AT, run.bundle, run.blobs),
        config=CONFIG,
        stopping=Event(),
    )
    assert asked == [luna]
    assert run_status(run.conn, run.run_id) is RunStatus.COMPLETE
    billed = run.conn.execute(
        "SELECT DISTINCT price_model, price_as_of FROM budget_reservations"
        " WHERE run_id = %s",
        (run.run_id,),
    ).fetchall()
    run.conn.rollback()
    assert billed == [("gpt-6-luna", date(2026, 9, 1))]


def test_a_run_on_a_model_the_deployment_dropped_parks_before_any_attempt(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> None:
    run = queued_run(case, route, bundle, blobs)
    _pin(run.conn, run.run_id, replace(RUN_AT, model="gpt-6-luna"))
    provider_for = approved({RUN_AT.model: RUN_AT})
    work_once(
        run.conn,
        run.blobs,
        execution_for=module_execution(provider_for, RUN_AT, run.bundle, run.blobs),
        config=CONFIG,
        stopping=Event(),
    )
    assert work_row(run.conn, run.run_id)[:2] == (
        "STOPPED",
        RefusalCode.PROVIDER_NOT_CONFIGURED.value,
    )
    assert count(run.conn, "run_attempts", run.run_id) == 0
