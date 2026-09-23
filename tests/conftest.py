"""Import paths for the test suite, and the database the store suite runs on."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest

if TYPE_CHECKING:
    from decimal import Decimal

    from caos.pricing import ModelPrice
    from caos.store import StoreConnection
    from caos.store.work import Lease

REPO = Path(__file__).resolve().parents[1]
# The gate scripts are executables, not a package; import them by path.
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

# The vendored bundle's verifier refuses a tree that carries bytecode.
sys.dont_write_bytecode = True

# The store suite needs a real PostgreSQL. Absent, it skips with its reason;
# CAOS_REQUIRE_POSTGRES=1 turns that skip into a failure, which is what CI sets,
# so that a store suite that skipped can never read as a store suite that passed
# (docs/AI_CODE_QUALITY.md section 4).
POSTGRES_URL = os.environ.get("CAOS_TEST_POSTGRES_URL")
POSTGRES_REQUIRED = os.environ.get("CAOS_REQUIRE_POSTGRES") == "1"
_UNSET = "CAOS_TEST_POSTGRES_URL is unset: no database to run the store suite against"
_LIVE_CONFIGURATION = (
    "OPENROUTER_API_KEY",
    "CAOS_MODEL_PRICE",
    "CAOS_LIVE_BUDGET_CEILING",
    "CAOS_TEST_POSTGRES_URL",
)


@contextmanager
def route_fault(conn: object) -> Iterator[None]:
    """Privileged corruption only in this suite's disposable UUID databases."""
    from typing import cast

    from caos.store import StoreConnection

    connection = cast(StoreConnection, conn)
    row = connection.execute("SELECT current_database()").fetchone()
    assert row is not None and row[0].startswith("caos_test_")
    with connection.transaction():
        connection.execute("ALTER TABLE run_routes DISABLE TRIGGER route_immutable")
        yield
        connection.execute("ALTER TABLE run_routes ENABLE TRIGGER route_immutable")


# Where a suite's `TestClient` stands (slice 4.5a1). The edge guard serves a
# tokenless process only to a loopback peer on a loopback host, and an unsafe
# `/api` call only as a same-origin fetch, so every client defaults to what the
# development browser presents. A suite proving a refusal names its own peer,
# base URL or headers, or deletes the default (`tests/test_edge.py`).
LOOPBACK_BASE_URL = "http://127.0.0.1:8000"
LOOPBACK_PEER = ("127.0.0.1", 50000)
LOOPBACK_HEADERS = {"sec-fetch-site": "same-origin"}
# The development shell exports the trust switch; a suite that needs it sets it.
_AMBIENT_IDENTITY = (
    "CAOS_EDGE_TOKEN",
    "CAOS_PUBLIC_ORIGIN",
    "CAOS_TRUST_ROLE_HEADER",
    "DATABRICKS_APP_NAME",
)


def _loopback_test_client() -> None:
    from starlette.testclient import TestClient

    original = TestClient.__init__
    if getattr(original, "loopback_default", False):
        return

    def init(
        self: TestClient,
        app: object,
        base_url: str = LOOPBACK_BASE_URL,
        *args: object,
        headers: dict[str, str] | None = None,
        client: tuple[str, int] = LOOPBACK_PEER,
        **kwargs: object,
    ) -> None:
        merged = {**LOOPBACK_HEADERS, **(headers or {})}
        original(self, app, base_url, *args, headers=merged, client=client, **kwargs)  # type: ignore[arg-type, misc]

    init.loopback_default = True  # type: ignore[attr-defined]
    TestClient.__init__ = init  # type: ignore[method-assign]


_loopback_test_client()


