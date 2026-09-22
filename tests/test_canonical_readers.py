"""Canonical runs read back by the API and the harness (Task 3.1 slice d-1).

The route engine reads typed `NodeResult`s, and both readers now hand
`accepted_artifacts` the bundle, so a LITE run's gate verdicts and QA status
come from its records (§42.4) rather than refusing -- or, in the harness,
falling back to presence, which would read a gate-BLOCKED module as RUNNABLE.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import priced
from fastapi.testclient import TestClient
from test_api_routes import _CountingConnection, _section, _serve, _view
from test_canonical_execution import harness, route
from test_execution_freshness import _Harness
from test_loop_charges import ESTIMATE

from caos.api import app as app_module
from caos.api.app import VENDORED_BUNDLE, app, methodology_bundle, store_connection
from caos.api.reads.run import (
    CANONICAL_READINESS_IO,
    IO_BUDGET,
    READINESS_ROWS,
    SECTION_READ_IO,
)
from caos.graph.route import GATE_MODULE, EdgeType, NodeState
from caos.graph.runtime import Execution, run_route
from caos.methodology.canonical import accepted_handoff
from caos.methodology.runner import ModuleProvider
from caos.methodology.verification import AcceptedRow
from caos.qualification.harness import _unrun
from caos.store.members import Standing, grant
from caos.store.outcomes import accepted_rows, execution_reads

__all__ = ["harness", "route"]


def _run(harness: _Harness, answers: CanonicalCompletions) -> None:
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        answers,
        harness.route,
        harness.run_id,
    )
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(provider, priced(ESTIMATE), harness.bundle),
    )


@pytest.fixture
def client(
    harness: _Harness, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    _serve(harness.conn, harness.blobs, harness.bundle)
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


def _reader(harness: _Harness) -> UUID:
    viewer = uuid4()
    grant(
        harness.conn, case_id=harness.case_id, user_id=viewer, standing=Standing.READER
    )
    harness.conn.commit()
    return viewer


def test_the_run_document_reads_a_completed_lite_run_from_its_records(
    harness: _Harness, client: TestClient
) -> None:
    _run(harness, CanonicalCompletions(harness.source_id))
    viewer = _reader(harness)
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = lambda: counter

    body = _view(_section(client, harness.case_id, harness.run_id, viewer))

    assert body["status"] == "COMPLETE"
    by_module = {node["module_id"]: node for node in body["nodes"]}
    assert sorted(by_module) == ["CP-0", "CP-5", "CP-L10"]
    assert {m: n["state"] for m, n in by_module.items()} == dict.fromkeys(
        by_module, "COMPLETE"
    )
    assert {m: n["gate_verdict"] for m, n in by_module.items()} == {
        "CP-0": None,
        "CP-5": "READY",
        "CP-L10": "READY",
    }
    # Measured: one identity rebuild per canonical readiness row, within budget.
    qa_sources = {e.source for e in harness.route.edges if e.type is EdgeType.QA_GATE}
    rows = sum(
        n.module_id == GATE_MODULE or n.module_id in qa_sources
        for n in harness.route.nodes
    )
    assert 1 <= rows <= READINESS_ROWS
    assert counter.executed == SECTION_READ_IO + rows * CANONICAL_READINESS_IO
    assert counter.executed <= IO_BUDGET


def test_a_gate_blocked_module_reads_as_blocked_by_its_verdict(
    harness: _Harness, client: TestClient
) -> None:
    _run(
        harness,
        CanonicalCompletions(harness.source_id, readiness={"CP-L10": "BLOCKED"}),
    )
    viewer = _reader(harness)

    body = _view(_section(client, harness.case_id, harness.run_id, viewer))

    assert body["status"] == "BLOCKED"
    by_module = {node["module_id"]: node for node in body["nodes"]}
    assert (
        by_module["CP-L10"]["state"],
        by_module["CP-L10"]["waiting_on"],
        by_module["CP-L10"]["gate_verdict"],
    ) == ("BLOCKED", [], "BLOCKED")


def test_the_harness_keeps_gate_readiness_on_a_canonical_run(harness: _Harness) -> None:
    """Presence alone would leave CP-L10 RUNNABLE: its only blocking edge is
    from the accepted gate. BLOCKED is the gate's verdict, read from its record.
    CP-5 is BLOCKED beside it, unattempted: no accepted input owns a named LITE
    object (§46.1)."""
    _run(
        harness,
        CanonicalCompletions(harness.source_id, readiness={"CP-L10": "BLOCKED"}),
    )
    with execution_reads(harness.conn):
        unrun = _unrun(harness.conn, harness.blobs, harness.bundle, harness.run_id)

    screen, qa = (
        next(n for n in harness.route.nodes if n.module_id == module_id)
        for module_id in ("CP-L10", "CP-5")
    )
    assert [(u.route_node_id, u.state, u.attempts) for u in unrun] == [
        (screen.route_node_id, NodeState.BLOCKED, ()),
        (qa.route_node_id, NodeState.BLOCKED, ()),
    ]


def test_the_api_verifies_records_under_the_vendored_bundle() -> None:
    assert methodology_bundle().root == VENDORED_BUNDLE
    assert methodology_bundle() is methodology_bundle()


def test_accepted_handoff_returns_the_exact_bytes_the_record_binds(
    harness: _Harness,
) -> None:
    """The seam three readers share -- the Analysis document, the matrix and
    the forecast -- and which none of them named. `forecast.py`'s own docstring
    says "callers must first obtain the Markdown with `accepted_handoff`", and
    a sentence is not a test.

    What it returns is a *pair*, and the pair is the point: the Markdown and
    the record that binds it, verified together inside the caller's read unit.
    A reader handed the Markdown alone could not tell whether the record still
    described it, which is the whole of section 42.4.
    """
    _run(harness, CanonicalCompletions(harness.source_id))
    node = harness.route.nodes[0]

    with execution_reads(harness.conn):
        rows = {row[0]: row for row in accepted_rows(harness.conn, harness.run_id)}
        _node, attempt, artifact, record_sha = rows[node.route_node_id]
        markdown, record = accepted_handoff(
            harness.conn,
            harness.blobs,
            harness.bundle,
            harness.route,
            AcceptedRow(
                run_id=harness.run_id,
                route_node_id=node.route_node_id,
                attempt_id=attempt,
                artifact_sha256=artifact,
                record_sha256=str(record_sha),
            ),
        )

    assert markdown == harness.blobs.get(artifact)
    # The binding itself: the record names the digest of the bytes returned
    # beside it, so a reader cannot be handed one node's Markdown under
    # another node's record.
    assert record.artifact_sha256 == artifact
    assert record.adapter_version == "canonical-markdown-v3"
