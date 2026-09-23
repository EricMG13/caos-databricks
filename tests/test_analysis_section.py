"""The Analysis section read (Phase 4 Task 4.1, slice 4.1e).

Every accepted handoff of the displayed run, in route order, read through
`accepted_handoff` -- the record bound to its Markdown and to the identity the
store rebuilds, no re-anchoring (§42.4) -- and labelled per §46.3: host-verified
source facts, model-authored analysis, and no host calculation. Unaccepted
nodes make the document partial. The case is the authorisation resource; a
run of another case is the same `RUN_NOT_FOUND` as an unknown one.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CATALOG
from conftest import priced
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from lite_route_fixtures import RealisticLiteCompletions
from test_canonical_execution import harness, route
from test_execution_freshness import _Harness
from test_loop_charges import ESTIMATE

from caos.api import app as app_module
from caos.api.app import app, blob_store, methodology_bundle, store_connection
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED
from caos.api.reads import analysis as analysis_read
from caos.api.wire import CLEARS, AnalysisDocument
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph.route import RouteExtensions, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.methodology.runner import ModuleProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run

__all__ = ["harness", "route"]


@pytest.fixture
def client(
    harness: _Harness, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    # Tokenless, so no groups header is read: the development switch is how a
    # test here asserts a global role above the floor.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    app.dependency_overrides[store_connection] = lambda: harness.conn
    app.dependency_overrides[blob_store] = lambda: harness.blobs
    app.dependency_overrides[methodology_bundle] = lambda: harness.bundle
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


class _CountingConnection:
    """Counts store round trips, so the declared budget is measured."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def _serving(counter: _CountingConnection) -> Callable[[], _CountingConnection]:
    return lambda: counter


def _as(user_id: UUID, role: str | None = None) -> dict[str, str]:
    headers = {"x-caos-user": str(user_id)}
    if role is not None:
        headers[ROLE_HEADER] = role
    return headers


def _refused(code: RefusalCode) -> dict[str, str]:
    return {"code": code.value, "clears": CLEARS[code]}


def _analysis(case_id: object, run: object | None = None) -> str:
    path = f"/api/v1/cases/{case_id}/analysis"
    return path if run is None else f"{path}?run={run}"


def _run(
    harness: _Harness, qa_by_module: dict[str, str] | None = None
) -> RealisticLiteCompletions:
    completions = RealisticLiteCompletions(
        harness.source_id, qa_by_module=qa_by_module or {}
    )
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
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
    harness.conn.rollback()
    return completions


def _reader(harness: _Harness) -> UUID:
    user = uuid4()
    grant(harness.conn, case_id=harness.case_id, user_id=user, standing=Standing.READER)
    harness.conn.commit()
    return user


def _document(client: TestClient, harness: _Harness, path: str) -> AnalysisDocument:
    response = client.get(path, headers=_as(_reader(harness)))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    return AnalysisDocument.model_validate(response.json())


def test_analysis_labels_source_facts_model_analysis_and_no_host_calculation(
    client: TestClient, harness: _Harness
) -> None:
    completions = _run(harness)

    document = _document(client, harness, _analysis(harness.case_id))

    body = document.body
    assert (document.status, document.notes, document.observed_empty) == (
        "complete",
        [],
        False,
    )
    assert body.case_id == harness.case_id
    assert body.latest_run_id == body.displayed_run_id == harness.run_id
    assert body.subject is not None
    assert body.subject.issuer_name
    assert body.pending == []
    assert [h.route_node_id for h in body.handoffs] == [
        n.route_node_id for n in harness.route.nodes
    ]
    rows = {
        str(node): (str(artifact), str(record), created)
        for node, artifact, record, created in harness.conn.execute(
            "SELECT route_node_id, artifact_sha256, record_sha256, created_at"
            " FROM artifacts WHERE run_id = %s",
            (harness.run_id,),
        ).fetchall()
    }
    harness.conn.rollback()
    for handoff, answer in zip(body.handoffs, completions.answers, strict=True):
        artifact, record, created = rows[handoff.route_node_id]
        assert (handoff.artifact_sha256, handoff.record_sha256) == (artifact, record)
        assert handoff.accepted_at == created
        assert handoff.host_calculation == "NONE"
        # The exact Markdown the model wrote, decoded, not rendered or trimmed.
        assert handoff.model_analysis == answer.decode("utf-8")
        assert handoff.model_analysis.encode() == harness.blobs.get(artifact)
        [fact] = handoff.source_facts
        assert fact.filename == "report.txt"
        # The pinned live source the page endpoint is addressed by (4.4a).
        assert fact.source_id == harness.source_id
        assert fact.page == 1
        assert fact.matched_text == completions.quotes[0]
        assert fact.withdrawn_at is None
        assert fact.rects and all(r.x1 > r.x0 for r in fact.rects)


