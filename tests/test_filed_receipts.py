"""Exact durable receipts from a real saved, signed, frozen and filed chain."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_filing_chain import _actor, _default_signer, _freeze, _sign
from test_revisions import _save

from caos.blobs import BlobStore
from caos.deliverable.filing import (
    Receipt,
    file_deliverable,
    freeze_in,
    receipt_bytes,
    revision_signatures,
    sign_opinion_in,
)
from caos.deliverable.receipts import read_filed_receipt
from caos.refusals import Refusal
from caos.store import connect
from caos.store.audit import (
    GENESIS,
    GovernedAction,
    _link,
    audit_trail,
    digest_of,
    verify_chain,
)
from caos.store.members import Standing

__all__ = ["harness", "lite", "route"]


def _file(lite: _Harness) -> Receipt:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    return file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=_actor(lite),
        revision_id=revision,
    )


def _read(lite: _Harness, receipt: Receipt) -> bytes:
    return read_filed_receipt(
        lite.conn,
        lite.blobs,
        case_id=receipt.case_id,
        run_id=receipt.run_id,
        revision_id=receipt.revision_id,
    )


def test_read_filed_receipt_returns_exact_bytes_after_reconnect_and_new_draft(
    lite: _Harness,
    empty_database: str,
) -> None:
    receipt = _file(lite)
    expected = receipt_bytes(receipt)
    _save(lite, [[{"text": "A later draft"}]])
    with connect(empty_database) as reopened:
        assert _read(replace(lite, conn=reopened), receipt) == expected
    row = lite.conn.execute(
        "SELECT receipt_sha256,filed_event_sha256 FROM deliverable_receipts"
    ).fetchone()
    assert row == (sha256(expected).hexdigest(), receipt.filed_event_sha256)
    assert audit_trail(lite.conn, lite.case_id)[-1].entry_sha256 != row[1]


@pytest.mark.parametrize("field", ["case_id", "run_id", "revision_id"])
def test_read_filed_receipt_refuses_wrong_identity(lite: _Harness, field: str) -> None:
    receipt = _file(lite)
    with pytest.raises(Refusal, match="DELIVERABLE_NOT_FOUND"):
        _read(
            lite,
            replace(
                receipt,
                case_id=uuid4() if field == "case_id" else receipt.case_id,
                run_id=uuid4() if field == "run_id" else receipt.run_id,
                revision_id=uuid4() if field == "revision_id" else receipt.revision_id,
            ),
        )


def test_unfiled_and_legacy_publications_are_not_receipts(lite: _Harness) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    for filed in (False, True):
        if filed:
            lite.conn.execute(
                "UPDATE deliverable_publications SET filed_by=%s,filed_at=now()",
                (uuid4(),),
            )
        with pytest.raises(Refusal, match="DELIVERABLE_NOT_FOUND"):
            read_filed_receipt(
                lite.conn,
                lite.blobs,
                case_id=lite.case_id,
                run_id=lite.run_id,
                revision_id=revision,
            )


@pytest.mark.parametrize("target", ["receipt", "payload"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_corrupt_filed_bytes_refuse(
    lite: _Harness,
    target: str,
    damage: str,
) -> None:
    receipt = _file(lite)
    digest = (
        sha256(receipt_bytes(receipt)).hexdigest()
        if target == "receipt"
        else receipt.payload_sha256
    )
    path = lite.blobs.path_of(digest)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corruption sentinel")
    with pytest.raises(Refusal, match=r"BLOB_(NOT_FOUND|DIGEST_MISMATCH)"):
        _read(lite, receipt)


def _corrupt(lite: _Harness, statement: str, value: object) -> None:
    """Fault injection stays inside this harness's disposable UUID database."""
    row = lite.conn.execute("SELECT current_database()").fetchone()
    assert row is not None and row[0].startswith("caos_test_")
    lite.conn.execute("SET LOCAL session_replication_role = replica")
    lite.conn.execute(statement, (value,))
    lite.conn.execute("SET LOCAL session_replication_role = origin")


@pytest.mark.parametrize("field", ["filed_by", "frozen_by", "signed_by", "digest"])
def test_receipt_refuses_changed_publication_or_signature(
    lite: _Harness,
    field: str,
) -> None:
    receipt = _file(lite)
    statements = {
        "filed_by": "UPDATE deliverable_publications SET filed_by=%s",
        "frozen_by": "UPDATE deliverable_publications SET frozen_by=%s",
        "signed_by": "UPDATE deliverable_opinions SET signed_by=%s",
        "digest": "UPDATE deliverable_publications SET payload_sha256=%s",
    }
    _corrupt(lite, statements[field], "f" * 64 if field == "digest" else uuid4())
    with pytest.raises(Refusal, match="DELIVERABLE_PAYLOAD_INVALID"):
        _read(lite, receipt)


