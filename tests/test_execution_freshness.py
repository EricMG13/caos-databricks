"""Post-transport authority is fresh before analysis or acceptance.

On the canonical LITE route through the canonical executor (slice f-1a)."""

from __future__ import annotations

import hashlib
import re
import shutil
import traceback
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import _url_for, approve_run, priced, tamper
from conftest import reserve_at as reserve
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_loop_charges import (
    ESTIMATE,
    MODEL,
    REPORT,
    REPORTED,
    VENDORED,
    _Completions,
    route,
)

from caos import methodology
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, RouteNode
from caos.graph.runtime import Execution, Provider, ProviderResult, run_route
from caos.methodology import canonical, handoff, invocation
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.methodology.canonical import execute_handoff
from caos.methodology.executor import Assignment
from caos.methodology.handoff import (
    Projections,
    UpstreamRef,
    _decoded_record,
    record_bytes,
)
from caos.methodology.runner import ModuleProvider
from caos.provider import Completion, CompletionProvider, encode_request
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect
from caos.store.events import RunEvent, append, lock_run
from caos.store.gates import (
    Gate,
    GateApproval,
    approve_gate,
    approved_run_input,
    execution_input,
    gate_preview,
    withdraw_source,
)
from caos.store.members import Standing, grant, revoke
from caos.store.outcomes import (
    CallOutcome,
    check_attempt,
    record_outcome,
)
from caos.store.runs import (
    Accepted,
    accept_attempt,
    block_run,
    create_case,
    start_attempt,
    start_run,
)

__all__ = ["route"]


@dataclass(frozen=True, slots=True)
class _Harness:
    conn: StoreConnection
    case_id: UUID
    run_id: UUID
    source_id: UUID
    witness_id: UUID
    blobs: BlobStore
    route: ResolvedRoute
    bundle: Bundle
    approver: UUID
    # Fixed at setup: an observer must still reach a connection closed by the
    # code under test.
    url: str


@pytest.fixture
def harness(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    conn, case_id = case
    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    blobs = BlobStore(tmp_path / "blobs")
    source_id, witness_id = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(filename=BoundaryText.of("report.txt"), data=REPORT),
            Document(
                filename=BoundaryText.of("uncited.txt"),
                data=b"Captured but deliberately not delivered.\n",
            ),
        ],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    approver = approve_run(
        conn, case_id=case_id, run_id=run_id, route=route, bundle=bundle
    )
    return _Harness(
        conn,
        case_id,
        run_id,
        source_id,
        witness_id,
        blobs,
        route,
        bundle,
        approver,
        _url_for(conn.info.dbname),
    )


def _revoke_during_transport(harness: _Harness) -> None:
    with connect(harness.url) as other:
        revoke(other, case_id=harness.case_id, user_id=harness.approver)
        other.commit()
        assert other.execute(
            "SELECT revoked_at IS NOT NULL FROM case_members"
            " WHERE case_id=%s AND user_id=%s",
            (harness.case_id, harness.approver),
        ).fetchone() == (True,)


@dataclass
class _DuringCompletion:
    delegate: _Completions
    mutate: Callable[[], None]
    calls: int = 0
    model: str = MODEL

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return self.delegate.request_bytes(prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        assert self.delegate.model == self.model
        assert self.calls == 0
        self.calls += 1
        self.mutate()
        return self.delegate.complete(prompt, json_object=json_object)


def _counts(harness: _Harness) -> tuple[int, list[Decimal], int, int, int]:
    with connect(harness.url) as observer:
        outcomes = observer.execute("SELECT count(*) FROM call_outcomes").fetchone()
        charges = observer.execute("SELECT amount FROM budget_ledger").fetchall()
        artifacts = observer.execute("SELECT count(*) FROM artifacts").fetchone()
        attempts = observer.execute("SELECT count(*) FROM run_attempts").fetchone()
        reservations = observer.execute(
            "SELECT count(*) FROM budget_reservations"
        ).fetchone()
    assert outcomes is not None and artifacts is not None
    assert attempts is not None and reservations is not None
    return (
        int(outcomes[0]),
        [row[0] for row in charges],
        int(artifacts[0]),
        int(attempts[0]),
        int(reservations[0]),
    )


def test_module_provider_rechecks_authority_after_transport_before_envelope_or_blob(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OLD-API RED: current code analyzes and stores after a real revocation.

    Only the call's diagnostic body is stored (§42.3); no handoff or record."""
    node = harness.route.nodes[0]
    attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
    reserve(harness.conn, attempt, ESTIMATE)
    completion = _DuringCompletion(
        _Completions(harness.source_id), lambda: _revoke_during_transport(harness)
    )
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completion,
        harness.route,
        harness.run_id,
    )
    before = {path for path in harness.blobs.root.rglob("*") if path.is_file()}
    validations = 0
    original: Callable[..., Projections] = handoff.validate_markdown

    def counted(*args: object, **kwargs: object) -> Projections:
        nonlocal validations
        validations += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(canonical, "validate_markdown", counted)
    code = None
    try:
        provider.execute(node.route_node_id, node.module_id, attempt_id=attempt)
    except Refusal as refused:
        code = refused.code
    added = {path for path in harness.blobs.root.rglob("*") if path.is_file()} - before
    [body] = completion.delegate.bodies

    assert (
        code,
        completion.calls,
        validations,
        added,
        _counts(harness),
    ) == (
        RefusalCode.GATE_APPROVAL_MISMATCH,
        1,
        0,
        {harness.blobs.path_of(hashlib.sha256(body.encode()).hexdigest())},
        (1, [REPORTED], 0, 1, 1),
    )


@dataclass
class _ArbitraryProvider:
    harness: _Harness
    mutate: Callable[[], None]
    calls: int = 0
    model: str = MODEL

    def check_context(self, route_node_id: str, module_id: str) -> int:
        # No prompt is built here, so there are no request bytes to price.
        return 0

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        assert self.harness.conn.info.transaction_status is TransactionStatus.IDLE
        assert (route_node_id, module_id) == (
            self.harness.route.nodes[0].route_node_id,
            self.harness.route.nodes[0].module_id,
        )
        assert isinstance(attempt_id, UUID)
        self.calls += 1
        digest = self.harness.blobs.put(b"arbitrary bytes")
        self.mutate()
        # A provider bills its own call before returning, as the real one does.
        record_outcome(
            self.harness.conn,
            attempt_id=attempt_id,
            outcome=CallOutcome(REPORTED, MODEL, "gen-arbitrary"),
        )
        return ProviderResult(digest, REPORTED, MODEL, "gen-arbitrary")


def test_runtime_rechecks_authority_after_transport_before_acceptance(
    harness: _Harness,
) -> None:
    """OLD-API RED: current runtime accepts the stale arbitrary result."""
    provider = _ArbitraryProvider(harness, lambda: _revoke_during_transport(harness))
    code = None
    try:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(provider, priced(ESTIMATE), harness.bundle),
        )
    except Refusal as refused:
        code = refused.code

    with connect(harness.url) as observer:
        accepted = observer.execute(
            "SELECT count(*) FROM run_events WHERE name='ATTEMPT_ACCEPTED'"
        ).fetchone()
        completed = observer.execute(
            "SELECT count(*) FROM run_events WHERE name='RUN_COMPLETE'"
        ).fetchone()
    assert accepted is not None and completed is not None
    assert (
        code,
        provider.calls,
        _counts(harness),
        int(accepted[0]),
        int(completed[0]),
    ) == (
        RefusalCode.GATE_APPROVAL_MISMATCH,
        1,
        (1, [REPORTED], 0, 1, 1),
        0,
        0,
    )


