"""Pinning a resolved route. The one place resolution meets the store.

`caos/graph/route.py` is pure by design -- no I/O, no clock -- because
invariant 10 rests on a replay from the same pins taking the same path, and a
resolver that read anything mutable could not promise that. So the pin lives
here: the row, the digest, and the event, in one transaction.

Pinning is once per run. A second pin carrying the same digest is a replay of the
gate and is accepted silently; one carrying a different digest is refused, because
execution reads only the pin and moving it underneath a running route rewrites
what that run is.
"""

from __future__ import annotations

from collections.abc import Mapping
from json import dumps, loads
from re import fullmatch
from typing import Any
from uuid import UUID

import psycopg

from caos.boundary_text import BoundaryText
from caos.graph.route import (
    EDGE_FIELDS,
    HOST_PIN,
    MODEL_STAGE,
    NODE_FIELDS,
    RESEARCH_STAGE,
    Edge,
    EdgeType,
    ResolvedRoute,
    RouteExtensions,
    RouteNode,
    dependency_order,
    resolve_route,
    route_digest,
    route_json,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, committed_unit
from caos.store.events import RunEvent, append, lock_run


def pin_route(conn: StoreConnection, run_id: UUID, resolved: ResolvedRoute) -> str:
    """Own the atomic pin/event transaction, including replay and refusal."""
    if conn.autocommit:
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)
    with committed_unit(conn):
        digest = pin_route_in(conn, run_id, resolved)
    return digest


def pin_route_in(conn: StoreConnection, run_id: UUID, resolved: ResolvedRoute) -> str:
    """`pin_route`'s row and event in the caller's transaction; never commits."""
    try:
        raw = _canonical(resolved)
    except (TypeError, ValueError, AttributeError, RecursionError):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID) from None
    resolved = _decode(raw)
    digest = route_digest(resolved)
    status = lock_run(conn, run_id)
    stored = route_pin(conn, run_id)
    if stored is not None:
        if stored[1] != digest:
            raise Refusal(RefusalCode.ROUTE_ALREADY_PINNED)
        return digest
    if status is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    if conn.execute(
        "SELECT 1 FROM run_attempts WHERE run_id = %s LIMIT 1", (run_id,)
    ).fetchone():
        raise Refusal(RefusalCode.ROUTE_PIN_TOO_LATE)
    conn.execute(
        "INSERT INTO run_routes (run_id, profile_id, selection_id, route_digest,"
        " resolved) VALUES (%s, %s, %s, %s, %s)",
        (
            run_id,
            resolved.profile_id,
            resolved.selection_id,
            digest,
            raw,
        ),
    )
    append(conn, run_id, RunEvent.ROUTE_PINNED)
    return digest


def require_catalog_route(route: ResolvedRoute, catalog: Mapping[str, Any]) -> None:
    """Refuse a pinned route the bundle's catalog does not itself resolve to
    (CF-025): `ROUTE_IDENTITY_INVALID`, the pinned route's own code.

    `pin_route_in` stores whatever route it is given and `invocation._upstream`
    trusts the stored edges, so a pin that was never the catalog's resolution
    -- a node, stage or edge type another than the catalog's, a pathway it has
    no longer -- would run on edges nobody resolved. Resolved again from the
    pinned build's catalog, under the extensions the route itself carries (a
    node at the research stage, one at the model stage) and its predicates,
    which nothing evaluates and resolution freezes as given, save the host pin
    it writes itself; equal digests are the proof (invariant 10). Pure.
    """
    stages = {node.stage for node in route.nodes}
    extensions = RouteExtensions(
        research_brief={} if RESEARCH_STAGE in stages else None,
        model_extension=MODEL_STAGE in stages,
    )
    predicates = {key: value for key, value in route.predicates if key != HOST_PIN}
    try:
        resolved = resolve_route(
            catalog,
            route.profile_id,
            route.selection_id,
            extensions=extensions,
            predicates=predicates,
        )
    except Refusal:
        resolved = None
    if resolved is None or route_digest(resolved) != route_digest(route):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)


