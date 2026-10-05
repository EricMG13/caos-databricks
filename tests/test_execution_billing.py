"""Provider facts commit before analytical refusal, acceptance or cleanup.

On the canonical LITE route through the canonical executor (slice f-1a)."""

from __future__ import annotations

import hashlib
import io
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import _url_for, priced
from fake_chat import ScriptedChat, StatusError, answer, fake_completions
from langchain_core.messages import AIMessage
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_call_outcomes import _counts
from test_execution_attempts import _invoke, provider, ready, route
from test_loop_charges import ESTIMATE, MODEL, REPORTED, _Completions

from caos.blobs import BlobStore
from caos.evidence.citations import (
    ANY_RUN,
    AnchoredCitation,
    Citation,
    CitationRule,
    TokenIndex,
    verify_citations,
)
from caos.methodology import canonical
from caos.methodology.runner import ModuleProvider
from caos.provider import Completion
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect
from caos.store.outcomes import CallOutcome, record_outcome

__all__ = ["provider", "ready", "route"]

# What `_invoke` reserves each call at, and so -- the charge is the provider's
# own, at the provider's price (CF-089) -- what the provider must charge at:
# nothing an input token, ESTIMATE's worth over the completion cap an output one.
AT_ESTIMATE = priced(ESTIMATE)


def _for_output(tokens: int) -> Decimal:
    """What `tokens` output tokens are billed at `AT_ESTIMATE`, exactly."""
    return tokens * AT_ESTIMATE.output_per_token


def _bill(
    dsn: str, run_id: UUID, charge: Decimal | None, *, status: str = "RUNNING"
) -> UUID:
    [attempt] = _bills(dsn, run_id, charge, 1, status=status)
    return attempt


def _bills(
    dsn: str,
    run_id: UUID,
    charge: Decimal | None,
    calls: int,
    *,
    status: str = "RUNNING",
) -> list[UUID]:
    """`calls` billed attempts, oldest first, each exactly `charge` against its
    own reservation, and nothing accepted. More than one is a node's guided
    retries (D30, D82) after a refusal the checks can explain."""
    with connect(dsn) as observer:
        rows = observer.execute(
            "SELECT o.attempt_id,o.run_id,l.amount,r.amount FROM call_outcomes o"
            " JOIN run_attempts t USING (attempt_id,run_id)"
            " LEFT JOIN budget_ledger l USING (attempt_id,run_id)"
            " JOIN budget_reservations r USING (attempt_id,run_id)"
            " ORDER BY t.ordinal"
        ).fetchall()
        assert len(rows) == calls
        for _attempt, run, amount, reserved in rows:
            assert (run, amount, reserved) == (run_id, charge, ESTIMATE)
        expected = 0 if charge is None else calls
        assert observer.execute("SELECT count(*) FROM budget_ledger").fetchone() == (
            expected,
        )
        assert observer.execute("SELECT count(*) FROM artifacts").fetchone() == (0,)
        assert observer.execute("SELECT status FROM runs").fetchone() == (status,)
        assert (
            observer.execute(
                "SELECT name FROM run_events WHERE name IN"
                " ('CALL_OUTCOME_RECORDED','ATTEMPT_ACCEPTED','RUN_COMPLETE')"
            ).fetchall()
            == [("CALL_OUTCOME_RECORDED",)] * calls
        )
        attempts = [row[0] for row in rows]
        assert all(isinstance(attempt, UUID) for attempt in attempts)
        return attempts


