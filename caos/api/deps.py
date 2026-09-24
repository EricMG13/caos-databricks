"""The shared request dependencies every section read, command and `app.py`
itself declare on their routes: who is asking, the ids the request names, the
caller's visibility of the case, the request's store connection, the blob
store, and the process's vendored methodology bundle.

Moved out of `caos/api/app.py` (Task 4.1c) so the section reads under
`caos/api/reads/` can depend on these functions directly instead of each
declaring its own lazily-imported wrapper. `app.py` used to be imported by
every section module (to register its router), which made importing `app.py`'s
dependencies from a section module a cycle -- whichever module loaded first
would find the other half-built. This module has no such edge: nothing here
imports `caos.api.app`, so both `app.py` and `caos/api/reads/*.py` import
it directly, and a test overriding one of these functions reaches every route
that declares it, section reads included.

`app.py` imports and re-exports every name here (`from caos.api.deps import
store_connection as store_connection`, and so on) so `caos.api.app.<name>` is
still the same function object -- an existing override of `app_module.X`
overrides this module's `X` too, because they are one object under two names.
`app.py`'s `_lifespan` keeps using `_database_url` the same way.

The id parsers (`case_path`, `run_path`, `run_query`, `revision_query`) are
typed `str` and parsed here rather than typed `UUID`, so a malformed id is
answered in the declared refusal body instead of FastAPI's 422 -- and, as
dependencies declared after identity and before the store, without opening a
connection. `visible_case` is the one round trip this module makes: the
caller's live standing on the path's case, refused as a private
`CASE_NOT_FOUND` below the reading floor, so an unknown case and a case the
caller may not read are one answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from os import environ
from pathlib import Path
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, Request
from psycopg import OperationalError

from caos.api.edge import _logged
from caos.api.identity import Actor, actor_from_headers
from caos.blobs import BlobStore
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect, interrupted
from caos.store.lakebase import store_url
from caos.store.members import Standing, satisfies, standing_of

IO_BUDGET = 1  # `visible_case`: the caller's standing on the case
# N35's remainder: this module's own dependencies read no blob -- `visible_case`
# is a store row, and `blob_store`/`request_blobs` construct the handle a
# route reads with, never reading through it themselves.
BLOB_BUDGET = 0

# Reading a case -- any section of it, its events, an evidence page -- is
# holding live standing on it; holding more grants nothing further here.
READ_REQUIRES = Standing.READER

DATABASE_URL = "CAOS_DATABASE_URL"
BLOB_ROOT = "CAOS_BLOB_ROOT"
# The vendored methodology bundle the image ships (`Dockerfile` copies it).
VENDORED_BUNDLE = Path(__file__).resolve().parents[2] / "vendor" / "deploy-v"


def _database_url() -> str:
    """The store's connection string: `CAOS_DATABASE_URL`, or Lakebase (D17)."""
    return store_url()


def store_connection() -> Iterator[StoreConnection]:
    """One connection per request, from the environment.

    A store that does not answer is refused like any other store fault. The
    refusal is raised outside the `except`, so psycopg's message -- the host,
    the port and the role -- is neither chained behind it nor logged with it.

    A fault after connect (CF-022) that is the store not answering -- a
    dropped session, a statement timeout, a lock wait or a transaction the
    server gave up on (`caos.store.interrupted`) -- is refused the same way:
    the store not answering mid-request is the same fact as it not answering
    at connect, and callers should be told the same thing (503, retryable).
    Any other `psycopg.Error` -- a statement the database refused, a unique
    violation, a trigger's refusal -- is no outage (N5): `INTERNAL_FAULT`,
    logged as the edge logs an unhandled fault, its class and frame and never
    its text, because once it is a refusal the edge no longer sees it.
    """
    conn: StoreConnection | None
    try:
        conn = connect(_database_url())
    except OperationalError:
        conn = None
    if conn is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    try:
        with conn:
            yield conn
    except psycopg.Error as fault:
        raise Refusal(_store_fault(fault)) from None


def _store_fault(fault: psycopg.Error) -> RefusalCode:
    """The code a store fault mid-request is answered with (N5)."""
    if interrupted(fault):
        return RefusalCode.STORE_UNAVAILABLE
    _logged(fault)
    return RefusalCode.INTERNAL_FAULT


def blob_store() -> BlobStore:
    root = environ.get(BLOB_ROOT)
    if not root:
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    return BlobStore.from_setting(root)


def request_blobs(blobs: Annotated[BlobStore, Depends(blob_store)]) -> BlobStore:
    """The blob store as one request uses it: every blob it verifies is
    downloaded and hashed once, however many readers ask (ED-7). A layer over
    `blob_store` rather than inside it, so a store a test substitutes there is
    read the way a request reads the real one."""
    return blobs.remembering()


