"""Definitions a test now names in their own module.

`scripts/check_tested.py` cleared a public definition when any test referenced
any symbol of the same name, so `cos_run_id` was cleared by `pin.cos_run_id`,
`finish` by a `finish=` keyword, `dispatch` by another module's `dispatch=`
argument and `Step` by a verification enum (DQ-11, FP-18). Resolving each
reference to `module.name` found these tested only by collision; each is
driven here through the module that defines it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from conftest import priced
from fastapi.testclient import TestClient
from test_qualification_harness import (
    ESTIMATE,
    REPORT,
    VENDORED,
    _case,
    _Completions,
    _perform,
)

from caos.api.site import SITE_ROOT_ENV, dispatch
from caos.blobs import BlobStore
from caos.graph.build import RunState, Step, _step, _terminal
from caos.graph.runtime import Execution, finish
from caos.methodology.bundle import Bundle
from caos.methodology.invocation import named_objects
from caos.methodology.runner import ModuleProvider
from caos.qualification.matrix import QualificationSet
from caos.store import RunStatus, apply_schema, connect
from caos.store.routes import resolved_route
from caos.store.run_inputs import cos_run_id
from caos.store.runs import run_status


def test_the_vendor_run_id_is_the_runs_creation_instant_in_utc() -> None:
    """`cos_run_id`: one run, one vendor id, whatever zone the instant came in."""
    run = UUID("8c0d2b7e-3f7a-4e53-9a53-2f4f4c1b7a10")
    east = datetime(2026, 9, 23, 9, 30, 5, tzinfo=timezone(timedelta(hours=9)))
    expected = f"COS-20260923T003005Z-{run.hex}"
    assert cos_run_id(run, east) == expected
    assert cos_run_id(run, east.astimezone(UTC)) == expected


def test_the_site_dispatch_sends_a_section_path_to_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dispatch`, the ASGI router `EdgeGuard` wraps: a section path is served
    from the export, an `/api` path by the app."""
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_bytes(b"<!doctype html><div id=root></div>")
    monkeypatch.setenv(SITE_ROOT_ENV, str(root))
    client = TestClient(dispatch)
    page = client.get("/directory/")
    assert page.status_code == 200
    assert page.content == b"<!doctype html><div id=root></div>"
    assert client.get("/api/not-declared").json()["code"] == "ENDPOINT_NOT_FOUND"


def test_a_graph_step_takes_the_state_and_returns_a_partial_update() -> None:
    """`Step`, LangGraph's node shape: each route node and the terminal node
    are one, and each answers with the update it contributes."""
    passed: list[str] = []

    def node_pass(route_node_id: str) -> str:
        passed.append(route_node_id)
        return "ACCEPTED"

    node: Step = _step("RN-1", node_pass)
    terminal: Step = _terminal(lambda: "COMPLETE")
    state = RunState(run_id="run")
    assert node(state) == {"passes": {"RN-1": "ACCEPTED"}}
    assert passed == ["RN-1"]
    assert terminal(state) == {"ended": "COMPLETE"}


def test_finish_over_an_ended_run_reports_the_verdict_the_store_holds(
    empty_database: str, tmp_path: Path
) -> None:
    """`finish`, the terminal decision: asked again over a run that already
    ended, it moves nothing and answers with the store's own verdict."""
    blobs = BlobStore(tmp_path / "blobs")
    bundle = Bundle(root=VENDORED)
    completions = _Completions()
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        performed = _perform(
            conn,
            blobs,
            QualificationSet(cases=(_case("finished", REPORT),)),
            completions=completions,
        )
        [record] = performed.performed
        assert record.status is RunStatus.COMPLETE
        route = resolved_route(conn, record.run_id)
        assert route is not None
        conn.rollback()
        calls = len(completions.prompts)
        execution = Execution(
            ModuleProvider(
                conn=conn,
                bundle=bundle,
                blobs=blobs,
                completions=completions,
                route=route,
                run_id=record.run_id,
            ),
            priced(ESTIMATE),
            bundle,
        )
        ended = finish(
            conn,
            blobs,
            run_id=record.run_id,
            route=route,
            execution=execution,
            named=named_objects(bundle, route),
        )
        assert ended == "COMPLETE"
        assert run_status(conn, record.run_id) is RunStatus.COMPLETE
        assert len(completions.prompts) == calls
