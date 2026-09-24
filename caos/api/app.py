"""The HTTP surface: the section reads, the run tail, and one answer for a
stranger.

Each section read lives in its own module under `caos/api/reads/` (Task 4.1);
the retired run document is now the Run section. The events path is the
socket `caos/api/stream.py`'s contract is served over -- that module already
answers every rule the case stream keeps, and this is where those answers
meet a connection.

The privacy rule is the load-bearing one. A run somebody may not see and a run
that does not exist get the same status and the same body, because 403 is the
informative answer and that is exactly its problem: it confirms the id names
something real. `NOT_AUTHENTICATED` is different in kind -- "I do not know who
you are" discloses nothing about any case -- so it is answered plainly, and a
client that got a 404 for it would retry the wrong thing forever.

Responses are named models with `extra="forbid"` in both directions. A response
shape that let an extra key through is how a store column reaches a browser
because somebody widened a SELECT.

FastAPI's own `/docs`, `/redoc` and `/openapi.json` are not served (Task 4.5
decision 6): Swagger loads a script from a CDN the policy refuses, and a route
map is nothing a browser of this workspace needs. Every request passes
`caos/api/edge.py`'s guard first -- the platform or the loopback rule, the
identity-header hygiene, the Origin check -- before routing or identity.
"""

from __future__ import annotations

import asyncio
import sys
import weakref
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import asynccontextmanager, suppress
from json import dumps
from uuid import UUID

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Receive, Scope, Send

