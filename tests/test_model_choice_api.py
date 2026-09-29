"""D75, the command half: a create pins the model it names, or the configured
one, refuses one the deployment does not approve, and the Run section serves
the choices and each run's model. The list and the worker are
`tests/test_model_choice.py`'s."""

from __future__ import annotations

from uuid import UUID

import pytest
from command_fixtures import command_client, member
from fastapi.testclient import TestClient
from test_model_choice import deployed
from test_run_commands import ROUTE, _outcome, _path, _send

from caos.pricing import MODEL_PRICE_ENV, model_choices
from caos.store import StoreConnection
from caos.store.audit import audit_trail, digest_of
from caos.store.budget import price_of
from caos.store.commands import request_digest
from caos.store.routes import pinned_route

__all__ = ["command_client", "deployed"]


def test_a_new_run_is_pinned_to_the_model_it_names_or_the_configured_one(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    started = {}
    for named in ("gpt-6-luna", None):
        created = _send(
            command_client, _path(case_id), writer, {**ROUTE, "model": named}
        )
        assert created.status_code == 201, created.text
        started[named] = price_of(conn, UUID(created.json()["run_id"]))
        conn.rollback()
    assert started == {
        "gpt-6-luna": model_choices()["gpt-6-luna"],
        None: model_choices()["claude-opus-5-5"],
    }
    # The audit binds the model each run was pinned to, the configured one
    # where the request named none; the request digest stays the request's.
    trail = audit_trail(conn, case_id)
    conn.rollback()
    for entry, (named, pinned_to) in zip(
        trail,
        [("gpt-6-luna", "gpt-6-luna"), (None, "claude-opus-5-5")],
        strict=True,
    ):
        body = {**ROUTE, "model": named}
        [run_id] = [
            UUID(str(row[0]))
            for row in conn.execute(
                "SELECT run_id FROM runs WHERE price_model = %s", (pinned_to,)
            ).fetchall()
        ]
        conn.rollback()
        assert entry.payload_sha256 == digest_of(
            {
                **body,
                "model": pinned_to,
                "route_digest": pinned_route(conn, run_id),
                "request_sha256": request_digest(
                    "CREATE_RUN", case_id=case_id, run_id=None, gate=None, body=body
                ),
            }
        )
        conn.rollback()
    listed = _send(command_client, f"/api/v1/cases/{case_id}/run", writer).json()
    assert [run["model"] for run in listed["body"]["runs"]] == [
        "claude-opus-5-5",
        "gpt-6-luna",
    ]
    assert listed["body"]["model_choices"][0] == {
        "model": "claude-opus-5-5",
        "input_per_token": "0.000005",
        "output_per_token": "0.000025",
        "as_of": "2026-09-22",
        "configured": True,
    }
    assert [choice["configured"] for choice in listed["body"]["model_choices"]] == [
        True,
        False,
        False,
    ]


def test_a_model_the_deployment_does_not_approve_is_refused_and_starts_nothing(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    for named in ("grok-4-7", "claude-opus-5"):
        refused = _send(
            command_client, _path(case_id), writer, {**ROUTE, "model": named}
        )
        assert _outcome(refused) == "400 PROVIDER_NOT_CONFIGURED"
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)
    conn.rollback()


def test_a_process_with_no_model_configured_pins_none(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run then takes the model of the worker that first executes it."""
    monkeypatch.delenv(MODEL_PRICE_ENV, raising=False)
    conn, case_id = case
    writer = member(conn, case_id)
    created = _send(command_client, _path(case_id), writer, {**ROUTE, "model": None})
    assert created.status_code == 201, created.text
    assert price_of(conn, UUID(created.json()["run_id"])) is None
    conn.rollback()
    named = _send(
        command_client, _path(case_id), writer, {**ROUTE, "model": "gpt-6-luna"}
    )
    assert _outcome(named) == "400 PROVIDER_NOT_CONFIGURED"
