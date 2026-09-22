"""The canonical adapter covers the catalog; legacy pins and records stay closed."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import (
    CATALOG,
    LITE_PROFILE,
    LITE_SELECTION,
    CanonicalCompletions,
    research_brief,
)
from conftest import priced
from fastapi.testclient import TestClient
from test_api_routes import _section
from test_canonical_readers import _reader, _run, client
from test_execution_freshness import _Harness, harness
from test_gates import _approval
from test_loop_charges import ESTIMATE, MODEL
from test_run_inputs import SUBJECT, pin_version_one
from test_source_sets import _admit

from caos import methodology
from caos.api.app import app, store_connection
from caos.api.wire import CLEARS
from caos.blobs import BlobStore
from caos.graph.route import ResolvedRoute, resolve_route
from caos.graph.runtime import (
    Execution,
    ProviderResult,
    accepted_artifacts,
    run_route,
)
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import (
    Gate,
    approve_gate,
    approved_run_input,
    execution_input,
    require_adapter_route,
)
from caos.store.members import Standing, grant
from caos.store.outcomes import execution_reads
from caos.store.routes import pin_route
from caos.store.run_inputs import pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set

__all__ = ["client", "harness"]

LITE = (LITE_PROFILE, LITE_SELECTION)
FULL = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
DEEP = ("FULL_CREDIT_32", "DEEP_RESEARCH")


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    return resolve_route(CATALOG, *getattr(request, "param", LITE))


@dataclass
class _Counting:
    """A provider that must never be asked: every call is recorded."""

    model: str = MODEL
    calls: list[str] = field(default_factory=list)

    def check_context(self, route_node_id: str, module_id: str) -> int:
        self.calls.append(module_id)
        raise AssertionError(module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        self.calls.append(module_id)
        raise AssertionError(module_id)


def _refusal(call: object) -> RefusalCode:
    assert callable(call)
    with pytest.raises(Refusal) as refused:
        call()
    assert refused.value.__cause__ is None
    return refused.value.code


def test_adapter_routes_are_exactly_the_catalog() -> None:
    catalog = frozenset(
        (profile, selection)
        for profile, declared in CATALOG["profiles"].items()
        for selection in declared["pathways"]
    )
    assert ADAPTER_ROUTES == catalog
    assert len(catalog) == 18


def test_adapter_allowlist_rejects_a_synthetic_non_catalog_route() -> None:
    mismatched = replace(
        resolve_route(CATALOG, *LITE), selection_id="NOT_A_CATALOG_PATHWAY"
    )
    with pytest.raises(Refusal) as refused:
        require_adapter_route(mismatched)
    assert refused.value.code is RefusalCode.HANDOFF_MODULE_UNSUPPORTED
    assert refused.value.__cause__ is None and refused.value.__context__ is None


def test_every_route_pins_the_one_adapter_and_a_subject(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    source = snapshot_source_set(conn, case_id)
    bundle = Bundle(Path(__file__).resolve().parents[1] / "vendor/deploy-v")
    assert not hasattr(methodology, "adapter_for")
    assert not hasattr(methodology, "CLAIMS_ADAPTER_VERSION")
    for selection in (LITE, FULL, DEEP):
        run = start_run(conn, case_id)
        pin_route(conn, run, resolve_route(CATALOG, *selection))
        conn.commit()
        assert _refusal(
            lambda run=run: pin_run_input(conn, run, source.version, bundle)
        ) is (RefusalCode.RUN_INPUT_INVALID)
        research = (
            research_brief(SUBJECT.issuer_id, SUBJECT.issuer_name)
            if selection == DEEP
            else None
        )
        pin = pin_run_input(
            conn, run, source.version, bundle, research, subject=SUBJECT
        )
        assert pin.adapter_version == methodology.CANONICAL_ADAPTER_VERSION


@pytest.mark.parametrize("selection", [LITE, DEEP])
def test_an_existing_claims_pin_refuses_execution(
    case: tuple[StoreConnection, UUID], tmp_path: Path, selection: tuple[str, str]
) -> None:
    """A version-1 `claims-json-v1` pin, fully approved, is authority no longer
    executable: the build/adapter check refuses it before any attempt."""
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    source = snapshot_source_set(conn, case_id)
    bundle = Bundle(Path(__file__).resolve().parents[1] / "vendor/deploy-v")
    route = resolve_route(CATALOG, *selection)
    run = start_run(conn, case_id)
    pin_route(conn, run, route)
    pin = pin_version_one(conn, run, source, bundle, route)
    assert pin.adapter_version == "claims-json-v1"
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, run, approver, gate))
    with execution_reads(conn):
        assert approved_run_input(conn, run) == (pin, route)
    with pytest.raises(Refusal) as refused:
        with execution_reads(conn):
            execution_input(conn, run, bundle)
    assert refused.value.code is RefusalCode.RUN_INPUT_INVALID
    provider = _Counting()
    with pytest.raises(Refusal) as ran:
        run_route(
            conn,
            BlobStore(tmp_path / "blobs"),
            run_id=run,
            route=route,
            execution=Execution(provider, priced(ESTIMATE), bundle),
        )
    assert ran.value.code is RefusalCode.RUN_INPUT_INVALID
    assert provider.calls == []
    assert conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s", (run,)
    ).fetchone() == (0,)


def _strip_record(harness: _Harness, module_id: str) -> None:
    node = next(n for n in harness.route.nodes if n.module_id == module_id)
    harness.conn.execute(
        "UPDATE artifacts SET record_sha256 = NULL WHERE run_id = %s"
        " AND route_node_id = %s",
        (harness.run_id, node.route_node_id),
    )
    harness.conn.commit()


@pytest.mark.parametrize("module_id", ["CP-0", "CP-L10"])
def test_readers_refuse_an_artifact_without_its_record(
    harness: _Harness, client: TestClient, module_id: str
) -> None:
    """No reader takes a row as a claims body: a NULL record refuses, whether
    or not the engine needs that node's readiness."""
    _run(harness, CanonicalCompletions(harness.source_id))
    viewer = _reader(harness)
    _strip_record(harness, module_id)
    args = (harness.conn, harness.blobs, harness.route, harness.run_id)
    with pytest.raises(Refusal) as runtime:
        with execution_reads(harness.conn):
            accepted_artifacts(*args, bundle=harness.bundle)
    assert runtime.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    with pytest.raises(Refusal) as proof:
        with execution_reads(harness.conn):
            assert_orchestration_proof(
                harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
            )
    assert proof.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    app.dependency_overrides[store_connection] = lambda: harness.conn
    response = _section(client, harness.case_id, harness.run_id, viewer)
    # 500 under D3: a stripped record is not restored by asking again.
    assert response.status_code == 500
    assert response.json() == {
        "code": "ARTIFACT_RECORD_MISMATCH",
        "clears": CLEARS[RefusalCode.ARTIFACT_RECORD_MISMATCH],
    }