@pytest.mark.parametrize(
    "damage",
    [
        "later_event",
        "audit_payload",
        "receipt",
        "pin",
        "prior_event",
        "head",
        "missing_event",
    ],
)
def test_receipt_refuses_corrupt_audit_linkage(lite: _Harness, damage: str) -> None:
    receipt = _file(lite)
    _save(lite)
    if damage == "later_event":
        _corrupt(
            lite,
            "UPDATE deliverable_receipts SET filed_event_sha256=%s",
            audit_trail(lite.conn, lite.case_id)[-1].entry_sha256,
        )
    elif damage in {"audit_payload", "prior_event"}:
        _corrupt(
            lite,
            "UPDATE audit_events SET payload_sha256=%s"
            + (
                " WHERE action='DELIVERABLE_FILED'"
                if damage == "audit_payload"
                else " WHERE seq=1"
            ),
            "e" * 64,
        )
    elif damage == "head":
        _corrupt(lite, "UPDATE audit_chain_heads SET head_sha256=%s", "e" * 64)
    elif damage == "missing_event":
        _corrupt(
            lite,
            "DELETE FROM audit_events WHERE entry_sha256=%s",
            receipt.filed_event_sha256,
        )
    elif damage == "pin":
        _corrupt(lite, "UPDATE deliverable_receipts SET renderer_sha256=%s", "e" * 64)
    else:
        data = json.loads(receipt_bytes(receipt))
        data["run_id"] = str(uuid4())
        _corrupt(
            lite,
            "UPDATE deliverable_receipts SET receipt_sha256=%s",
            lite.blobs.put(json.dumps(data).encode()),
        )
    with pytest.raises(Refusal, match="DELIVERABLE_PAYLOAD_INVALID"):
        _read(lite, receipt)


def test_read_filed_receipt_refuses_a_signature_or_freeze_never_audited(
    lite: _Harness,
) -> None:
    """FP-34: `read_filed_receipt`'s one caller, `_publication`
    (`caos/api/reads/reports.py`), checks that an `OPINION_SIGNED` event for
    every signer and a `DELIVERABLE_FROZEN` event for the freezer are in the
    case's own audit trail; this reader did not. `sign_opinion_in`/`freeze_in`
    write the `deliverable_opinions`/`deliverable_publications` rows this
    checks for consistency, but -- called outside `governed_write`, as they
    are meant to be composed by a caller with its own envelope -- write no
    audit event at all. Filed normally afterward, the receipt was self
    consistent and read back as genuine although no signature or freeze was
    ever on the record.
    """
    revision = _save(lite)
    signer, freezer, filer = _actor(lite), _actor(lite), _actor(lite)
    sign_opinion_in(lite.conn, case_id=lite.case_id, actor_id=signer, revision_id=revision)
    freeze_in(
        lite.conn,
        lite.blobs,
        lite.bundle,
        case_id=lite.case_id,
        actor_id=freezer,
        revision_id=revision,
    )
    lite.conn.commit()
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=filer,
        revision_id=revision,
    )
    # The audit trail is genuinely valid and holds the filing event, but never
    # an OPINION_SIGNED or a DELIVERABLE_FROZEN one.
    actions = {entry.action for entry in audit_trail(lite.conn, lite.case_id)}
    assert "DELIVERABLE_FILED" in actions
    assert not actions & {"OPINION_SIGNED", "DELIVERABLE_FROZEN"}
    with pytest.raises(Refusal, match="DELIVERABLE_PAYLOAD_INVALID"):
        _read(lite, receipt)


def test_receipt_rows_are_immutable(lite: _Harness) -> None:
    receipt = _file(lite)
    for statement in (
        "UPDATE deliverable_receipts SET receipt_sha256=receipt_sha256",
        "DELETE FROM deliverable_receipts",
        "TRUNCATE deliverable_receipts CASCADE",
    ):
        with pytest.raises(psycopg.Error):
            lite.conn.execute(statement)
        lite.conn.rollback()
    assert _read(lite, receipt) == receipt_bytes(receipt)


def test_receipt_storage_failure_rolls_back_filing_and_audit(
    lite: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    filer = _actor(lite)

    def failed_put(self: BlobStore, data: bytes) -> str:
        raise OSError

    monkeypatch.setattr(BlobStore, "put", failed_put)
    with pytest.raises(OSError):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=filer,
            revision_id=revision,
        )
    lite.conn.commit()  # A caller cannot accidentally commit the failed write.
    assert lite.conn.execute(
        "SELECT filed_by,filed_at FROM deliverable_publications"
    ).fetchone() == (None, None)
    assert lite.conn.execute(
        "SELECT count(*) FROM deliverable_receipts"
    ).fetchone() == (0,)
    assert all(
        e.action != "DELIVERABLE_FILED" for e in audit_trail(lite.conn, lite.case_id)
    )
    assert verify_chain(lite.conn, lite.case_id)


