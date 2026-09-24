"""Real PostgreSQL route authority, mutation guards and transaction boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import route_fault
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_case_ordering import _blocked
from test_route_pinning import CATALOG_PATH, PROFILE
from test_store_schema import _records

import caos.store.routes as routes
from caos.boundary_text import BoundaryText
from caos.graph.route import (
    Edge,
    EdgeType,
    ResolvedRoute,
    RouteExtensions,
    RouteNode,
    resolve_route,
    route_digest,
)
from caos.refusals import Refusal
from caos.store import StoreConnection, connect
from caos.store.cases import lock_case
from caos.store.events import RunEvent, append, events_of
from caos.store.runs import create_case, start_attempt, start_run


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(json.loads(CATALOG_PATH.read_text()), PROFILE, "DEEP_RESEARCH")


def test_all_catalog_routes_and_host_extensions_roundtrip(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    catalog = json.loads(CATALOG_PATH.read_text())
    choices = [
        resolve_route(catalog, profile, selection)
        for profile, body in catalog["profiles"].items()
        for selection in body["pathways"]
    ]
    choices.append(
        resolve_route(
            catalog,
            PROFILE,
            "FULL_CREDIT_ASSESSMENT",
            extensions=RouteExtensions(research_brief={}, model_extension=True),
            predicates={"has_covenants": "yes"},
        )
    )
    for route in choices:
        run = start_run(conn, case_id)
        conn.commit()
        digest = routes.pin_route(conn, run, route)
        assert conn.info.transaction_status is TransactionStatus.IDLE
        assert routes.resolved_route(conn, run) == route
        assert routes.pinned_route(conn, run) == digest == route_digest(route)
        fail_run(conn, run)
        before = events_of(conn, run)
        assert routes.pin_route(conn, run, route) == digest
        assert conn.info.transaction_status is TransactionStatus.IDLE
        assert events_of(conn, run) == before


@pytest.mark.parametrize(
    "column,value",
    [
        ("profile_id", "other"),
        ("selection_id", "other"),
        ("route_digest", "0" * 64),
    ],
)
def test_inconsistent_columns_refuse(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    column: str,
    value: str,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    routes.pin_route(conn, run, route)
    with route_fault(conn):
        conn.execute(
            psycopg.sql.SQL("UPDATE run_routes SET {} = %s").format(
                psycopg.sql.Identifier(column)
            ),
            (value,),
        )
    conn.commit()
    _refuse_reads_and_replay(conn, run, route)


@pytest.mark.parametrize(
    "path,value",
    [
        ([], None),
        ([], []),
        (["profile_id"], 4),
        (["selection_id"], " "),
        (["profile_id"], "x" * 129),
        (["nodes"], []),
        (["nodes"], {}),
        (["nodes", "0", "extra"], True),
        (["extra"], True),
        (["nodes", "0", "stage"], True),
        (["nodes", "0", "stage"], "1"),
        (["nodes", "0", "stage"], 1.5),
        (["nodes", "0", "stage"], 0),
        (["nodes", "0", "stage"], 101),
        (["nodes", "0", "module_id"], None),
        (["nodes", "0", "route_node_id"], "\nsecret"),
        (["nodes", "1", "module_id"], "CP-0"),
        (["edges", "0", "source"], "outside"),
        (["edges", "0", "type"], "UNKNOWN"),
        (["edges", "0", "target"], "CP-0"),
        (["edges"], None),
        (["predicates"], [["a", True]]),
        (["predicates"], [["a"]]),
        (["predicates"], [["a", "b", "c"]]),
        (["predicates"], [["a", "b"], ["a", "c"]]),
        (["predicates"], "ab"),
        (["predicates"], [["", "yes"]]),
        (["nodes", "0", "stage"], 2),  # valid shape, unchanged digest
    ],
)
def test_stored_shape_and_content_refuse(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    path: list[str],
    value: object,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    routes.pin_route(conn, run, route)
    with route_fault(conn):
        if path:
            conn.execute(
                "UPDATE run_routes SET resolved = jsonb_set(resolved, %s, %s)",
                (path, json.dumps(value)),
            )
        else:
            conn.execute("UPDATE run_routes SET resolved = %s", (json.dumps(value),))
    conn.commit()
    _refuse_reads_and_replay(conn, run, route)


def _refuse_reads_and_replay(
    conn: StoreConnection, run: UUID, route: ResolvedRoute
) -> None:
    for read in (routes.resolved_route, routes.pinned_route):
        with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
            read(conn, run)
        assert conn.info.transaction_status is TransactionStatus.INTRANS
    before = events_of(conn, run)
    with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
        routes.pin_route(conn, run, route)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert events_of(conn, run) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE run_routes SET profile_id = 'changed'",
        "DELETE FROM run_routes",
        "TRUNCATE run_routes CASCADE",
        "TRUNCATE runs CASCADE",
    ],
)
def test_normal_sql_cannot_mutate_pins(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    mutation: str,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    digest = routes.pin_route(conn, run, route)
    before = _records(conn)
    # CF-091: `TRUNCATE runs CASCADE` also reaches `run_events`,
    # `budget_reservations`, `run_attempts` and `artifacts` now that they
    # refuse their own truncation (`0033`, `0037`), and Postgres does not
    # promise which cascaded table's trigger fires first -- so any of the six
    # is an acceptable refusal, not just the two this test first tolerated.
    subject = (
        "(?:route pins|call records|run_events rows|budget_reservations rows"
        "|run_attempts rows|artifacts rows)"
        if " runs " in mutation
        else "route pins"
    )
    with pytest.raises(psycopg.Error, match=f"{subject} are immutable"):
        conn.execute(mutation)
    conn.rollback()
    assert _records(conn) == before
    assert routes.pinned_route(conn, run) == digest
    assert len(events_of(conn, run)) == 1


@pytest.mark.parametrize(
    "state", ["complete", "failed", "attempt", "invalid", "missing", "autocommit"]
)
def test_new_pin_refuses_without_orphans(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    state: str,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    conn.commit()
    expected = "ROUTE_IDENTITY_INVALID"
    if state in {"complete", "failed"}:
        conn.execute("UPDATE runs SET status = %s", (state.upper(),))
        expected = "RUN_NOT_RUNNING"
    elif state == "attempt":
        start_attempt(conn, run, route.nodes[0].route_node_id)
        expected = "ROUTE_PIN_TOO_LATE"
    elif state == "invalid":
        route = replace(route, nodes=())
    elif state == "missing":
        run, expected = uuid4(), "RUN_NOT_FOUND"
    conn.commit()
    if state == "autocommit":
        conn.autocommit, expected = True, "STORE_NOT_TRANSACTIONAL"
    with pytest.raises(Refusal, match=f"^{expected}$"):
        routes.pin_route(conn, run, route)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    conn.commit()
    assert routes.pinned_route(conn, run) is None
    assert all(event.name != "ROUTE_PINNED" for event in events_of(conn, run))


@pytest.mark.parametrize("failure", ["database", "commit", "cancel", "broken"])
def test_pin_failure_rolls_back_row_event_and_locks(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    route: ResolvedRoute,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    conn.commit()
    if failure == "commit":
        conn.execute(
            "CREATE FUNCTION synthetic_commit_failure() RETURNS trigger"
            " LANGUAGE plpgsql"
            " AS $$ BEGIN RAISE EXCEPTION 'synthetic secret'; END; $$;"
            " CREATE CONSTRAINT TRIGGER synthetic_failure AFTER INSERT ON run_routes"
            " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " EXECUTE FUNCTION synthetic_commit_failure()"
        )
        conn.commit()

    def fail(c: StoreConnection, r: UUID, e: RunEvent) -> None:
        append(c, r, e)
        if failure == "database":
            c.execute("SELECT synthetic_route_failure")
        if failure == "broken":
            c.close()
        raise KeyboardInterrupt

    if failure != "commit":
        monkeypatch.setattr(routes, "append", fail)
    with pytest.raises(
        Refusal if failure in {"database", "commit"} else KeyboardInterrupt
    ) as caught:
        routes.pin_route(conn, run, route)
    if failure in {"database", "commit"}:
        assert str(caught.value) == "STORE_UNAVAILABLE"
    assert conn.closed or conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_case(other, case_id)
        assert routes.pinned_route(other, run) is None
        assert events_of(other, run) == []


@pytest.mark.parametrize("conflict", [False, True])
def test_concurrent_first_pins_serialize(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    route: ResolvedRoute,
    conflict: bool,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    conn.commit()
    lock_case(conn, case_id)
    waiting = replace(route, predicates=(("x", "y"),)) if conflict else route
    with connect(empty_database) as other:

        def pin() -> None:
            if conflict:
                with pytest.raises(Refusal, match=r"^ROUTE_ALREADY_PINNED$"):
                    routes.pin_route(other, run, waiting)
            else:
                assert routes.pin_route(other, run, waiting) == route_digest(route)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, pin):
            routes.pin_route(conn, run, route)
    assert routes.resolved_route(conn, run) == route
    assert len(events_of(conn, run)) == 1


@pytest.mark.parametrize("coerced", [("ab",), ({"a": 0, "b": 0},)])
def test_invalid_new_shapes_cannot_be_pinned(
    case: tuple[StoreConnection, UUID], route: ResolvedRoute, coerced: object
) -> None:
    conn, case_id = case
    a, b = route.nodes
    invalid = [
        replace(route, profile_id=True),  # type: ignore[arg-type]  # corrupt input
        replace(route, selection_id="x" * 129),
        replace(route, nodes=(a, replace(b, route_node_id=a.route_node_id))),
        replace(route, nodes=(a, replace(b, module_id=a.module_id))),
        replace(route, nodes=(replace(a, stage=True), b)),
        replace(route, nodes=route.nodes * 129),
        replace(route, edges=(Edge("outside", "CP-DR", EdgeType.REQUIRED),)),
        replace(route, edges=(*route.edges, Edge("CP-DR", "CP-0", EdgeType.REQUIRED))),
        replace(route, edges=route.edges * 2),
        replace(route, edges=route.edges * 1025),
        replace(route, predicates=(("x", True),)),  # type: ignore[arg-type]
        replace(route, predicates=(("x", "y", "z"),)),  # type: ignore[arg-type]
        replace(route, predicates=(("x", "yes"),) * 129),
        replace(route, predicates=(("x", "yes"), ("x", "no"))),
        replace(route, predicates=(("x", "x" * 4097),)),
        replace(route, nodes=tuple(reversed(route.nodes))),
        replace(route, predicates=coerced),  # type: ignore[arg-type]
        replace(route, nodes=(None,)),  # type: ignore[arg-type]
    ]
    for bad in invalid:
        run = start_run(conn, case_id)
        conn.commit()
        with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
            routes.pin_route(conn, run, bad)
        assert conn.info.transaction_status is TransactionStatus.IDLE
        assert routes.pinned_route(conn, run) is None
        assert events_of(conn, run) == []


def test_pin_waits_for_attempt_and_other_case_remains_independent(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    route: ResolvedRoute,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    independent = start_run(conn, create_case(conn, BoundaryText.of("Independent")))
    conn.commit()
    lock_case(conn, case_id)
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        routes.pin_route(other, independent, route)

        def pin() -> None:
            with pytest.raises(Refusal, match=r"^ROUTE_PIN_TOO_LATE$"):
                routes.pin_route(other, run, route)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, pin):
            start_attempt(conn, run, route.nodes[0].route_node_id)
    assert routes.pinned_route(conn, run) is None


def test_fault_injection_restores_guard_after_cancellation(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
) -> None:
    conn, case_id = case
    run = start_run(conn, case_id)
    routes.pin_route(conn, run, route)
    with pytest.raises(KeyboardInterrupt), route_fault(conn):
        conn.execute("DELETE FROM run_routes")
        raise KeyboardInterrupt
    conn.commit()
    assert routes.resolved_route(conn, run) == route
    with pytest.raises(psycopg.Error, match="route pins are immutable"):
        conn.execute("DELETE FROM run_routes")
    conn.rollback()


def test_route_text_limits_roundtrip_without_json_encoding_disagreement(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
) -> None:
    conn, case_id = case
    bounded = replace(
        route,
        profile_id="p" * 128,
        selection_id="s" * 128,
        nodes=tuple(
            RouteNode(f"{i:03}" + "n" * 125, f"CP-{i}", 100) for i in range(128)
        ),
        edges=(),
        predicates=tuple((f"p{i}", "😀" * 4096) for i in range(128)),
    )
    run = start_run(conn, case_id)
    conn.commit()
    assert routes.pin_route(conn, run, bounded) == route_digest(bounded)
    assert routes.resolved_route(conn, run) == bounded


def test_json_parse_ceiling_and_diagnostics_are_bounded(route: ResolvedRoute) -> None:
    raw = routes._canonical(route)
    at_limit = raw + " " * (8_388_608 - len(raw))
    assert routes._decode(at_limit) == route
    for invalid in (at_limit + " ", "{", "[" * 5000):
        with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
            routes._decode(invalid)