@pytest.fixture(autouse=True)
def _development_edge() -> Iterator[None]:
    """No suite inherits an edge token, public origin or trust switch.

    Not through `monkeypatch`: an autouse request would set that fixture up
    first and so tear it down last, leaving a suite's own patches in place
    while its database fixtures clean up.
    """
    saved = {name: os.environ.pop(name, None) for name in _AMBIENT_IDENTITY}
    from caos.api import identity

    identity._CACHE.clear()
    identity._NEGATIVE.clear()
    yield
    for name, value in saved.items():
        os.environ.pop(name, None)
        if value is not None:
            os.environ[name] = value


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live-provider", action="store_true", help="run live provider tests"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    live = [item for item in items if item.get_closest_marker("live_provider")]
    if not config.getoption("--live-provider"):
        items[:] = [item for item in items if item not in live]
        config.hook.pytest_deselected(items=live)
        return

    missing = [name for name in _LIVE_CONFIGURATION if not os.environ.get(name)]
    if live and missing:
        raise pytest.UsageError("live provider tests require: " + ", ".join(missing))


def _url_for(database: str) -> str:
    parts = urlsplit(POSTGRES_URL or "")
    return urlunsplit(parts._replace(path=f"/{database}"))


def gate_verdict(prompt: str, status: str = "READY") -> dict[str, object]:
    """The gate's readiness map when the prompt asked for one, nothing when it
    did not -- merged by a stub into the body it was already returning.

    Phase 11 refuses a gate that does not cover every other module of the pinned
    route, so four completion stubs need the same extra key; here once rather
    than as four copies of one row. Every fixture route in this suite with a gate
    is DEEP_RESEARCH -- CP-0 and CP-DR alone -- so one row covers the rest of it.
    """
    if "content_to_module_map" not in prompt:
        return {}
    return {
        "content_to_module_map": [
            {
                "module_id": "CP-DR",
                "readiness_status": status,
                "readiness_effect": "what the admitted source allows",
            }
        ]
    }


def approve_run(
    conn: object,
    *,
    case_id: UUID,
    run_id: UUID,
    route: object,
    bundle: object,
) -> UUID:
    """Pin and govern one real test run, returning its synthetic approver."""
    from canonical_fixtures import research_brief

    from caos.graph.route import ResolvedRoute
    from caos.methodology.bundle import Bundle
    from caos.store import StoreConnection
    from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
    from caos.store.members import Standing, grant
    from caos.store.routes import pin_route
    from caos.store.run_inputs import RunSubject, pin_run_input
    from caos.store.source_sets import snapshot_source_set

    connection = cast(StoreConnection, conn)
    source = snapshot_source_set(connection, case_id)
    pinned = cast(ResolvedRoute, route)
    pin_route(connection, run_id, pinned)
    # Every route pins the canonical adapter, whose handoffs name a subject.
    subject = RunSubject("EXAMPLE", "Example Holdings plc", "FY2025", "2026-09-08")
    research = (
        research_brief() if any(n.module_id == "CP-DR" for n in pinned.nodes) else None
    )
    pin_run_input(
        connection,
        run_id,
        source.version,
        cast(Bundle, bundle),
        research,
        subject=subject,
    )
    approver = uuid4()
    grant(
        connection,
        case_id=case_id,
        user_id=approver,
        standing=Standing.APPROVER,
    )
    connection.commit()
    for gate in Gate:
        preview = gate_preview(connection, run_id, gate)
        approve_gate(
            connection,
            GateApproval(
                run_id=run_id,
                gate=gate,
                actor_id=approver,
                preview_sha256=preview.preview_sha256,
                input_fingerprint=preview.input_fingerprint,
            ),
        )
    return approver


@pytest.fixture
def case(empty_database: str) -> Iterator[tuple[object, UUID]]:
    """An open case on a committed connection, with the schema applied.

    Typed loosely here so this module does not import the store at collection
    time; the suites that use it annotate the connection as `StoreConnection`.
    """
    from caos.boundary_text import BoundaryText
    from caos.store import apply_schema, connect
    from caos.store.runs import create_case

    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))
        conn.commit()
        yield conn, case_id


