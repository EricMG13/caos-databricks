"""Why a billed answer was not accepted, written once (Task 4.3 slice d, D7).

`record_refusal` explains a recorded call's answer so a retry never replays a
known refusal. It writes only for an attempt with a call outcome, only once,
and never for a code that describes the store, the run or its fence.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import psycopg
import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from test_accepted_owner import _billed
from test_execution_freshness import _Harness, harness

from caos.graph.route import ResolvedRoute, resolve_route
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, outcomes
from caos.store.outcomes import record_refusal
from caos.store.runs import start_attempt

__all__ = ["harness"]


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)


def _refusals(harness: _Harness) -> list[tuple[object, str]]:
    return harness.conn.execute(
        "SELECT attempt_id, code FROM attempt_refusals ORDER BY recorded_at"
    ).fetchall()


def test_a_billed_answer_is_explained_once(harness: _Harness) -> None:
    attempt = _billed(harness)

    assert record_refusal(
        harness.conn, attempt_id=attempt, code=RefusalCode.CITATION_NOT_LOCATED
    )
    assert not record_refusal(
        harness.conn, attempt_id=attempt, code=RefusalCode.HANDOFF_MALFORMED
    )
    assert _refusals(harness) == [(attempt, "CITATION_NOT_LOCATED")]


def test_a_store_or_run_code_is_never_an_explanation(harness: _Harness) -> None:
    attempt = _billed(harness)

    for code in (
        RefusalCode.STORE_UNAVAILABLE,
        RefusalCode.LEASE_NOT_HELD,
        RefusalCode.RUN_NOT_RUNNING,
        RefusalCode.HANDOFF_BLOCKED,
    ):
        assert not record_refusal(harness.conn, attempt_id=attempt, code=code)
    assert _refusals(harness) == []


def test_an_attempt_without_a_recorded_call_is_not_explained(
    harness: _Harness,
) -> None:
    node = harness.route.nodes[0].route_node_id
    attempt = start_attempt(harness.conn, harness.run_id, node)

    assert not record_refusal(
        harness.conn, attempt_id=attempt, code=RefusalCode.CITATION_NOT_LOCATED
    )
    assert _refusals(harness) == []


def test_a_code_that_is_not_a_refusal_code_is_refused_before_the_store() -> None:
    """The explanation is a typed code, never a caller's string: refused before
    a connection is touched, which is why this one needs no harness."""
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_INVALID$"):
        record_refusal(
            cast("StoreConnection", None),
            attempt_id=uuid4(),
            code=cast("RefusalCode", "CITATION_NOT_LOCATED"),
        )


def test_a_store_fault_leaves_no_transaction_and_types_the_refusal(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault under the lock is a typed store refusal with nothing written, and
    the connection is not left holding the caller's transaction open."""
    attempt = _billed(harness)

    def broken(conn: object, attempt_id: object) -> tuple[object, ...]:
        raise psycopg.OperationalError("synthetic")

    monkeypatch.setattr(outcomes, "_locked_attempt", broken)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        record_refusal(
            harness.conn, attempt_id=attempt, code=RefusalCode.CITATION_NOT_LOCATED
        )
    monkeypatch.undo()
    assert _refusals(harness) == []


def test_a_refusal_under_the_lock_travels_out_with_its_own_code(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything that is not a store fault keeps its own code — the cleanup arm
    rolls back and re-raises rather than retyping what it did not cause."""
    attempt = _billed(harness)

    def broken(conn: object, attempt_id: object) -> tuple[object, ...]:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)

    monkeypatch.setattr(outcomes, "_locked_attempt", broken)
    with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
        record_refusal(
            harness.conn, attempt_id=attempt, code=RefusalCode.CITATION_NOT_LOCATED
        )
    monkeypatch.undo()
    assert _refusals(harness) == []
