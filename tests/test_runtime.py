"""Phase 4 exit test: recovery is recomputation, not restoration.

`docs/DECISIONS.md` §3: execution state *is* the accepted-attempt ledger. There
is no checkpointer, so there is nothing to restore and nothing that can disagree
with the domain state -- which is where most of the predecessor's recovery
machinery came from.

A process that dies mid-run leaves accepted attempts behind. The next one
recomputes `node_states` over exactly those rows and continues from the frontier
that falls out. A node that completed is not run again, because it is COMPLETE,
not because anything remembered that it was.

Every run here is the canonical LITE route (CP-0 -> CP-L10 -> CP-5) through the
real `ModuleProvider`, answered by `CanonicalCompletions` (Task 3.1 slice e-2).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from canonical_fixtures import (
    CATALOG,
    LITE_PROFILE,
    LITE_SELECTION,
    QUOTE,
    UNANCHORED,
    VENDORED,
    CanonicalCompletions,
)
from conftest import _url_for, approve_run, priced
from psycopg.pq import TransactionStatus

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph import runtime as subject
from caos.graph.route import NodeResult, ResolvedRoute, resolve_route
from caos.graph.runtime import (
    Execution,
    Provider,
    ProviderResult,
    accepted_artifacts,
    artifact_digests,
    run_route,
)
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.methodology.runner import ModuleProvider
from caos.pricing import ModelPrice, worst_case
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, connect
from caos.store.budget import reserve as reserve_budget
from caos.store.events import RunEvent, events_of
from caos.store.gates import Gate, withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.outcomes import record_refusal
from caos.store.routes import pin_route
from caos.store.runs import (
    Accepted,
    accept_attempt,
    run_status,
    start_attempt,
    start_run,
)
from caos.store.work import Lease, claim_run, enqueue_run

ESTIMATE = Decimal("0.10")
# What `CanonicalCompletions` reports per call unless told otherwise.
REPORTED = Decimal("0.0000041")
LITE_ORDER = ["CP-0", "CP-L10", "CP-5"]
# One line, so the fixtures' quote anchors on page 1 of the one source.
REPORT = QUOTE.encode() + b" was USD 1,240.0m\n"


class _Boom(Exception):
    """A process death, in the only form a test can arrange."""


@dataclass
class _Provider:
    """The real module provider, recording what it was asked for; can die on a
    chosen node after its attempt and reservation exist."""

    inner: ModuleProvider
    answers: CanonicalCompletions
    die_on: str | None = None
    calls: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        return self.inner.model

    def check_context(self, route_node_id: str, module_id: str) -> int:
        return self.inner.check_context(route_node_id, module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        self.calls.append(module_id)
        if module_id == self.die_on:
            raise _Boom(module_id)
        return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)


@dataclass(frozen=True)
class _Run:
    conn: StoreConnection
    blobs: BlobStore
    bundle: Bundle
    route: ResolvedRoute
    run_id: UUID
    source_id: UUID

    def provider(
        self,
        die_on: str | None = None,
        at_call: Callable[[], None] | None = None,
        charge: Decimal = REPORTED,
        *,
        answers: CanonicalCompletions | None = None,
        lease: Lease | None = None,
    ) -> _Provider:
        if answers is None:
            answers = CanonicalCompletions(
                self.source_id, charge=charge, during=at_call
            )
        inner = ModuleProvider(
            self.conn, self.bundle, self.blobs, answers, self.route, self.run_id, lease
        )
        return _Provider(inner, answers, die_on)

    def run(
        self,
        provider: Provider,
        *,
        bundle: Bundle | None = None,
        lease: Lease | None = None,
    ) -> None:
        run_route(
            self.conn,
            self.blobs,
            run_id=self.run_id,
            route=self.route,
            execution=Execution(
                provider, priced(ESTIMATE), bundle or self.bundle, lease
            ),
        )


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


@pytest.fixture
def bundle() -> Bundle:
    return Bundle(VENDORED)


def _started(  # noqa: PLR0913
    conn: StoreConnection,
    case_id: UUID,
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    *,
    ceiling: Decimal | None = None,
) -> _Run:
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("runtime.txt"), data=REPORT)],
    )
    run_id = start_run(conn, case_id, budget_ceiling=ceiling)
    conn.commit()
    return _Run(conn, blobs, bundle, route, run_id, source_id)


def _approved_run(  # noqa: PLR0913
    conn: StoreConnection,
    case_id: UUID,
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    *,
    ceiling: Decimal | None = None,
) -> _Run:
    run = _started(conn, case_id, route, bundle, blobs, ceiling=ceiling)
    approve_run(conn, case_id=case_id, run_id=run.run_id, route=route, bundle=bundle)
    return run


def _attempts_per_module(conn: StoreConnection, run_id: UUID) -> dict[str, int]:
    rows = conn.execute(
        "SELECT route_node_id, count(*) FROM run_attempts"
        " WHERE run_id = %s GROUP BY route_node_id",
        (run_id,),
    ).fetchall()
    return {str(node_id): int(count) for node_id, count in rows}


_WORK_TABLES = (
    "run_attempts",
    "budget_reservations",
    "call_outcomes",
    "budget_ledger",
    "artifacts",
)


def _assert_no_work(run: _Run, provider: _Provider) -> None:
    assert provider.calls == []
    assert provider.answers.prompts == []
    for table in _WORK_TABLES:
        assert run.conn.execute(
            "SELECT count(*) FROM " + table + " WHERE run_id=%s", (run.run_id,)
        ).fetchone() == (0,), table


def test_the_fake_provider_satisfies_the_protocol(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """The recording wrapper must have the shape `run_route` calls, or these
    tests would exercise a seam the real provider does not have."""
    conn, case_id = case
    provider: Provider = _started(conn, case_id, route, bundle, blobs).provider()

    assert provider.model == "a-model/for-the-test"
    assert callable(provider.execute)
    execute_params = list(inspect.signature(provider.execute).parameters)
    protocol_params = list(inspect.signature(Provider.execute).parameters)[1:]
    assert execute_params == protocol_params


def test_an_unapproved_run_never_reaches_the_provider(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _started(conn, case_id, route, bundle, blobs)
    provider = run.provider(die_on="CP-0")

    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        run.run(provider)

    _assert_no_work(run, provider)


def test_a_historical_route_without_a_complete_input_never_reaches_the_provider(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _started(conn, case_id, route, bundle, blobs)
    pin_route(conn, run.run_id, route)
    provider = run.provider()

    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        run.run(provider)

    _assert_no_work(run, provider)


@pytest.mark.parametrize("gate", list(Gate))
@pytest.mark.parametrize("fault", ["missing", "preview", "input"])
def test_each_current_gate_is_required_before_work(  # noqa: PLR0913
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    gate: Gate,
    fault: str,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    if fault == "missing":
        conn.execute(
            "DELETE FROM run_gates WHERE run_id=%s AND gate=%s", (run.run_id, gate)
        )
    else:
        column = "preview_sha256" if fault == "preview" else "input_fingerprint"
        conn.execute(
            psycopg.sql.SQL(
                "UPDATE run_gates SET {}=%s WHERE run_id=%s AND gate=%s"
            ).format(psycopg.sql.Identifier(column)),
            ("0" * 64, run.run_id, gate),
        )
    conn.commit()
    provider = run.provider()

    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        run.run(provider)

    _assert_no_work(run, provider)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("revoked", RefusalCode.GATE_APPROVAL_MISMATCH),
        ("downgraded", RefusalCode.GATE_APPROVAL_MISMATCH),
        ("withdrawn", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ],
)
def test_live_authority_is_required_before_work(  # noqa: PLR0913
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    change: str,
    code: RefusalCode,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    actor = conn.execute(
        "SELECT DISTINCT approved_by FROM run_gates WHERE run_id=%s", (run.run_id,)
    ).fetchone()
    assert actor is not None
    actor_id = UUID(str(actor[0]))
    if change == "revoked":
        revoke(conn, case_id=case_id, user_id=actor_id)
        conn.commit()
    elif change == "downgraded":
        grant(conn, case_id=case_id, user_id=actor_id, standing=Standing.READER)
        conn.commit()
    else:
        withdraw_source(
            conn, case_id=case_id, source_id=run.source_id, actor_id=actor_id
        )
    provider = run.provider()

    with pytest.raises(Refusal, match=f"^{code.value}$"):
        run.run(provider)

    _assert_no_work(run, provider)


def test_the_final_pre_call_check_sees_a_late_revocation(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    actor = conn.execute(
        "SELECT DISTINCT approved_by FROM run_gates WHERE run_id=%s", (run.run_id,)
    ).fetchone()
    assert actor is not None
    conn.rollback()
    original = reserve_budget
    reservations = 0

    def reserve_then_revoke(
        connection: StoreConnection,
        attempt_id: UUID,
        amount: Decimal,
        *,
        price: ModelPrice,
        lease: Lease | None = None,
    ) -> None:
        nonlocal reservations
        original(connection, attempt_id, amount, price=price, lease=lease)
        reservations += 1
        if reservations == 2:
            revoke(connection, case_id=case_id, user_id=UUID(str(actor[0])))
            connection.commit()

    monkeypatch.setattr(subject, "reserve", reserve_then_revoke)
    provider = run.provider()

    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        run.run(provider)

    assert provider.calls == ["CP-0"]
    assert len(provider.answers.prompts) == 1
    for table, count in (
        ("run_attempts", 2),
        ("budget_reservations", 2),
        ("artifacts", 1),
    ):
        assert conn.execute(
            "SELECT count(*) FROM " + table + " WHERE run_id=%s", (run.run_id,)
        ).fetchone() == (count,), table


def test_provider_transport_is_idle_and_holds_no_case_or_run_lock(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    checked: list[str] = []

    def unlocked() -> None:
        assert conn.info.transaction_status is TransactionStatus.IDLE
        with connect(_url_for(conn.info.dbname)) as observer:
            observer.execute(
                "SELECT 1 FROM cases WHERE case_id=%s FOR UPDATE NOWAIT", (case_id,)
            )
            observer.execute(
                "SELECT 1 FROM runs WHERE run_id=%s FOR UPDATE NOWAIT", (run.run_id,)
            )
            observer.rollback()
        checked.append("transport")

    # Inside the completion call itself: the moment the model is answering.
    provider = run.provider(at_call=unlocked)
    run.run(provider)

    assert provider.calls == LITE_ORDER
    assert checked == ["transport"] * 3


@pytest.mark.parametrize(
    "mode", ["pending", "autocommit", "repeatable", "serializable"]
)
def test_runtime_entry_preserves_caller_transaction_ownership(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    mode: str,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    if mode == "pending":
        conn.execute("CREATE TABLE caller_work (id integer)")
    elif mode == "autocommit":
        conn.autocommit = True
    else:
        conn.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if mode == "repeatable"
            else psycopg.IsolationLevel.SERIALIZABLE
        )
    provider = run.provider()

    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        run.run(provider)

    assert provider.calls == []
    if mode == "pending":
        assert conn.info.transaction_status is TransactionStatus.INTRANS
        assert conn.execute("SELECT to_regclass('caller_work')").fetchone() == (
            "caller_work",
        )
    else:
        assert conn.info.transaction_status is TransactionStatus.IDLE
    conn.rollback()
    conn.autocommit = False
    conn.isolation_level = None
    _assert_no_work(run, provider)


@pytest.mark.parametrize("wrong", ["route", "bundle"])
def test_caller_identity_cannot_replace_stored_authority(  # noqa: PLR0913
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    tmp_path: Path,
    wrong: str,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    executing = bundle
    code = RefusalCode.ROUTE_IDENTITY_INVALID
    if wrong == "route":
        # Another canonical LITE route, so only the identity differs.
        other = resolve_route(CATALOG, LITE_PROFILE, "LITE_DEEP_RESEARCH")
        assert other != route
        run = _Run(conn, blobs, bundle, other, run.run_id, run.source_id)
    else:
        raw = (bundle.root / MANIFEST_NAME).read_text(encoding="utf-8")
        (tmp_path / MANIFEST_NAME).write_text(
            raw.replace(bundle.build_id, "d" * 64), encoding="utf-8"
        )
        executing = Bundle(tmp_path)
        code = RefusalCode.RUN_INPUT_INVALID
    provider = run.provider()

    with pytest.raises(Refusal, match=f"^{code.value}$"):
        run.run(provider, bundle=executing)

    _assert_no_work(run, provider)


def test_a_route_runs_to_completion(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    provider = run.provider()

    run.run(provider)

    assert provider.calls == LITE_ORDER
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    assert [e.name for e in events_of(conn, run.run_id)].count(
        RunEvent.RUN_COMPLETE.value
    ) == 1


def test_recovery_is_recomputation(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """The Phase 4 exit test. Kill mid-run, restart, and the run completes
    without restarting completed nodes and without a checkpoint file."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)

    dying = run.provider(die_on="CP-L10")
    with pytest.raises(_Boom):
        run.run(dying)

    assert dying.calls == ["CP-0", "CP-L10"]
    assert run_status(conn, run.run_id) is RunStatus.RUNNING
    before = _attempts_per_module(conn, run.run_id)

    # The restart. Nothing was restored: node_states is recomputed over the rows
    # that survived, and the frontier falls out of them.
    restarted = run.provider()
    conn.rollback()
    run.run(restarted)

    assert restarted.calls == ["CP-L10", "CP-5"], "completed nodes are not run again"
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE

    after = _attempts_per_module(conn, run.run_id)
    completed_before = [
        node_id for node_id in before if node_id != _node_id(route, "CP-L10")
    ]
    assert completed_before == [_node_id(route, "CP-0")]
    for node_id in completed_before:
        assert after[node_id] == 1, "an accepted node was attempted a second time"


