"""The one added pathway completes/proves/freezes or blocks without more calls."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from canonical_route_fixtures import (
    LIMITATION,
    MODULES,
    PACK,
    ROUTE,
    SELECTION,
    RouteCompletions,
)
from conftest import _url_for, priced
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import canonical_payload
from caos.deliverable.render import render
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.provider import MAX_REQUEST_BYTES, Completion
from caos.qualification.proof import assert_orchestration_proof
from caos.store import StoreConnection
from caos.store.gates import Gate, approve_gate
from caos.store.members import Standing, grant
from caos.store.routes import pin_route
from caos.store.run_inputs import RunSubject, pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    return resolve_route(CATALOG, *getattr(request, "param", SELECTION))


@pytest.fixture
def harness(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    [source] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("issuer-pack.txt"), data=PACK)],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    source_set = snapshot_source_set(conn, case_id)
    pin_route(conn, run_id, route)
    pin_run_input(
        conn,
        run_id,
        source_set.version,
        BUNDLE,
        subject=RunSubject("ACME", "Acme Holdings plc", "FY2025", "2026-09-08"),
    )
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, run_id, approver, gate))
    return _Harness(
        conn,
        case_id,
        run_id,
        source,
        source,
        blobs,
        route,
        BUNDLE,
        approver,
        _url_for(conn.info.dbname),
    )


def run_completed(
    harness: _Harness, answers: RouteCompletions | None = None
) -> RouteCompletions:
    answers = answers or RouteCompletions(harness.source_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )
    assert _status(harness) == "COMPLETE"
    assert [fields_from_prompt(p)["module_id"] for p in answers.prompts] == list(
        MODULES
    )
    return answers


def test_relative_value_route_completes_proves_and_freezes(harness: _Harness) -> None:
    import hashlib
    from dataclasses import replace
    from uuid import uuid4

    from caos.boundary_text import BoundaryText
    from caos.deliverable.canonical import (
        freeze_canonical,
        payload_bytes,
        verify_frozen,
    )
    from caos.deliverable.filing import sign_opinion
    from caos.deliverable.revisions import read_revision, save_revision
    from caos.store.members import Standing, grant

    answers = run_completed(harness)
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == proof.citations == 9
    assert {m for m, _, _ in proof.anchored} == set(MODULES)
    saved = save_revision(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    revision = replace(_revision(harness), revision_id=BoundaryText.of(str(saved)))
    payload = read_revision(
        harness.conn, harness.blobs, case_id=harness.case_id, revision_id=saved
    )
    harness.conn.rollback()
    assert [a["route_node_id"] for a in payload["artifacts"]] == [
        n.route_node_id for n in ROUTE.nodes
    ]
    data = payload_bytes(payload)
    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=harness.approver,
        revision_id=saved,
    )
    freezer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=freezer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    assert (
        freeze_canonical(
            harness.conn, harness.blobs, BUNDLE, revision, actor_id=freezer
        )
        == hashlib.sha256(data).hexdigest()
    )
    verify_frozen(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )
    cp3 = fields_from_prompt(answers.prompts[-1])
    assert {r["module_id"] for r in cp3["upstream_artifacts_used"]} == {
        e.source for e in ROUTE.edges if e.target == "CP-3"
    }


def test_relative_value_requests_fit_the_request_ceiling(harness: _Harness) -> None:
    answers = run_completed(harness)
    assert len(answers.prompts) == 9
    assert all(
        len(answers.request_bytes(p, json_object=True)) <= MAX_REQUEST_BYTES
        for p in answers.prompts
    )


def test_a_blocked_cp1_holds_every_dependent_and_calls_nothing_after(
    harness: _Harness,
) -> None:
    answers = RouteCompletions(harness.source_id, qa_by_module={"CP-1": "Blocked"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert [fields_from_prompt(p)["module_id"] for p in answers.prompts] == [
        "CP-0",
        "CP-1",
    ]
    assert _status(harness) == "BLOCKED"
    assert _events(harness, "RUN_BLOCKED") == 1
    assert _events(harness, "RUN_COMPLETE") == 0
    assert _counts(harness) == (2, [answers.charge] * 2, 1, 2, 2)


def test_a_restricted_owner_keeps_its_limitations_downstream(harness: _Harness) -> None:
    answers = run_completed(
        harness,
        RouteCompletions(harness.source_id, qa_by_module={"CP-1": "Restricted"}),
    )
    assert LIMITATION in answers.prompts[-1]
    payload = canonical_payload(harness.conn, harness.blobs, BUNDLE, _revision(harness))
    assert LIMITATION in render(payload).decode()


def test_missing_optional_peer_input_restricts_cp3_but_does_not_complete_the_route(
    harness: _Harness,
) -> None:
    from caos.graph.route import NodeState, node_states
    from caos.graph.runtime import accepted_artifacts

    answers = RouteCompletions(harness.source_id, readiness={"CP-1C": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "BLOCKED"
    called = [fields_from_prompt(p) for p in answers.prompts]
    assert "CP-1C" not in {p["module_id"] for p in called}
    cp3 = next(p for p in called if p["module_id"] == "CP-3")
    assert "CP-1C" not in {r["module_id"] for r in cp3["upstream_artifacts_used"]}
    accepted = accepted_artifacts(
        harness.conn, harness.blobs, ROUTE, harness.run_id, bundle=BUNDLE
    )
    before_cp3 = {
        n: r for n, r in accepted.items() if n != ROUTE.nodes[-1].route_node_id
    }
    assert (
        node_states(ROUTE, before_cp3)[ROUTE.nodes[-1].route_node_id]
        is NodeState.RESTRICTED
    )
    harness.conn.rollback()


CATALOG_ROUTES = frozenset(
    (profile, selection)
    for profile, declared in CATALOG["profiles"].items()
    for selection in declared["pathways"]
)
# The exact enabled set, asserted here and in each pathway's own contract test.
ENABLED = frozenset(
    {
        SELECTION,
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_DECISION_LEDGER"),
        ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "LIQUIDITY_REVIEW"),
        ("FULL_CREDIT_32", "EARNINGS_UPDATE"),
        ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
        ("FULL_CREDIT_32", "DECISION_LEDGER"),
        ("FULL_CREDIT_32", "COVENANT_REFINANCING"),
        ("FULL_CREDIT_32", "PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "MARKET_DISLOCATION"),
        ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING"),
        ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING"),
        ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN"),
        ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING"),
    }
)


def test_all_catalog_routes_are_enabled() -> None:
    assert ADAPTER_ROUTES == ENABLED == CATALOG_ROUTES
    assert len(ADAPTER_ROUTES) == 18


def test_without_a_per_node_factory_the_pass_is_exactly_sequential(
    harness: _Harness,
) -> None:
    """The default, and every caller that is not the worker: the harness and
    the suite drive a run on a connection they own and hold open around it, so
    the loop must not open a second one behind their back. Without this the
    test above would pass against a loop that was concurrent unconditionally,
    which is a different and much riskier change."""
    from threading import Lock
    from time import monotonic, sleep

    spans: list[tuple[float, float]] = []
    guard = Lock()
    answers = RouteCompletions(harness.source_id)
    inner = answers.complete

    def timed(prompt: str, *, json_object: bool = False) -> Completion:
        began = monotonic()
        sleep(0.05)
        answer = inner(prompt, json_object=json_object)
        with guard:
            spans.append((began, monotonic()))
        return answer

    answers.complete = timed  # type: ignore[method-assign]

    _run_route(harness, _module_provider(harness, answers))

    assert _status(harness) == "COMPLETE"
    assert not [
        (one, two)
        for index, one in enumerate(spans)
        for two in spans[index + 1 :]
        if one[0] < two[1] and two[0] < one[1]
    ], "a caller that supplied no factory had its run made concurrent anyway"