@pytest.mark.parametrize(
    "response,code,charge",
    [
        (answer(), "PROVIDER_OUTPUT_TRUNCATED", _for_output(1500)),
        (answer(finish="content_filter"), "PROVIDER_REFUSED", _for_output(1500)),
        (StatusError(402), "PROVIDER_CALL_INVALID", None),
        (StatusError(503), "PROVIDER_UNAVAILABLE", None),
        (answer(finish="stop"), "HANDOFF_MALFORMED", _for_output(1500)),
        # A request billed no input is a count the provider never stated: the
        # client reads a null or absent one as zero (ST-11). Unknown.
        (answer(tokens=(0, 0)), "PROVIDER_OUTPUT_TRUNCATED", None),
        # An empty answer may bill no output; its input is still a known
        # charge, here at the input rate the run reserved at: zero.
        (answer("", tokens=(1000, 0)), "PROVIDER_OUTPUT_TRUNCATED", Decimal(0)),
        # No generation id: the host mints one and the bill still commits.
        (answer(generation=None), "PROVIDER_OUTPUT_TRUNCATED", _for_output(1500)),
        # No usage: the charge is unknown, never zero.
        (answer(tokens=None), "PROVIDER_OUTPUT_TRUNCATED", None),
        (answer(finish="stop", tokens=None), "PROVIDER_RESPONSE_INVALID", None),
        (
            answer(finish="something-else"),
            "PROVIDER_RESPONSE_INVALID",
            _for_output(1500),
        ),
        (TimeoutError("private"), "PROVIDER_UNAVAILABLE", None),
        (ValueError("private"), "PROVIDER_UNAVAILABLE", None),
    ],
)
def test_native_refusal_records_only_independently_known_money(
    provider: ModuleProvider,
    response: AIMessage | Exception,
    code: str,
    charge: Decimal | None,
) -> None:
    conn = provider.conn

    def idle() -> None:
        assert conn.info.transaction_status is TransactionStatus.IDLE

    chat = ScriptedChat(answer=response, before=idle)
    provider = replace(
        provider, completions=fake_completions(chat, model=MODEL, price=AT_ESTIMATE)
    )
    with pytest.raises(Refusal, match=f"^{code}$") as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert "private" not in str(caught.value) + repr(caught.value)
    assert caught.value.__cause__ is None
    # D30, N52, D82: a refusal the checks can explain earns its node guided
    # retries, each refused the same way here.
    calls = (
        1 + canonical.GUIDED_RETRIES if code in canonical.SECOND_ATTEMPT_CODES else 1
    )
    assert chat.calls == calls
    assert provider.conn.info.transaction_status is TransactionStatus.IDLE
    _bills(_url_for(provider.conn.info.dbname), provider.run_id, charge, calls)


class _UnreadableBody(Exception):
    """A provider error whose `body` cannot be read without raising."""

    @property
    def body(self) -> object:
        raise RuntimeError("private")


class _UnwritableStderr(io.StringIO):
    """A stderr whose reader is gone."""

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "private")


@pytest.mark.parametrize(
    ("failure", "unwritable"),
    [
        pytest.param(ValueError("private"), True, id="stderr-cannot-be-written"),
        pytest.param(_UnreadableBody("private"), False, id="a-body-that-raises"),
        pytest.param(ValueError({"code": 10**5000}), False, id="a-code-str-refuses"),
    ],
)
def test_a_failing_diagnostic_never_changes_the_recorded_outcome(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    unwritable: bool,
) -> None:
    """F513's stderr line is a fail-open: whatever its facts or its write
    raise, the call is refused PROVIDER_UNAVAILABLE and its outcome recorded
    exactly as before the line existed (ST-8), never an untyped raise ahead
    of the bill."""
    chat = ScriptedChat(answer=failure)
    provider = replace(
        provider, completions=fake_completions(chat, model=MODEL, price=AT_ESTIMATE)
    )
    if unwritable:
        monkeypatch.setattr(sys, "stderr", _UnwritableStderr())
    with pytest.raises(Refusal, match=r"^PROVIDER_UNAVAILABLE$"):
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    monkeypatch.undo()
    assert chat.calls == 1
    _bills(_url_for(provider.conn.info.dbname), provider.run_id, None, 1)