@contextmanager
def _guard_disabled(
    conn: StoreConnection,
    table: str,
    trigger: str,
) -> Iterator[None]:
    assert re.fullmatch(r"caos_test_[0-9a-f]{32}", conn.info.dbname)
    enabled = conn.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s",
        (table, trigger),
    ).fetchone()
    assert enabled == ("O",)
    conn.execute(
        psycopg.sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
            psycopg.sql.Identifier(table), psycopg.sql.Identifier(trigger)
        )
    )
    try:
        yield
    finally:
        conn.execute(
            psycopg.sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(
                psycopg.sql.Identifier(table), psycopg.sql.Identifier(trigger)
            )
        )
    assert conn.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s",
        (table, trigger),
    ).fetchone() == ("O",)


def _actor_change(
    harness: _Harness, gate: Gate, *, downgrade: bool
) -> Callable[[], None]:
    actor = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=actor,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    preview = gate_preview(harness.conn, harness.run_id, gate)
    harness.conn.rollback()
    approve_gate(
        harness.conn,
        GateApproval(
            harness.run_id,
            gate,
            actor,
            preview.preview_sha256,
            preview.input_fingerprint,
        ),
    )

    def change() -> None:
        with connect(harness.url) as other:
            if downgrade:
                grant(
                    other,
                    case_id=harness.case_id,
                    user_id=actor,
                    standing=Standing.READER,
                )
            else:
                revoke(other, case_id=harness.case_id, user_id=actor)
            other.commit()
            assert other.execute(
                "SELECT standing,revoked_at IS NOT NULL FROM case_members"
                " WHERE case_id=%s AND user_id=%s",
                (harness.case_id, actor),
            ).fetchone() == (("READER", False) if downgrade else ("APPROVER", True))

    return change


def _corrupt_input(harness: _Harness, *, remove: bool) -> None:
    with connect(harness.url) as other:
        with _guard_disabled(other, "run_inputs", "input_immutable"):
            if remove:
                changed = other.execute(
                    "DELETE FROM run_inputs WHERE run_id=%s", (harness.run_id,)
                ).rowcount
            else:
                changed = other.execute(
                    "UPDATE run_inputs SET research_json='{}' WHERE run_id=%s",
                    (harness.run_id,),
                ).rowcount
            assert changed == 1
        other.commit()


def _corrupt_route(harness: _Harness) -> None:
    with connect(harness.url) as other:
        with _guard_disabled(other, "run_routes", "route_immutable"):
            assert (
                other.execute(
                    "UPDATE run_routes SET resolved='{}' WHERE run_id=%s",
                    (harness.run_id,),
                ).rowcount
                == 1
            )
        other.commit()


def _mutation(  # noqa: C901
    harness: _Harness, name: str, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], None]:
    if name.startswith("actor_"):
        state, gate = name.removeprefix("actor_").split("_", 1)
        return _actor_change(harness, Gate(gate), downgrade=state == "downgraded")

    def change() -> None:  # noqa: C901
        if name == "bundle_moved":
            manifest = harness.bundle.root / MANIFEST_NAME
            manifest.write_bytes(manifest.read_bytes() + b" ")
            return
        if name == "adapter_mismatch":
            monkeypatch.setattr(methodology, "CANONICAL_ADAPTER_VERSION", "changed")
            return
        if name == "input_missing":
            _corrupt_input(harness, remove=True)
            return
        if name == "input_corrupt":
            _corrupt_input(harness, remove=False)
            return
        if name == "route_corrupt":
            _corrupt_route(harness)
            return
        with connect(harness.url) as other:
            if name.startswith("gate_"):
                state, gate = name.removeprefix("gate_").split("_", 1)
                if state == "missing":
                    changed = other.execute(
                        "DELETE FROM run_gates WHERE run_id=%s AND gate=%s",
                        (harness.run_id, gate),
                    ).rowcount
                else:
                    changed = other.execute(
                        "UPDATE run_gates SET preview_sha256=%s"
                        " WHERE run_id=%s AND gate=%s",
                        ("0" * 64, harness.run_id, gate),
                    ).rowcount
                assert changed == 1
                other.commit()
            elif name.startswith("withdraw_"):
                source = (
                    harness.source_id if name.endswith("cited") else harness.witness_id
                )
                withdraw_source(
                    other,
                    case_id=harness.case_id,
                    source_id=source,
                    actor_id=harness.approver,
                )
            elif name.startswith("identity_"):
                source = (
                    harness.source_id if name.endswith("cited") else harness.witness_id
                )
                assert (
                    other.execute(
                        "UPDATE sources SET document_sha256=%s WHERE case_id=%s"
                        " AND source_id=%s",
                        ("0" * 64, harness.case_id, source),
                    ).rowcount
                    == 1
                )
                other.commit()
            elif name == "failed":
                assert fail_run(other, harness.run_id)
            else:
                assert name == "blocked"
                assert block_run(other, harness.run_id)

    return change


def _invoke_after_transport(
    harness: _Harness, entry: str, mutate: Callable[[], None]
) -> tuple[Refusal | None, int]:
    if entry == "module":
        node = harness.route.nodes[0]
        attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
        reserve(harness.conn, attempt, ESTIMATE)
        completion = _DuringCompletion(_Completions(harness.source_id), mutate)
        provider = ModuleProvider(
            harness.conn,
            harness.bundle,
            harness.blobs,
            completion,
            harness.route,
            harness.run_id,
        )
        try:
            provider.execute(node.route_node_id, node.module_id, attempt_id=attempt)
        except Refusal as refused:
            return refused, completion.calls
        return None, completion.calls
    arbitrary = _ArbitraryProvider(harness, mutate)
    try:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(arbitrary, priced(ESTIMATE), harness.bundle),
        )
    except Refusal as refused:
        return refused, arbitrary.calls
    return None, arbitrary.calls


