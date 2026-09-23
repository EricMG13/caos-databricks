"""Explicit attempt identity and bounded, caller-safe execution read units.

On the canonical LITE route through the canonical executor (slice f-1a)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import _url_for, priced
from conftest import reserve_at as reserve
from fake_chat import PRICE, ScriptedChat, answer, fake_completions
from langchain_core.messages import AIMessage
from psycopg.pq import TransactionStatus
from test_loop_charges import (
    ESTIMATE,
    MODEL,
    REPORTED,
    VENDORED,
    _Completions,
    ready,
    route,
)

import caos.store as store
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph.route import ResolvedRoute, RouteNode
from caos.graph.runtime import Execution, ProviderResult, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import execute_handoff
from caos.methodology.executor import Assignment
from caos.methodology.runner import ModuleProvider
from caos.pricing import ModelPrice
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, apply_schema, connect
from caos.store.events import RunEvent, events_of, lock_run
from caos.store.outcomes import CallOutcome, record_outcome
from caos.store.runs import (
    Accepted,
    accept_attempt,
    cancel_run,
    create_case,
    fail_run,
    run_status,
    start_attempt,
    start_run,
)
from caos.store.work import (
    Lease,
    claim_run,
    enqueue_run,
    mark_work_done,
    release,
    request_cancel,
    requeue_run,
    require_lease,
    stop,
)

__all__ = ["ready", "route"]


@pytest.fixture
def provider(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> ModuleProvider:
    conn, run, source, blobs = ready
    return ModuleProvider(
        conn,
        Bundle(VENDORED),
        blobs,
        _Completions(source),
        route,
        run,
    )


def _reserve(provider: ModuleProvider, node: RouteNode) -> UUID:
    attempt = start_attempt(provider.conn, provider.run_id, node.route_node_id)
    reserve(provider.conn, attempt, ESTIMATE)
    return attempt


def _invoke(
    provider: ModuleProvider,
    attempt: UUID,
    entry: str,
    node: RouteNode,
    module: str | None = None,
) -> None:
    module = node.module_id if module is None else module
    if entry == "runtime":
        run_route(
            provider.conn,
            provider.blobs,
            run_id=provider.run_id,
            route=provider.route,
            execution=Execution(provider, priced(ESTIMATE), provider.bundle),
        )
    elif entry == "module":
        provider.execute(node.route_node_id, module, attempt_id=attempt)
    else:
        execute_handoff(
            provider.conn,
            provider.bundle,
            provider.blobs,
            assignment=Assignment(
                module, provider.run_id, node, provider.route, attempt
            ),
            provider=provider.completions,
        )


def _fault(
    provider: ModuleProvider, node: RouteNode, attempt: UUID, fault: str
) -> tuple[ModuleProvider, UUID, RouteNode, str]:
    module = node.module_id
    conn = provider.conn
    if fault == "run":
        provider = replace(provider, run_id=uuid4())
    elif fault == "node":
        node = replace(node, route_node_id="wrong-node")
    elif fault == "module":
        module = "CP-1"
    elif fault == "missing":
        attempt = uuid4()
    elif fault == "unreserved":
        attempt = start_attempt(conn, provider.run_id, node.route_node_id)
    elif fault == "terminal":
        fail_run(conn, provider.run_id)
    elif fault == "used":
        record_outcome(conn, attempt_id=attempt, outcome=CallOutcome(None, None, None))
    elif fault == "ledger":
        conn.execute(
            "INSERT INTO budget_ledger (attempt_id,run_id,amount) VALUES (%s,%s,0)",
            (attempt, provider.run_id),
        )
    else:
        conn.execute(
            "INSERT INTO artifacts (attempt_id,run_id,case_id,artifact_sha256,model,"
            " generation_id) SELECT %s,run_id,case_id,%s,'legacy','legacy'"
            " FROM runs WHERE run_id=%s",
            (attempt, "a" * 64, provider.run_id),
        )
    conn.commit()
    return provider, attempt, node, module


def _accepted(result: ProviderResult) -> Accepted:
    return Accepted(
        result.artifact_sha256,
        result.charge,
        result.model,
        result.generation_id,
        diagnostic_sha256=result.diagnostic_sha256,
        record_sha256=result.record_sha256,
    )


def test_two_attempts_are_attributed_explicitly_and_transport_reads_are_idle(
    provider: ModuleProvider,
) -> None:
    first, second = provider.route.nodes[:2]
    a1, a2 = _reserve(provider, first), _reserve(provider, second)
    answers = provider.completions
    conn = provider.conn

    def reply(prompt: str) -> AIMessage:
        content = answers.complete(prompt, json_object=True).content or ""
        # An answer billed no output is a count never stated (ST-11); one
        # output token at a zero output rate still bills exactly REPORTED.
        return answer(content, finish="stop", tokens=(1, 1))

    def idle() -> None:
        assert conn.info.transaction_status is TransactionStatus.IDLE

    chat = ScriptedChat(answer=reply, before=idle)
    # One input token at REPORTED per token: the ledger records exactly REPORTED.
    provider = replace(
        provider,
        completions=fake_completions(
            chat,
            model=MODEL,
            price=ModelPrice(MODEL, REPORTED, Decimal(0), PRICE.as_of),
        ),
    )
    result = provider.execute(first.route_node_id, first.module_id, attempt_id=a1)
    accept_attempt(provider.conn, attempt_id=a1, accepted=_accepted(result))
    result = provider.execute(second.route_node_id, second.module_id, attempt_id=a2)
    with connect(_url_for(provider.conn.info.dbname)) as observer:
        assert observer.execute(
            "SELECT attempt_id,amount FROM budget_ledger ORDER BY charged_at"
        ).fetchall() == [(a1, REPORTED), (a2, REPORTED)]
        assert observer.execute(
            "SELECT attempt_id FROM call_outcomes ORDER BY recorded_at"
        ).fetchall() == [(a1,), (a2,)]
        assert observer.execute("SELECT attempt_id FROM artifacts").fetchall() == [
            (a1,)
        ]
    accept_attempt(provider.conn, attempt_id=a2, accepted=_accepted(result))
    assert provider.conn.info.transaction_status is TransactionStatus.IDLE
    assert provider.conn.execute(
        "SELECT attempt_id,amount FROM budget_ledger ORDER BY charged_at"
    ).fetchall() == [(a1, REPORTED), (a2, REPORTED)]
    assert chat.calls == 2
    assert "--- UPSTREAM" in chat.prompts[1]


@pytest.mark.parametrize("entry", ["module", "executor"])
@pytest.mark.parametrize(
    "fault,code",
    [
        ("run", "ATTEMPT_NOT_FOUND"),
        ("node", "ATTEMPT_NOT_FOUND"),
        ("module", "ROUTE_IDENTITY_INVALID"),
        ("missing", "ATTEMPT_NOT_FOUND"),
        ("unreserved", "BUDGET_NOT_RESERVED"),
        ("used", "CALL_OUTCOME_CONFLICT"),
        ("ledger", "CALL_OUTCOME_LEGACY"),
        ("artifact", "CALL_OUTCOME_LEGACY"),
        ("terminal", "RUN_NOT_RUNNING"),
    ],
)
def test_invalid_or_used_attempt_cannot_reach_completion(
    provider: ModuleProvider,
    entry: str,
    fault: str,
    code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_call refuses before either evidence or upstream context is read."""
    from caos.methodology import canonical, executor

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid attempt reached evidence or upstream reads")

    monkeypatch.setattr(executor, "read_run_blocks", forbidden)
    monkeypatch.setattr(canonical, "_identity", forbidden)
    node = provider.route.nodes[0]
    attempt = _reserve(provider, node)
    actual_run = provider.run_id
    conn = provider.conn
    provider, attempt, node, module = _fault(provider, node, attempt, fault)
    with connect(_url_for(conn.info.dbname)) as blocker:
        if fault == "run":
            lock_run(blocker, actual_run)
            conn.execute("SET lock_timeout = '100ms'")
            conn.commit()
        with pytest.raises(Refusal, match=f"^{code}$"):
            _invoke(provider, attempt, entry, node, module)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert isinstance(provider.completions, _Completions)
    assert provider.completions.prompts == []


