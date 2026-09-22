"""Human approvals bind captured content and remain subject to live authority.

Keep the named Phase 6 exit and withdrawal tests while using complete run pins.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import research_brief
from psycopg.pq import TransactionStatus
from test_route_pinning import CATALOG_PATH, PROFILE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.read import read_evidence
from caos.graph.route import resolve_route
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect, gates, run_inputs
from caos.store.audit import audit_trail, verify_chain
from caos.store.cases import lock_case
from caos.store.gates import (
    Gate,
    GateApproval,
    GateState,
    approve_gate,
    gate_state,
    source_set_fingerprint,
    withdraw_source,
)
from caos.store.members import Standing, grant, revoke
from caos.store.routes import pin_route, resolved_route
from caos.store.run_inputs import RunSubject, load_run_input, pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set


@pytest.fixture
def gated(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> tuple[StoreConnection, UUID, UUID, UUID, UUID]:
    """A case with one source, a run on it, and an APPROVER."""
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("report.txt"),
                data=b"Total debt at 31 December 2026 was USD 1,240.0m\n",
            )
        ],
    )
    run_id = start_run(conn, case_id)
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    _pin(conn, case_id, run_id)
    return conn, case_id, run_id, source_id, approver


def _pin(
    conn: StoreConnection, case_id: UUID, run_id: UUID, research: object = None
) -> None:
    source = snapshot_source_set(conn, case_id)
    selection = "DEEP_RESEARCH" if research is not None else "MARKET_DISLOCATION"
    route = resolve_route(json.loads(CATALOG_PATH.read_text()), PROFILE, selection)
    pin_route(conn, run_id, route)
    pin_run_input(
        conn,
        run_id,
        source.version,
        Bundle(CATALOG_PATH.parents[3]),
        research,
        subject=RunSubject("EXAMPLE", "Example Holdings plc", "FY2025", "2026-09-08"),
    )


@pytest.mark.parametrize("field", ["preview_sha256", "input_fingerprint"])
def test_arbitrary_expected_digests_refuse(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], field: str
) -> None:
    conn, case_id, run_id, _source_id, approver = gated
    approval = _approval(conn, run_id, approver)
    approve_gate(conn, approval)
    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        approve_gate(
            conn,
            replace(approval, preview_sha256="0" * 64)
            if field == "preview_sha256"
            else replace(approval, input_fingerprint="0" * 64),
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert len(audit_trail(conn, case_id)) == 1
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.RELEASED


def _approval(
    conn: StoreConnection, run_id: UUID, approver: UUID, gate: Gate = Gate.SOURCE_SET
) -> GateApproval:
    preview = gates.gate_preview(conn, run_id, gate)
    return GateApproval(
        run_id=run_id,
        gate=gate,
        actor_id=approver,
        preview_sha256=preview.preview_sha256,
        input_fingerprint=preview.input_fingerprint,
    )


def test_a_gate_starts_open(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    conn, _case_id, run_id, _source_id, _approver = gated
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.OPEN


def test_changed_live_document_identity_reopens_both_gates(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    conn, _case_id, run_id, source_id, approver = gated
    previews = {gate: gates.gate_preview(conn, run_id, gate) for gate in Gate}
    for gate in Gate:
        approve_gate(conn, _approval(conn, run_id, approver, gate))
        assert gate_state(conn, run_id, gate) is GateState.RELEASED
    conn.execute(
        "UPDATE sources SET document_sha256 = %s WHERE source_id = %s",
        ("0" * 64, source_id),
    )
    conn.commit()
    for gate in Gate:
        assert gates.gate_preview(conn, run_id, gate) == previews[gate]
        assert gate_state(conn, run_id, gate) is GateState.OPEN


@pytest.mark.parametrize("gate", list(Gate))
def test_an_approval_releases_the_gate_it_was_given_for(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
    gate: Gate,
) -> None:
    conn, _case_id, run_id, _source_id, approver = gated
    approve_gate(conn, _approval(conn, run_id, approver, gate))
    assert gate_state(conn, run_id, gate) is GateState.RELEASED
    assert (
        gate_state(conn, run_id, next(g for g in Gate if g != gate)) is GateState.OPEN
    )


def test_approval_binds_the_exact_reviewed_content(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], tmp_path: Path
) -> None:
    """Phase 6 exit: an old approval cannot release a new run's source version."""
    conn, case_id, run_id, _source_id, approver = gated
    reviewed = gates.gate_preview(conn, run_id, Gate.SOURCE_SET)
    approval = _approval(conn, run_id, approver)
    approve_gate(conn, approval)
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.RELEASED

    # Later admission belongs to a new run/version, never expands the old pin.
    admit_pack(
        conn,
        BlobStore(tmp_path / "more"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("memo.txt"),
                data=b"Leverage is 3.4x on a net basis\n",
            )
        ],
    )
    conn.commit()
    newer = start_run(conn, case_id)
    _pin(conn, case_id, newer)
    assert gates.gate_preview(conn, run_id, Gate.SOURCE_SET) == reviewed
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.RELEASED
    assert gates.gate_preview(conn, newer, Gate.SOURCE_SET).input_fingerprint != (
        reviewed.input_fingerprint
    )
    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        approve_gate(conn, replace(approval, run_id=newer))
    conn.execute(
        "INSERT INTO run_gates (run_id, gate, preview_sha256,"
        " input_fingerprint, approved_by)"
        " SELECT %s, gate, preview_sha256, input_fingerprint, approved_by"
        " FROM run_gates WHERE run_id = %s",
        (newer, run_id),
    )
    conn.commit()
    assert gate_state(conn, newer, Gate.SOURCE_SET) is GateState.OPEN
    assert len(audit_trail(conn, case_id)) == 1