_CHANGES = [
    ("gate_missing_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("gate_mismatch_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("gate_missing_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("gate_mismatch_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_revoked_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_downgraded_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_revoked_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_downgraded_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("withdraw_cited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("withdraw_uncited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("identity_cited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("identity_uncited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("input_missing", RefusalCode.RUN_INPUT_INVALID),
    ("input_corrupt", RefusalCode.RUN_INPUT_INVALID),
    ("route_corrupt", RefusalCode.ROUTE_IDENTITY_INVALID),
    ("failed", RefusalCode.RUN_NOT_RUNNING),
    ("blocked", RefusalCode.RUN_NOT_RUNNING),
    ("bundle_moved", RefusalCode.AUTHORITY_BYTES_MISMATCH),
    ("adapter_mismatch", RefusalCode.RUN_INPUT_INVALID),
]


@pytest.mark.parametrize("entry", ["module", "runtime"])
@pytest.mark.parametrize("change,expected", _CHANGES)
def test_check_attempt_and_runtime_recheck_transport_authority_before_use(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
    change: str,
    expected: RefusalCode,
) -> None:
    """`check_attempt` and the runtime boundary reject stale returned work."""
    refused, calls = _invoke_after_transport(
        harness, entry, _mutation(harness, change, monkeypatch)
    )
    assert refused is not None
    assert (refused.code, str(refused), refused.__cause__, calls) == (
        expected,
        expected.value,
        None,
        1,
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    with connect(harness.url) as observer:
        accepted = observer.execute(
            "SELECT count(*) FROM run_events WHERE name='ATTEMPT_ACCEPTED'"
        ).fetchone()
        status = observer.execute(
            "SELECT status FROM runs WHERE run_id=%s", (harness.run_id,)
        ).fetchone()
    assert accepted == (0,)
    expected_status = {"failed": "FAILED", "blocked": "BLOCKED"}.get(change, "RUNNING")
    assert status == (expected_status,)
    # F02: a post-call refusal never manufactures a completion of its own.
    assert _events(harness, "RUN_COMPLETE") == 0


def _events(harness: _Harness, name: str) -> int:
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM run_events WHERE name=%s", (name,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def _free(harness: _Harness, table: str) -> bool:
    """Whether an independent connection can lock this case or run row now."""
    column = {"cases": "case_id", "runs": "run_id"}[table]
    key = harness.case_id if table == "cases" else harness.run_id
    with connect(harness.url) as other:
        try:
            other.execute(
                psycopg.sql.SQL(
                    "SELECT 1 FROM {} WHERE {}=%s FOR UPDATE NOWAIT"
                ).format(psycopg.sql.Identifier(table), psycopg.sql.Identifier(column)),
                (key,),
            )
        except psycopg.errors.LockNotAvailable:
            return False
        finally:
            other.rollback()
    return True


def _lockable(harness: _Harness) -> tuple[bool, bool]:
    """(case lock free, run lock free), each probed on its own connection."""
    return _free(harness, "cases"), _free(harness, "runs")


def _still_running(harness: _Harness) -> None:
    """F02: a refused post-call path leaves the run RUNNING, never COMPLETE."""
    with connect(harness.url) as observer:
        status = observer.execute(
            "SELECT status FROM runs WHERE run_id=%s", (harness.run_id,)
        ).fetchone()
    assert (status, _events(harness, "RUN_COMPLETE")) == (("RUNNING",), 0)


def _provider(
    harness: _Harness,
    completions: CompletionProvider,
    route: ResolvedRoute | None = None,
) -> ModuleProvider:
    return ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        route or harness.route,
        harness.run_id,
    )


def _reserved(harness: _Harness) -> UUID:
    node = harness.route.nodes[0]
    attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
    reserve(harness.conn, attempt, ESTIMATE)
    return attempt


def test_the_module_provider_commits_its_bill_before_it_returns(
    harness: _Harness,
) -> None:
    """`Provider.execute`'s contract, on the only implementation that ships.

    The loop no longer records the outcome after the call, so a provider that
    returned without billing would lose that call to the next crash: nothing
    would match `replay_billed` or `unexplained_charge`, and the node would be
    paid for twice. An independent connection is what proves the row is
    committed by the time `execute` returns, not merely written.
    """
    node = harness.route.nodes[0]
    attempt = _reserved(harness)
    result = _provider(harness, _Completions(harness.source_id)).execute(
        node.route_node_id, node.module_id, attempt_id=attempt
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    with connect(harness.url) as observer:
        outcome = observer.execute(
            "SELECT model, generation_id, diagnostic_sha256 FROM call_outcomes"
            " WHERE attempt_id = %s",
            (attempt,),
        ).fetchone()
    assert outcome == (result.model, result.generation_id, result.diagnostic_sha256)


def _blob_files(harness: _Harness) -> set[Path]:
    return {path for path in harness.blobs.root.rglob("*") if path.is_file()}


def test_module_provider_control_analyzes_in_one_locked_read_committed_unit(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unmutated control: transport idle and unlocked; bill committed, then one
    READ COMMITTED unit holds the lock through identity, input and validation."""
    from caos.methodology import executor

    stamps: list[tuple[str, object]] = []
    during: list[tuple[object, ...]] = []

    def stamp(name: str, wrapped: Callable[..., object]) -> Callable[..., object]:
        def inner(conn: StoreConnection, *args: object, **kwargs: object) -> object:
            result = wrapped(conn, *args, **kwargs)
            row = conn.execute("SELECT transaction_timestamp()").fetchone()
            stamps.append((name, row))
            return result

        return inner

    def validate(*args: object, **kwargs: object) -> Projections:
        conn = harness.conn
        during.append(
            (
                conn.info.transaction_status,
                conn.execute("SHOW transaction_isolation").fetchone(),
                _counts(harness)[:2],
                _lockable(harness),
            )
        )
        return original(*args, **kwargs)

    original: Callable[..., Projections] = handoff.validate_markdown
    monkeypatch.setattr(canonical, "check_attempt", stamp("check", check_attempt))
    monkeypatch.setattr(executor, "execution_input", stamp("input", execution_input))
    monkeypatch.setattr(canonical, "validate_markdown", validate)
    idle_unlocked: list[tuple[object, tuple[bool, bool]]] = []
    completion = _DuringCompletion(
        _Completions(harness.source_id),
        lambda: idle_unlocked.append(
            (harness.conn.info.transaction_status, _lockable(harness))
        ),
    )
    attempt = _reserved(harness)
    before = _blob_files(harness)
    node = harness.route.nodes[0]

    result = _provider(harness, completion).execute(
        node.route_node_id, node.module_id, attempt_id=attempt
    )

    # The diagnostic body, the Markdown and the record.
    assert (result.charge, result.model, len(_blob_files(harness) - before)) == (
        REPORTED,
        MODEL,
        3,
    )
    assert idle_unlocked == [(TransactionStatus.IDLE, (True, True))]
    # Pre-call input read, then one post-billing unit: check and input share a
    # transaction the pre-call read did not.
    assert [name for name, _ in stamps] == ["input", "check", "input"]
    assert stamps[1][1] == stamps[2][1] != stamps[0][1]
    assert during == [
        (
            TransactionStatus.INTRANS,
            ("read committed",),
            (1, [REPORTED]),
            (False, False),
        )
    ]
    assert (harness.conn.info.transaction_status, _lockable(harness)) == (
        TransactionStatus.IDLE,
        (True, True),
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


def test_runtime_control_accepts_every_node_without_duplicating_outcomes(
    harness: _Harness,
) -> None:
    """The outer record of a ModuleProvider result is an exact replay."""
    completions = _Completions(harness.source_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _provider(harness, completions), priced(ESTIMATE), harness.bundle
        ),
    )

    nodes = len(harness.route.nodes)
    assert _counts(harness) == (nodes, [REPORTED] * nodes, nodes, nodes, nodes)
    assert [
        _events(harness, name)
        for name in ("CALL_OUTCOME_RECORDED", "ATTEMPT_ACCEPTED", "RUN_COMPLETE")
    ] == [nodes, nodes, 1]


def test_whole_route_mismatch_keeping_the_node_is_refused(
    harness: _Harness,
) -> None:
    """A different route holding the same node never becomes analysis."""
    other = replace(harness.route, predicates=(("changed", "route"),))
    assert harness.route.nodes[0] in other.nodes and other != harness.route

    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    node = harness.route.nodes[0]
    attempt = _reserved(harness)
    with pytest.raises(Refusal) as module:
        _provider(harness, completion, other).execute(
            node.route_node_id, node.module_id, attempt_id=attempt
        )
    assert (module.value.code, completion.calls) == (
        RefusalCode.ROUTE_IDENTITY_INVALID,
        0,
    )
    assert _counts(harness) == (0, [], 0, 1, 1)

    arbitrary = _ArbitraryProvider(harness, lambda: None)
    with pytest.raises(Refusal) as runtime:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=other,
            execution=Execution(arbitrary, priced(ESTIMATE), harness.bundle),
        )
    assert (runtime.value.code, arbitrary.calls) == (
        RefusalCode.ROUTE_IDENTITY_INVALID,
        0,
    )
    assert _counts(harness) == (0, [], 0, 1, 1)
    _still_running(harness)


def _assignment(harness: _Harness, attempt: UUID) -> Assignment:
    node = harness.route.nodes[0]
    return Assignment(node.module_id, harness.run_id, node, harness.route, attempt)


def test_direct_executor_refuses_a_mismatched_module_before_any_call(
    harness: _Harness,
) -> None:
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    assignment = _assignment(harness, _reserved(harness))

    with pytest.raises(Refusal) as module:
        execute_handoff(
            harness.conn,
            harness.bundle,
            harness.blobs,
            assignment=replace(assignment, module_id="CP-L10"),
            provider=completion,
        )
    assert (module.value.code, completion.calls) == (
        RefusalCode.ROUTE_IDENTITY_INVALID,
        0,
    )
    assert _counts(harness) == (0, [], 0, 1, 1)
    assert harness.conn.info.transaction_status is TransactionStatus.IDLE
    _still_running(harness)


def test_direct_executor_refuses_a_moved_node_before_any_call(
    harness: _Harness,
) -> None:
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    assignment = _assignment(harness, _reserved(harness))
    moved = replace(assignment.node, stage=assignment.node.stage + 7)
    with pytest.raises(Refusal) as node:
        execute_handoff(
            harness.conn,
            harness.bundle,
            harness.blobs,
            assignment=replace(assignment, node=moved),
            provider=completion,
        )
    assert (node.value.code, completion.calls, _counts(harness)) == (
        RefusalCode.ROUTE_IDENTITY_INVALID,
        0,
        (0, [], 0, 1, 1),
    )


@dataclass
class _RefusedCompletion:
    mutate: Callable[[], None]
    model: str = MODEL
    calls: int = 0

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        self.calls += 1
        self.mutate()
        return Completion(
            content=None,
            charge=REPORTED,
            generation_id="gen-refused",
            refusal=RefusalCode.PROVIDER_REFUSED,
        )


def test_known_provider_refusal_keeps_precedence_over_stale_authority(
    harness: _Harness,
) -> None:
    completion = _RefusedCompletion(lambda: _revoke_during_transport(harness))
    node = harness.route.nodes[0]
    attempt = _reserved(harness)
    with pytest.raises(Refusal) as refused:
        _provider(harness, completion).execute(
            node.route_node_id, node.module_id, attempt_id=attempt
        )
    assert (refused.value.code, refused.value.__cause__, completion.calls) == (
        RefusalCode.PROVIDER_REFUSED,
        None,
        1,
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    _still_running(harness)


def _fail_in_analysis(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, failure: Callable[[], None]
) -> Refusal | BaseException:
    from caos.methodology import executor

    original = execution_input

    reads = 0

    def failing(conn: StoreConnection, run_id: UUID, bundle: Bundle) -> object:
        nonlocal reads
        reads += 1
        result = original(conn, run_id, bundle)
        if reads == 2:  # The post-billing read, not the pre-call one.
            failure()
        return result

    monkeypatch.setattr(executor, "execution_input", failing)
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    node = harness.route.nodes[0]
    attempt = _reserved(harness)
    provider = _provider(harness, completion)
    with pytest.raises(BaseException) as caught:
        provider.execute(node.route_node_id, node.module_id, attempt_id=attempt)
    assert completion.calls == 1
    return caught.value


def test_native_sql_error_after_billing_is_sanitized_and_leaves_the_bill(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def divide() -> None:
        harness.conn.execute("SELECT 1/0")

    raised = _fail_in_analysis(harness, monkeypatch, divide)
    assert isinstance(raised, Refusal)
    assert (raised.code, raised.__cause__, harness.conn.info.transaction_status) == (
        RefusalCode.STORE_UNAVAILABLE,
        None,
        TransactionStatus.IDLE,
    )
    assert (_counts(harness), _lockable(harness)) == (
        (1, [REPORTED], 0, 1, 1),
        (True, True),
    )
    _still_running(harness)


def test_cancellation_in_analysis_propagates_and_leaves_the_bill(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cancel() -> None:
        raise KeyboardInterrupt

    raised = _fail_in_analysis(harness, monkeypatch, cancel)
    assert type(raised) is KeyboardInterrupt
    assert harness.conn.info.transaction_status is TransactionStatus.IDLE
    assert (_counts(harness), _lockable(harness)) == (
        (1, [REPORTED], 0, 1, 1),
        (True, True),
    )
    _still_running(harness)


def test_rollback_failure_closes_and_keeps_the_typed_refusal(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_and_break_rollback() -> None:
        def broken() -> None:
            raise psycopg.OperationalError

        monkeypatch.setattr(harness.conn, "rollback", broken)
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)

    raised = _fail_in_analysis(harness, monkeypatch, refuse_and_break_rollback)
    assert isinstance(raised, Refusal)
    assert (raised.code, harness.conn.closed) == (RefusalCode.HANDOFF_MALFORMED, True)
    assert (_counts(harness), _lockable(harness)) == (
        (1, [REPORTED], 0, 1, 1),
        (True, True),
    )
    _still_running(harness)


@dataclass
class _Charged:
    """An arbitrary Provider answering every node with one fixed call fact."""

    model = "a-model/for-the-test"

    harness: _Harness
    charge: Decimal | None
    mutate: Callable[[], None] = lambda: None

    def check_context(self, route_node_id: str, module_id: str) -> int:
        # No prompt is built here, so there are no request bytes to price.
        return 0

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        assert self.harness.conn.info.transaction_status is TransactionStatus.IDLE
        digest = self.harness.blobs.put(b"arbitrary bytes")
        self.mutate()
        # A provider bills its own call before returning, as the real one does;
        # an unknown charge is recorded as unknown exposure, without spend.
        record_outcome(
            self.harness.conn,
            attempt_id=attempt_id,
            outcome=CallOutcome(self.charge, MODEL, f"gen-{route_node_id}"),
        )
        return ProviderResult(digest, self.charge, MODEL, f"gen-{route_node_id}")  # type: ignore[arg-type]


def _run(harness: _Harness, provider: Provider) -> RefusalCode | None:
    try:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(provider, priced(ESTIMATE), harness.bundle),
        )
    except Refusal as refused:
        assert refused.__cause__ is None
        return refused.code
    return None


def test_unknown_charge_is_recorded_without_spend_and_never_accepted(
    harness: _Harness,
) -> None:
    assert _run(harness, _Charged(harness, None)) is RefusalCode.MONEY_NOT_DECIMAL
    assert _counts(harness) == (1, [], 0, 1, 1)
    assert [_events(harness, n) for n in ("ATTEMPT_ACCEPTED", "RUN_COMPLETE")] == [
        0,
        0,
    ]


def test_zero_charge_is_known_spend_and_replay_never_duplicates(
    harness: _Harness,
) -> None:
    free = _Completions(harness.source_id, charge=Decimal("0"))
    assert _run(harness, _provider(harness, free)) is None
    nodes = len(harness.route.nodes)
    assert _counts(harness) == (nodes, [Decimal("0")] * nodes, nodes, nodes, nodes)

    attempt = harness.conn.execute(
        "SELECT attempt_id FROM run_attempts ORDER BY started_at LIMIT 1"
    ).fetchone()
    harness.conn.rollback()
    assert attempt is not None
    diagnostic = hashlib.sha256(free.bodies[0].encode()).hexdigest()
    replay = CallOutcome(Decimal("0"), MODEL, free.generation_id, diagnostic)
    assert record_outcome(harness.conn, attempt_id=attempt[0], outcome=replay) is False
    with pytest.raises(Refusal) as conflict:
        record_outcome(
            harness.conn,
            attempt_id=attempt[0],
            outcome=replace(replay, charge=REPORTED),
        )
    assert conflict.value.code is RefusalCode.CALL_OUTCOME_CONFLICT
    assert _counts(harness) == (nodes, [Decimal("0")] * nodes, nodes, nodes, nodes)
    assert _events(harness, "CALL_OUTCOME_RECORDED") == nodes


def test_outcome_persistence_failure_accepts_nothing_and_keeps_the_reservation(
    harness: _Harness,
) -> None:
    def hide_outcomes() -> None:
        with connect(harness.url) as other:
            assert re.fullmatch(r"caos_test_[0-9a-f]{32}", other.info.dbname)
            other.execute("ALTER TABLE call_outcomes RENAME TO call_outcomes_hidden")
            other.commit()

    try:
        code = _run(harness, _Charged(harness, REPORTED, hide_outcomes))
    finally:
        with connect(harness.url) as other:
            other.execute("ALTER TABLE call_outcomes_hidden RENAME TO call_outcomes")
            other.commit()

    assert (code, harness.conn.info.transaction_status) == (
        RefusalCode.STORE_UNAVAILABLE,
        TransactionStatus.IDLE,
    )
    assert _counts(harness) == (0, [], 0, 1, 1)
    assert [
        _events(harness, n) for n in ("CALL_OUTCOME_RECORDED", "ATTEMPT_ACCEPTED")
    ] == [0, 0]
    _still_running(harness)


def test_guard_is_restored_when_the_guarded_change_fails(harness: _Harness) -> None:
    with connect(harness.url) as other:
        with pytest.raises(ValueError):
            with _guard_disabled(other, "run_routes", "route_immutable"):
                raise ValueError
        assert other.execute(
            "SELECT tgenabled FROM pg_trigger"
            " WHERE tgrelid='run_routes'::regclass AND tgname='route_immutable'"
        ).fetchone() == ("O",)
        other.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            other.execute(
                "UPDATE run_routes SET resolved='{}' WHERE run_id=%s",
                (harness.run_id,),
            )


def test_accept_boundary_refuses_authority_revoked_after_the_runtime_check(
    harness: _Harness,
) -> None:
    """A revocation committed after the runtime check refuses at acceptance."""
    attempt = _reserved(harness)
    record_outcome(
        harness.conn,
        attempt_id=attempt,
        outcome=CallOutcome(REPORTED, MODEL, "gen-accept"),
    )
    _revoke_during_transport(harness)
    digest = harness.blobs.put(b"{}")
    with pytest.raises(Refusal) as refused:
        accept_attempt(
            harness.conn,
            attempt_id=attempt,
            accepted=Accepted(
                digest, REPORTED, MODEL, "gen-accept", record_sha256=digest
            ),
        )
    assert (refused.value.code, refused.value.__cause__) == (
        RefusalCode.GATE_APPROVAL_MISMATCH,
        None,
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _events(harness, "ATTEMPT_ACCEPTED") == 0
    _still_running(harness)


def _billed(harness: _Harness, node: str | None = None) -> tuple[UUID, Accepted]:
    """A reserved attempt whose bill is already committed, and its acceptance."""
    node = node or harness.route.nodes[0].route_node_id
    attempt = start_attempt(harness.conn, harness.run_id, node)
    reserve(harness.conn, attempt, ESTIMATE)
    record_outcome(
        harness.conn, attempt_id=attempt, outcome=CallOutcome(REPORTED, MODEL, "gen")
    )
    # A canonical pin accepts only with a record; acceptance reads neither blob.
    accepted = Accepted(harness.blobs.put(b"{}"), REPORTED, MODEL, "gen")
    return attempt, replace(accepted, record_sha256=harness.blobs.put(b"record"))


def _accept_refused(harness: _Harness, attempt: UUID, accepted: Accepted) -> object:
    try:
        return accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)
    except Refusal as refused:
        assert refused.__cause__ is None
        return refused.code


_AT_ACCEPT = [
    ("gate_mismatch_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("gate_missing_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_revoked_SOURCE_SET", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("actor_downgraded_RESEARCH_PLAN", RefusalCode.GATE_APPROVAL_MISMATCH),
    ("withdraw_cited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("withdraw_uncited", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ("input_missing", RefusalCode.RUN_INPUT_INVALID),
    ("input_corrupt", RefusalCode.RUN_INPUT_INVALID),
    ("route_corrupt", RefusalCode.ROUTE_IDENTITY_INVALID),
    ("failed", False),
    ("blocked", False),
]


@pytest.mark.parametrize("change,expected", _AT_ACCEPT)
def test_accept_refuses_what_changed_after_the_bill_committed(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    expected: object,
) -> None:
    """Governed and terminal changes committed after the bill never reach an
    artifact; the bill stays."""
    attempt, accepted = _billed(harness)
    _mutation(harness, change, monkeypatch)()
    assert _accept_refused(harness, attempt, accepted) == expected
    assert harness.conn.info.transaction_status is TransactionStatus.IDLE
    assert (_counts(harness), _lockable(harness)) == (
        (1, [REPORTED], 0, 1, 1),
        (True, True),
    )
    assert _events(harness, "ATTEMPT_ACCEPTED") == 0
    if change in {"failed", "blocked"}:
        with connect(harness.url) as observer:
            status = observer.execute(
                "SELECT status FROM runs WHERE run_id=%s", (harness.run_id,)
            ).fetchone()
        assert status == (change.upper(),)
        assert _events(harness, "RUN_" + change.upper()) == 1
    else:
        _still_running(harness)


@pytest.mark.parametrize("terminal", [None, block_run])
def test_exact_replay_never_rechecks_authority_or_duplicates(
    harness: _Harness, terminal: Callable[[StoreConnection, UUID], bool] | None
) -> None:
    attempt, accepted = _billed(harness)
    assert accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)
    if terminal is not None:
        assert terminal(harness.conn, harness.run_id)
    _revoke_during_transport(harness)
    assert accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted) is False
    with pytest.raises(Refusal) as conflict:
        accept_attempt(
            harness.conn,
            attempt_id=attempt,
            accepted=replace(accepted, artifact_sha256="c" * 64),
        )
    assert conflict.value.code is RefusalCode.CALL_OUTCOME_CONFLICT
    assert _counts(harness) == (1, [REPORTED], 1, 1, 1)
    assert _events(harness, "ATTEMPT_ACCEPTED") == 1


def test_accept_waits_for_a_case_lock_holder_then_sees_its_revocation(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holder takes the case lock after the bill commits, so the wait lands
    on acceptance's own lock rather than the bill replay."""
    from test_case_ordering import _wait_for_blocking

    attempt, accepted = _billed(harness)
    harness.conn.execute("SET statement_timeout = '5s'")
    harness.conn.commit()
    released: list[Future[None]] = []

    def release(holder: StoreConnection) -> None:
        _wait_for_blocking(holder, harness.conn)
        holder.commit()

    with connect(harness.url) as holder, ThreadPoolExecutor(max_workers=1) as pool:

        def billed(
            conn: StoreConnection, *, attempt_id: UUID, outcome: CallOutcome
        ) -> bool:
            result = record_outcome(conn, attempt_id=attempt_id, outcome=outcome)
            revoke(holder, case_id=harness.case_id, user_id=harness.approver)
            released.append(pool.submit(release, holder))
            return result

        monkeypatch.setattr("caos.store.runs.record_outcome", billed)
        seen = _accept_refused(harness, attempt, accepted)
        released[0].result(timeout=6)
    assert seen == RefusalCode.GATE_APPROVAL_MISMATCH
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _events(harness, "ATTEMPT_ACCEPTED") == 0
    _still_running(harness)


def test_accept_holds_the_case_lock_from_the_authority_check_to_the_insert(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revocation started after the check waits, and the insert shares the
    check's transaction, so it cannot commit in between."""
    from test_case_ordering import _wait_for_blocking

    attempt, accepted = _billed(harness)
    revoking: list[Future[None]] = []
    unit: list[object] = []
    with connect(harness.url) as other, ThreadPoolExecutor(max_workers=1) as pool:
        other.execute("SET statement_timeout = '5s'")
        other.commit()

        def revoke_now() -> None:
            revoke(other, case_id=harness.case_id, user_id=harness.approver)
            other.commit()

        def checked(conn: StoreConnection, run_id: UUID) -> object:
            result = approved_run_input(conn, run_id)
            unit.append(conn.execute("SELECT pg_current_xact_id()").fetchone())
            revoking.append(pool.submit(revoke_now))
            _wait_for_blocking(conn, other)
            return result

        def inserted(conn: StoreConnection, run_id: UUID, event: RunEvent) -> None:
            # Same transaction as the check, so its lock was never released.
            assert unit == [conn.execute("SELECT pg_current_xact_id()").fetchone()]
            append(conn, run_id, event)

        monkeypatch.setattr("caos.store.runs.approved_run_input", checked)
        monkeypatch.setattr("caos.store.runs.append", inserted)
        assert accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)
        revoking[0].result(timeout=6)
    assert _counts(harness) == (1, [REPORTED], 1, 1, 1)
    assert _events(harness, "ATTEMPT_ACCEPTED") == 1


@pytest.mark.parametrize("failure", ["sql", "interrupt"])
def test_failure_inside_accept_leaves_the_bill_and_no_artifact(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    attempt, accepted = _billed(harness)

    def failing(conn: StoreConnection, run_id: UUID) -> object:
        approved_run_input(conn, run_id)
        if failure == "sql":
            conn.execute("SELECT 1/0")
        raise KeyboardInterrupt

    monkeypatch.setattr("caos.store.runs.approved_run_input", failing)
    with pytest.raises(Refusal if failure == "sql" else KeyboardInterrupt) as raised:
        accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)
    if isinstance(raised.value, Refusal):
        assert (raised.value.code, raised.value.__cause__) == (
            RefusalCode.STORE_UNAVAILABLE,
            None,
        )
    assert harness.conn.closed or (
        harness.conn.info.transaction_status is TransactionStatus.IDLE
    )
    assert (_counts(harness), _lockable(harness)) == (
        (1, [REPORTED], 0, 1, 1),
        (True, True),
    )
    assert _events(harness, "ATTEMPT_ACCEPTED") == 0
    _still_running(harness)


def test_accept_refuses_a_node_outside_the_stored_route(harness: _Harness) -> None:
    attempt, accepted = _billed(harness, "NOT-A-ROUTE-NODE")
    assert _accept_refused(harness, attempt, accepted) == (
        RefusalCode.ROUTE_IDENTITY_INVALID
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _events(harness, "ATTEMPT_ACCEPTED") == 0
    _still_running(harness)


# Task17e: the host derives delivered context and upstream from the pins.


def _admit_unpinned(harness: _Harness, *, other_case: bool) -> None:
    """A document admitted after the run was pinned, here or in another case."""
    case_id = (
        create_case(harness.conn, BoundaryText.of("Another case"))
        if other_case
        else harness.case_id
    )
    admit_pack(
        harness.conn,
        harness.blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("late.txt"), data=b"UNPINNED\n")],
    )
    harness.conn.commit()


@pytest.mark.parametrize("other_case", [False, True])
def test_module_provider_never_delivers_a_block_outside_the_captured_set(
    harness: _Harness, other_case: bool
) -> None:
    _admit_unpinned(harness, other_case=other_case)
    completions = _Completions(harness.source_id)
    node = harness.route.nodes[0]
    attempt = _reserved(harness)
    _provider(harness, completions).execute(
        node.route_node_id, node.module_id, attempt_id=attempt
    )
    [prompt] = completions.prompts
    assert "UNPINNED" not in prompt


def test_direct_executor_derives_its_context_from_the_pins(harness: _Harness) -> None:
    """Evidence is every captured block and the gate is asked about exactly the
    stored route's other modules: nothing a caller could hand in. (The gate has
    no predecessors; upstream derivation is proven by the identity tests.)"""
    completions = _Completions(harness.source_id)
    execute_handoff(
        harness.conn,
        harness.bundle,
        harness.blobs,
        assignment=_assignment(harness, _reserved(harness)),
        provider=completions,
    )
    [prompt] = completions.prompts
    assert str(harness.source_id) in prompt and str(harness.witness_id) in prompt
    assert "no others: CP-5, CP-L10\n" in prompt


def _accepted_gate(
    harness: _Harness,
    record_fields: dict[str, str] | None = None,
    projected: dict[str, object] | None = None,
    /,
    **identity: object,
) -> str:
    """Run and accept CP-0 for real; identity and record fields override its
    record's."""
    gate = harness.route.nodes[0]
    attempt = _reserved(harness)
    result = _provider(harness, _Completions(harness.source_id)).execute(
        gate.route_node_id, gate.module_id, attempt_id=attempt
    )
    assert result.record_sha256 is not None
    record = result.record_sha256
    if identity or record_fields or projected:
        stored = _decoded_record(harness.blobs.get(record))
        moved = replace(stored.identity, **identity)  # type: ignore[arg-type]
        foreign = replace(stored, identity=moved, **(record_fields or {}))  # type: ignore[arg-type]
        shown = replace(stored.projections, **(projected or {}))  # type: ignore[arg-type]
        foreign = replace(foreign, projections=shown)
        record = harness.blobs.put(record_bytes(foreign))
    accepted = Accepted(
        result.artifact_sha256,
        result.charge,
        result.model,
        result.generation_id,
        diagnostic_sha256=result.diagnostic_sha256,
        record_sha256=record,
    )
    assert accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)
    return result.artifact_sha256


def _rewrite_gate(harness: _Harness, conn: StoreConnection) -> None:
    """Point CP-0's accepted row at other bytes, under the run lock."""
    gate = harness.route.nodes[0]
    lock_run(conn, harness.run_id)
    tamper(
        conn,
        "UPDATE artifacts SET artifact_sha256 = %s"
        " WHERE run_id = %s AND route_node_id = %s",
        (harness.blobs.put(b"other bytes"), harness.run_id, gate.route_node_id),
    )
    conn.commit()


def _refused_before_cp_l10_call(harness: _Harness, entry: str) -> RefusalCode:
    """CP-L10 run through the frontier or entered directly; no call either way.

    The frontier refuses before CP-L10 is attempted; the executor, entered
    directly, refuses in its pre-call unit with the reservation kept."""
    completions = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    if entry == "frontier":
        code = _run(harness, _provider(harness, completions))
        assert _counts(harness) == (1, [REPORTED], 1, 1, 1)
    else:
        node = harness.route.nodes[1]
        attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
        reserve(harness.conn, attempt, ESTIMATE)
        with pytest.raises(Refusal) as refused:
            _provider(harness, completions).execute(
                node.route_node_id, node.module_id, attempt_id=attempt
            )
        assert refused.value.__cause__ is None
        code = refused.value.code
        _unbilled(harness, attempt)
    assert completions.calls == 0
    assert code is not None
    return code


@pytest.mark.parametrize("entry", ["frontier", "module"])
@pytest.mark.parametrize(
    "identity",
    [{"module_id": "CP-L10"}, {"ordinal": 2}, {"authority_bundle_sha256": "0" * 64}],
)
def test_upstream_with_foreign_envelope_identity_is_refused_before_any_call(
    harness: _Harness, identity: dict[str, object], entry: str
) -> None:
    """CP-0's record names another invocation: refused before CP-L10's call."""
    _accepted_gate(harness, **identity)
    code = _refused_before_cp_l10_call(harness, entry)
    assert code is RefusalCode.ARTIFACT_RECORD_MISMATCH


@pytest.mark.parametrize("entry", ["frontier", "module"])
@pytest.mark.parametrize(
    "field",
    [
        "build_id",
        "manifest_sha256",
        "authority_digest",
        "delivered_authority_digest",
        "adapter_version",
    ],
)
def test_upstream_record_from_another_build_is_refused_before_any_call(
    harness: _Harness, field: str, entry: str
) -> None:
    """CP-0's record binds its invocation but names another build, manifest,
    authority or adapter (invariant 4): nothing it says may feed CP-L10's
    prompt, whichever way CP-L10 is entered."""
    _accepted_gate(harness, {field: "0" * 64})
    code = _refused_before_cp_l10_call(harness, entry)
    assert code is RefusalCode.ORCHESTRATION_BUILD_MOVED


@pytest.mark.parametrize("entry", ["frontier", "module"])
def test_upstream_record_disagreeing_with_its_markdown_is_refused_before_any_call(
    harness: _Harness, entry: str
) -> None:
    """CP-0's record binds its invocation and build but projects what its
    Markdown does not say: it never feeds CP-L10's prompt."""
    _accepted_gate(harness, None, {"qa_status": "Restricted"})
    code = _refused_before_cp_l10_call(harness, entry)
    assert code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_upstream_rewritten_during_the_call_is_refused_keeping_the_bill(
    harness: _Harness,
) -> None:
    """A second acceptance cannot replace CP-0 (`tests/test_accepted_owner.py`);
    a privileged rewrite of its row during the call is still caught."""
    _accepted_gate(harness)

    def supersede() -> None:
        with connect(harness.url) as other:
            _rewrite_gate(harness, other)

    completions = _DuringCompletion(_Completions(harness.source_id), supersede)
    node = harness.route.nodes[1]
    attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
    reserve(harness.conn, attempt, ESTIMATE)
    with pytest.raises(Refusal) as refused:
        _provider(harness, completions).execute(
            node.route_node_id, node.module_id, attempt_id=attempt
        )
    assert (refused.value.code, completions.calls) == (
        RefusalCode.ROUTE_IDENTITY_INVALID,
        1,
    )
    with connect(harness.url) as observer:
        billed = observer.execute(
            "SELECT count(*) FROM call_outcomes WHERE attempt_id=%s", (attempt,)
        ).fetchone()
        artifact = observer.execute(
            "SELECT count(*) FROM artifacts WHERE attempt_id=%s", (attempt,)
        ).fetchone()
    assert (billed, artifact) == ((1,), (0,))


# Task17e-b: context derivation under real locks and failures.

GOOD_QUOTE = "Total debt at 31 December 2026"


def _attempt_at(harness: _Harness, index: int) -> tuple[RouteNode, UUID]:
    """A reserved attempt on route node `index`; CP-L10 gets an accepted CP-0."""
    if index == 1:
        _accepted_gate(harness)
    node = harness.route.nodes[index]
    attempt = start_attempt(harness.conn, harness.run_id, node.route_node_id)
    reserve(harness.conn, attempt, ESTIMATE)
    return node, attempt


def _unbilled(harness: _Harness, attempt: UUID) -> None:
    """No call reached the store: reservation kept, no outcome, run RUNNING."""
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT (SELECT count(*) FROM call_outcomes WHERE attempt_id=%s),"
            " (SELECT count(*) FROM budget_reservations WHERE attempt_id=%s)",
            (attempt, attempt),
        ).fetchone()
    assert (row, _lockable(harness)) == ((0, 1), (True, True))
    _still_running(harness)


@pytest.mark.parametrize("change", ["withdraw", "upstream"])
def test_a_change_waits_for_the_context_unit_and_is_caught_after_the_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """The context unit holds the case lock: a withdrawal or a privileged
    rewrite of the predecessor row started inside it waits, lands before the
    answer is analysed, and refuses it with the bill kept."""
    from test_case_ordering import _wait_for_blocking

    node, attempt = _attempt_at(harness, int(change == "upstream"))
    before: dict[str, str] = dict(
        harness.conn.execute(
            "SELECT t.route_node_id, a.artifact_sha256 FROM artifacts a"
            " JOIN run_attempts t USING (attempt_id)"
        ).fetchall()
    )
    harness.conn.rollback()
    pending: list[Future[None]] = []
    derived: list[dict[str, str]] = []
    derive = invocation.upstream_markdown
    with connect(harness.url) as other, ThreadPoolExecutor(max_workers=1) as pool:
        other.execute("SET statement_timeout = '5s'")
        other.commit()

        def commit_change() -> None:
            if change == "withdraw":
                withdraw_source(
                    other,
                    case_id=harness.case_id,
                    source_id=harness.witness_id,
                    actor_id=harness.approver,
                )
            else:
                _rewrite_gate(harness, other)

        def inside(
            blobs: BlobStore, refs: tuple[UpstreamRef, ...]
        ) -> tuple[tuple[UpstreamRef, bytes], ...]:
            result = derive(blobs, refs)
            derived.append({ref.module_id: ref.sha256 for ref, _ in result})
            if not pending:
                pending.append(pool.submit(commit_change))
                _wait_for_blocking(harness.conn, other)
            return result

        monkeypatch.setattr(canonical, "upstream_markdown", inside)
        completion = _DuringCompletion(
            _Completions(harness.source_id), lambda: pending[0].result(timeout=6)
        )
        with pytest.raises(Refusal) as refused:
            _provider(harness, completion).execute(
                node.route_node_id, node.module_id, attempt_id=attempt
            )
    expected = {
        "withdraw": RefusalCode.EVIDENCE_NOT_AVAILABLE,
        "upstream": RefusalCode.ROUTE_IDENTITY_INVALID,
    }[change]
    assert (refused.value.code, refused.value.__cause__, completion.calls) == (
        expected,
        None,
        1,
    )
    # The call saw the state before the change: it could not land inside the unit.
    assert str(harness.witness_id) in completion.delegate.prompts[0]
    gate = harness.route.nodes[0]
    assert derived[0] == (
        {gate.module_id: before[gate.route_node_id]} if change == "upstream" else {}
    )
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT (SELECT count(*) FROM call_outcomes WHERE attempt_id=%s),"
            " (SELECT count(*) FROM artifacts WHERE attempt_id=%s)",
            (attempt, attempt),
        ).fetchone()
    assert (row, _lockable(harness)) == ((1, 0), (True, True))
    _still_running(harness)


@pytest.mark.parametrize("failure", ["sql", "interrupt"])
@pytest.mark.parametrize("stage", ["evidence", "upstream"])
def test_failure_while_deriving_context_makes_no_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, stage: str, failure: str
) -> None:
    from caos.methodology import executor

    node, attempt = _attempt_at(harness, int(stage == "upstream"))
    owner, name = {
        "evidence": (executor, "read_run_blocks"),
        "upstream": (canonical, "upstream_markdown"),
    }[stage]
    real = getattr(owner, name)

    def failing(*args: object, **kwargs: object) -> object:
        real(*args, **kwargs)
        if failure == "sql":
            # A native error whose message quotes document text.
            harness.conn.execute("SELECT (%s)::int", (GOOD_QUOTE,))
        raise KeyboardInterrupt

    monkeypatch.setattr(owner, name, failing)
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    with pytest.raises((Refusal, KeyboardInterrupt)) as raised:
        _provider(harness, completion).execute(
            node.route_node_id, node.module_id, attempt_id=attempt
        )
    if failure == "sql":
        assert isinstance(raised.value, Refusal)
        assert (str(raised.value), raised.value.__cause__) == (
            "STORE_UNAVAILABLE",
            None,
        )
        assert GOOD_QUOTE not in "".join(traceback.format_exception(raised.value))
    else:
        assert type(raised.value) is KeyboardInterrupt
    assert completion.calls == 0
    assert harness.conn.closed or (
        harness.conn.info.transaction_status is TransactionStatus.IDLE
    )
    _unbilled(harness, attempt)


@pytest.mark.parametrize("fault", ["missing", "altered"])
def test_an_unreadable_upstream_blob_is_refused_before_any_call(
    harness: _Harness, fault: str
) -> None:
    node, attempt = _attempt_at(harness, 1)
    [digest] = [
        row[0] for row in harness.conn.execute("SELECT artifact_sha256 FROM artifacts")
    ]
    harness.conn.rollback()
    path = harness.blobs.path_of(digest)
    if fault == "missing":
        path.unlink()
    else:
        path.write_bytes(b'{"module_id": "CP-0"}')
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    with pytest.raises(Refusal) as refused:
        _provider(harness, completion).execute(
            node.route_node_id, node.module_id, attempt_id=attempt
        )
    # The record check reads the Markdown first, so an unreadable upstream is a
    # record that no longer binds its bytes.
    assert (refused.value.code, refused.value.__cause__, completion.calls) == (
        RefusalCode.ARTIFACT_RECORD_MISMATCH,
        None,
        0,
    )
    _unbilled(harness, attempt)