def test_filed_receipt_keeps_its_historical_renderer_pin(
    lite: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _file(lite)
    read_bytes = Path.read_bytes

    def changed_renderer(path: Path) -> bytes:
        return b"new renderer version" if path.name == "render.py" else read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changed_renderer)
    assert _read(lite, receipt) == receipt_bytes(receipt)


def test_coherently_replaced_receipt_and_pin_cannot_change_the_filed_event(
    lite: _Harness,
) -> None:
    receipt = _file(lite)
    forged = replace(receipt, renderer_sha256="e" * 64)
    _corrupt(
        lite,
        "UPDATE deliverable_receipts SET renderer_sha256=%s",
        forged.renderer_sha256,
    )
    _corrupt(
        lite,
        "UPDATE deliverable_receipts SET receipt_sha256=%s",
        lite.blobs.put(receipt_bytes(forged)),
    )
    assert verify_chain(lite.conn, lite.case_id)
    with pytest.raises(Refusal, match="DELIVERABLE_PAYLOAD_INVALID"):
        _read(lite, receipt)


@pytest.mark.parametrize("fault", ["freezer_is_signer", "cosigner_digest"])
def test_filing_rechecks_every_signer_and_freezer_independence(
    lite: _Harness,
    fault: str,
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _sign(lite, revision, _actor(lite))
    _freeze(lite, revision)
    if fault == "freezer_is_signer":
        _corrupt(
            lite,
            "UPDATE deliverable_publications SET frozen_by=%s",
            _default_signer(lite),
        )
    else:
        _corrupt(
            lite,
            "UPDATE deliverable_opinions SET payload_sha256=%s"
            " WHERE signed_at=(SELECT min(signed_at) FROM deliverable_opinions)",
            "f" * 64,
        )
    with pytest.raises(
        Refusal, match=r"APPROVER_NOT_INDEPENDENT|DELIVERABLE_NOT_SIGNED"
    ):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=_actor(lite),
            revision_id=revision,
        )


def test_freeze_refuses_a_signature_altered_outside_this_code(
    lite: _Harness,
) -> None:
    """`freeze_in`'s signature digest check is tamper evidence: signing through
    this code always binds the revision's digest, so only a row altered outside
    it -- here with triggers bypassed -- can disagree, and the freeze refuses."""
    revision = _save(lite)
    _sign(lite, revision)
    _corrupt(lite, "UPDATE deliverable_opinions SET payload_sha256=%s", "f" * 64)
    with pytest.raises(Refusal, match=r"^DELIVERABLE_MOVED_SINCE_SIGNING$"):
        _freeze(lite, revision)


def test_filing_refuses_a_freeze_altered_outside_this_code(lite: _Harness) -> None:
    """The freeze's digest is the revision's by construction; a publication row
    altered outside this code is the one thing that makes filing disagree."""
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    _corrupt(lite, "UPDATE deliverable_publications SET payload_sha256=%s", "f" * 64)
    with pytest.raises(Refusal, match=r"^DELIVERABLE_MOVED_SINCE_SIGNING$"):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=_actor(lite),
            revision_id=revision,
        )


def test_receipt_row_failure_rolls_back_even_after_blob_and_audit_writes(
    lite: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    filer = _actor(lite)
    execute = lite.conn.execute

    def fail_receipt_row(query: str, *args: object, **kwargs: object) -> object:
        if "INSERT INTO deliverable_receipts" in query:
            raise psycopg.OperationalError
        return execute(query, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lite.conn, "execute", fail_receipt_row)
    with pytest.raises(Refusal, match="STORE_UNAVAILABLE"):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=filer,
            revision_id=revision,
        )
    lite.conn.commit()
    assert lite.conn.execute(
        "SELECT filed_by FROM deliverable_publications"
    ).fetchone() == (None,)
    assert lite.conn.execute(
        "SELECT count(*) FROM deliverable_receipts"
    ).fetchone() == (0,)
    assert all(
        e.action != "DELIVERABLE_FILED" for e in audit_trail(lite.conn, lite.case_id)
    )


