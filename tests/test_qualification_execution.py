"""Qualification execution requires current stored identity and external approval."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import research_brief
from test_qualification_harness import (
    OTHER,
    _approve,
    _case,
    _Completions,
    _count,
    _without_route,
)
from test_qualification_prepare import Fixture, ready

from caos.boundary_text import BoundaryText
from caos.evidence.ingest import admit_pack
from caos.methodology import executor
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.provider import Completion
from caos.qualification import harness as subject
from caos.qualification.matrix import ExpectedCitation, QualificationSet
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, connect
from caos.store.gates import Gate, execution_input, gate_preview, withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.outcomes import execution_reads
from caos.store.routes import pin_route, resolved_route
from caos.store.run_inputs import (
    RunInput,
    load_run_input,
    pin_run_input,
    research_text,
)
from caos.store.runs import create_case, start_run
from caos.store.source_sets import snapshot_source_set

__all__ = ["ready"]

_MEMBERS = "SELECT m.filename,m.document_sha256 FROM source_set_members m"
# The run's captured pins, still read on their own by the proof and the
# deliverable; a module's delivery is now the one batched read beside it.
_BLOCKS = "SELECT b.source_id, b.block_id FROM run_inputs i"
_DELIVERED = "WITH captured AS (SELECT inputs.case_id"
_PROOF = "SELECT a.artifact_sha256, t.route_node_id, (a.model, a.generation_id)"


def test_legacy_perform_refuses_without_spending(ready: Fixture) -> None:
    conn, blobs, harness, qualification = ready
    stopped = None
    try:
        subject.perform(conn, blobs, harness, qualification=qualification)
    except Refusal as refused:
        stopped = refused.code
    observed = (
        stopped,
        len(cast(_Completions, harness.completions).prompts),
        _count(conn, "SELECT count(*) FROM run_attempts"),
        _count(conn, "SELECT count(*) FROM budget_reservations"),
    )
    assert observed == (RefusalCode.RUN_INPUT_INVALID, 0, 0, 0)
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_changed_answer_key_refuses_before_any_provider_call(ready: Fixture) -> None:
    conn, blobs, harness, qualification = ready
    prepared = _prepared(ready)
    first = qualification.cases[0]
    changed = replace(
        qualification,
        cases=(
            replace(
                first,
                expects=(
                    ExpectedCitation(
                        module_id="CP-L10",
                        document_sha256=first.expects[0].document_sha256,
                        matched_text=first.expects[0].matched_text,
                    ),
                ),
            ),
            *qualification.cases[1:],
        ),
    )

    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        subject.perform(conn, blobs, harness, qualification=changed, prepared=prepared)

    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


@pytest.mark.parametrize(
    ("field", "changed"), [("provider", "other-provider"), ("model", "other/model")]
)
def test_changed_execution_target_refuses_before_any_provider_call(
    ready: Fixture, field: str, changed: str
) -> None:
    conn, blobs, harness, qualification = ready
    prepared = _prepared(ready)
    completions = cast(_Completions, harness.completions)
    changed_completions = (
        replace(completions, provider=changed)
        if field == "provider"
        else replace(completions, model=changed)
    )
    changed_harness = replace(harness, completions=changed_completions)

    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        subject.perform(
            conn,
            blobs,
            changed_harness,
            qualification=qualification,
            prepared=prepared,
        )

    assert completions.prompts == []
    _unspent(conn)


def _run(ready: Fixture, prepared: object) -> subject.PerformedSet:
    conn, blobs, harness, qualification = ready
    return subject.perform(
        conn,
        blobs,
        harness,
        qualification=qualification,
        prepared=cast(tuple[subject.PreparedCase, ...], prepared),
    )


def _prepared(ready: Fixture) -> tuple[subject.PreparedCase, ...]:
    conn, blobs, harness, qualification = ready
    return subject.prepare(conn, blobs, harness, qualification=qualification)


def _unspent(conn: StoreConnection, run: UUID | None = None) -> None:
    for table in (
        "run_attempts",
        "budget_reservations",
        "call_outcomes",
        "budget_ledger",
        "artifacts",
    ):
        assert (
            conn.execute(
                "SELECT 1 FROM " + table + (" WHERE run_id=%s" if run else ""),
                (run,) if run else (),
            ).fetchall()
            == []
        ), table
    conn.rollback()


def test_approved_captured_inputs_survive_later_catalog_and_source_changes(
    ready: Fixture,
) -> None:
    conn, blobs, harness, qualification = ready
    prepared = _prepared(ready)
    previews = [
        [gate_preview(conn, item.input.run_id, gate) for gate in Gate]
        for item in prepared
    ]
    conn.rollback()
    _approve(conn, prepared)
    pin = prepared[0].input
    added = admit_pack(
        conn,
        blobs,
        case_id=pin.case_id,
        documents=list(_case("extra", OTHER).documents),
    )
    conn.commit()
    snapshot_source_set(conn, pin.case_id)
    assert load_run_input(conn, pin.run_id) == pin
    assert [
        [gate_preview(conn, item.input.run_id, gate) for gate in Gate]
        for item in prepared
    ] == previews
    for item_previews in previews:
        for preview in item_previews:
            assert (
                sha256(preview.content.encode()).hexdigest() == preview.preview_sha256
            )
            assert conn.execute(
                "SELECT preview_sha256,input_fingerprint FROM run_gates"
                " WHERE run_id=%s AND gate=%s",
                (preview.run_id, preview.gate.value),
            ).fetchone() == (preview.preview_sha256, preview.input_fingerprint)
    conn.rollback()
    result = _run((conn, blobs, replace(harness, catalog={}), qualification), prepared)
    assert conn.info.transaction_status.name == "IDLE"
    assert result.matrix is not None and len(result.matrix.rows) == 2
    assert all(
        record.proof is not None and record.proof.artifacts == 3
        for record in result.performed
    )
    prompts = cast(_Completions, harness.completions).prompts
    assert len(prompts) == 6 and all(str(added[0]) not in prompt for prompt in prompts)


@pytest.mark.parametrize("field", list(RunInput.__dataclass_fields__))
def test_every_carrier_field_matches_the_stored_input(
    ready: Fixture, field: str
) -> None:
    conn, _, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    a, b = prepared
    value = (
        uuid4()
        if field in {"run_id", "case_id"}
        else 2
        if field == "source_version"
        else "changed"
    )
    pin = replace(a.input, **{field: value})  # type: ignore[arg-type]
    changed = replace(a, input=pin)
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _run(ready, (changed, b))
    assert conn.info.transaction_status.name == "IDLE"
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "length",
        "list",
        "tuple-subclass",
        "swapped",
        "run",
        "case",
        "run-string",
        "case-string",
        "label",
        "item",
        "input",
        "item-subclass",
        "input-subclass",
        "bool-version",
        "bundle",
    ],
)
def test_untrusted_carrier_shape_refuses_before_paid_work(
    ready: Fixture, fault: str
) -> None:
    conn, blobs, harness, qualification = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    a, b = prepared
    candidates = {
        "none": None,
        "length": (a,),
        "list": list(prepared),
        "tuple-subclass": type("Carrier", (tuple,), {})(prepared),
        "swapped": (b, a),
        "run": (a, replace(b, input=replace(b.input, run_id=a.input.run_id))),
        "case": (a, replace(b, input=replace(b.input, case_id=a.input.case_id))),
        "run-string": (
            replace(a, input=replace(a.input, run_id=cast(UUID, str(a.input.run_id)))),
            b,
        ),
        "case-string": (
            replace(
                a, input=replace(a.input, case_id=cast(UUID, str(a.input.case_id)))
            ),
            b,
        ),
        "label": (replace(a, case_label="different"), b),
        "item": (SimpleNamespace(case_label=a.case_label, input=a.input), b),
        "input": (
            replace(a, input=cast(RunInput, SimpleNamespace(**asdict(a.input)))),
            b,
        ),
        "item-subclass": (
            type("CarrierItem", (subject.PreparedCase,), {})(
                a.case_label,
                a.input,
                a.qualification_set_sha256,
                a.provider,
                a.model,
            ),
            b,
        ),
        "input-subclass": (
            replace(a, input=type("Pin", (RunInput,), {})(**asdict(a.input))),
            b,
        ),
        "bool-version": (replace(a, input=replace(a.input, source_version=True)), b),
    }
    if fault == "bundle":
        harness = replace(
            harness,
            bundle=cast(
                Bundle,
                SimpleNamespace(
                    build_id=harness.bundle.build_id,
                    manifest_sha256=harness.bundle.manifest_sha256,
                ),
            ),
        )
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _run((conn, blobs, harness, qualification), candidates.get(fault, prepared))
    assert conn.info.transaction_status.name == "IDLE"
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "title",
        "budget",
        "research",
        "profile",
        "selection",
        "bytes",
        "filename",
        "multiplicity",
        "bundle",
    ],
)
def test_real_approved_input_transplants_are_refused(
    ready: Fixture, tmp_path: Path, fault: str
) -> None:
    conn, blobs, harness, qualification = ready
    a, b = _prepared(ready)
    original = qualification.cases[0]
    if fault in {"budget", "research"}:
        route = resolved_route(conn, a.input.run_id)
        assert route is not None
        run = start_run(
            conn,
            a.input.case_id,
            budget_ceiling=Decimal("6") if fault == "budget" else None,
        )
        conn.commit()
        pin_route(conn, run, route)
        if fault == "research":
            # §96: a brief on a route no CP-DR node is on reaches nobody, so the
            # transplant is refused at its own pin before the harness sees it.
            with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
                pin_run_input(
                    conn,
                    run,
                    a.input.source_version,
                    harness.bundle,
                    research_brief(),
                    subject=original.subject,
                )
            assert cast(_Completions, harness.completions).prompts == []
            return
        a = replace(
            a,
            input=pin_run_input(
                conn,
                run,
                a.input.source_version,
                harness.bundle,
                subject=original.subject,
            ),
        )
    _approve(conn, (a, b))
    if fault == "owner":
        a = replace(a, input=replace(b.input, case_id=a.input.case_id))
    changed = {
        "title": replace(original, label="renamed"),
        "profile": replace(original, profile_id="OTHER"),
        "selection": replace(original, selection_id="BASELINE"),
        "bytes": _case(original.label, OTHER),
        "filename": replace(
            original,
            documents=(
                replace(original.documents[0], filename=BoundaryText.of("renamed.txt")),
            ),
        ),
        "multiplicity": replace(original, documents=original.documents * 2),
    }.get(fault, original)
    a = replace(a, case_label=changed.label)
    if fault == "bundle":
        raw = (harness.bundle.root / MANIFEST_NAME).read_text()
        (tmp_path / MANIFEST_NAME).write_text(
            raw.replace(harness.bundle.build_id, "d" * 64)
        )
        harness = replace(harness, bundle=Bundle(tmp_path))
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _run((conn, blobs, harness, QualificationSet((changed,))), (a,))
    assert conn.info.transaction_status.name == "IDLE"
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


@pytest.mark.parametrize("later", [False, True])
@pytest.mark.parametrize("gate", list(Gate))
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "preview_sha256",
        "input_fingerprint",
        "revoked",
        "downgraded",
        "withdrawn",
    ],
)
def test_current_authority_is_rechecked_before_each_case(
    ready: Fixture, monkeypatch: pytest.MonkeyPatch, later: bool, gate: Gate, fault: str
) -> None:
    conn, _, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    actor = _approve(conn, prepared[1:], gates=(gate,))[0]
    pin = prepared[1].input

    def change() -> None:
        if fault == "missing":
            conn.execute(
                "DELETE FROM run_gates WHERE run_id=%s AND gate=%s",
                (pin.run_id, gate.value),
            )
        elif fault in {"preview_sha256", "input_fingerprint"}:
            conn.execute(
                psycopg.sql.SQL(
                    "UPDATE run_gates SET {}=%s WHERE run_id=%s AND gate=%s"
                ).format(psycopg.sql.Identifier(fault)),
                ("0" * 64, pin.run_id, gate.value),
            )
        elif fault == "revoked":
            revoke(conn, case_id=pin.case_id, user_id=actor)
        elif fault == "downgraded":
            grant(conn, case_id=pin.case_id, user_id=actor, standing=Standing.WRITER)
        else:
            source = conn.execute(
                "SELECT source_id FROM source_set_members"
                " WHERE case_id=%s AND version=%s",
                (pin.case_id, pin.source_version),
            ).fetchone()
            assert source is not None
            conn.rollback()
            withdraw_source(
                conn, case_id=pin.case_id, source_id=source[0], actor_id=actor
            )
        conn.commit()

    original = _Completions.complete

    def complete(
        provider: _Completions, prompt: str, *, json_object: bool = False
    ) -> Completion:
        result = original(provider, prompt, json_object=json_object)
        if len(provider.prompts) == 1:
            change()
        return result

    code = (
        RefusalCode.EVIDENCE_NOT_AVAILABLE
        if fault == "withdrawn"
        else RefusalCode.GATE_APPROVAL_MISMATCH
    )
    if later:
        monkeypatch.setattr(_Completions, "complete", complete)
        result = _run(ready, prepared)
        assert conn.info.transaction_status.name == "IDLE"
        first, second = result.performed
        assert (
            first.proof is not None
            and first.proof.artifacts == 3
            and first.stopped is None
        )
        assert second.run_id == pin.run_id and second.stopped is code
        assert second.status is RunStatus.RUNNING
        assert (
            second.proof is None
            and second.refusal is RefusalCode.ORCHESTRATION_NOTHING_TO_PROVE
        )
        assert len(second.unrun) == 3 and result.matrix is None
        assert _count(conn, "SELECT count(*) FROM budget_ledger") == 3
        assert _count(conn, "SELECT count(*) FROM artifacts") == 3
        assert len(cast(_Completions, harness.completions).prompts) == 3
        sources = conn.execute(
            "SELECT source_id FROM source_set_members WHERE case_id=%s", (pin.case_id,)
        ).fetchall()
        assert sources and all(
            str(source[0]) not in prompt
            for source in sources
            for prompt in cast(_Completions, harness.completions).prompts
        )
        _unspent(conn, pin.run_id)
    else:
        change()
        with pytest.raises(Refusal, match=f"^{code.value}$"):
            _run(ready, prepared)
        assert conn.info.transaction_status.name == "IDLE"
        assert cast(_Completions, harness.completions).prompts == []
        _unspent(conn)


@pytest.mark.parametrize(
    "mode", ["pending", "autocommit", "repeatable", "serializable"]
)
def test_execution_preserves_caller_transaction_and_settings(
    ready: Fixture, empty_database: str, mode: str
) -> None:
    conn, _, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    pending = None
    if mode == "pending":
        pending = create_case(conn, BoundaryText.of("caller work"))
    elif mode == "autocommit":
        conn.autocommit = True
    else:
        conn.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if mode == "repeatable"
            else psycopg.IsolationLevel.SERIALIZABLE
        )
    settings = conn.autocommit, conn.isolation_level
    try:
        with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
            _run(ready, prepared)
        assert (conn.autocommit, conn.isolation_level) == settings
        if pending is not None:
            assert conn.info.transaction_status.name == "INTRANS"
            assert conn.execute(
                "SELECT title FROM cases WHERE case_id=%s", (pending,)
            ).fetchone() == ("caller work",)
            with connect(empty_database) as observer:
                assert (
                    observer.execute(
                        "SELECT 1 FROM cases WHERE case_id=%s", (pending,)
                    ).fetchone()
                    is None
                )
            for table in (
                "run_attempts",
                "budget_reservations",
                "call_outcomes",
                "budget_ledger",
                "artifacts",
            ):
                assert _count(conn, "SELECT count(*) FROM " + table) == 0, table
            assert conn.info.transaction_status.name == "INTRANS"
        else:
            assert conn.info.transaction_status.name == "IDLE"
    finally:
        conn.rollback()
        conn.autocommit = False
        conn.isolation_level = None
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


def test_execution_reads_share_native_transactions_and_reports_own_theirs(
    ready: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    execute = psycopg.Connection.execute
    observed: list[tuple[str, int]] = []

    def transaction(c: StoreConnection) -> int:
        assert c is conn and c.info.transaction_status.name == "INTRANS"
        assert execute(c, "SHOW transaction_isolation").fetchone() == (
            "read committed",
        )
        row = execute(c, "SELECT txid_current()").fetchone()
        assert row is not None
        return int(row[0])

    def boundary(name: str, read: Callable[..., object]) -> Callable[..., object]:
        def checked(c: StoreConnection, *args: object, **kwargs: object) -> object:
            unit = transaction(c)
            observed.append((name, unit))
            result = read(c, *args, **kwargs)
            assert transaction(c) == unit
            return result

        return checked

    def sql(c: StoreConnection, query: str, *args: object, **kwargs: object) -> object:
        if c is conn and isinstance(query, str):
            for prefix, name in (
                (_MEMBERS, "members"),
                (_BLOCKS, "blocks"),
                (_DELIVERED, "blocks"),
            ):
                if query.startswith(prefix):
                    observed.append((name, transaction(c)))
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        for name, label in (
            ("execution_input", "input"),
            ("_record", "record"),
            ("build_matrix", "matrix"),
        ):
            patch.setattr(subject, name, boundary(label, getattr(subject, name)))
        # Each node's own authority unit, where its evidence is now read.
        patch.setattr(executor, "execution_input", boundary("node", execution_input))
        patch.setattr(psycopg.Connection, "execute", sql)
        result = _run(ready, prepared)
    # Per node: the whole context is read and bounded before any attempt exists
    # (3.3b), evidence is read again in the pre-call authority unit, and the
    # post-call unit rechecks input and anchors in those same deliveries without
    # reading the blocks again; the proof reads them inside the record and the
    # matrix units (3.2e).
    unit = ["node", "blocks", "node", "blocks", "node"]
    case = ["input", "members", *unit * 3, "record", "blocks"]
    assert [name for name, _ in observed] == [
        *["input", "members"] * 2,
        *case,
        *case,
        "matrix",
        "blocks",
        "blocks",
    ]
    units = _units(observed)
    assert all(len(ids) == 1 for ids in units)
    assert len(set().union(*units)) == len(units)
    assert conn.info.transaction_status.name == "IDLE"
    assert result.matrix is not None and len(result.matrix.rows) == 2
    assert len(cast(_Completions, harness.completions).prompts) == 6


def _units(observed: list[tuple[str, int]]) -> list[set[int]]:
    """Each boundary opens one unit; every read after it belongs to that unit."""
    units: list[set[int]] = []
    for name, transaction_id in observed:
        if name in {"input", "node", "record", "matrix"}:
            units.append(set())
        units[-1].add(transaction_id)
    return units


@pytest.mark.parametrize(
    "fault", ["initial_members", "members", "blocks", "report", "matrix", "rollback"]
)
def test_native_execution_read_failures_clean_owned_work_and_retain_purchases(
    ready: Fixture, empty_database: str, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    conn, blobs, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    prefix, occurrence, paid = {
        "initial_members": (_MEMBERS, 2, 0),
        "members": (_MEMBERS, 3, 0),
        "blocks": (_DELIVERED, 1, 0),
        "report": (_PROOF, 1, 3),
        "matrix": (_PROOF, 3, 6),
        "rollback": (_DELIVERED, 1, 0),
    }[fault]
    execute, rollback = psycopg.Connection.execute, psycopg.Connection.rollback
    hits = 0
    injected = False
    cleanup_failed = False

    def fail(c: StoreConnection, query: str, *args: object, **kwargs: object) -> object:
        nonlocal hits, injected
        matches = c is conn and isinstance(query, str) and query.startswith(prefix)
        hits += int(matches)
        if matches and hits == occurrence:
            injected = True
            return execute(c, "SELECT qualification_private_column")
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    def failed_rollback(c: StoreConnection) -> None:
        nonlocal cleanup_failed
        if (
            fault == "rollback"
            and c is conn
            and c.info.transaction_status.name == "INERROR"
        ):
            cleanup_failed = True
            raise psycopg.OperationalError("private")
        rollback(c)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail)
        patch.setattr(psycopg.Connection, "rollback", failed_rollback)
        if fault in {"members", "blocks"}:
            result = _run(ready, prepared)
            assert result.matrix is None and len(result.performed) == 1
            record = result.performed[0]
            assert record.run_id == prepared[0].input.run_id
            assert record.stopped is RefusalCode.STORE_UNAVAILABLE
            assert "qualification_private_column" not in repr(result)
        else:
            with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
                _run(ready, prepared)
            assert caught.value.__cause__ is None
            assert caught.value.__suppress_context__
    assert injected and hits >= occurrence
    assert cleanup_failed == (fault == "rollback")
    assert (
        conn.closed
        if fault == "rollback"
        else conn.info.transaction_status.name == "IDLE"
    )
    assert len(cast(_Completions, harness.completions).prompts) == paid
    with connect(empty_database) as observer:
        for item in prepared:
            assert observer.execute(
                "SELECT case_id FROM cases WHERE case_id=%s FOR UPDATE NOWAIT",
                (item.input.case_id,),
            ).fetchone() == (item.input.case_id,)
            assert observer.execute(
                "SELECT run_id FROM runs WHERE run_id=%s FOR UPDATE NOWAIT",
                (item.input.run_id,),
            ).fetchone() == (item.input.run_id,)
        for table in (
            "run_attempts",
            "budget_reservations",
            "call_outcomes",
            "budget_ledger",
            "artifacts",
        ):
            # A blocks read now fails in the node's context check (3.3b),
            # before any attempt, reservation or call.
            assert _count(observer, "SELECT count(*) FROM " + table) == paid
        for [digest] in observer.execute("SELECT artifact_sha256 FROM artifacts"):
            assert blobs.get(digest)
        if paid == 3:
            _unspent(observer, prepared[1].input.run_id)


@pytest.mark.parametrize("fault", ["body", "restore", "wrong_database"])
def test_route_fault_restores_rows_and_all_triggers_on_failure(
    ready: Fixture, empty_database: str, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    conn = ready[0]
    run = _prepared(ready)[0].input.run_id
    database = urlsplit(empty_database).path.lstrip("/")
    trigger_query = (
        "SELECT tgname,tgenabled FROM pg_trigger"
        " WHERE tgrelid='run_routes'::regclass ORDER BY tgname"
    )
    route_query = "SELECT * FROM run_routes WHERE run_id=%s"
    triggers = conn.execute(trigger_query).fetchall()
    route = conn.execute(route_query, (run,)).fetchone()
    assert triggers and route is not None
    conn.rollback()
    execute = psycopg.Connection.execute
    ddl: list[str] = []
    injected = False
    entered = False

    def fail_restore(
        c: StoreConnection,
        query: str | psycopg.sql.Composable,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal injected
        text = query if isinstance(query, str) else query.as_string(c)
        if c is conn and text.startswith("ALTER TABLE run_routes"):
            ddl.append(text)
            if fault == "restore" and " ENABLE TRIGGER " in text:
                injected = True
                return execute(c, "SELECT qualification_private_column")
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    target = "caos_test_" + uuid4().hex if fault == "wrong_database" else database
    expected = (
        AssertionError if fault == "wrong_database" else psycopg.errors.UndefinedColumn
    )
    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail_restore)
        with pytest.raises(expected):
            with _without_route(conn, target, run):
                entered = True
                assert conn.execute(route_query, (run,)).fetchone() is None
                if fault == "body":
                    conn.execute("SELECT qualification_private_column")
    assert injected == (fault == "restore")
    assert entered == (fault != "wrong_database")
    assert ddl == [] if fault == "wrong_database" else len(ddl) >= 3
    assert conn.info.transaction_status.name == "IDLE"
    assert conn.execute(trigger_query).fetchall() == triggers
    assert conn.execute(route_query, (run,)).fetchone() == route
    conn.rollback()


def test_first_case_rechecks_separate_approver_after_whole_set_pass(
    ready: Fixture, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, _, harness, _ = ready
    prepared = _prepared(ready)
    _approve(conn, prepared)
    actor = _approve(conn, prepared[:1], gates=(Gate.RESEARCH_PLAN,))[0]
    original = execution_reads
    units = 0

    @contextmanager
    def reads(c: StoreConnection) -> Iterator[None]:
        nonlocal units
        with original(c):
            yield
        units += 1
        if units == len(prepared):
            with connect(empty_database) as independent:
                revoke(independent, case_id=prepared[0].input.case_id, user_id=actor)
                independent.commit()

    with monkeypatch.context() as patch:
        patch.setattr(subject, "execution_reads", reads)
        result = _run(ready, prepared)
    assert conn.info.transaction_status.name == "IDLE"
    assert result.matrix is None and len(result.performed) == 1
    assert result.performed[0].run_id == prepared[0].input.run_id
    assert result.performed[0].stopped is RefusalCode.GATE_APPROVAL_MISMATCH
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)


def test_a_deep_research_case_pins_its_brief_and_a_different_brief_is_refused(
    ready: Fixture,
) -> None:
    """§96: the harness pins a case's research brief exactly as the case carries
    it, and eligibility compares the two -- a case whose brief moved after the
    pin is not the case that was prepared, and is refused before any call."""
    conn, blobs, harness, qualification = ready
    first = qualification.cases[0]
    assert first.subject is not None
    brief = research_brief(first.subject.issuer_id, first.subject.issuer_name)
    case = replace(
        first,
        selection_id="LITE_DEEP_RESEARCH",
        research_brief=research_text(brief),
    )
    deep = (conn, blobs, harness, QualificationSet((case,)))
    [prepared] = _prepared(deep)
    assert prepared.input.research_json == case.research_brief
    _approve(conn, (prepared,))
    moved = replace(
        case,
        research_brief=research_text({**brief, "decision_context": "Moved"}),
    )
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _run((conn, blobs, harness, QualificationSet((moved,))), (prepared,))
    assert cast(_Completions, harness.completions).prompts == []
    _unspent(conn)
    without = replace(case, research_brief=None)
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _prepared((conn, blobs, harness, QualificationSet((without,))))