@pytest.mark.parametrize("entry", ["runtime", "module", "executor"])
@pytest.mark.parametrize(
    "state", ["pending", "autocommit", "repeatable", "serializable"]
)
def test_execution_refuses_unowned_transaction_without_touching_pending_writes(
    provider: ModuleProvider,
    entry: str,
    state: str,
) -> None:
    """require_idle preserves caller writes; isolation checks own only new reads."""
    conn = provider.conn
    node = provider.route.nodes[0]
    attempt = _reserve(provider, node)
    if state == "pending":
        conn.execute("UPDATE cases SET title = 'pending caller work'")
    elif state == "autocommit":
        conn.autocommit = True
    else:
        conn.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if state == "repeatable"
            else psycopg.IsolationLevel.SERIALIZABLE
        )
    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        _invoke(provider, attempt, entry, node)
    if state == "pending":
        assert conn.info.transaction_status is TransactionStatus.INTRANS
        assert conn.execute("SELECT title FROM cases").fetchone() == (
            "pending caller work",
        )
        with connect(_url_for(conn.info.dbname)) as observer:
            assert observer.execute("SELECT title FROM cases").fetchone() != (
                "pending caller work",
            )
    else:
        assert conn.info.transaction_status is TransactionStatus.IDLE
    assert isinstance(provider.completions, _Completions)
    assert provider.completions.prompts == []
    conn.rollback()