def pinned_route(conn: StoreConnection, run_id: UUID) -> str | None:
    """The digest pinned to this run, or None. What execution reads."""
    pin = route_pin(conn, run_id)
    return None if pin is None else pin[1]


def resolved_route(conn: StoreConnection, run_id: UUID) -> ResolvedRoute | None:
    """The pinned route itself, or None before the gate. See `route_pin`."""
    pin = route_pin(conn, run_id)
    return None if pin is None else pin[0]


def route_pin(conn: StoreConnection, run_id: UUID) -> tuple[ResolvedRoute, str] | None:
    """The pinned route and its digest, rebuilt from the row, or None.

    Read back rather than re-resolved. A surface that resolved the catalog again
    to draw a running route would draw whatever the catalog says today, which is
    the one thing pinning exists to prevent.

    The digest comes out with the route because deriving it is how the row is
    checked: a stored digest that disagrees with the route beside it refuses
    here, so a caller that hashed the returned route again could only ever get
    the number this already vouched for.
    """
    try:
        row = conn.execute(
            "SELECT profile_id, selection_id, route_digest, resolved::text"
            " FROM run_routes WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if row is None:
        return None
    route = _decode(row[3])
    digest = route_digest(route)
    if (route.profile_id, route.selection_id, digest) != row[:3]:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return route, digest


def _fields(value: object, fields: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return value


def _items(value: object, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return value


def _decode(raw: str) -> ResolvedRoute:
    """Validate stored shape without coercing, reordering or changing its hash.

    Catalog: 18 routes, max19 nodes/88 edges, IDs57/6 and stages1-19.
    Limits allow both host slots99/100 and headroom: 128 nodes/IDs/predicates,
    1024 edges, 8,388,608 JSON characters (including worst-case ASCII escapes).
    Predicates reuse the existing 4096 text boundary.
    """
    if len(raw) > 8_388_608:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    try:
        return _rebuild(loads(raw))
    except (Refusal, TypeError, ValueError, RecursionError):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID) from None


def _rebuild(value: object) -> ResolvedRoute:
    stored = _fields(value, "profile_id selection_id nodes edges predicates")
    nodes = tuple(_node(node) for node in _items(stored["nodes"], 128))
    edges = tuple(_edge(edge) for edge in _items(stored["edges"], 1024))
    predicates = tuple(_predicate(pair) for pair in _items(stored["predicates"], 128))
    modules = {node.module_id for node in nodes}
    if (
        not nodes
        or len({n.route_node_id for n in nodes}) != len(nodes)
        or len(set(edges)) != len(edges)
        or any(e.source not in modules or e.target not in modules for e in edges)
        or len({p[0] for p in predicates}) != len(predicates)
        or dependency_order(nodes, edges) != nodes
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return ResolvedRoute(
        _identifier(stored["profile_id"]),
        _identifier(stored["selection_id"]),
        nodes,
        edges,
        predicates,
    )


def _node(value: object) -> RouteNode:
    node = _fields(value, "route_node_id module_id stage")
    if type(node["stage"]) is not int or not 1 <= node["stage"] <= 100:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return RouteNode(
        _identifier(node["route_node_id"]),
        _identifier(node["module_id"]),
        node["stage"],
    )


def _edge(value: object) -> Edge:
    edge = _fields(value, "source target type")
    return Edge(
        _identifier(edge["source"]), _identifier(edge["target"]), EdgeType(edge["type"])
    )


def _predicate(value: object) -> tuple[str, str]:
    pair = _items(value, 2)
    if (
        len(pair) != 2
        or not isinstance(pair[1], str)
        or not pair[1].strip()
        or BoundaryText.of(pair[1]).value != pair[1]
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return _identifier(pair[0]), pair[1]


def _canonical(resolved: ResolvedRoute) -> str:
    """Stored object shape; route_digest retains its established array shape."""
    rows = route_json(resolved)
    rows["nodes"] = [
        dict(zip(NODE_FIELDS, node, strict=True)) for node in rows["nodes"]
    ]
    rows["edges"] = [
        dict(zip(EDGE_FIELDS, edge, strict=True)) for edge in rows["edges"]
    ]
    return dumps(rows, sort_keys=True, separators=(",", ":"))