# D106: a citation fault is no analysis failure any more, so "citation" left.
@pytest.mark.parametrize("failure", ["envelope", "readiness", "blob"])
def test_analysis_failure_preserves_bill_and_exact_replay(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    completions = provider.completions
    assert isinstance(completions, _Completions)
    if failure == "envelope":
        completions.content = "private"
    elif failure == "readiness":
        completions.readiness = {"CP-5": "NOT-A-STATUS"}

    def broken_blob(self: BlobStore, data: bytes) -> str:
        raise OSError("synthetic")

    if failure == "blob":
        monkeypatch.setattr(BlobStore, "put", broken_blob)
    codes = {
        "envelope": "HANDOFF_MALFORMED",
        "readiness": "HANDOFF_INCOMPLETE",
        # The response body could not be stored as the call's diagnostic.
        "blob": "STORE_UNAVAILABLE",
    }
    with pytest.raises(Refusal) as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert str(caught.value) == codes[failure]
    assert provider.conn.info.transaction_status is TransactionStatus.IDLE
    dsn = _url_for(provider.conn.info.dbname)
    # D30, N52, D82: a refusal the checks can explain earns guided retries,
    # each refused the same way.
    explained = codes[failure] in canonical.SECOND_ATTEMPT_CODES
    calls = 1 + canonical.GUIDED_RETRIES if explained else 1
    attempts = _bills(dsn, provider.run_id, REPORTED, calls)
    attempt = attempts[-1]
    assert len(completions.bodies) == calls
    body = completions.bodies[-1]
    diagnostic = (
        None if failure == "blob" else hashlib.sha256(body.encode()).hexdigest()
    )
    facts = CallOutcome(REPORTED, MODEL, "gen-loop-test", diagnostic)
    assert not record_outcome(provider.conn, attempt_id=attempt, outcome=facts)
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
        record_outcome(
            provider.conn, attempt_id=attempt, outcome=replace(facts, charge=None)
        )
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
        _invoke(provider, attempt, "module", provider.route.nodes[0])
    assert isinstance(provider.completions, _Completions)
    assert len(provider.completions.prompts) == calls
    assert _bills(dsn, provider.run_id, REPORTED, calls) == attempts


@pytest.mark.parametrize("stored", ["markdown", "record"])
def test_a_blob_write_failing_after_analysis_keeps_the_bill_and_accepts_nothing(
    provider: ModuleProvider, monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    """The runner stores the accepted Markdown and its record after the whole
    analysis passed: a write that fails there is a typed store fault, with the
    bill and diagnostic already committed and nothing accepted."""
    real = BlobStore.put
    marker = b"---\n" if stored == "markdown" else b'"format":"caos-canonical-record'

    def put(self: BlobStore, data: bytes) -> str:
        if data.startswith(marker) or (stored == "record" and marker in data):
            raise OSError("synthetic")
        return real(self, data)

    monkeypatch.setattr(BlobStore, "put", put)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert caught.value.__cause__ is None
    assert provider.conn.info.transaction_status is TransactionStatus.IDLE
    completions = provider.completions
    assert isinstance(completions, _Completions)
    assert len(completions.prompts) == 1
    attempt = _bill(_url_for(provider.conn.info.dbname), provider.run_id, REPORTED)
    [body] = completions.bodies
    facts = CallOutcome(
        REPORTED, MODEL, "gen-loop-test", hashlib.sha256(body.encode()).hexdigest()
    )
    assert not record_outcome(provider.conn, attempt_id=attempt, outcome=facts)


@pytest.mark.parametrize(
    "failure,broken_cleanup,code",
    [
        ("sql", False, "STORE_UNAVAILABLE"),
        ("sql", True, "STORE_UNAVAILABLE"),
        # Evidence that will not read, not a citation fault, which since
        # D106 leaves a citation unverified rather than refusing.
        ("refusal", False, "EVIDENCE_NOT_AVAILABLE"),
        ("refusal", True, "EVIDENCE_NOT_AVAILABLE"),
        ("success", True, "STORE_UNAVAILABLE"),
    ],
)
def test_postbilling_citation_cleanup_preserves_money_and_original_refusal(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    broken_cleanup: bool,
    code: str,
) -> None:
    dsn = _url_for(provider.conn.info.dbname)

    def broken(conn: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    def fault(
        conn: StoreConnection,
        *,
        delivered: Mapping[UUID, frozenset[str]],
        citations: Sequence[Citation],
        index: TokenIndex | None = None,
        rule: CitationRule = ANY_RUN,
    ) -> list[AnchoredCitation]:
        anchored = verify_citations(
            conn, delivered=delivered, citations=citations, index=index, rule=rule
        )
        if broken_cleanup:
            monkeypatch.setattr(psycopg.Connection, "rollback", broken)
        if failure == "sql":
            conn.execute("SELECT missing_private_column")
        elif failure == "refusal":
            raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)
        return anchored

    monkeypatch.setattr(canonical, "verify_citations", fault)
    with pytest.raises(Refusal, match=f"^{code}$") as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert caught.value.__cause__ is None
    assert (
        provider.conn.closed
        or provider.conn.info.transaction_status is TransactionStatus.IDLE
    )
    assert isinstance(provider.completions, _Completions)
    # No refusal here earns a guided retry (D106 took anchoring's out).
    calls = 1
    assert len(provider.completions.prompts) == calls
    monkeypatch.undo()
    _bills(dsn, provider.run_id, REPORTED, calls)


@pytest.mark.parametrize("broken_cleanup", [False, True])
def test_failed_outcome_persistence_refuses_before_blob_storage(
    provider: ModuleProvider,
    monkeypatch: pytest.MonkeyPatch,
    broken_cleanup: bool,
) -> None:
    dsn = _url_for(provider.conn.info.dbname)
    provider.conn.execute("ALTER TABLE call_outcomes ADD CHECK (false)")
    provider.conn.commit()
    completions = provider.completions
    assert isinstance(completions, _Completions)
    original = completions.complete
    bodies = completions.bodies

    def broken(conn: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    def complete(prompt: str, *, json_object: bool = False) -> Completion:
        result = original(prompt, json_object=json_object)
        if broken_cleanup:
            monkeypatch.setattr(psycopg.Connection, "rollback", broken)
        return result

    real_put = BlobStore.put

    def forbidden(self: BlobStore, data: bytes) -> str:
        # Only the response body is addressed before billing, as its diagnostic.
        if data == bodies[-1].encode():
            return real_put(self, data)
        pytest.fail("failed billing reached blob storage")

    monkeypatch.setattr(completions, "complete", complete)
    monkeypatch.setattr(BlobStore, "put", forbidden)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert caught.value.__cause__ is None
    assert provider.conn.closed is broken_cleanup
    assert (
        broken_cleanup
        or provider.conn.info.transaction_status is TransactionStatus.IDLE
    )
    assert isinstance(provider.completions, _Completions)
    assert len(provider.completions.prompts) == 1
    monkeypatch.undo()
    with connect(dsn) as observer:
        assert _counts(observer) == (0, 0, 0)
        assert observer.execute(
            "SELECT amount FROM budget_reservations"
        ).fetchall() == [(ESTIMATE,)]
        assert observer.execute("SELECT status FROM runs").fetchone() == ("RUNNING",)


def test_late_known_refusal_is_billed_after_inflight_run_cancellation(
    provider: ModuleProvider,
) -> None:
    dsn = _url_for(provider.conn.info.dbname)
    run_id = provider.run_id

    def cancel_in_flight() -> None:
        with connect(dsn) as cancellation:
            cancellation.execute("SET lock_timeout = '1s'")
            assert fail_run(cancellation, run_id)

    chat = ScriptedChat(answer=answer(), before=cancel_in_flight)
    provider = replace(
        provider, completions=fake_completions(chat, model=MODEL, price=AT_ESTIMATE)
    )
    with pytest.raises(Refusal, match=r"^PROVIDER_OUTPUT_TRUNCATED$"):
        _invoke(provider, uuid4(), "runtime", provider.route.nodes[0])
    assert chat.calls == 1
    assert provider.conn.info.transaction_status is TransactionStatus.IDLE
    _bill(dsn, provider.run_id, _for_output(1500), status="FAILED")