def test_a_withdrawn_source_refuses_the_read_and_reopens_the_gate(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    """The Phase 2 debt Phase 6 owes, and the second half of invariant 1.

    Both halves in one test because they are one fact: the source is gone, so
    reading it refuses and the approval that covered it no longer covers
    anything. Captured content remains intact; live withdrawal reopens use.
    """
    conn, case_id, run_id, source_id, approver = gated
    row = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s", (source_id,)
    ).fetchone()
    assert row is not None
    block_id = str(row[0])
    approve_gate(conn, _approval(conn, run_id, approver))
    assert read_evidence(conn, source_id=source_id, block_id=block_id)
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.RELEASED

    withdraw_source(conn, case_id=case_id, source_id=source_id, actor_id=approver)

    with pytest.raises(Refusal) as caught:
        read_evidence(conn, source_id=source_id, block_id=block_id)
    assert caught.value.code is RefusalCode.EVIDENCE_NOT_AVAILABLE

    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.OPEN
    assert [e.action for e in audit_trail(conn, case_id)] == [
        "GATE_RELEASED:SOURCE_SET",
        "SOURCE_WITHDRAWN",
    ]


def test_withdrawal_is_a_governed_write(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    """It removes evidence a conclusion may already rest on, so it is recorded
    and it is refused to someone who may not do it."""
    conn, case_id, _run_id, source_id, _approver = gated
    stranger = uuid4()

    with pytest.raises(Refusal) as caught:
        withdraw_source(conn, case_id=case_id, source_id=source_id, actor_id=stranger)

    assert caught.value.code is RefusalCode.NOT_AUTHORISED
    assert source_set_fingerprint(conn, case_id)


def test_withdrawing_what_is_not_live_here_is_refused_and_recorded_nowhere(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], tmp_path: Path
) -> None:
    """The audit chain records decisions that happened.

    A second withdrawal, another case's source and an id that names nothing all
    changed no row -- and each wrote SOURCE_WITHDRAWN into this case's chain, so
    the chain claimed four withdrawals where there had been one.
    """
    conn, case_id, _run_id, source_id, approver = gated
    other = conn.execute(
        "INSERT INTO cases (case_id, title) VALUES (%s, %s) RETURNING case_id",
        (uuid4(), "another issuer"),
    ).fetchone()
    assert other is not None
    [foreign] = admit_pack(
        conn,
        BlobStore(tmp_path / "other"),
        case_id=other[0],
        documents=[Document(filename=BoundaryText.of("b.txt"), data=b"Beta line\n")],
    )
    conn.commit()
    withdraw_source(conn, case_id=case_id, source_id=source_id, actor_id=approver)

    for target in (source_id, foreign, uuid4()):
        with pytest.raises(Refusal) as caught:
            withdraw_source(conn, case_id=case_id, source_id=target, actor_id=approver)
        assert caught.value.code is RefusalCode.EVIDENCE_NOT_AVAILABLE

    actions = [entry.action for entry in audit_trail(conn, case_id)]
    assert actions.count("SOURCE_WITHDRAWN") == 1