def test_restricted_limitations_and_screening_scope_reach_the_wire(
    client: TestClient, harness: _Harness
) -> None:
    _run(harness, qa_by_module={"CP-L10": "Restricted"})

    document = _document(client, harness, _analysis(harness.case_id))

    by_module = {h.module_id: h for h in document.body.handoffs}
    restricted = by_module["CP-L10"]
    assert restricted.qa_status == "Restricted"
    assert "Only one source report was delivered" in restricted.limitation_flags
    assert by_module["CP-5"].qa_status == "Passed"
    for handoff in by_module.values():
        # Every LITE handoff is a screen, whatever committee status it wrote.
        assert (handoff.decision_scope, handoff.screening_only) == (
            "SCREENING_ONLY",
            True,
        )


def test_withdrawal_of_a_cited_source_is_read_live(
    client: TestClient, harness: _Harness
) -> None:
    _run(harness)
    withdraw_source(
        harness.conn,
        case_id=harness.case_id,
        source_id=harness.source_id,
        actor_id=harness.approver,
    )
    harness.conn.commit()

    document = _document(client, harness, _analysis(harness.case_id))

    for handoff in document.body.handoffs:
        assert all(f.withdrawn_at is not None for f in handoff.source_facts)


def test_a_record_that_no_longer_binds_its_markdown_refuses_artifact_record_mismatch(
    client: TestClient, harness: _Harness
) -> None:
    _run(harness)
    last = harness.route.nodes[-1].route_node_id
    [[record_sha]] = harness.conn.execute(
        "SELECT record_sha256 FROM artifacts WHERE run_id = %s AND route_node_id = %s",
        (harness.run_id, last),
    ).fetchall()
    record = _decoded_record(harness.blobs.get(str(record_sha)))
    moved = replace(
        record,
        projections=replace(
            record.projections,
            confidence_score=record.projections.confidence_score - 1,
        ),
    )
    harness.conn.execute(
        "UPDATE artifacts SET record_sha256 = %s WHERE run_id = %s"
        " AND route_node_id = %s",
        (harness.blobs.put(record_bytes(moved)), harness.run_id, last),
    )
    harness.conn.commit()

    response = client.get(_analysis(harness.case_id), headers=_as(_reader(harness)))
    harness.conn.rollback()

    # 500 under the owner's D3 split: a record that no longer binds its
    # projections binds them no better on the next request.
    assert (response.status_code, response.json()) == (
        500,
        _refused(RefusalCode.ARTIFACT_RECORD_MISMATCH),
    )


def test_unaccepted_nodes_make_analysis_partial_with_a_note(
    client: TestClient, harness: _Harness
) -> None:
    _run(harness, qa_by_module={"CP-L10": "Blocked"})
    reader = _reader(harness)
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = _serving(counter)

    response = client.get(_analysis(harness.case_id), headers=_as(reader))
    harness.conn.rollback()

    assert response.status_code == 200
    document = AnalysisDocument.model_validate(response.json())
    # The budget is linear in accepted handoffs: one here.
    assert counter.executed == analysis_read.FIXED_IO + analysis_read.PER_HANDOFF_IO

    assert document.status == "partial"
    assert [note.value for note in document.notes] == ["HANDOFFS_PENDING"]
    assert document.observed_empty is False
    assert [h.module_id for h in document.body.handoffs] == ["CP-0"]
    pending = [(p.module_id, p.state.value) for p in document.body.pending]
    assert [module for module, _state in pending] == ["CP-L10", "CP-5"]
    assert all(state != "COMPLETE" for _module, state in pending)