@pytest.fixture(scope="session")
def _migrated_template() -> Iterator[str]:
    """One database with the schema applied, cloned by every test using `case`.

    Nothing connects to it after this fixture closes its connection, which is
    what `CREATE DATABASE ... TEMPLATE` needs.
    """
    import psycopg

    from caos.store import apply_schema, connect

    assert POSTGRES_URL is not None
    name = f"caos_test_template_{uuid4().hex}"
    with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with connect(_url_for(name)) as conn:
            apply_schema(conn)
            conn.commit()
        yield name
    finally:
        with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_database(request: pytest.FixtureRequest) -> Iterator[str]:
    """A database of its own, created empty and dropped after the test.

    A namespace inside one shared database would be cheaper and would not answer
    the question these tests ask: what a process finds when it starts against a
    database no schema has been applied to yet.

    A test that uses `case` applies the schema anyway, so its database is cloned
    from a migrated template instead; `case` still runs `apply_schema`, which
    verifies the recorded migration prefix on the clone.
    """
    if POSTGRES_URL is None:
        if POSTGRES_REQUIRED:
            pytest.fail(_UNSET)
        pytest.skip(_UNSET)

    import psycopg

    template = (
        request.getfixturevalue("_migrated_template")
        if "case" in request.fixturenames
        else None
    )
    name = f"caos_test_{uuid4().hex}"
    with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
        # Both names are uuid4 hex this module minted, never caller input.
        suffix = f' TEMPLATE "{template}"' if template else ""
        admin.execute(f'CREATE DATABASE "{name}"{suffix}')
    try:
        yield _url_for(name)
    finally:
        with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def priced(estimate: Decimal, model: str = "a-model/for-the-test") -> ModelPrice:
    """A dated price whose worst case (F06) is exactly `estimate`, for `model`.

    Input is priced at zero and output at `estimate / MAX_COMPLETION_TOKENS`, which
    divides exactly because the cap is a power of two.
    """
    from datetime import date
    from decimal import Decimal

    from caos.pricing import ModelPrice
    from caos.provider import MAX_COMPLETION_TOKENS

    return ModelPrice(
        model,
        Decimal(0),
        estimate / MAX_COMPLETION_TOKENS,
        date(2026, 9, 13),
    )


@contextmanager
def recorded_statements(conn: object) -> Iterator[list[str]]:
    """Every statement `conn.execute` runs inside the block, in order: for
    suites pinning how often a path reads the store."""
    from caos.store import StoreConnection

    store = cast(StoreConnection, conn)
    statements: list[str] = []
    execute = store.execute

    def recorded(query: str, *args: object, **kwargs: object) -> object:
        statements.append(str(query))
        return execute(query, *args, **kwargs)  # type: ignore[arg-type]

    store.execute = recorded  # type: ignore[method-assign,assignment]
    try:
        yield statements
    finally:
        vars(store).pop("execute", None)


def every_block(conn: object, *sources: UUID) -> dict[UUID, frozenset[str]]:
    """Each source mapped to every block it holds: a whole-source delivery,
    for suites calling `verify_citations` outside a run."""
    from caos.store import StoreConnection

    rows = (
        cast(StoreConnection, conn)
        .execute(
            "SELECT source_id, block_id FROM source_blocks WHERE source_id = ANY(%s)",
            (list(sources),),
        )
        .fetchall()
    )
    blocks: dict[UUID, set[str]] = {source: set() for source in sources}
    for source, block in rows:
        blocks[UUID(str(source))].add(str(block))
    return {source: frozenset(found) for source, found in blocks.items()}


def reserve_at(
    conn: StoreConnection,
    attempt_id: UUID,
    amount: Decimal,
    *,
    lease: Lease | None = None,
) -> None:
    """Reserve `amount` under a dated price whose worst case is exactly it.

    Most fixtures want budget state rather than a particular price, and since
    Task 8.2 `reserve` requires the price the amount was computed from. This is
    that price: `priced(amount)`, so the row reads back consistently. A test
    about the price itself calls `reserve` with its own.
    """
    from caos.store.budget import reserve

    reserve(conn, attempt_id, amount, price=priced(amount), lease=lease)


# Shared fixtures for the FULL route live with its LITE counterpart. Pytest
# requires plugin registration in a top-level conftest module.
pytest_plugins = ("test_lite_deep_research_route",)
