"""Every run pins the one canonical adapter, and acceptance always carries the
host record (Task 3.1 slices c-2 and f-1c; §42.1). Disabled routes are
`tests/test_disabled_routes.py`."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from conftest import tamper
from test_accepted_owner import _billed, _count
from test_execution_freshness import _Harness, harness
from test_loop_charges import MODEL, REPORTED, VENDORED
from test_run_inputs import SUBJECT, _prepare

import caos.store as store
from caos import methodology
from caos.boundary_text import BoundaryText
from caos.graph.route import ResolvedRoute, resolve_route
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.events import events_of
from caos.store.gates import execution_input
from caos.store.routes import pin_route
from caos.store.run_inputs import load_run_input, pin_run_input
from caos.store.runs import Accepted, accept_attempt, create_case, start_run

__all__ = ["harness"]

CATALOG = json.loads(
    (
        VENDORED
        / "skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
    ).read_text(encoding="utf-8")
)
CANONICAL = ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    return resolve_route(CATALOG, *getattr(request, "param", CANONICAL))


def _accepted(harness: _Harness, attempt: UUID, record: str | None) -> Accepted:
    return Accepted(
        harness.blobs.put(b"artifact"),
        REPORTED,
        MODEL,
        f"g{attempt.hex}",
        record_sha256=record,
    )


def test_a_canonical_route_pins_the_canonical_adapter_and_requires_a_subject(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    _run, source, bundle, _claims = _prepare(conn, case_id, tmp_path)
    lite = start_run(conn, case_id)
    pin_route(conn, lite, resolve_route(CATALOG, *CANONICAL))
    conn.commit()
    before = events_of(conn, lite)
    with pytest.raises(Refusal) as refused:
        pin_run_input(conn, lite, source.version, bundle)
    assert refused.value.code is RefusalCode.RUN_INPUT_INVALID
    assert load_run_input(conn, lite) is None and events_of(conn, lite) == before
    pin = pin_run_input(conn, lite, source.version, bundle, subject=SUBJECT)
    assert pin.adapter_version == "canonical-markdown-v3"
    assert load_run_input(conn, lite) == pin


def test_a_canonical_pin_passes_execution_input(harness: _Harness) -> None:
    pin, route = execution_input(harness.conn, harness.run_id, harness.bundle)
    harness.conn.rollback()
    assert pin.adapter_version == methodology.CANONICAL_ADAPTER_VERSION
    assert route == harness.route


def _refused(harness: _Harness, attempt: UUID, record: str | None) -> object:
    try:
        return accept_attempt(
            harness.conn,
            attempt_id=attempt,
            accepted=_accepted(harness, attempt, record),
        )
    except Refusal as refusal:
        assert refusal.__cause__ is None
        return refusal.code


def test_acceptance_without_a_record_refuses(harness: _Harness) -> None:
    attempt = _billed(harness)
    before = events_of(harness.conn, harness.run_id)
    assert _refused(harness, attempt, None) is RefusalCode.ARTIFACT_RECORD_MISMATCH
    assert events_of(harness.conn, harness.run_id) == before
    assert _count(harness, "artifacts") == 0
    # The bill committed first survives; only the analysis was refused.
    assert _count(harness, "budget_ledger") == 1


def test_a_replay_with_another_record_is_refused(harness: _Harness) -> None:
    attempt = _billed(harness)
    assert _refused(harness, attempt, "E" * 64) is RefusalCode.BLOB_ADDRESS_INVALID
    assert _refused(harness, attempt, "e" * 64) is True
    stored = harness.conn.execute(
        "SELECT record_sha256 FROM artifacts WHERE attempt_id = %s", (attempt,)
    ).fetchone()
    harness.conn.rollback()
    assert stored == ("e" * 64,)
    assert _refused(harness, attempt, "e" * 64) is False
    assert _refused(harness, attempt, "f" * 64) is RefusalCode.CALL_OUTCOME_CONFLICT
    assert _refused(harness, attempt, None) is RefusalCode.CALL_OUTCOME_CONFLICT
    assert _count(harness, "artifacts") == 1


def test_version_twelve_adds_an_empty_record_column(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:11])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("before records"))
        run = start_run(conn, case_id)
        conn.commit()
        attempt = conn.execute(
            "INSERT INTO run_attempts (attempt_id, run_id, route_node_id, ordinal)"
            " VALUES (gen_random_uuid(), %s, 'RN-1', 1) RETURNING attempt_id",
            (run,),
        ).fetchone()
        assert attempt is not None
        conn.execute(
            "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
            " model, generation_id) VALUES (%s, %s, %s, %s, 'm', 'g')",
            (attempt[0], "a" * 64, run, case_id),
        )
        conn.commit()
        apply_schema(conn)
        assert conn.execute(
            "SELECT artifact_sha256, record_sha256 FROM artifacts"
        ).fetchall() == [("a" * 64, None)]
        with pytest.raises(psycopg.errors.CheckViolation):
            tamper(conn, "UPDATE artifacts SET record_sha256 = 'E' || repeat('e', 63)")
        conn.rollback()