def test_the_analysis_document_names_the_node_whose_verdict_ended_the_run(
    client: TestClient, harness: _Harness
) -> None:
    """A BLOCKED run's pending list holds the node that *did* run.

    `pending` is recomputed from accepted artifacts, and a validated `Blocked`
    verdict accepts nothing -- so the node that answered and ended the run sits
    in the same list as the two that never started. The run document has named
    it since 4.1i; without the same field here a reader of this page is told
    only that three nodes have no handoff.
    """
    _run(harness, qa_by_module={"CP-L10": "Blocked"})
    blocking = harness.conn.execute(
        "SELECT v.attempt_id, a.route_node_id FROM run_blocking_verdicts v"
        " JOIN run_attempts a USING (attempt_id) WHERE v.run_id = %s",
        (harness.run_id,),
    ).fetchone()
    harness.conn.rollback()
    assert blocking is not None, "the fixture run ended on a validated verdict"

    document = _document(client, harness, _analysis(harness.case_id))

    body = document.body
    assert body.displayed_run_status == "BLOCKED"
    assert body.blocked_by is not None
    assert body.blocked_by.module_id == "CP-L10"
    assert body.blocked_by.route_node_id == str(blocking[1])
    assert body.blocked_by.attempt_id == UUID(str(blocking[0]))
    # The node it names is one of the nodes with no handoff, which is what lets
    # a reader tell the one that answered from the two that never ran.
    assert body.blocked_by.route_node_id in {p.route_node_id for p in body.pending}


def test_a_run_that_is_not_blocked_names_no_blocking_node(
    client: TestClient, harness: _Harness
) -> None:
    """The wire never claims a blocking node that does not exist."""
    _run(harness)

    body = _document(client, harness, _analysis(harness.case_id)).body

    assert body.displayed_run_status == "COMPLETE"
    assert body.blocked_by is None


def test_run_and_analysis_name_displayed_and_latest_runs_separately(
    client: TestClient, harness: _Harness
) -> None:
    _run(harness)
    latest = start_run(harness.conn, harness.case_id)
    harness.conn.commit()

    shown = _document(client, harness, _analysis(harness.case_id, harness.run_id))
    assert (shown.body.latest_run_id, shown.body.displayed_run_id) == (
        latest,
        harness.run_id,
    )
    assert len(shown.body.handoffs) == 3
    assert shown.status == "complete"

    unpinned = _document(client, harness, _analysis(harness.case_id))
    assert (unpinned.body.latest_run_id, unpinned.body.displayed_run_id) == (
        latest,
        latest,
    )
    assert (unpinned.body.subject, unpinned.body.handoffs) == (None, [])
    assert unpinned.body.pending == []
    assert unpinned.status == "partial"
    assert [note.value for note in unpinned.notes] == ["ROUTE_NOT_PINNED"]


def test_a_case_without_a_run_is_observed_empty(
    client: TestClient, harness: _Harness
) -> None:
    empty = create_case(harness.conn, BoundaryText.of("No runs yet"))
    reader = uuid4()
    grant(harness.conn, case_id=empty, user_id=reader, standing=Standing.READER)
    harness.conn.commit()

    response = client.get(_analysis(empty), headers=_as(reader))
    harness.conn.rollback()

    document = AnalysisDocument.model_validate(response.json())
    assert (document.observed_empty, document.status, document.notes) == (
        True,
        "complete",
        [],
    )
    body = document.body
    assert [body.latest_run_id, body.displayed_run_id, body.subject] == [None] * 3


def test_a_run_of_another_case_unknown_or_malformed_is_run_not_found(
    client: TestClient, harness: _Harness
) -> None:
    other = create_case(harness.conn, BoundaryText.of("Another case"))
    foreign = start_run(harness.conn, other)
    harness.conn.commit()
    reader = _reader(harness)

    for run in (foreign, uuid4(), "not-a-run"):
        response = client.get(_analysis(harness.case_id, run), headers=_as(reader))
        harness.conn.rollback()
        assert (response.status_code, response.json()) == (
            404,
            _refused(RefusalCode.RUN_NOT_FOUND),
        ), run


