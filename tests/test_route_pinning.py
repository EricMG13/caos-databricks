"""The pin: where a resolved route becomes the thing execution reads.

Invariant 10 in two halves. `tests/test_route_resolution.py` holds the pure half
-- resolution is a function of pinned inputs, so it digests the same every time.
This file holds the other: the digest is written once, with its event, and a
replay reads the pin rather than re-resolving against a catalog that may have
moved underneath it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from psycopg.pq import TransactionStatus

from caos.graph.route import (
    Edge,
    EdgeType,
    ResolvedRoute,
    RouteNode,
    resolve_route,
    route_digest,
    route_json,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, routes
from caos.store.events import RunEvent, events_of
from caos.store.routes import pin_route, pinned_route, resolved_route, route_pin
from caos.store.runs import start_run

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-os-credit-os/references"
    / "CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
PROFILE = "FULL_CREDIT_32"


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return loaded


def _route(catalog: dict[str, Any], selection_id: str) -> ResolvedRoute:
    return resolve_route(catalog, PROFILE, selection_id)


def test_a_pinned_route_is_what_execution_reads(
    catalog: dict[str, Any], case: tuple[StoreConnection, UUID]
) -> None:
    """The other half of invariant 10. Pinning happens once at the plan gate;
    the pin is what a replay reads, so re-pinning the same route is the gate
    replayed and re-pinning a different one is a different run wearing the same
    id."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    resolved = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")

    digest = pin_route(conn, run_id, resolved)

    assert digest == route_digest(resolved)
    assert pinned_route(conn, run_id) == digest
    # The route and its digest come out of one read and one hash.
    assert route_pin(conn, run_id) == (resolved, digest)
    assert [event.name for event in events_of(conn, run_id)] == [
        RunEvent.ROUTE_PINNED.value
    ]

    # The same gate, replayed after a crash: accepted, and not a second event.
    assert pin_route(conn, run_id, resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW"))
    assert len(events_of(conn, run_id)) == 1

    with pytest.raises(Refusal) as caught:
        pin_route(conn, run_id, resolve_route(catalog, PROFILE, "EARNINGS_UPDATE"))
    assert caught.value.code is RefusalCode.ROUTE_ALREADY_PINNED
    assert pinned_route(conn, run_id) == digest


def test_the_pinned_route_reads_back_as_the_route_that_was_pinned(
    catalog: dict[str, Any], case: tuple[StoreConnection, UUID]
) -> None:
    """`resolved_route` is what a surface draws a running route from.

    Read back, never re-resolved: resolving the catalog again would draw
    whatever it says today, which is the one thing pinning exists to prevent.
    The digest is the check -- a round trip that lost an edge's type or a
    predicate would digest differently, which is precisely what execution would
    then disagree with.
    """
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    pinned = resolve_route(
        catalog, PROFILE, "FULL_CREDIT_ASSESSMENT", predicates={"has_covenants": "yes"}
    )
    pin_route(conn, run_id, pinned)

    read_back = resolved_route(conn, run_id)

    assert read_back == pinned
    assert read_back is not None
    assert route_digest(read_back) == pinned_route(conn, run_id)


def test_a_run_before_its_plan_gate_has_no_resolved_route(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Not an error. There is simply nothing pinned yet, and a caller that got a
    route here would be reading one nobody approved."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()

    assert resolved_route(conn, run_id) is None


def test_a_refused_pin_does_not_keep_the_run_row_locked(
    catalog: dict[str, Any], case: tuple[StoreConnection, UUID]
) -> None:
    """`pin_route` takes the run row lock to read the pin under it.

    The replay path commits before returning, because "the lock is not worth
    holding"; the refusal path raised with the transaction still open, so a
    second plan gate on that run waited for whatever the caller did next --
    which for a caller that answered the refusal and went on to serve another
    request was the rest of that request. Every other refusal that takes this
    lock -- `apply_schema`, `reserve` -- ends its transaction first.
    """
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    pin_route(conn, run_id, _route(catalog, "LIQUIDITY_REVIEW"))

    with pytest.raises(Refusal) as caught:
        pin_route(conn, run_id, _route(catalog, "EARNINGS_UPDATE"))

    assert caught.value.code is RefusalCode.ROUTE_ALREADY_PINNED
    assert conn.info.transaction_status is TransactionStatus.IDLE


# Taken from ab80314, before the two serialisers were given one spelling. A
# golden computed after the change would only say the change agrees with itself.
GOLDEN_ROUTE = ResolvedRoute(
    "FULL_CREDIT_32",
    "RELATIVE_VALUE",
    (
        RouteNode("n-1", "CP-0", 1),
        RouteNode("n-2", "CP-5", 2),
        RouteNode("n-3", "CP-6", 3),
    ),
    (
        Edge("CP-5", "CP-6", EdgeType.QA_GATE),
        Edge("CP-0", "CP-5", EdgeType.REQUIRED),
        Edge("CP-0", "CP-6", EdgeType.ADVISORY),
    ),
    (("CP-6", "a predicate the host does not evaluate"),),
)
GOLDEN_DIGEST = "2eac150719617521ea164a8067d8abb1b5044d80a63e37dfd6257d64ff1e6dd6"
GOLDEN_STORED = (
    '{"edges":[{"source":"CP-5","target":"CP-6","type":"QA_GATE"},'
    '{"source":"CP-0","target":"CP-5","type":"REQUIRED"},'
    '{"source":"CP-0","target":"CP-6","type":"ADVISORY"}],'
    '"nodes":[{"module_id":"CP-0","route_node_id":"n-1","stage":1},'
    '{"module_id":"CP-5","route_node_id":"n-2","stage":2},'
    '{"module_id":"CP-6","route_node_id":"n-3","stage":3}],'
    '"predicates":[["CP-6","a predicate the host does not evaluate"]],'
    '"profile_id":"FULL_CREDIT_32","selection_id":"RELATIVE_VALUE"}'
)
GOLDEN_CATALOG_DIGEST = (
    "a25846cbb12eaa68aa1265cdf84ad0b17806717e3020ab7c55e2541ac6936168"
)


def test_route_digest_bytes_are_unchanged_by_the_shared_serialiser(
    catalog: dict[str, Any],
) -> None:
    """Two byte forms, one field list, and neither form may move.

    `route_digest` hashes rows with its edges sorted; the stored `resolved`
    column keys each row by its field name and keeps the route's own edge
    order. Both are pinned -- the digest by invariant 10 and by every
    `run_routes.route_digest` already written, the stored shape by every row
    `_decode` must still read back. `route_json` is the one spelling of what
    they carry, so this asserts the bytes each still produces against goldens
    taken before it existed: the synthetic route pins the edge sort and a
    predicate, and the catalog's own RELATIVE_VALUE route pins a real one.
    """
    assert route_digest(GOLDEN_ROUTE) == GOLDEN_DIGEST
    assert routes._canonical(GOLDEN_ROUTE) == GOLDEN_STORED
    assert route_digest(_route(catalog, "RELATIVE_VALUE")) == GOLDEN_CATALOG_DIGEST
    assert route_json(GOLDEN_ROUTE)["edges"] == [
        ["CP-5", "CP-6", "QA_GATE"],
        ["CP-0", "CP-5", "REQUIRED"],
        ["CP-0", "CP-6", "ADVISORY"],
    ]


def test_require_catalog_route_accepts_only_the_catalog_s_own_resolution(
    catalog: dict[str, Any],
) -> None:
    """CF-025: a pinned route is re-resolved from the catalog under the
    extensions it carries and its caller's predicates, and must digest the
    same. Anything else -- a node, stage or edge the catalog does not resolve,
    a pathway it lacks, a host pin it did not write -- is
    `ROUTE_IDENTITY_INVALID`."""
    from dataclasses import replace

    from caos.graph.route import HOST_PIN, RouteExtensions
    from caos.store.routes import require_catalog_route

    plain = _route(catalog, "FULL_CREDIT_ASSESSMENT")
    for good in (
        plain,
        resolve_route(
            catalog, PROFILE, "FULL_CREDIT_ASSESSMENT", predicates={"x": "caller's"}
        ),
        resolve_route(
            catalog,
            PROFILE,
            "RELATIVE_VALUE",
            extensions=RouteExtensions(model_extension=True),
        ),
        resolve_route(
            catalog,
            PROFILE,
            "FULL_CREDIT_ASSESSMENT",
            extensions=RouteExtensions(research_brief={}),
        ),
    ):
        require_catalog_route(good, catalog)
    first, *rest = plain.edges
    stale = resolve_route(
        catalog,
        PROFILE,
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    stale = replace(
        stale,
        predicates=tuple(
            (key, "0" * 64 if key == HOST_PIN else value)
            for key, value in stale.predicates
        ),
    )
    for bad in (
        replace(plain, edges=(replace(first, type=EdgeType.ADVISORY), *rest)),
        replace(plain, edges=tuple(rest)),
        replace(plain, edges=(*plain.edges, Edge("CP-0", "CP-1", EdgeType.REQUIRED))),
        replace(plain, nodes=(replace(plain.nodes[0], stage=5), *plain.nodes[1:])),
        replace(
            plain,
            nodes=(replace(plain.nodes[0], route_node_id="n-1"), *plain.nodes[1:]),
        ),
        replace(plain, selection_id="NO_SUCH_PATHWAY"),
        replace(plain, predicates=((HOST_PIN, "0" * 64),)),
        stale,
    ):
        with pytest.raises(Refusal) as caught:
            require_catalog_route(bad, catalog)
        assert caught.value.code is RefusalCode.ROUTE_IDENTITY_INVALID