@pytest.mark.parametrize("entry", ["runtime", "module", "executor"])
def test_failed_successful_read_cleanup_closes_before_call(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    node = provider.route.nodes[0]
    attempt = _reserve(provider, node)

    def broken(conn: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    monkeypatch.setattr(psycopg.Connection, "rollback", broken)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        _invoke(provider, attempt, entry, node)
    assert provider.conn.closed
    assert isinstance(provider.completions, _Completions)
    assert provider.completions.prompts == []


@pytest.mark.parametrize("stage", ["delivery", "upstream", "frontier"])
@pytest.mark.parametrize("broken_cleanup", [False, True])
def test_owned_pretransport_read_failure_cleans_up_without_call(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    broken_cleanup: bool,
) -> None:
    """execution_reads releases its unit or closes when its own cleanup fails."""
    from caos.graph import runtime
    from caos.methodology import canonical, executor

    dsn = _url_for(provider.conn.info.dbname)

    def fail(*args: object, **kwargs: object) -> None:
        provider.conn.execute("SELECT 1")
        if broken_cleanup:
            monkeypatch.setattr(psycopg.Connection, "rollback", broken)
        raise psycopg.OperationalError("private")

    def broken(conn: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    owner, name = {
        "delivery": (executor, "read_run_blocks"),
        # The host identity is the store read that derives the upstream refs.
        "upstream": (canonical, "_identity"),
        "frontier": (runtime, "accepted_artifacts"),
    }[stage]
    monkeypatch.setattr(owner, name, fail)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert caught.value.__cause__ is None
    assert (
        provider.conn.closed
        or provider.conn.info.transaction_status is TransactionStatus.IDLE
    )
    assert isinstance(provider.completions, _Completions)
    assert provider.completions.prompts == []
    monkeypatch.undo()
    with connect(dsn) as observer:
        assert observer.execute("SELECT count(*) FROM budget_ledger").fetchone() == (0,)


# --- Slice 4.3a: the run work queue (brief D2-D4) ---------------------------

WORKER = BoundaryText.of("worker-a")


@pytest.fixture
def work_run(
    case: tuple[StoreConnection, UUID],
) -> tuple[StoreConnection, UUID, UUID]:
    """A RUNNING run with no work row, committed, and its case."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    return conn, run_id, case_id


def _work(conn: StoreConnection, run_id: UUID) -> tuple[object, ...] | None:
    row = conn.execute(
        "SELECT state, lease_token, worker, stop_code, cancel_requested_at IS NOT NULL"
        " FROM run_work WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    conn.rollback()
    return row


def _expire(conn: StoreConnection, run_id: UUID) -> None:
    conn.execute(
        "UPDATE run_work SET lease_expires_at = clock_timestamp() - interval '1 second'"
        " WHERE run_id = %s",
        (run_id,),
    )
    conn.commit()


def test_enqueue_is_idempotent_and_rides_the_callers_transaction(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run_id, case_id = work_run
    assert enqueue_run(conn, run_id) is True
    with connect(_url_for(conn.info.dbname)) as observer:
        assert _work(observer, run_id) is None, "the caller owns the commit"
        conn.rollback()
        assert _work(observer, run_id) is None
        assert enqueue_run(conn, run_id) is True
        assert enqueue_run(conn, run_id) is False
        conn.commit()
        assert _work(observer, run_id) == ("QUEUED", 0, None, None, False)
    assert enqueue_run(conn, run_id) is False
    conn.commit()
    other = start_run(conn, case_id)
    fail_run(conn, other)
    with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
        enqueue_run(conn, other)
    conn.rollback()
    assert _work(conn, other) is None


def test_only_an_expired_or_queued_row_is_claimable_and_each_claim_advances_the_token(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run_id, _case = work_run
    assert claim_run(conn, worker=WORKER, lease_seconds=60) is None
    enqueue_run(conn, run_id)
    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        claim_run(conn, worker=WORKER, lease_seconds=60)
    conn.commit()
    with pytest.raises(Refusal, match=r"^BOUNDARY_TEXT_INVALID$"):
        claim_run(conn, worker=BoundaryText.of("é" * 65), lease_seconds=60)
    first = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert first == Lease(run_id, 1, 60)
    assert _work(conn, run_id) == ("CLAIMED", 1, "worker-a", None, False)
    assert claim_run(conn, worker=WORKER, lease_seconds=60) is None, "live lease"
    _expire(conn, run_id)
    second = claim_run(conn, worker=BoundaryText.of("worker-b"), lease_seconds=60)
    assert second == Lease(run_id, 2, 60)
    assert stop(conn, second, RefusalCode.CONTEXT_OVER_CEILING) is True
    conn.commit()
    assert _work(conn, run_id) == ("STOPPED", 2, None, "CONTEXT_OVER_CEILING", False)
    assert claim_run(conn, worker=WORKER, lease_seconds=60) is None, "stopped"
    assert requeue_run(conn, run_id) is True
    assert requeue_run(conn, run_id) is False
    conn.commit()
    third = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert third == Lease(run_id, 3, 60)
    mark_work_done(conn, run_id)
    conn.commit()
    _expire(conn, run_id)
    assert _work(conn, run_id) == ("DONE", 3, None, None, False)
    assert claim_run(conn, worker=WORKER, lease_seconds=60) is None, "done"


def test_a_stale_lease_is_refused_and_a_live_one_renews(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run_id, _case = work_run
    lock_run(conn, run_id)
    assert require_lease(conn, run_id, None) is False, "an unenqueued run is direct"
    enqueue_run(conn, run_id)
    conn.commit()
    stale = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert stale is not None
    _expire(conn, run_id)
    lock_run(conn, run_id)
    assert require_lease(conn, run_id, stale) is False, "same token renews"
    conn.commit()
    assert conn.execute(
        "SELECT lease_expires_at > clock_timestamp() FROM run_work"
    ).fetchone() == (True,)
    conn.rollback()
    _expire(conn, run_id)
    live = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert live is not None and live == Lease(run_id, stale.token + 1, live.seconds)
    for held in (stale, None, Lease(uuid4(), live.token)):
        lock_run(conn, run_id)
        with pytest.raises(Refusal, match=r"^LEASE_NOT_HELD$"):
            require_lease(conn, run_id, held)
        conn.rollback()
    assert release(conn, stale) is False
    assert stop(conn, stale, RefusalCode.RUN_NOT_RUNNING) is False
    lock_run(conn, run_id)
    assert require_lease(conn, run_id, live) is False
    assert release(conn, live) is True
    conn.commit()
    assert _work(conn, run_id) == ("QUEUED", 2, None, None, False)


def test_a_cancel_on_a_queued_run_ends_it_cancelled_once_with_its_event(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run_id, case_id = work_run
    enqueue_run(conn, run_id)
    conn.commit()
    assert request_cancel(conn, run_id) is True
    conn.rollback()
    assert run_status(conn, run_id) is RunStatus.RUNNING, "rides the transaction"
    assert events_of(conn, run_id) == []
    conn.rollback()
    assert request_cancel(conn, run_id) is True
    assert request_cancel(conn, run_id) is False
    conn.commit()
    assert run_status(conn, run_id) is RunStatus.CANCELLED
    assert [e.name for e in events_of(conn, run_id)] == [RunEvent.RUN_CANCELLED.value]
    assert _work(conn, run_id) == ("DONE", 0, None, None, True)
    assert claim_run(conn, worker=WORKER, lease_seconds=60) is None
    # A claimed run records the request and keeps running until its holder acts.
    claimed = start_run(conn, case_id)
    enqueue_run(conn, claimed)
    conn.commit()
    lease = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert lease is not None
    assert request_cancel(conn, claimed) is True
    assert request_cancel(conn, claimed) is False
    conn.commit()
    assert run_status(conn, claimed) is RunStatus.RUNNING
    lock_run(conn, claimed)
    assert require_lease(conn, claimed, lease) is True
    conn.commit()
    assert events_of(conn, claimed) == []
    conn.rollback()
    # A holder that parks the run instead ends it CANCELLED there (MAX-04): the
    # cancel was acknowledged, and a parked run needed a second cancel to end.
    assert stop(conn, lease, RefusalCode.CONTEXT_OVER_CEILING) is True
    conn.commit()
    assert run_status(conn, claimed) is RunStatus.CANCELLED
    assert [e.name for e in events_of(conn, claimed)] == [RunEvent.RUN_CANCELLED.value]
    assert _work(conn, claimed) == ("DONE", lease.token, None, None, True)
    conn.rollback()
    with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
        requeue_run(conn, claimed)
    conn.rollback()
    assert request_cancel(conn, claimed) is False
    conn.rollback()


def test_a_cancel_on_an_abandoned_claimed_run_ends_it_cancelled_now(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """CF-039: a CLAIMED row whose lease has expired is claimable again --
    `claim_run` treats it exactly like QUEUED -- so nobody is coming back to
    read `require_lease` and act on a recorded cancel. A cancel on it must end
    the run now, the same as a QUEUED run, instead of recording a request an
    abandoned holder will never see."""
    conn, run_id, case_id = work_run
    enqueue_run(conn, run_id)
    conn.commit()
    lease = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert lease is not None
    _expire(conn, run_id)
    assert request_cancel(conn, run_id) is True
    conn.commit()
    assert run_status(conn, run_id) is RunStatus.CANCELLED
    assert [e.name for e in events_of(conn, run_id)] == [RunEvent.RUN_CANCELLED.value]
    assert _work(conn, run_id) == ("DONE", lease.token, None, None, True)
    assert request_cancel(conn, run_id) is False
    conn.rollback()
    # A live lease is untouched: only an expired one is treated as abandoned.
    claimed = start_run(conn, case_id)
    enqueue_run(conn, claimed)
    conn.commit()
    live = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert live is not None
    assert request_cancel(conn, claimed) is True
    conn.commit()
    assert run_status(conn, claimed) is RunStatus.RUNNING
    assert events_of(conn, claimed) == []
    conn.rollback()


def test_attempt_refusals_are_write_once_and_never_store_faults(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, run_id, _case = work_run
    attempt = start_attempt(conn, run_id, "CP-0")
    insert = "INSERT INTO attempt_refusals (attempt_id, code) VALUES (%s, %s)"
    for code in ("STORE_UNAVAILABLE", "STORE_SCHEMA_DRIFT", "lower_case", "A" * 65):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, (attempt, code))
        conn.rollback()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(insert, (uuid4(), "CITATION_NOT_LOCATED"))
    conn.rollback()
    conn.execute(insert, (attempt, "CITATION_NOT_LOCATED"))
    conn.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(insert, (attempt, "ROUTE_IDENTITY_INVALID"))
    conn.rollback()
    for mutation in (
        "UPDATE attempt_refusals SET code = 'ROUTE_IDENTITY_INVALID'",
        "DELETE FROM attempt_refusals",
        "TRUNCATE attempt_refusals",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            conn.execute(mutation)
        conn.rollback()
    assert conn.execute("SELECT attempt_id, code FROM attempt_refusals").fetchall() == [
        (attempt, "CITATION_NOT_LOCATED")
    ]
    conn.rollback()


def test_version_thirteen_adds_empty_work_and_keeps_attempts_unleased(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:12])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("before work"))
        run_id = start_run(conn, case_id)
        conn.commit()
        # Rows as version 12 wrote them: the store functions now read run_work.
        attempt = uuid4()
        conn.execute(
            "INSERT INTO run_attempts (attempt_id, run_id, route_node_id, ordinal)"
            " VALUES (%s, %s, 'CP-0', 1)",
            (attempt, run_id),
        )
        conn.execute("UPDATE runs SET status = 'FAILED' WHERE run_id = %s", (run_id,))
        conn.commit()
        apply_schema(conn)
        assert conn.execute(
            "SELECT attempt_id, lease_token FROM run_attempts"
        ).fetchall() == [(attempt, None)]
        assert conn.execute("SELECT count(*) FROM run_work").fetchone() == (0,)
        assert run_status(conn, run_id) is RunStatus.FAILED
        conn.rollback()


def test_the_holder_ends_a_cancel_requested_run_with_cancel_run_once(
    work_run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """`cancel_run` is the holder's fenced transition after a requested cancel:
    one RUN_CANCELLED, the work row DONE, and a stale lease ends nothing."""
    conn, run_id, _case_id = work_run
    enqueue_run(conn, run_id)
    conn.commit()
    lease = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert lease is not None
    assert request_cancel(conn, run_id) is True
    conn.commit()
    with pytest.raises(Refusal) as stale:
        cancel_run(conn, run_id, lease=Lease(run_id, lease.token + 1))
    assert stale.value.code is RefusalCode.LEASE_NOT_HELD

    assert cancel_run(conn, run_id, lease=lease) is True
    assert cancel_run(conn, run_id, lease=lease) is False
    assert run_status(conn, run_id) is RunStatus.CANCELLED
    assert [e.name for e in events_of(conn, run_id)] == [RunEvent.RUN_CANCELLED.value]
    work = _work(conn, run_id)
    assert work is not None and work[0] == "DONE"
