"""Identity before the store, stated by each route rather than by parameter order.

FastAPI solves a route's parameter dependencies in the order the signature
declares them, so `actor: Caller` ahead of `conn: Store` used to be the whole of
what kept an anonymous request off a connection. A route's decorator-level
`dependencies=` are inserted at the *front* of its dependency list whatever the
parameters say, which is what `IDENTITY_FIRST` on every store-touching decorator
buys: the order is a declaration on the route, not a property of its signature.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from caos.api import app as app_module
from caos.api import deps
from caos.api.app import app
from caos.api.deps import (
    IDENTITY_FIRST,
    Caller,
    Store,
    actor_from_request,
    store_connection,
)
from caos.api.identity import Actor, actor_from_headers
from caos.blobs import BlobStore
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.members import Standing, grant

# Routes that deliberately take no identity: the readiness probe is read by an
# orchestrator that has none, and it does no I/O on the request.
NO_IDENTITY = frozenset({("GET", "/api/health")})


def _calls(dependant: Dependant) -> Iterator[Callable[..., object]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _calls(sub)


def _routes() -> list[APIRoute]:
    """Every route the app serves, through the routers it includes."""
    return [
        inner
        for route in app.routes
        for inner in getattr(getattr(route, "original_router", None), "routes", [route])
        if isinstance(inner, APIRoute)
    ]


def _keys(route: APIRoute) -> set[tuple[str, str]]:
    return {(method, route.path) for method in route.methods or ()}


def _identity_first(route: APIRoute) -> bool:
    return bool(route.dependencies) and route.dependencies[0].dependency is (
        actor_from_request
    )


def _throwaway(*, declared: bool) -> tuple[FastAPI, list[str]]:
    """A route whose store is declared *before* its caller in the signature."""
    opened: list[str] = []
    router = APIRouter()
    extra = [IDENTITY_FIRST] if declared else []

    @router.get("/probe", dependencies=extra)
    def probe(conn: Store, actor: Caller) -> dict[str, str]:
        return {"user": str(actor.user_id)}

    def counted() -> Iterator[object]:
        opened.append(store_connection.__name__)
        yield object()

    probe_app = FastAPI()
    probe_app.include_router(router)
    probe_app.dependency_overrides[store_connection] = counted
    return probe_app, opened


def test_identity_is_resolved_before_a_store_declared_ahead_of_it() -> None:
    """With `IDENTITY_FIRST` on the decorator an anonymous request opens no
    connection even though the signature names the store first -- and without
    it the same route does, which is what makes the first half mean something.
    """
    declared, opened = _throwaway(declared=True)
    with pytest.raises(Refusal) as refused:
        TestClient(declared).get("/probe")
    assert refused.value.code is RefusalCode.NOT_AUTHENTICATED
    assert opened == []

    undeclared, opened_anyway = _throwaway(declared=False)
    with pytest.raises(Refusal):
        TestClient(undeclared).get("/probe")
    assert opened_anyway == [store_connection.__name__]


def test_every_store_touching_route_declares_identity_on_its_decorator() -> None:
    """A new route that reaches the store without `IDENTITY_FIRST` fails here."""
    touching = [r for r in _routes() if store_connection in set(_calls(r.dependant))]
    assert len(touching) > 20  # a census that found nothing is a failure

    missing = {
        key for route in touching if not _identity_first(route) for key in _keys(route)
    }
    assert missing == set()


def test_the_routes_that_take_no_identity_reach_no_store() -> None:
    """The exemption is only for a route with nothing behind it to protect."""
    exempt = [r for r in _routes() if _keys(r) & NO_IDENTITY]
    assert [key for r in exempt for key in _keys(r)] == sorted(NO_IDENTITY)
    for route in exempt:
        calls = set(_calls(route.dependant))
        assert store_connection not in calls
        assert actor_from_request not in calls
        assert not route.dependencies


@pytest.fixture
def served(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    conn, _case_id = case
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    app.dependency_overrides[store_connection] = lambda: conn
    app.dependency_overrides[deps.blob_store] = lambda: BlobStore(tmp_path / "b")
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


def test_the_caller_is_resolved_once_though_it_is_declared_twice(
    served: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decorator's `IDENTITY_FIRST` and the handler's `Caller` are one
    dependency to FastAPI's per-request cache, so identity is read once."""
    conn, case_id = case
    member = UUID("00000000-0000-4000-8000-000000000001")
    grant(conn, case_id=case_id, user_id=member, standing=Standing.READER)
    conn.commit()

    resolved: list[Actor] = []

    def counted(headers: Headers) -> Actor:
        actor = actor_from_headers(headers)
        resolved.append(actor)
        return actor

    monkeypatch.setattr("caos.api.deps.actor_from_headers", counted)
    response = served.get(
        f"/api/v1/cases/{case_id}/upload", headers={"x-caos-user": str(member)}
    )

    assert response.status_code == 200
    assert [actor.user_id for actor in resolved] == [member]