def test_analysis_private_404_and_actor_matrix(
    client: TestClient, harness: _Harness
) -> None:
    conn, case_id = harness.conn, harness.case_id
    members = {s: uuid4() for s in (Standing.READER, Standing.WRITER)}
    for standing, user in members.items():
        grant(conn, case_id=case_id, user_id=user, standing=standing)
    revoked = uuid4()
    grant(conn, case_id=case_id, user_id=revoked, standing=Standing.WRITER)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()

    anonymous = client.get(_analysis(case_id))
    assert (anonymous.status_code, anonymous.json()) == (
        401,
        _refused(RefusalCode.NOT_AUTHENTICATED),
    )
    allowed = (*members.items(), (Standing.APPROVER, harness.approver))
    for standing, user in allowed:
        response = client.get(_analysis(case_id), headers=_as(user))
        conn.rollback()
        assert response.status_code == 200, standing
        served = AnalysisDocument.model_validate(response.json()).chrome.served_role
        assert served.standing is standing

    refused = [
        (uuid4(), None, case_id),
        (revoked, None, case_id),
        (uuid4(), "ADMIN", case_id),
        (members[Standing.READER], None, uuid4()),
        (members[Standing.READER], None, "not-a-case"),
    ]
    for user, role, path_case in refused:
        response = client.get(_analysis(path_case), headers=_as(user, role))
        conn.rollback()
        assert (response.status_code, response.json()) == (
            404,
            _refused(RefusalCode.CASE_NOT_FOUND),
        ), (user, role, path_case)


def test_an_anonymous_or_malformed_analysis_request_opens_no_store_connection(
    client: TestClient, harness: _Harness
) -> None:
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append("store")
        return harness.conn

    app.dependency_overrides[store_connection] = counted

    assert client.get(_analysis(harness.case_id)).status_code == 401
    for path in (_analysis("not-a-case"), _analysis(harness.case_id, "not-a-run")):
        assert client.get(path, headers=_as(uuid4())).status_code == 404
    assert opened == []


def test_the_analysis_request_path_declares_its_store_budget(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linear in accepted handoffs, store and blobs alike, and declared for the
    longest route a run can pin (ED-7): the budget once declared was this
    three-node route's cost, and a ten-node route paid four times it. The
    blobs are counted as downloads: the request's store remembers each blob
    it verified, and the lineage and record readers asked for the same
    record up to sixteen times."""
    _run(harness)
    reader = _reader(harness)
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = _serving(counter)
    downloads = _downloads(monkeypatch)

    response = client.get(_analysis(harness.case_id), headers=_as(reader))
    harness.conn.rollback()

    assert response.status_code == 200
    assert len(AnalysisDocument.model_validate(response.json()).body.handoffs) == 3
    per_handoff = analysis_read.PER_HANDOFF_IO
    assert counter.executed == analysis_read.FIXED_IO + 3 * per_handoff
    assert len(downloads) == len(set(downloads)) == 3 * analysis_read.PER_HANDOFF_BLOBS
    longest = max(
        len(resolve_route(CATALOG, profile, pathway, extensions=extensions).nodes)
        for profile, pathways in _pathways()
        for pathway in pathways
        for extensions in (None, RouteExtensions(model_extension=True))
        if _resolves(profile, pathway, extensions)
    )
    assert longest == analysis_read.LONGEST_ROUTE_NODES
    assert analysis_read.IO_BUDGET == (
        analysis_read.FIXED_IO + longest * per_handoff + analysis_read.MODEL_PROOFS_IO
    )
    assert analysis_read.BLOB_BUDGET == longest * analysis_read.PER_HANDOFF_BLOBS


def _downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every blob a request's store downloads: a `get` its memo cannot answer."""
    downloaded: list[str] = []
    real_get = BlobStore.get

    def counted(store: BlobStore, digest: str) -> bytes:
        if store.verified is None or digest not in store.verified:
            downloaded.append(digest)
        return real_get(store, digest)

    monkeypatch.setattr(BlobStore, "get", counted)
    return downloaded


def _pathways() -> list[tuple[str, list[str]]]:
    return [
        (profile, list(declared["pathways"]))
        for profile, declared in CATALOG["profiles"].items()
    ]


def _resolves(profile: str, pathway: str, extensions: RouteExtensions | None) -> bool:
    try:
        resolve_route(CATALOG, profile, pathway, extensions=extensions)
    except Refusal:
        return False
    return True


def test_the_analysis_route_is_read_analysis() -> None:
    """`read_analysis` serves the path.

    Dependency order and identity -- `actor_from_request`, `case_path`,
    `run_query`, then `store_connection`, `blob_store` and
    `methodology_bundle` from `caos.api.deps` -- is
    `tests/test_api_routes.py`'s
    `test_every_section_read_depends_on_the_shared_dependencies`.
    """
    [served] = [
        route for route in analysis_read.router.routes if isinstance(route, APIRoute)
    ]
    assert served.path == "/api/v1/cases/{case_id}/analysis"
    assert served.endpoint is analysis_read.read_analysis
