"""Stored execution authority in owned read units; runtime integration is later."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import research_brief
from conftest import route_fault
from psycopg.pq import TransactionStatus
from test_case_ordering import _blocked
from test_gates import _approval
from test_run_inputs import SUBJECT, Prepared, _prepare
from test_source_sets import _admit

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.refusals import Refusal
from caos.store import StoreConnection, connect, gates
from caos.store.audit import audit_trail
from caos.store.cases import lock_case
from caos.store.gates import Gate, approve_gate, gate_preview, withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.outcomes import execution_reads
from caos.store.routes import pin_route
from caos.store.run_inputs import (
    RunInput,
    load_run_input,
    pin_run_input,
    research_text,
)
from caos.store.runs import create_case, start_run

type Approved = tuple[Prepared, RunInput, tuple[UUID, UUID]]

# Execution authority is only ever read for a route the adapter executes (§42.2).
LITE = ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH")


@pytest.fixture
def prepared(case: tuple[StoreConnection, UUID], tmp_path: Path) -> Prepared:
    conn, case_id = case
    return conn, *_prepare(conn, case_id, tmp_path, LITE)


@pytest.fixture
def approved(prepared: Prepared) -> Approved:
    conn, run, source, bundle, _route = prepared
    pin = pin_run_input(
        conn,
        run,
        source.version,
        bundle,
        research_brief(decision_context="Café?\r\nExact."),
        subject=SUBJECT,
    )
    actors = (uuid4(), uuid4())
    for gate, actor in zip(Gate, actors, strict=True):
        grant(conn, case_id=source.case_id, user_id=actor, standing=Standing.APPROVER)
        conn.commit()
        approve_gate(conn, _approval(conn, run, actor, gate))
    return prepared, pin, actors


@pytest.mark.parametrize("entry", ["approved", "execution"])
def test_exact_historical_input_with_one_component_load(
    approved: Approved, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    (conn, run, source, bundle, route), pin, _actors = approved
    previews = [gate_preview(conn, run, gate) for gate in Gate]
    _admit(conn, source.case_id, tmp_path)
    conn.commit()
    queries: list[str] = []
    execute = psycopg.Connection.execute

    def counted(
        c: StoreConnection, query: str, *args: object, **kwargs: object
    ) -> object:
        queries.append(query)
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", counted)
        with execution_reads(conn):
            result = (
                gates.approved_run_input(conn, run)
                if entry == "approved"
                else gates.execution_input(conn, run, bundle)
            )
            assert conn.info.transaction_status.name == "INTRANS"
    assert result == (pin, route)
    assert pin.research_json == research_text(
        research_brief(decision_context="Café?\r\nExact.")
    )
    for table in ("source_set_versions", "source_set_members", "run_routes"):
        assert sum(f"FROM {table}" in query for query in queries) == 1
    assert sum("LEFT JOIN live_sources" in query for query in queries) == 1
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert [gate_preview(conn, run, gate) for gate in Gate] == previews


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing-run", "RUN_INPUT_INVALID"),
        ("missing-input", "RUN_INPUT_INVALID"),
        ("route-only", "RUN_INPUT_INVALID"),
        ("input", "RUN_INPUT_INVALID"),
        ("route", "ROUTE_IDENTITY_INVALID"),
        ("COMPLETE", "RUN_NOT_RUNNING"),
        ("FAILED", "RUN_NOT_RUNNING"),
    ],
)
def test_ineligible_input_refuses_without_mutating_authority(
    approved: Approved, fault: str, code: str
) -> None:
    (conn, run, source, bundle, route), _pin, _actors = approved
    if fault == "missing-run":
        run = uuid4()
    elif fault in {"missing-input", "route-only"}:
        run = start_run(conn, source.case_id)
        if fault == "route-only":
            pin_route(conn, run, route)
    elif fault == "input":
        database = conn.execute("SELECT current_database()").fetchone()
        assert database is not None and database[0].startswith("caos_test_")
        conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER input_immutable")
        conn.execute("UPDATE run_inputs SET research_json = '{}'")
        conn.execute("ALTER TABLE run_inputs ENABLE TRIGGER input_immutable")
    elif fault == "route":
        with route_fault(conn):
            conn.execute("UPDATE run_routes SET resolved = '{}'")
    else:
        conn.execute("UPDATE runs SET status = %s WHERE run_id = %s", (fault, run))
    tables = ("run_inputs", "run_gates", "audit_events")
    before = [conn.execute("SELECT * FROM " + table).fetchall() for table in tables]
    conn.commit()
    with pytest.raises(Refusal, match=f"^{code}$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, bundle)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert [conn.execute("SELECT * FROM " + table).fetchall() for table in tables] == (
        before
    )


@pytest.mark.parametrize("gate", list(Gate))
@pytest.mark.parametrize("field", ["missing", "preview_sha256", "input_fingerprint"])
def test_both_exact_approvals_are_required(
    approved: Approved, gate: Gate, field: str
) -> None:
    (conn, run, source, bundle, _route), pin, _actors = approved
    if field == "missing":
        conn.execute("DELETE FROM run_gates WHERE gate = %s", (gate.value,))
    else:
        conn.execute(
            psycopg.sql.SQL("UPDATE run_gates SET {} = %s WHERE gate = %s").format(
                psycopg.sql.Identifier(field)
            ),
            ("0" * 64, gate.value),
        )
    before = audit_trail(conn, source.case_id)
    approvals = conn.execute("SELECT * FROM run_gates ORDER BY gate").fetchall()
    conn.commit()
    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, bundle)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert audit_trail(conn, source.case_id) == before
    assert conn.execute("SELECT * FROM run_gates ORDER BY gate").fetchall() == approvals
    assert load_run_input(conn, run) == pin


@pytest.mark.parametrize(
    "change", ["build", "manifest", "adapter", "moving", "removed"]
)
def test_current_bundle_and_adapter_are_distinct_from_historical_readability(
    approved: Approved, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    (conn, run, _source, bundle, route), pin, _actors = approved
    previews = [gate_preview(conn, run, gate) for gate in Gate]
    raw = (bundle.root / MANIFEST_NAME).read_text()
    path = tmp_path / MANIFEST_NAME
    path.write_text(raw)
    current = Bundle(tmp_path)
    if change in {"build", "manifest"}:
        path.write_text(
            raw.replace(bundle.build_id, "d" * 64) if change == "build" else raw + " "
        )
        current = Bundle(tmp_path)
    elif change == "adapter":
        monkeypatch.setattr(
            methodology, "CANONICAL_ADAPTER_VERSION", "canonical-markdown-v4"
        )
    elif change == "moving":
        path.write_text(raw + " ")
    else:
        path.unlink()
    assert load_run_input(conn, run) == pin
    assert [gate_preview(conn, run, gate) for gate in Gate] == previews
    conn.commit()
    with execution_reads(conn):
        assert gates.approved_run_input(conn, run) == (pin, route)
    code = (
        "AUTHORITY_BYTES_MISMATCH"
        if change in {"moving", "removed"}
        else "RUN_INPUT_INVALID"
    )
    with pytest.raises(Refusal, match=f"^{code}$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, current)
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize("fake", [False, True])
def test_execution_requires_an_actual_bundle_instance(
    approved: Approved, fake: bool
) -> None:
    (conn, run, _source, _bundle, _route), pin, _actors = approved
    supplied = (
        SimpleNamespace(build_id=pin.build_id, manifest_sha256=pin.manifest_sha256)
        if fake
        else None
    )
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, cast(Bundle, supplied))
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize("gate", list(Gate))
@pytest.mark.parametrize("change", ["revoke", "downgrade", "withdraw"])
def test_each_recorded_approver_and_captured_source_stays_live(
    approved: Approved, gate: Gate, change: str
) -> None:
    (conn, run, source, bundle, _route), _pin, actors = approved
    actor = actors[list(Gate).index(gate)]
    if change == "revoke":
        revoke(conn, case_id=source.case_id, user_id=actor)
    elif change == "downgrade":
        grant(conn, case_id=source.case_id, user_id=actor, standing=Standing.WRITER)
    else:
        withdraw_source(
            conn,
            case_id=source.case_id,
            source_id=source.members[0].source_id,
            actor_id=actor,
        )
    conn.commit()
    code = (
        "EVIDENCE_NOT_AVAILABLE" if change == "withdraw" else "GATE_APPROVAL_MISMATCH"
    )
    with pytest.raises(Refusal, match=f"^{code}$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, bundle)
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize(
    "field",
    ["document_sha256", "extractor_identity", "output_sha256", "extraction_sha256"],
)
def test_captured_identity_must_match_current_source_and_extraction(
    approved: Approved, field: str
) -> None:
    (conn, run, source, bundle, _route), pin, _actors = approved
    table = "sources" if field == "document_sha256" else "source_extractions"
    if table == "source_extractions":
        database = conn.execute("SELECT current_database()").fetchone()
        assert database is not None and database[0].startswith("caos_test_")
        conn.execute(
            "ALTER TABLE source_extractions DISABLE TRIGGER extraction_is_immutable"
        )
    conn.execute(
        psycopg.sql.SQL("UPDATE {} SET {} = %s WHERE source_id = %s").format(
            psycopg.sql.Identifier(table), psycopg.sql.Identifier(field)
        ),
        (
            "{}" if field == "extractor_identity" else "0" * 64,
            source.members[0].source_id,
        ),
    )
    if table == "source_extractions":
        conn.execute(
            "ALTER TABLE source_extractions ENABLE TRIGGER extraction_is_immutable"
        )
    conn.commit()
    assert load_run_input(conn, run) == pin
    conn.rollback()
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, bundle)
    assert conn.info.transaction_status is TransactionStatus.IDLE


def test_boundary_waits_for_case_and_reads_committed_revocation(
    approved: Approved, empty_database: str
) -> None:
    (conn, run, source, _bundle, _route), _pin, actors = approved
    revoke(conn, case_id=source.case_id, user_id=actors[1])
    with connect(empty_database) as other:

        def waiting() -> None:
            with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
                with execution_reads(other):
                    gates.approved_run_input(other, run)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, waiting):
            # The boundary cannot hold the run while it waits for the case.
            with connect(empty_database) as observer:
                assert observer.execute(
                    "SELECT run_id FROM runs WHERE run_id = %s FOR UPDATE NOWAIT",
                    (run,),
                ).fetchone() == (run,)


def test_read_unit_excludes_revocation_but_not_an_independent_case(
    approved: Approved, empty_database: str, tmp_path: Path
) -> None:
    (conn, run, source, bundle, route), pin, actors = approved
    independent_case = create_case(conn, BoundaryText.of("Independent"))
    other_run, other_source, _, _ = _prepare(conn, independent_case, tmp_path, LITE)
    pin_run_input(
        conn,
        other_run,
        other_source.version,
        bundle,
        research_brief(),
        subject=SUBJECT,
    )
    grant(conn, case_id=independent_case, user_id=actors[0], standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, other_run, actors[0], gate))
    with connect(empty_database) as waiter, connect(empty_database) as independent:

        def revoking() -> None:
            revoke(waiter, case_id=source.case_id, user_id=actors[1])
            waiter.commit()

        with ExitStack() as reads:
            reads.enter_context(execution_reads(conn))
            assert gates.execution_input(conn, run, bundle) == (pin, route)
            with _blocked(conn, waiter, revoking):
                with execution_reads(independent):
                    assert (
                        gates.execution_input(independent, other_run, bundle)[0].run_id
                        == other_run
                    )
                assert gates.approved_run_input(conn, run) == (pin, route)
                reads.close()  # Release the actual owned unit before joining.
        assert conn.info.transaction_status is TransactionStatus.IDLE
    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        with execution_reads(conn):
            gates.approved_run_input(conn, run)


@pytest.mark.parametrize("fault", ["select", "cleanup", "cancel", "cancel-cleanup"])
def test_owned_failures_release_locks_or_close_and_sanitize(
    approved: Approved, empty_database: str, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    (conn, run, source, bundle, _route), _pin, _actors = approved
    execute = psycopg.Connection.execute

    def fail(c: StoreConnection, query: str, *args: object, **kwargs: object) -> object:
        if "FROM run_gates" in query:
            if fault == "select":
                return execute(c, 'SELECT "private document SQL"')
            if fault.startswith("cancel"):
                raise KeyboardInterrupt
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    def broken(c: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail)
        if fault in {"cleanup", "cancel-cleanup"}:
            patch.setattr(psycopg.Connection, "rollback", broken)
        with pytest.raises(
            KeyboardInterrupt if fault.startswith("cancel") else Refusal
        ) as caught:
            with execution_reads(conn):
                gates.execution_input(conn, run, bundle)
        if isinstance(caught.value, Refusal):
            assert str(caught.value) == "STORE_UNAVAILABLE"
            assert caught.value.__cause__ is None
        assert (
            conn.closed
            if fault in {"cleanup", "cancel-cleanup"}
            else (conn.info.transaction_status is TransactionStatus.IDLE)
        )
    with connect(empty_database) as observer:
        observer.execute("SET lock_timeout = '1s'")
        lock_case(observer, source.case_id)
        assert len(audit_trail(observer, source.case_id)) == 2


def test_pending_caller_transaction_is_neither_adopted_nor_rolled_back(
    approved: Approved, empty_database: str
) -> None:
    (conn, run, _source, bundle, _route), _pin, _actors = approved
    conn.execute("UPDATE cases SET title = 'pending caller work'")
    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        with execution_reads(conn):
            gates.execution_input(conn, run, bundle)
    assert conn.info.transaction_status is TransactionStatus.INTRANS
    assert conn.execute("SELECT title FROM cases").fetchone() == (
        "pending caller work",
    )
    with connect(empty_database) as observer:
        assert observer.execute("SELECT title FROM cases").fetchone() != (
            "pending caller work",
        )
    conn.rollback()


@pytest.mark.parametrize("failure", [False, True])
def test_direct_boundary_preserves_caller_transaction(
    approved: Approved, failure: bool
) -> None:
    (conn, run, _source, bundle, route), pin, _actors = approved
    conn.execute("UPDATE cases SET title = 'pending caller work'")
    if failure:
        conn.execute("ALTER TABLE run_gates RENAME TO hidden_gates")
        with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
            gates.approved_run_input(conn, run)
        assert caught.value.__cause__ is None
        assert conn.info.transaction_status is TransactionStatus.INERROR
    else:
        assert gates.execution_input(conn, run, bundle) == (pin, route)
        assert conn.info.transaction_status is TransactionStatus.INTRANS
        assert conn.execute("SELECT title FROM cases").fetchone() == (
            "pending caller work",
        )
    conn.rollback()
    assert conn.execute("SELECT title FROM cases").fetchone() != (
        "pending caller work",
    )
    assert load_run_input(conn, run) == pin