from caos.api import health
from caos.api.commands import cases as cases_command
from caos.api.commands import deliverable as deliverable_command
from caos.api.commands import execution as execution_command
from caos.api.commands import members as members_command
from caos.api.commands import qualification as qualification_command
from caos.api.commands import runs as runs_command
from caos.api.deps import BLOB_ROOT as BLOB_ROOT
from caos.api.deps import DATABASE_URL as DATABASE_URL
from caos.api.deps import IDENTITY_FIRST
from caos.api.deps import VENDORED_BUNDLE as VENDORED_BUNDLE
from caos.api.deps import Blobs as Blobs
from caos.api.deps import Caller as Caller
from caos.api.deps import CasePath as CasePath
from caos.api.deps import Methodology as Methodology
from caos.api.deps import RunQuery as RunQuery
from caos.api.deps import Store as Store
from caos.api.deps import VisibleCase as VisibleCase
from caos.api.deps import _database_url as _database_url
from caos.api.deps import _vendored_bundle as _vendored_bundle
from caos.api.deps import actor_from_request as actor_from_request
from caos.api.deps import blob_store as blob_store
from caos.api.deps import methodology_bundle as methodology_bundle
from caos.api.deps import store_connection as store_connection
from caos.api.edge import EdgeGuard, is_api_path, refusal_body
from caos.api.identity import actor_from_headers
from caos.api.reads import analysis as analysis_read
from caos.api.reads import book as book_read
from caos.api.reads import deliverable as deliverable_read
from caos.api.reads import directory as directory_read
from caos.api.reads import evidence as evidence_read
from caos.api.reads import model as model_read
from caos.api.reads import qualification as qualification_read
from caos.api.reads import reports as reports_read
from caos.api.reads import run as run_read
from caos.api.reads import upload as upload_read
from caos.api.stream import IO_BUDGET as STREAM_IO
from caos.api.stream import (
    StreamEvent,
    StreamSlot,
    case_tail,
    guarded,
    take_stream_slot,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.budget import configured_ceiling

# `GET /api/v1/cases/{case_id}/events`, the one path this module serves: the
# caller's standing and the run's case, then the stream's own connect, cursor
# recheck and first poll (`stream.IO_BUDGET`) -- after which each poll costs
# `POLL_IO` again and each named frame `FRAME_IO`. Measured in
# `tests/test_case_events.py`. The section reads declare their own budgets.
EVENTS_IO_BUDGET = 2 + STREAM_IO
IO_BUDGET = EVENTS_IO_BUDGET
# N35's remainder: the tail streams named store events; it opens no blob.
BLOB_BUDGET = 0

# §9: a tail closes so the edge can reauthenticate. Five minutes, and it lives
# here rather than in `stream.py` because it is a property of the connection
# being held open, which is a thing only the route has.
TAIL_DEADLINE = 300.0
# How long the loop waits before asking again. Short enough that a run finishing
# closes the stream promptly, long enough that an idle watcher is not a query a
# second -- `LISTEN`/`NOTIFY` is the upgrade.
POLL_INTERVAL = 0.5

# What a transient answer promises, in seconds. A constant rather than a
# forecast: the host knows nothing about when its store returns, so this is a
# floor on how often a client may ask again, not a prediction that it will work.
RETRY_AFTER_SECONDS = 5

# The status for every refusal, total over `RefusalCode` the way `CLEARS` is:
# a code a future route raises must not inherit 400 from a lookup default,
# because "your request was wrong" is a claim about the caller and nothing
# chose it. The server's own faults are 5xx: it cannot answer, whoever asks,
# and a 400 would tell the caller their request was the problem.
#
# Which 5xx is the owner's D3 decision (17 September 2026). One status had been
# carrying two claims: "this is not your request's fault" and "come back
# later". Only the second is what 503 means on the wire, so a proxy read every
# server fault as worth retrying, including the ones no amount of retrying
# reaches. The split asks one question per code -- would the identical
# request, later, with nobody doing anything in between, plausibly succeed? --
# and a fault only an operator can repair answers no, because the client's
# waiting is not what repairs it.
#
# The store not answering is the whole of the yes side, with the provider not
# answering beside it since the owner's second half (§88). `STREAM_LIMIT_REACHED`
# joins it for the same reason and not by analogy: the capacity is released by
# a watcher closing a tail, so waiting is exactly what repairs it. Nothing an
# operator does is required. `CONCURRENCY_LIMIT_REACHED` (CF-051) is the same
# shape one level up: the capacity is released by another request finishing,
# not by anything an operator does either. Everything else at 500 is stored
# bytes failing verification against what this server itself wrote, a pinned
# input the run cannot change, or an operator's repair; each `CLEARS` entry
# beside it already says as much in words before the status agreed.
_STATUS = {
    RefusalCode.NOT_AUTHENTICATED: 401,
    # Below the signing floor or not held: one private answer, as for a case.
    RefusalCode.QUALIFICATION_EVIDENCE_NOT_FOUND: 404,
    RefusalCode.RUN_NOT_FOUND: 404,
    RefusalCode.CASE_NOT_FOUND: 404,
    RefusalCode.DELIVERABLE_NOT_FOUND: 404,
    # W1: the filing exists and is proven; the package it would need does not,
    # and nothing the caller or an operator does later brings it into being.
    RefusalCode.DELIVERABLE_PACKAGE_NOT_STORED: 404,
    # Every unavailable evidence page is one private answer (decision 7).
    RefusalCode.PAGE_NOT_AVAILABLE: 404,
    RefusalCode.STORE_NOT_CONFIGURED: 500,
    RefusalCode.STORE_UNAVAILABLE: 503,
    RefusalCode.IDENTITY_UNAVAILABLE: 503,
    RefusalCode.STREAM_LIMIT_REACHED: 503,
    # Answered by the edge guard before routing (CF-051, replacing uvicorn's
    # own `limit_concurrency`); listed here, beside the store's own capacity
    # refusals, so a route could not give it a different status either.
    RefusalCode.CONCURRENCY_LIMIT_REACHED: 503,
    RefusalCode.STORE_NOT_TRANSACTIONAL: 500,
    RefusalCode.STORE_SCHEMA_DRIFT: 500,
    RefusalCode.BLOB_NOT_FOUND: 500,
    RefusalCode.BLOB_DIGEST_MISMATCH: 500,
    RefusalCode.BLOB_ADDRESS_INVALID: 500,
    # A route pin whose identity the host cannot rebuild is stored bytes, and
    # the next read rebuilds the same identity from the same pin, so waiting is
    # not what fixes it. It was filed at 503 by copying a neighbour, since
    # retired (`READINESS_INVALID`), that was wrong the same way.
    RefusalCode.ROUTE_IDENTITY_INVALID: 500,
    # A pinned build whose catalog declares an edge type this engine cannot
    # evaluate: the vendored bytes, not the request. No profile or pathway the
    # caller could name instead would avoid it, and no later attempt teaches
    # the engine the type -- which is the whole of why this is 500 and not the
    # 503 the entry was first written at, under a reading of 503 as blame.
    RefusalCode.ROUTE_EDGE_UNSUPPORTED: 500,
    RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE: 500,
    # A recorded blocking verdict at a node the pinned route does not carry:
    # rows this server wrote disagreeing with pins it wrote (§68).
    RefusalCode.ORCHESTRATION_NODE_NOT_IN_ROUTE: 500,
    # A canonical record that no longer binds its Markdown, pin or bundle is
    # likewise the server's own bytes failing verification.
    RefusalCode.ARTIFACT_RECORD_MISMATCH: 500,
    RefusalCode.RUN_INPUT_INVALID: 500,
    RefusalCode.SOURCE_IDENTITY_INVALID: 500,
    RefusalCode.AUTHORITY_BYTES_MISMATCH: 500,
    # Re-validating an accepted handoff: it passed these under the same pin,
    # so failing now is stored bytes or authority moving, never the request.
    RefusalCode.HANDOFF_MALFORMED: 500,
    RefusalCode.HANDOFF_BLOCKED: 500,
    RefusalCode.HANDOFF_IDENTITY_MISMATCH: 500,
    RefusalCode.HANDOFF_INCOMPLETE: 500,
    RefusalCode.HANDOFF_UNDECLARED_FIELD: 500,
    RefusalCode.HANDOFF_MODULE_UNSUPPORTED: 500,
    RefusalCode.ATTEMPT_NOT_FOUND: 500,
    RefusalCode.AUTHORITY_MODULE_UNKNOWN: 500,
    # A stored block count this build's packing rule does not reproduce: bytes
    # this server wrote read under a rule that has since moved. The same request
    # later meets the same rows and the same rule; re-admission is the discharge.
    RefusalCode.EVIDENCE_PACKING_MISMATCH: 500,
    # A gate cell the host can neither read as a selection nor ignore (§95):
    # an answer the provider already gave, which the same request meets again.
    RefusalCode.EVIDENCE_DEMAND_UNRESOLVED: 500,
    # An exception this server did not anticipate, or an invariant of its own it
    # found broken. It was 400 here while the edge guard answered the same code
    # 500 for an unhandled exception, so its status depended on which layer
    # caught it (§75's upgrade). Permanent: nothing promises the identical
    # request later meets different code. Its clearance -- retry, and
    # investigate if it persists -- stays true, because a 500 forbids no retry;
    # it only promises none, which is what the absent `Retry-After` says.
    RefusalCode.INTERNAL_FAULT: 500,
    # The attempt's own reservation below the request the host rebuilt for it:
    # the host disagreeing with itself, not the caller's request (so not 400),
    # and the same attempt meets the same reservation later (so not 503). A new
    # attempt, which reserves for what it sends, is the discharge.
    RefusalCode.RESERVATION_BELOW_REQUEST: 500,
    # Served only by `_undeclared`, for a path under `/api/` nobody declared;
    # an undeclared method on a declared path is routing's own 405.
    RefusalCode.ENDPOINT_NOT_FOUND: 404,
    # Commands (Task 4.2 decision 8). A member below a command's floor is told
    # so; a stranger never reaches this, being answered CASE_NOT_FOUND first.
    RefusalCode.NOT_AUTHORISED: 403,
    # Answered by the edge guard before routing; listed so a route cannot give
    # either a different status.
    RefusalCode.EDGE_NOT_TRUSTED: 403,
    RefusalCode.ORIGIN_REFUSED: 403,
    RefusalCode.SOURCE_TOO_LARGE: 413,
    # The request was sound and the state it expected has moved: a conflict.
    RefusalCode.IDEMPOTENCY_KEY_REUSED: 409,
    RefusalCode.RUN_NOT_RUNNING: 409,
    RefusalCode.RUN_NOT_BLOCKED: 409,
    RefusalCode.RUN_ALREADY_SUPERSEDED: 409,
    RefusalCode.GATE_APPROVAL_MISMATCH: 409,
    RefusalCode.EVIDENCE_NOT_AVAILABLE: 409,
    RefusalCode.ROUTE_ALREADY_PINNED: 409,
    RefusalCode.ROUTE_PIN_TOO_LATE: 409,
    RefusalCode.RUN_INPUT_ALREADY_PINNED: 409,
    RefusalCode.RUN_INPUT_TOO_LATE: 409,
    RefusalCode.RUN_INPUT_NOT_PINNED: 409,
    RefusalCode.RUN_ALREADY_STARTED: 409,
    RefusalCode.RUN_NOT_STOPPED: 409,
    # The caller's own queue is full (N15): a conflict with state the caller
    # holds, cleared by one of their runs ending or being cancelled -- not a
    # server fault, and no `Retry-After` promises when.
    RefusalCode.QUEUED_RUNS_LIMIT_REACHED: 409,
    RefusalCode.RUN_CANCEL_REQUESTED: 409,
    # One signature per signer per revision (`0029`): the request was sound and
    # the state already holds it, as VERDICT_ALREADY_RECORDED's is.
    RefusalCode.DELIVERABLE_ALREADY_SIGNED: 409,
    RefusalCode.COMMAND_EXPECTATION_STALE: 409,
    RefusalCode.ORCHESTRATION_BUILD_MOVED: 409,
    # Every other code: 400, the status each was already served by the
    # default this table replaced. The map is total so that a code added
    # later cannot inherit "your request was wrong" without being read.
    RefusalCode.BOUNDARY_TEXT_INVALID: 400,
    RefusalCode.BOUNDARY_TEXT_TOO_LONG: 400,
    RefusalCode.LEASE_NOT_HELD: 400,
    RefusalCode.RUN_NODES_UNACCEPTED: 400,
    RefusalCode.RUN_TERMINAL_STALE: 400,
    RefusalCode.ATTEMPT_LIMIT_REACHED: 400,
    RefusalCode.CALL_OUTCOME_INVALID: 400,
    RefusalCode.CALL_OUTCOME_CONFLICT: 400,
    RefusalCode.CALL_OUTCOME_LEGACY: 400,
    RefusalCode.CALL_OUTCOME_UNEXPLAINED: 400,
    RefusalCode.NODE_ALREADY_ACCEPTED: 400,
    RefusalCode.MONEY_NOT_DECIMAL: 400,
    RefusalCode.MONEY_INVALID: 400,
    RefusalCode.BUDGET_ALREADY_RESERVED: 400,
    RefusalCode.BUDGET_NOT_RESERVED: 400,
    RefusalCode.BUDGET_CEILING_REACHED: 400,
    RefusalCode.PROVIDER_NOT_CONFIGURED: 400,
    RefusalCode.PROVIDER_CALL_INVALID: 400,
    RefusalCode.CONTEXT_OVER_CEILING: 400,
    RefusalCode.UPSTREAM_SECTION_OVER_CEILING: 400,
    # The owner's second half of D3 (§88). These answered 400 while their
    # clearances said retry. The provider not answering is cleared by waiting,
    # so 503. The rest are an answer the provider already gave -- truncated,
    # refused or unreadable -- which the identical request later meets again:
    # not the caller's fault (so not 400) and not cleared by waiting (so not
    # 503). A new attempt is the discharge, which is what "Retry the attempt"
    # names.
    RefusalCode.PROVIDER_UNAVAILABLE: 503,
    RefusalCode.PROVIDER_OUTPUT_TRUNCATED: 500,
    RefusalCode.PROVIDER_REFUSED: 500,
    RefusalCode.PROVIDER_RESPONSE_INVALID: 500,
    RefusalCode.EDGE_CONFIG_INVALID: 400,
    RefusalCode.REQUEST_INVALID: 400,
    RefusalCode.IDEMPOTENCY_KEY_REQUIRED: 400,
    RefusalCode.ROUTE_NOT_ENABLED: 400,
    RefusalCode.METHODOLOGY_INPUT_INVALID: 400,
    # W4: the caller's own brief, judged at the pin exactly as CP-DR will read
    # it. `RUN_INPUT_INVALID` stays 500 for the stored input it names.
    RefusalCode.RESEARCH_BRIEF_INVALID: 400,
    RefusalCode.FORECAST_DRIVER_NOT_READY: 400,
    RefusalCode.DELIVERABLE_PAYLOAD_INVALID: 400,
    RefusalCode.NARRATIVE_FIGURE_UNREFERENCED: 400,
    RefusalCode.NARRATIVE_REFERENCE_INVALID: 400,
    RefusalCode.DELIVERABLE_UNCITED_FIGURE: 400,
    RefusalCode.DELIVERABLE_MARKDOWN_UNSUPPORTED: 400,
    RefusalCode.DELIVERABLE_NOT_SIGNED: 400,
    RefusalCode.DELIVERABLE_NOT_FROZEN: 400,
    RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING: 400,
    RefusalCode.DELIVERABLE_ALREADY_FILED: 400,
    RefusalCode.DELIVERABLE_ALREADY_FROZEN: 400,
    RefusalCode.APPROVER_NOT_INDEPENDENT: 400,
    RefusalCode.SOURCE_PACK_EMPTY: 400,
    RefusalCode.SOURCE_NOT_READABLE: 400,
    RefusalCode.SOURCE_ENCRYPTED: 400,
    RefusalCode.SOURCE_HAS_NO_TEXT: 400,
    RefusalCode.SOURCE_EXTRACTION_TIMEOUT: 400,
    RefusalCode.CITATION_NOT_LOCATED: 400,
    RefusalCode.CITATION_AMBIGUOUS: 400,
    RefusalCode.CITATION_NOT_DELIVERED: 400,
    RefusalCode.ROUTE_PROFILE_UNKNOWN: 400,
    RefusalCode.ROUTE_SELECTION_UNKNOWN: 400,
    RefusalCode.ROUTE_EXTENSION_OWNER_MISSING: 400,
    RefusalCode.ROUTE_HAS_A_CYCLE: 400,
    RefusalCode.ROUTE_DUPLICATE_MODULE: 400,
    RefusalCode.QUALIFICATION_SET_EMPTY: 400,
    RefusalCode.QUALIFICATION_KEY_UNANSWERABLE: 400,
    RefusalCode.QUALIFICATION_SET_AMBIGUOUS: 400,
    RefusalCode.QUALIFICATION_KEY_AMBIGUOUS: 400,
    RefusalCode.QUALIFICATION_RUN_MISSING: 400,
    RefusalCode.QUALIFICATION_SET_FILE_INVALID: 400,
    RefusalCode.QUALIFICATION_SET_PATH_ESCAPES: 400,
    RefusalCode.QUALIFICATION_SET_OVER_CEILING: 400,
    RefusalCode.ORCHESTRATION_NOTHING_TO_PROVE: 400,
    RefusalCode.ORCHESTRATION_ROUTE_NOT_PINNED: 400,
    RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED: 400,
    RefusalCode.ORCHESTRATION_CITATION_LOST: 400,
    RefusalCode.VERDICT_INCOMPLETE: 400,
    RefusalCode.VERDICT_BINDING_INVALID: 400,
    RefusalCode.VERDICT_UNDECLARED_FIELD: 400,
    RefusalCode.VERDICT_EXPIRED: 400,
    RefusalCode.VERDICT_ALREADY_RECORDED: 409,
}

# The codes classed transient above: derived from `_STATUS` rather than held
# as a second table, so a code's classification cannot come apart from its own
# status by one of the two being edited and not the other.
TRANSIENT = frozenset(code for code, status in _STATUS.items() if status == 503)


SHUTDOWN_HOOKS: list[Callable[[], None]] = []


def on_shutdown(hook: Callable[[], None]) -> None:
    """Run `hook` when the app shuts down; the process entry drains its worker."""
    SHUTDOWN_HOOKS.append(hook)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply the declared schema before the first request, and refuse to start
    without a database or a readable run ceiling.

    "Postgres schema in full at startup" is the store's rule, and `apply_schema`
    is idempotent -- it advances a verified migration prefix on this fresh
    connection and refuses `STORE_SCHEMA_DRIFT` for unknown or edited history.
    It commits the migration transaction before requests begin. Doing it
    here rather than lazily means a process pointed at the wrong database dies at
    boot instead of serving 500s that look like a bug in the route. A malformed
    `CAOS_RUN_CEILING` (CF-048) is checked the same way here, rather than left
    invisible until the first caller tries to start a run.
    """
    _boot_or_refuse()
    # The one health probe task (slice 4.5b); the route reads what it leaves.
    _app.state.health = health.ProbeState()
    probes = asyncio.create_task(health.probe_loop(_app.state.health))
    try:
        yield
    finally:
        probes.cancel()
        # The process's own shutdown work (the worker drain, DP-4) runs here,
        # inside uvicorn's shutdown, because the signal is re-raised after it.
        for hook in list(SHUTDOWN_HOOKS):
            hook()
        with suppress(asyncio.CancelledError):
            await probes


def _boot_or_refuse() -> None:
    """The store connect and schema, then the run ceiling: a fault in either
    refuses to start, printed as its typed code alone (CF-078, CF-048).

    psycopg's own exception for a connection the driver never opened -- a
    malformed DSN included -- may quote the whole connection string, password
    and all, back in its message; only `code.value` is ever written here. The
    new `Refusal` is raised after the `except` that observed the fault has
    finished, as `caos.api.deps.store_connection` already raises its own, so
    it carries no chained context -- of the driver's or of the ceiling's raw
    value -- for anything downstream to print.
    """
    code: RefusalCode | None = None
    try:
        with connect(_database_url()) as conn:
            apply_schema(conn)
    except Refusal as refused:
        code = refused.code
    except psycopg.Error:
        code = RefusalCode.STORE_UNAVAILABLE
    if code is None:
        try:
            configured_ceiling()
        except Refusal as refused:
            code = refused.code
    if code is None:
        return
    print(code.value, file=sys.stderr)
    raise Refusal(code)


app = FastAPI(
    title="CAOS",
    version="2",
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(EdgeGuard)
# One router per section read (Task 4.1), so each slice adds its route in its
# own module and none edits this one.
for _section in (
    directory_read,
    upload_read,
    run_read,
    analysis_read,
    model_read,
    book_read,
    qualification_read,
    reports_read,
    evidence_read,
    deliverable_read,
):
    app.include_router(_section.router)
app.include_router(health.router)
for _commands in (
    cases_command,
    runs_command,
    execution_command,
    qualification_command,
    members_command,
    deliverable_command,
):
    app.include_router(_commands.router)


def _body(code: RefusalCode, status: int) -> Response:
    """The refusal on the wire, and -- for a transient fault only -- when to ask
    again. The header is keyed on the code rather than on the status so that
    the promise and the classification cannot come apart."""
    return Response(
        status_code=status,
        content=refusal_body(code),
        media_type="application/json",
        headers=(
            {"retry-after": str(RETRY_AFTER_SECONDS)} if code in TRANSIENT else None
        ),
    )


@app.exception_handler(Refusal)
def _refused(_request: Request, refusal: Refusal) -> Response:
    """A refusal on the wire: the code, its constant clearance, and no part of
    what caused it."""
    return _body(refusal.code, _STATUS[refusal.code])


@app.exception_handler(StarletteHTTPException)
async def _undeclared(request: Request, error: StarletteHTTPException) -> Response:
    """Routing's own 404 and 405 under `/api/` answer in the one refusal body.

    Routing decides before any dependency runs, so this discloses no case and
    needs no identity. Outside `/api/`, and for any other status, the default
    stands: that surface is not this contract's.
    """
    if is_api_path(request.url.path) and error.status_code in (404, 405):
        return _body(RefusalCode.ENDPOINT_NOT_FOUND, error.status_code)
    return await http_exception_handler(request, error)


@app.exception_handler(RequestValidationError)
async def _malformed_run_id(
    request: Request, error: RequestValidationError
) -> Response:
    """A run id that cannot be read names no run, and a body that cannot be
    read is an invalid request.

    FastAPI's own 422 answered them before identity, in a body that is not the
    declared refusal and that quotes the input back. So a run id is answered as
    `_visible` answers any run it cannot show: NOT_AUTHENTICATED to a caller
    with no identity, RUN_NOT_FOUND to everyone else. A body (Task 4.2
    decision 5) is REQUEST_INVALID after the same identity check. Any other
    path parameter or a query gets the default until the route that takes one
    says what it should get instead.
    """
    unreadable = {tuple(detail.get("loc") or ())[:2] for detail in error.errors()}
    if unreadable == {("path", "run_id")}:
        code = RefusalCode.RUN_NOT_FOUND
    elif unreadable and all(loc[:1] == ("body",) for loc in unreadable):
        code = RefusalCode.REQUEST_INVALID
    else:
        return await request_validation_exception_handler(request, error)
    try:
        await actor_from_headers(request.headers)
    except Refusal as refusal:
        return _refused(request, refusal)
    return _refused(request, Refusal(code))


@app.get("/api/v1/cases/{case_id}/events", dependencies=[IDENTITY_FIRST])
def read_case_events(
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    _standing: VisibleCase,
    request: Request,
    conn: Store,
) -> StreamingResponse:
    """The case's events as `text/event-stream`, resuming after `Last-Event-ID`.

    The authority read happens before the first byte, so an unauthorised
    watcher gets the private 404 a missing case gets rather than an empty 200.
    Identity, then the path and query parsers and the case's visibility, then
    the store: the order is what keeps an anonymous or malformed request off a
    connection, and standing first means a stranger learns nothing about
    which runs a case holds.
    """
    _owned_run(conn, case_id, run)
    # The slot is taken before the response is built, so a refusal is an
    # ordinary refusal body with a status and a `Retry-After` -- a 503 the
    # client can read. Taken *after* the authority read, so a stranger still
    # learns nothing: a private 404 must not become "the case exists but we are
    # busy". The response gives it back when it ends, however it ends -- a
    # browser going away included (`_TailResponse`, ED-1). Named with the
    # actor, so the cap is a share of the fleet's tails rather than a race for
    # all of them (MX-2).
    slot = take_stream_slot(actor_id=actor.user_id)
    events = guarded(
        case_tail(
            conn,
            case_id=case_id,
            run_id=run,
            actor_id=actor.user_id,
            after=request.headers.get("last-event-id"),
            deadline=TAIL_DEADLINE,
            poll=POLL_INTERVAL,
            heartbeat=True,
        )
    )

    def framed() -> Generator[bytes]:
        try:
            for event in events:
                yield _frame(event)
        finally:
            slot.release()

    tail = framed()
    # The safety net for the one case neither the `finally` above nor the
    # response can reach: a generator that is never started never unwinds, so
    # a response built and then never sent would hold its slot until the
    # process restarted. `StreamSlot.release` is one-shot, so whichever of the
    # three runs first is the one that counts.
    weakref.finalize(tail, slot.release)
    return _TailResponse(tail, slot)


class _TailResponse(StreamingResponse):
    """A tail on the wire, which gives its slot back when the response ends.

    The generator's own `finally` is not enough (ED-1). On a disconnect
    Starlette cancels the task iterating the body; the cancellation's
    traceback keeps `iterate_in_threadpool`'s frame alive in a reference
    cycle, and that frame holds the sync generator -- so its `finally` ran
    only at CPython's next *full* collection, minutes or hours away in a quiet
    App, and four closed tabs spent an actor's whole share on dead tails.

    Here the slot is released and the generator closed in `__call__`'s own
    `finally`, which the disconnect unwinds at once. Closing it is safe: the
    body is pulled with `anyio.to_thread.run_sync`, which shields the await
    until the thread returns, so no thread is inside the generator by the
    time the call has ended.
    """

    def __init__(self, tail: Generator[bytes], slot: StreamSlot) -> None:
        super().__init__(
            tail,
            media_type="text/event-stream",
            # No store, and no proxy buffering: a tail that arrived in one
            # block when the deadline passed would not be a tail.
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )
        self._tail, self._slot = tail, slot

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._slot.release()
            self._tail.close()


def _frame(event: StreamEvent | None) -> bytes:
    """One SSE frame. The cursor frame is `id` and `retry`, which sets the
    browser's `lastEventId` and its reconnect delay and dispatches nothing.
    A named frame's `data` is a placeholder because the spec dispatches no
    event without one. The keepalive (`None`) is a comment, which the
    browser ignores.

    `retry` (N48): `TAIL_DEADLINE` closes every tail, expected reconnects
    included, and with none ever sent the browser's own default reconnect
    delay was the gap a watcher saw -- indistinguishable from a real drop.
    Carried on the cursor frame, the first of any connection, so a fresh
    reconnect after the deadline is as quick as an idle poll would have been.
    """
    if event is None:
        return b":\n\n"
    if event.name is None:
        retry_ms = int(POLL_INTERVAL * 1000)
        return f"retry: {retry_ms}\nid: {event.id}\n\n".encode()
    return f"id: {event.id}\nevent: {event.name}\ndata: {dumps({})}\n\n".encode()


def _owned_run(conn: StoreConnection, case_id: UUID, run_id: UUID | None) -> None:
    """Refuse a run that is not the case's; no run named is nothing to refuse."""
    if run_id is None:
        return
    row = conn.execute(
        "SELECT 1 FROM runs WHERE run_id = %s AND case_id = %s", (run_id, case_id)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