async def actor_from_request(request: Request) -> Actor:
    """Who is asking. A dependency rather than a line in a route body.

    Every store-touching route declares it on its decorator as
    `IDENTITY_FIRST`, which FastAPI solves before any parameter dependency, so
    identity is ahead of the connection whatever order a signature names them
    in. Two things rest on that. An
    anonymous request is refused without opening one -- a connection is per
    request and unpooled, and asking in a loop costs the asker nothing. And the
    answer to a stranger does not depend on the store being reachable: a process
    that has lost its database still says "I do not know who you are", which is
    the only one of the two answers that is about the caller.

    It closes the anonymous half and not the whole of it. A request asserting
    any well-formed subject still reaches the connection, because whether that
    subject is real is the edge's question rather than this process's
    (`caos/api/identity.py`).

    Async so that FastAPI solves it on the event loop rather than one of
    AnyIO's worker threads (N36): dev mode awaits nothing, and behind the
    platform only the request actually making a cold SCIM lookup ever leaves
    it, in `caos.api.identity._resolved`.
    """
    return await actor_from_headers(request.headers)


def methodology_bundle() -> Bundle:
    """The process's one bundle, which canonical records are verified under.

    Built once: its manifest snapshot is taken at construction and every use
    re-verifies the bytes (invariant 4), so a moved manifest refuses rather than
    being adopted.
    """
    return _vendored_bundle()


@cache
def _vendored_bundle() -> Bundle:
    bundle = Bundle(VENDORED_BUNDLE)
    bundle.verify_pinned()
    return bundle


# Declared on every store-touching route's decorator, `dependencies=
# [IDENTITY_FIRST]`. FastAPI inserts decorator-level dependencies at the front
# of a route's list whatever its parameters say, so identity is solved before
# any connection even on a signature that names `Store` first. The handler's
# own `Caller` is the same dependency to the per-request cache, so the actor
# is read once (`tests/test_identity_first.py`).
IDENTITY_FIRST = Depends(actor_from_request)

Caller = Annotated[Actor, Depends(actor_from_request)]
Store = Annotated[StoreConnection, Depends(store_connection)]
Blobs = Annotated[BlobStore, Depends(request_blobs)]
Methodology = Annotated[Bundle, Depends(methodology_bundle)]


def parse_uuid(value: str, code: RefusalCode) -> UUID:
    """`value` as a UUID, or the refusal `code` a request naming nothing gets.

    Raised outside the `except`: the ValueError's message quotes the input --
    a path, a query or a header the client chose -- and `from None` would
    still leave it on `__context__`.
    """
    parsed: UUID | None
    try:
        parsed = UUID(value)
    except ValueError:
        parsed = None
    if parsed is None:
        raise Refusal(code)
    return parsed


def case_path(case_id: str) -> UUID:
    """The path's case id, or the refusal a case the caller may not read gets."""
    return parse_uuid(case_id, RefusalCode.CASE_NOT_FOUND)


def run_path(run_id: str) -> UUID:
    """The path's run id, or `RUN_NOT_FOUND`.

    Declared after the case's visibility on a route that has one, so a
    stranger with a malformed run id is answered about the case, not the run.
    """
    return parse_uuid(run_id, RefusalCode.RUN_NOT_FOUND)


def source_path(source_id: str) -> UUID:
    """The path's source id, or the one answer a source nobody may use gets."""
    return parse_uuid(source_id, RefusalCode.EVIDENCE_NOT_AVAILABLE)


def revision_path(revision_id: str) -> UUID:
    """The path's revision id, or `DELIVERABLE_NOT_FOUND`."""
    return parse_uuid(revision_id, RefusalCode.DELIVERABLE_NOT_FOUND)


def member_path(user_id: str) -> UUID:
    """The path's member. A subject that is not an identifier is a malformed
    request, not a missing case: the caller already reads this case."""
    return parse_uuid(user_id, RefusalCode.REQUEST_INVALID)


def run_query(run: str | None = None) -> UUID | None:
    """The `run` query, or `RUN_NOT_FOUND` for one that names no run."""
    return None if run is None else parse_uuid(run, RefusalCode.RUN_NOT_FOUND)


def revision_query(revision: str | None = None) -> UUID:
    """The `revision` query, required: absent or malformed names no deliverable."""
    return parse_uuid(revision or "", RefusalCode.DELIVERABLE_NOT_FOUND)


def readable(standing: Standing | None) -> Standing:
    """The one visibility rule: live standing at or above `READ_REQUIRES`, or
    the private `CASE_NOT_FOUND` a stranger, a revoked member and an unknown
    case all get. `visible_case` applies it to a standing read on its own; a
    read that folds the membership join into its projection row applies it to
    the standing that row carries."""
    if standing is None or not satisfies(standing, READ_REQUIRES):
        raise Refusal(RefusalCode.CASE_NOT_FOUND)
    return standing


def visible_case(actor: Caller, case_id: CasePath, conn: Store) -> Standing:
    """The caller's live standing on the path's case, one query.

    Its own sub-dependencies keep the order that matters: identity, then the
    path, then the store -- so a route declaring `VisibleCase` before `Store`
    still opens no connection for an anonymous or malformed request.
    """
    return readable(standing_of(conn, case_id=case_id, user_id=actor.user_id))


CasePath = Annotated[UUID, Depends(case_path)]
RunPath = Annotated[UUID, Depends(run_path)]
SourcePath = Annotated[UUID, Depends(source_path)]
RevisionPath = Annotated[UUID, Depends(revision_path)]
MemberPath = Annotated[UUID, Depends(member_path)]
RunQuery = Annotated[UUID | None, Depends(run_query)]
RevisionQuery = Annotated[UUID, Depends(revision_query)]
VisibleCase = Annotated[Standing, Depends(visible_case)]