def test_a_reader_cannot_release_a_gate(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    conn, case_id, run_id, _source_id, _approver = gated
    reader = uuid4()
    grant(conn, case_id=case_id, user_id=reader, standing=Standing.READER)
    conn.commit()
    with pytest.raises(Refusal) as caught:
        approve_gate(conn, _approval(conn, run_id, reader))

    assert caught.value.code is RefusalCode.NOT_AUTHORISED
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.OPEN
    assert audit_trail(conn, case_id) == []


def test_approving_twice_keeps_the_later_approval(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
) -> None:
    """Repeated exact approvals retain the latest actor and both audit events."""
    conn, case_id, run_id, _source_id, approver = gated
    approve_gate(conn, _approval(conn, run_id, approver))
    other = uuid4()
    grant(conn, case_id=case_id, user_id=other, standing=Standing.ADMIN)
    conn.commit()
    approve_gate(conn, _approval(conn, run_id, other))
    assert gate_state(conn, run_id, Gate.SOURCE_SET) is GateState.RELEASED
    assert [e.actor_id for e in audit_trail(conn, case_id)] == [approver, other]
    assert conn.execute("SELECT approved_by FROM run_gates").fetchone() == (other,)
    assert verify_chain(conn, case_id)


def test_the_fingerprint_ignores_the_order_sources_arrived_in(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The isolated compatibility digest remains admission-order independent."""
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    first = Document(filename=BoundaryText.of("a.txt"), data=b"Alpha line\n")
    second = Document(filename=BoundaryText.of("b.txt"), data=b"Beta line\n")

    admit_pack(conn, blobs, case_id=case_id, documents=[first, second])
    one_way = source_set_fingerprint(conn, case_id)

    created = conn.execute(
        "INSERT INTO cases (case_id, title) VALUES (%s, %s) RETURNING case_id",
        (uuid4(), "same documents, other order"),
    ).fetchone()
    assert created is not None
    other = created[0]
    admit_pack(conn, blobs, case_id=other, documents=[second, first])

    assert source_set_fingerprint(conn, other) == one_way


@pytest.mark.parametrize(
    "research",
    [None, research_brief(), research_brief(decision_context="Café?\nExact text.")],
)
def test_preview_is_exact_immutable_captured_content(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], research: object
) -> None:
    conn, case_id, _run, source_id, _actor = gated
    run = start_run(conn, case_id)
    _pin(conn, case_id, run, research)
    pin = load_run_input(conn, run)
    assert pin is not None
    for gate in Gate:
        preview = gates.gate_preview(conn, run, gate)
        assert (preview.run_id, preview.case_id, preview.gate) == (run, case_id, gate)
        assert preview.input_fingerprint == pin.input_fingerprint
        assert (
            preview.preview_sha256
            == sha256(preview.content.encode("utf-8")).hexdigest()
        )
        data = json.loads(preview.content)
        assert preview.content == json.dumps(
            data, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
        )
        assert data["input"] == {
            **run_inputs.input_fields(pin),
            "run_id": str(run),
            "case_id": str(case_id),
        }
        assert data["input"]["research_json"] == pin.research_json
        if gate is Gate.SOURCE_SET:
            assert data["sources"][0]["filename"] == "report.txt"
            assert data["sources"][0]["source_id"] == str(source_id)
            assert data["sources"][0]["extractor_identity"]
            conn.execute("UPDATE sources SET filename = 'moving.txt'")
            conn.commit()
        else:
            route = resolved_route(conn, run)
            assert route is not None
            assert data["route"] == json.loads(json.dumps(asdict(route)))
        assert gates.gate_preview(conn, run, gate) == preview
        with pytest.raises(FrozenInstanceError):
            preview.content = "changed"  # type: ignore[misc]
    assert conn.info.transaction_status is TransactionStatus.INTRANS


@pytest.mark.parametrize("changed", ["run", "gate", "case"])
def test_approval_cannot_be_transplanted(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], changed: str, tmp_path: Path
) -> None:
    conn, case_id, run, _source, actor = gated
    approval = _approval(conn, run, actor)
    if changed == "gate":
        foreign = replace(approval, gate=Gate.RESEARCH_PLAN)
    else:
        target_case = case_id
        if changed == "case":
            target_case = uuid4()
            conn.execute(
                "INSERT INTO cases (case_id, title) VALUES (%s, 'Other')",
                (target_case,),
            )
            grant(conn, case_id=target_case, user_id=actor, standing=Standing.APPROVER)
            admit_pack(
                conn,
                BlobStore(tmp_path),
                case_id=target_case,
                documents=[Document(BoundaryText.of("other.txt"), b"Other input.")],
            )
        target = start_run(conn, target_case)
        _pin(conn, target_case, target)
        if changed == "run":
            # A version-2 pin binds its run through the COS run id, so even the
            # fingerprint differs; the preview digest binds it as well.
            assert (
                _approval(conn, target, actor).input_fingerprint
                != approval.input_fingerprint
            )
        conn.commit()
        foreign = replace(approval, run_id=target)
    with pytest.raises(Refusal, match=r"^GATE_APPROVAL_MISMATCH$"):
        approve_gate(conn, foreign)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert conn.execute("SELECT count(*) FROM run_gates").fetchone() == (0,)
    assert audit_trail(conn, case_id) == []


@pytest.mark.parametrize("state", ["absent", "corrupt"])
def test_input_ineligibility_refuses_approval_and_use(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], state: str
) -> None:
    conn, case_id, run, _source, actor = gated
    approval = _approval(conn, run, actor)
    if state == "absent":
        run = start_run(conn, case_id)
        approval = replace(approval, run_id=run)
        conn.execute(
            "INSERT INTO run_gates (run_id, gate, preview_sha256,"
            " input_fingerprint, approved_by)"
            " VALUES (%s, %s, %s, %s, %s)",
            (
                run,
                approval.gate.value,
                approval.preview_sha256,
                approval.input_fingerprint,
                actor,
            ),
        )
    else:
        database = conn.execute("SELECT current_database()").fetchone()
        assert database is not None and database[0].startswith("caos_test_")
        conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER input_immutable")
        conn.execute(
            "UPDATE run_inputs SET research_json = '{}' WHERE run_id = %s", (run,)
        )
        conn.execute("ALTER TABLE run_inputs ENABLE TRIGGER input_immutable")
    conn.commit()
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        approve_gate(conn, approval)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        gates.gate_preview(conn, run, Gate.SOURCE_SET)
    if state == "absent":
        assert gate_state(conn, run, Gate.SOURCE_SET) is GateState.OPEN
    else:
        with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
            gate_state(conn, run, Gate.SOURCE_SET)
    assert conn.info.transaction_status.name == "INTRANS"
    assert audit_trail(conn, case_id) == []


@pytest.mark.parametrize("change", ["withdraw", "revoke", "downgrade"])
@pytest.mark.parametrize("gate", list(Gate))
def test_live_authority_is_required_at_approval_and_use(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], change: str, gate: Gate
) -> None:
    conn, case_id, run, source, actor = gated
    approval = _approval(conn, run, actor, gate)
    approve_gate(conn, approval)
    if change == "withdraw":
        withdraw_source(conn, case_id=case_id, source_id=source, actor_id=actor)
    elif change == "revoke":
        revoke(conn, case_id=case_id, user_id=actor)
    else:
        grant(conn, case_id=case_id, user_id=actor, standing=Standing.WRITER)
    conn.commit()
    before = audit_trail(conn, case_id)
    assert gate_state(conn, run, gate) is GateState.OPEN
    expected = "EVIDENCE_NOT_AVAILABLE" if change == "withdraw" else "NOT_AUTHORISED"
    with pytest.raises(Refusal, match=f"^{expected}$"):
        approve_gate(conn, approval)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert audit_trail(conn, case_id) == before


@pytest.mark.parametrize("field", ["preview_sha256", "input_fingerprint"])
def test_use_checks_both_stored_digests(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], field: str
) -> None:
    conn, _case, run, _source, actor = gated
    approve_gate(conn, _approval(conn, run, actor))
    conn.execute(
        psycopg.sql.SQL("UPDATE run_gates SET {} = %s").format(
            psycopg.sql.Identifier(field)
        ),
        ("0" * 64,),
    )
    conn.commit()
    assert gate_state(conn, run, Gate.SOURCE_SET) is GateState.OPEN


@pytest.mark.parametrize("failure", ["first", "second", "commit", "cancel", "broken"])
def test_approval_failure_is_atomic_and_releases_locks(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, case_id, run, _source, actor = gated
    approval = _approval(conn, run, actor)
    if failure in {"first", "second"}:
        conn.execute(
            "ALTER TABLE "
            + (
                "run_gates ADD CHECK (false)"
                if failure == "first"
                else "audit_events ADD CHECK (false)"
            )
        )
    elif failure == "commit":
        conn.execute(
            "CREATE FUNCTION gate_failure() RETURNS trigger LANGUAGE plpgsql AS $$"
            " BEGIN RAISE EXCEPTION 'private'; END; $$;"
            " CREATE CONSTRAINT TRIGGER gate_failure AFTER INSERT ON run_gates"
            " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " EXECUTE FUNCTION gate_failure()"
        )
    else:
        from caos.store import audit

        def cancel(payload: object) -> str:
            if failure == "broken":
                conn.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(audit, "digest_of", cancel)
    conn.commit()
    with pytest.raises(
        KeyboardInterrupt if failure in {"cancel", "broken"} else Refusal
    ):
        approve_gate(conn, approval)
    assert conn.closed or conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_case(other, case_id)
        assert other.execute("SELECT count(*) FROM run_gates").fetchone() == (0,)
        assert other.execute("SELECT count(*) FROM audit_chain_heads").fetchone() == (
            0,
        )
        assert audit_trail(other, case_id) == []


@pytest.mark.parametrize("failure", ["missing", "database", "cancel"])
def test_owner_lookup_failure_cleans_up(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, _case, run, _source, actor = gated
    approval = _approval(conn, run, actor)
    conn.commit()
    if failure == "database":
        conn.execute("ALTER TABLE runs RENAME TO hidden_runs")
        conn.commit()
    elif failure == "cancel":
        execute = psycopg.Connection.execute

        def cancel(c: StoreConnection, *args: object, **kwargs: object) -> object:
            execute(c, *args, **kwargs)  # type: ignore[arg-type]
            raise KeyboardInterrupt

        monkeypatch.setattr(psycopg.Connection, "execute", cancel)
    else:
        approval = replace(approval, run_id=uuid4())
    with pytest.raises(KeyboardInterrupt if failure == "cancel" else Refusal) as caught:
        approve_gate(conn, approval)
    if isinstance(caught.value, Refusal):
        assert caught.value.code is (
            RefusalCode.RUN_NOT_FOUND
            if failure == "missing"
            else RefusalCode.STORE_UNAVAILABLE
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize("read", ["preview", "state"])
def test_read_failure_keeps_caller_transaction(
    gated: tuple[StoreConnection, UUID, UUID, UUID, UUID], read: str
) -> None:
    conn, _case, run, _source, _actor = gated
    conn.execute("ALTER TABLE run_inputs RENAME TO hidden_inputs")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        (gates.gate_preview if read == "preview" else gate_state)(
            conn, run, Gate.SOURCE_SET
        )
    assert conn.info.transaction_status is TransactionStatus.INERROR
    conn.rollback()
    assert load_run_input(conn, run) is not None