@pytest.mark.parametrize("change", ["source", "authority"])
def test_a_filed_receipt_survives_live_state_moving_under_it(
    lite: _Harness, change: str
) -> None:
    """A filed record is served from its own bytes, whatever moves after it.

    This asserted the opposite until FP-05. Every Committee read of a filed
    revision re-ran `prove_revision` against the current sources and the current
    `vendor/deploy-v`, so a WRITER withdrawing a cited source or a routine
    bundle upgrade -- two ordinary events -- locked every filed record out of
    the section permanently, refusing with the codes tampering produces and
    offering remediation for a record nobody can change. Filing re-proves under
    the case lock; after that the bytes and the audit chain are the proof.
    """
    from caos.methodology.bundle import MANIFEST_NAME
    from caos.store.gates import withdraw_source

    receipt = _file(lite)
    expected = _read(lite, receipt)
    if change == "source":
        withdraw_source(
            lite.conn,
            case_id=lite.case_id,
            actor_id=lite.approver,
            source_id=lite.source_id,
        )
    else:
        path = lite.bundle.root / MANIFEST_NAME
        path.write_bytes(path.read_bytes() + b"\nchanged\n")
    assert _read(lite, receipt) == expected


def test_receipt_migration_preserves_legacy_filing_without_inventing_bytes(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import caos.store as store
    from caos.boundary_text import BoundaryText
    from caos.store.runs import create_case, start_run

    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:15])
            store.apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Historical issuer"))
        run_id = start_run(conn, case_id)
        revision, signer, freezer, filer = uuid4(), uuid4(), uuid4(), uuid4()
        conn.execute(
            "INSERT INTO deliverable_revisions"
            " (revision_id,case_id,run_id,payload_sha256,saved_by)"
            " VALUES (%s,%s,%s,%s,%s)",
            (revision, case_id, run_id, "a" * 64, signer),
        )
        conn.execute(
            "INSERT INTO deliverable_publications"
            " (revision_id,case_id,payload_sha256,frozen_by,filed_by,filed_at)"
            " VALUES (%s,%s,%s,%s,%s,now())",
            (str(revision), case_id, "a" * 64, freezer, filer),
        )
        payload = {
            "revision_id": str(revision),
            "payload_sha256": "a" * 64,
            "renderer_sha256": "b" * 64,
        }
        action = GovernedAction(
            case_id, filer, "DELIVERABLE_FILED", Standing.APPROVER, payload
        )
        digest = digest_of(payload)
        event = _link(action, 1, GENESIS, digest)
        conn.execute(
            "INSERT INTO audit_events"
            " (case_id,seq,actor_id,action,payload_sha256,previous_sha256,entry_sha256)"
            " VALUES (%s,1,%s,%s,%s,%s,%s)",
            (case_id, filer, action.action, digest, GENESIS, event),
        )
        conn.execute(
            "INSERT INTO audit_chain_heads (case_id,seq,head_sha256) VALUES (%s,1,%s)",
            (case_id, event),
        )
        conn.commit()
        before = conn.execute("SELECT * FROM deliverable_publications").fetchall()
        store.apply_schema(conn)
        assert (
            conn.execute("SELECT * FROM deliverable_publications").fetchall() == before
        )
        assert conn.execute("SELECT count(*) FROM deliverable_receipts").fetchone() == (
            0,
        )
        assert conn.execute("SELECT * FROM legacy_filing_events").fetchall() == [
            (case_id, event)
        ]
        assert verify_chain(conn, case_id)


def test_released_receipt_prefix_refuses_an_ambiguous_receiptless_filing(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import caos.store as store
    from caos.boundary_text import BoundaryText
    from caos.store.runs import create_case

    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:16])
            store.apply_schema(conn)
        case_id, filer, revision = (
            create_case(conn, BoundaryText.of("Ambiguous")),
            uuid4(),
            uuid4(),
        )
        payload = {
            "revision_id": str(revision),
            "payload_sha256": "a" * 64,
            "renderer_sha256": "b" * 64,
        }
        action = GovernedAction(
            case_id, filer, "DELIVERABLE_FILED", Standing.APPROVER, payload
        )
        digest = digest_of(payload)
        event = _link(action, 1, GENESIS, digest)
        conn.execute(
            "INSERT INTO audit_events"
            " (case_id,seq,actor_id,action,payload_sha256,previous_sha256,entry_sha256)"
            " VALUES (%s,1,%s,%s,%s,%s,%s)",
            (case_id, filer, action.action, digest, GENESIS, event),
        )
        conn.execute(
            "INSERT INTO audit_chain_heads (case_id,seq,head_sha256) VALUES (%s,1,%s)",
            (case_id, event),
        )
        conn.commit()
        with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
            store.apply_schema(conn)


def test_revision_signatures_names_each_signer_and_what_they_signed(
    lite: _Harness,
) -> None:
    """The reader three callers share: who signed this revision, over which
    payload digest. A signature over a digest the revision no longer has is
    what `file_deliverable` refuses, so it must be read, not assumed."""
    revision = _save(lite)
    assert revision_signatures(lite.conn, lite.case_id, revision) == []
    signer = _actor(lite)
    _sign(lite, revision, signer)
    signed = revision_signatures(lite.conn, lite.case_id, revision)
    assert [who for who, _ in signed] == [signer]
    assert all(len(digest) == 64 for _, digest in signed)