def test_no_checkpoint_is_written_anywhere(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """`docs/DECISIONS.md` §3: no checkpointer. The store's own tables are the
    execution state, so there is no second place for it to disagree from."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)

    run.run(run.provider())

    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema()"
    ).fetchall()
    assert not [name for (name,) in tables if "checkpoint" in str(name)]


def test_a_failed_attempt_leaves_its_row_and_its_reservation(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """One attempt row per try. The row and the reservation outlive the failure,
    because the call may have reached the provider and may be billed."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)

    with pytest.raises(_Boom):
        run.run(run.provider(die_on="CP-L10"))

    assert _attempts_per_module(conn, run.run_id) == {
        _node_id(route, "CP-0"): 1,
        _node_id(route, "CP-L10"): 1,
    }
    row = conn.execute(
        "SELECT count(*) FROM budget_reservations WHERE run_id = %s", (run.run_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == 2, "CP-0 and the failed CP-L10 both reserved"


def test_the_run_stops_when_the_ceiling_is_reached(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """Invariant 8 reaching the loop: the next node is refused, not attempted."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs, ceiling=Decimal("0.15"))
    provider = run.provider()

    with pytest.raises(Refusal) as caught:
        run.run(provider)

    assert caught.value.code is RefusalCode.BUDGET_CEILING_REACHED
    assert provider.calls == ["CP-0"], "the second node never reached the provider"
    assert len(provider.answers.prompts) == 1


def test_accepted_artifacts_reads_cp0s_payload_and_no_other(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """`node_states` needs CP-0's readiness and nothing else's body, so nothing
    else's body is fetched from the blob store."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    run.run(run.provider())

    accepted = accepted_artifacts(conn, blobs, route, run.run_id, bundle=bundle)

    assert accepted[_node_id(route, "CP-0")] == NodeResult(
        readiness=(
            ("CP-5", "READY"),
            ("CP-L10", "READY"),
        ),
        qa_status="Passed",
    )
    assert accepted[_node_id(route, "CP-L10")] == NodeResult()
    assert accepted[_node_id(route, "CP-5")] == NodeResult()


def test_artifact_digests_maps_accepted_attempts_to_their_digest(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """The join `accepted_artifacts` above and `executor._upstream_digests`
    both read now lives in this one function -- proved here in isolation from
    either caller, since a test that only ever saw it through one of them could
    not tell a coincidence from the shared row set the fix depends on."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)

    assert artifact_digests(conn, run.run_id) == {}, "nothing accepted yet"
    conn.rollback()

    provider = run.provider()
    run.run(provider)

    digests = artifact_digests(conn, run.run_id)
    assert set(digests) == {_node_id(route, module) for module in LITE_ORDER}
    # Each digest addresses the exact Markdown that node's call answered.
    for module, markdown in zip(LITE_ORDER, provider.answers.answers, strict=True):
        assert blobs.get(digests[_node_id(route, module)]) == markdown


def _node_id(route: ResolvedRoute, module_id: str) -> str:
    return next(n.route_node_id for n in route.nodes if n.module_id == module_id)


# Brief 4.3 D6/D7: a crash at each boundary, then a fresh drive of the run.


@dataclass
class _Uncallable:
    """A provider a resumed run must not touch: the stored facts decide."""

    model: str = "a-model/for-the-test"

    def check_context(self, route_node_id: str, module_id: str) -> int:
        pytest.fail(f"{module_id} was prepared for a second call")

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        pytest.fail(f"{module_id} was called again")


@dataclass
class _DiesAfterItsBill:
    """Dies after the call's bill and diagnostic commit, whatever it answered."""

    inner: _Provider

    @property
    def model(self) -> str:
        return self.inner.model

    def check_context(self, route_node_id: str, module_id: str) -> int:
        return self.inner.check_context(route_node_id, module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        try:
            return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)
        except Refusal:
            pass
        raise _Boom(module_id)


def _count(run: _Run, table: str) -> int:
    row = run.conn.execute(
        "SELECT count(*) FROM " + table + " WHERE run_id=%s", (run.run_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _refusals(run: _Run) -> list[tuple[UUID, str]]:
    rows = run.conn.execute(
        "SELECT r.attempt_id, r.code FROM attempt_refusals r"
        " JOIN run_attempts t USING (attempt_id) WHERE t.run_id=%s",
        (run.run_id,),
    ).fetchall()
    return [(UUID(str(attempt)), str(code)) for attempt, code in rows]


def test_a_leased_run_calls_its_provider_through_the_module_provider(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    enqueue_run(conn, run.run_id)
    conn.commit()
    lease = claim_run(conn, worker=BoundaryText.of("worker-a"), lease_seconds=300)
    assert lease is not None and lease.run_id == run.run_id
    provider = run.provider(lease=lease)

    run.run(provider, lease=lease)

    assert provider.calls == LITE_ORDER
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE


def test_crash_after_a_billed_answer_accepts_from_the_stored_body_without_a_call(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    real = accept_attempt
    accepts: list[UUID] = []

    def crashing(
        conn: StoreConnection,
        *,
        attempt_id: UUID,
        accepted: Accepted,
        lease: Lease | None = None,
    ) -> bool:
        accepts.append(attempt_id)
        if len(accepts) == len(LITE_ORDER):
            raise _Boom(attempt_id)  # after the bill, before the acceptance
        return real(conn, attempt_id=attempt_id, accepted=accepted, lease=lease)

    monkeypatch.setattr(subject, "accept_attempt", crashing)
    first = run.provider()
    with pytest.raises(_Boom):
        run.run(first)
    assert (_count(run, "budget_ledger"), _count(run, "artifacts")) == (3, 2)
    conn.rollback()
    monkeypatch.setattr(subject, "accept_attempt", real)

    run.run(_Uncallable())

    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    assert set(_attempts_per_module(conn, run.run_id).values()) == {1}
    assert (_count(run, "budget_ledger"), _count(run, "artifacts")) == (3, 3)
    screen = artifact_digests(conn, run.run_id)[_node_id(route, "CP-5")]
    assert blobs.get(screen) == first.answers.answers[2]
    assert _refusals(run) == []


def test_crash_after_a_billed_refused_answer_records_it_and_stops_without_a_call(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    answers = CanonicalCompletions(run.source_id, quotes=(UNANCHORED,))
    with pytest.raises(_Boom):
        run.run(_DiesAfterItsBill(run.provider(answers=answers)))
    [(attempt,)] = conn.execute(
        "SELECT attempt_id FROM run_attempts WHERE run_id=%s", (run.run_id,)
    ).fetchall()
    assert _count(run, "budget_ledger") == 1
    assert _refusals(run) == []
    conn.rollback()

    with pytest.raises(Refusal) as caught:
        run.run(_Uncallable())

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED
    assert _refusals(run) == [(attempt, "CITATION_NOT_LOCATED")]
    conn.rollback()
    # Written once; a store fault is never an explanation of an answer.
    for code in (RefusalCode.ROUTE_IDENTITY_INVALID, RefusalCode.STORE_UNAVAILABLE):
        assert not record_refusal(conn, attempt_id=attempt, code=code)
    assert _refusals(run) == [(attempt, "CITATION_NOT_LOCATED")]
    assert _attempts_per_module(conn, run.run_id) == {_node_id(route, "CP-0"): 1}
    assert _count(run, "budget_ledger") == 1
    assert run_status(conn, run.run_id) is RunStatus.RUNNING


def test_a_retry_skips_a_recorded_refusal_and_makes_one_new_attempt(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    answers = CanonicalCompletions(run.source_id, quotes=(UNANCHORED,))
    with pytest.raises(Refusal) as caught:
        run.run(run.provider(answers=answers))
    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED
    # The live path explains the billed answer, so no retry replays it.
    [(refused, code)] = _refusals(run)
    assert code == "CITATION_NOT_LOCATED"
    conn.rollback()

    retry = run.provider()
    run.run(retry)

    assert retry.calls == LITE_ORDER
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    assert _attempts_per_module(conn, run.run_id) == {
        _node_id(route, "CP-0"): 2,
        _node_id(route, "CP-L10"): 1,
        _node_id(route, "CP-5"): 1,
    }
    assert _refusals(run) == [(refused, "CITATION_NOT_LOCATED")]
    assert _count(run, "budget_ledger") == 4


def test_a_stored_answer_predating_a_later_soft_input_is_explained_not_accepted(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    """CP-5's answer was billed before its soft input CP-L10 was accepted, so it
    names no CP-L10: replayed now, it is explained, never accepted or re-paid."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    with pytest.raises(_Boom):
        run.run(run.provider(die_on="CP-L10"))
    conn.rollback()
    screen = _node_id(route, "CP-5")
    early = start_attempt(conn, run.run_id, screen)
    reserve_budget(conn, early, worst_case(priced(ESTIMATE)), price=priced(ESTIMATE))
    run.provider().inner.execute(screen, "CP-5", attempt_id=early)
    conn.rollback()

    resumed = run.provider(die_on="CP-5")
    with pytest.raises(Refusal) as caught:
        run.run(resumed)

    assert caught.value.code is RefusalCode.ROUTE_IDENTITY_INVALID
    assert resumed.calls == ["CP-L10"]
    assert _refusals(run) == [(early, "ROUTE_IDENTITY_INVALID")]
    assert screen not in artifact_digests(conn, run.run_id)
    assert _attempts_per_module(conn, run.run_id)[screen] == 1


def test_crash_after_acceptance_does_not_rerun_the_node(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    real = accept_attempt

    def crashing(
        conn: StoreConnection,
        *,
        attempt_id: UUID,
        accepted: Accepted,
        lease: Lease | None = None,
    ) -> bool:
        real(conn, attempt_id=attempt_id, accepted=accepted, lease=lease)
        raise _Boom(attempt_id)  # after the acceptance

    monkeypatch.setattr(subject, "accept_attempt", crashing)
    with pytest.raises(_Boom):
        run.run(run.provider())
    monkeypatch.setattr(subject, "accept_attempt", real)
    conn.rollback()

    resumed = run.provider()
    run.run(resumed)

    assert resumed.calls == ["CP-L10", "CP-5"]
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    assert set(_attempts_per_module(conn, run.run_id).values()) == {1}
    assert (_count(run, "budget_ledger"), _count(run, "artifacts")) == (3, 3)


def test_crash_after_reservation_counts_possible_spend_and_retries_once(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    blobs: BlobStore,
    bundle: Bundle,
) -> None:
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    with pytest.raises(_Boom):
        run.run(run.provider(die_on="CP-L10"))
    conn.rollback()

    resumed = run.provider()
    run.run(resumed)

    assert resumed.calls == ["CP-L10", "CP-5"]
    assert run_status(conn, run.run_id) is RunStatus.COMPLETE
    assert _attempts_per_module(conn, run.run_id)[_node_id(route, "CP-L10")] == 2
    # The indeterminate call's reservation stays counted; only known calls bill.
    assert _count(run, "budget_reservations") == 4
    assert (_count(run, "call_outcomes"), _count(run, "budget_ledger")) == (3, 3)
    assert _refusals(run) == []
