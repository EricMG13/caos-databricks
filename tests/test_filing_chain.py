"""Sign, freeze and file the exact saved revision with independent actors."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_revisions import _read, _save

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import payload_bytes
from caos.deliverable.filing import (
    Receipt,
    file_deliverable,
    file_deliverable_in,
    freeze,
    freeze_in,
    persist_receipt,
    receipt_bytes,
    revision_signatures,
    sign_opinion,
    sign_opinion_in,
)
from caos.deliverable.revisions import save_revision_in
from caos.refusals import Refusal, RefusalCode
from caos.store import connect
from caos.store.audit import audit_trail
from caos.store.gates import withdraw_source, withdraw_source_in
from caos.store.members import Standing, grant
from caos.store.runs import create_case

__all__ = ["harness", "lite", "route"]


def _actor(lite: _Harness) -> UUID:
    actor = uuid4()
    grant(lite.conn, case_id=lite.case_id, user_id=actor, standing=Standing.APPROVER)
    lite.conn.commit()
    return actor


# FP-33: `_save` always drafts as `lite.approver`, so `lite.approver` cannot
# sign what it drafted. Callers that do not care who signs still need one
# stable identity per case -- not a fresh one on every call -- so a second,
# unqualified `_sign` still hits `DELIVERABLE_ALREADY_SIGNED` rather than
# quietly co-signing. Memoized per case rather than per test so two harnesses
# sharing no case never collide.
_DEFAULT_SIGNERS: dict[UUID, UUID] = {}


def _default_signer(lite: _Harness) -> UUID:
    signer = _DEFAULT_SIGNERS.get(lite.case_id)
    if signer is None:
        signer = _actor(lite)
        _DEFAULT_SIGNERS[lite.case_id] = signer
    return signer


def _sign(lite: _Harness, revision: UUID, actor: UUID | None = None) -> None:
    sign_opinion(
        lite.conn,
        case_id=lite.case_id,
        actor_id=actor or _default_signer(lite),
        revision_id=revision,
    )


def _freeze(lite: _Harness, revision: UUID, actor: UUID | None = None) -> str:
    return freeze(
        lite.conn,
        lite.blobs,
        lite.bundle,
        case_id=lite.case_id,
        actor_id=actor or _actor(lite),
        revision_id=revision,
    )


def test_signing_binds_the_stored_digest_with_no_caller_digest(lite: _Harness) -> None:
    assert "payload_sha256" not in inspect.signature(sign_opinion).parameters
    revision = _save(lite)
    _sign(lite, revision)
    row = lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_opinions"
    ).fetchone()
    lite.conn.rollback()
    assert row is not None
    assert row[0] == hashlib.sha256(payload_bytes(_read(lite, revision))).hexdigest()


def test_a_signer_cannot_sign_one_revision_twice(lite: _Harness) -> None:
    """One signature per signer per revision: a second press by the same
    approver is refused with its own code and writes nothing, while a second,
    distinct approver still signs."""
    from caos.api.app import _STATUS

    revision = _save(lite)
    _sign(lite, revision)
    with pytest.raises(Refusal, match=r"^DELIVERABLE_ALREADY_SIGNED$"):
        _sign(lite, revision)
    lite.conn.rollback()
    cosigner = _actor(lite)
    _sign(lite, revision, cosigner)
    signers = [who for who, _ in revision_signatures(lite.conn, lite.case_id, revision)]
    lite.conn.rollback()
    assert sorted(signers) == sorted([_default_signer(lite), cosigner])
    assert _STATUS[RefusalCode.DELIVERABLE_ALREADY_SIGNED] == 409


def test_revision_signatures_names_the_signer_and_its_bound_digest(
    lite: _Harness,
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    signatures = revision_signatures(lite.conn, lite.case_id, revision)
    lite.conn.rollback()
    assert signatures == [
        (
            _default_signer(lite),
            hashlib.sha256(payload_bytes(_read(lite, revision))).hexdigest(),
        )
    ]


def test_freeze_persists_exactly_the_signed_bytes(lite: _Harness) -> None:
    from caos.deliverable.revisions import prove_revision

    assert "payload" not in inspect.signature(freeze).parameters
    revision = _save(lite)
    data = payload_bytes(_read(lite, revision))
    assert (
        prove_revision(
            lite.conn,
            lite.blobs,
            lite.bundle,
            case_id=lite.case_id,
            revision_id=revision,
        )
        == data
    )
    lite.conn.rollback()
    _sign(lite, revision)
    digest = _freeze(lite, revision)
    assert lite.blobs.get(digest) == data
    assert lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_publications"
    ).fetchone() == (digest,)


def test_a_revision_of_another_case_cannot_be_signed_frozen_or_filed(
    lite: _Harness,
) -> None:
    revision = _save(lite)
    other = create_case(lite.conn, BoundaryText.of("Other issuer"))
    actor = uuid4()
    grant(lite.conn, case_id=other, user_id=actor, standing=Standing.APPROVER)
    lite.conn.commit()
    for function, args in (
        (sign_opinion, ()),
        (freeze, (lite.blobs, lite.bundle)),
        (file_deliverable, (lite.blobs,)),
    ):
        with pytest.raises(Refusal) as caught:
            function(
                lite.conn, *args, case_id=other, actor_id=actor, revision_id=revision
            )
        assert caught.value.code.value == "DELIVERABLE_NOT_FOUND"


@pytest.mark.parametrize("change", ["source", "authority"])
def test_freeze_refuses_after_a_source_withdrawal_or_bundle_authority_change(
    lite: _Harness, change: str
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    actor = _actor(lite)
    if change == "source":
        withdraw_source(
            lite.conn,
            case_id=lite.case_id,
            actor_id=lite.approver,
            source_id=lite.source_id,
        )
    else:
        from caos.methodology.bundle import MANIFEST_NAME

        path = lite.bundle.root / MANIFEST_NAME
        path.write_bytes(path.read_bytes() + b"\nchanged\n")
    with pytest.raises(Refusal):
        _freeze(lite, revision, actor)
    assert lite.conn.execute(
        "SELECT count(*) FROM deliverable_publications"
    ).fetchone() == (0,)


def test_filing_refuses_the_signer_and_the_freezer(lite: _Harness) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    freezer = _actor(lite)
    _freeze(lite, revision, freezer)
    for actor in (_default_signer(lite), freezer):
        with pytest.raises(Refusal) as caught:
            file_deliverable(
                lite.conn,
                lite.blobs,
                case_id=lite.case_id,
                actor_id=actor,
                revision_id=revision,
            )
        assert caught.value.code.value == "APPROVER_NOT_INDEPENDENT"


def test_the_receipt_names_its_case_run_and_filing_event(
    lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable

    from caos.deliverable import filing
    from caos.store import StoreConnection
    from caos.store.audit import GovernedAction, governed_write

    def followed_by_another_event(
        conn: StoreConnection,
        action: GovernedAction,
        write: Callable[[StoreConnection], None],
        *,
        after_event: Callable[[StoreConnection, str], None] | None = None,
    ) -> str:
        link = governed_write(conn, action, write, after_event=after_event)
        governed_write(
            conn,
            GovernedAction(
                action.case_id,
                action.actor_id,
                "FOLLOWING_EVENT",
                Standing.APPROVER,
                {},
            ),
            lambda unit: None,
        )
        return link

    revision = _save(lite)
    _sign(lite, revision)
    freezer, filer = _actor(lite), _actor(lite)
    _freeze(lite, revision, freezer)
    monkeypatch.setattr(filing, "governed_write", followed_by_another_event)
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=filer,
        revision_id=revision,
    )
    assert receipt.case_id == lite.case_id and receipt.run_id == lite.run_id
    assert isinstance(receipt, Receipt)
    assert receipt.revision_id == revision
    event = next(
        e
        for e in audit_trail(lite.conn, lite.case_id)
        if e.action == "DELIVERABLE_FILED"
    )
    assert receipt.filed_event_sha256 == event.entry_sha256
    assert (
        audit_trail(lite.conn, lite.case_id)[-1].entry_sha256
        != receipt.filed_event_sha256
    )
    assert "audit_head" not in json.loads(receipt_bytes(receipt))
    path = Path(__file__).parents[1] / "caos/deliverable/render.py"
    assert receipt.renderer_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_sign_freeze_file_refusals_preserve_one_chain(lite: _Harness) -> None:
    revision = _save(lite)
    with pytest.raises(Refusal, match="DELIVERABLE_NOT_SIGNED"):
        _freeze(lite, revision)
    with pytest.raises(Refusal, match="DELIVERABLE_NOT_FROZEN"):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=lite.approver,
            revision_id=revision,
        )
    _sign(lite, revision)
    cosigner = _actor(lite)
    _sign(lite, revision, cosigner)
    for signer in (_default_signer(lite), cosigner):
        with pytest.raises(Refusal, match="APPROVER_NOT_INDEPENDENT"):
            _freeze(lite, revision, signer)
    freezer, filer = _actor(lite), _actor(lite)
    _freeze(lite, revision, freezer)
    with pytest.raises(Refusal, match="DELIVERABLE_ALREADY_FROZEN"):
        _sign(lite, revision, filer)
    with pytest.raises(Refusal, match="DELIVERABLE_ALREADY_FROZEN"):
        _freeze(lite, revision, freezer)
    for signer in (_default_signer(lite), cosigner):
        with pytest.raises(Refusal, match="APPROVER_NOT_INDEPENDENT"):
            file_deliverable(
                lite.conn,
                lite.blobs,
                case_id=lite.case_id,
                actor_id=signer,
                revision_id=revision,
            )
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=filer,
        revision_id=revision,
    )
    assert receipt.signed_by == cosigner
    with pytest.raises(Refusal, match="DELIVERABLE_ALREADY_FILED"):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=filer,
            revision_id=revision,
        )
    actions = [e.action for e in audit_trail(lite.conn, lite.case_id)]
    assert (
        actions.count("DELIVERABLE_FROZEN") == actions.count("DELIVERABLE_FILED") == 1
    )


def test_filing_refuses_the_opinion_signer(lite: _Harness) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    with pytest.raises(Refusal, match="APPROVER_NOT_INDEPENDENT"):
        file_deliverable(
            lite.conn,
            lite.blobs,
            case_id=lite.case_id,
            actor_id=_default_signer(lite),
            revision_id=revision,
        )
    assert not any(
        e.action == "DELIVERABLE_FILED" for e in audit_trail(lite.conn, lite.case_id)
    )


def test_audit_package_verifies_with_stdlib_alone(
    lite: _Harness, tmp_path: Path
) -> None:
    import subprocess
    import sys
    import zipfile
    from io import BytesIO

    from caos.deliverable.package import build_package
    from caos.deliverable.render import render

    revision = _save(lite)
    payload = _read(lite, revision)
    _sign(lite, revision)
    _freeze(lite, revision)
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=_actor(lite),
        revision_id=revision,
    )
    archive = build_package(
        payload_bytes(payload), receipt_bytes(receipt), render(payload)
    )
    lite.conn.close()
    package = tmp_path / "filed.zip"
    package.write_bytes(archive)
    verifier = tmp_path / "verify_package.py"
    with zipfile.ZipFile(BytesIO(archive)) as opened:
        verifier.write_bytes(opened.read("verify_package.py"))
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(verifier), str(package)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == {"verified": True, "reason": None}


def test_the_in_unit_writes_commit_nothing_of_their_own(
    lite: _Harness, empty_database: str
) -> None:
    """Each governed write here is a whole `governed_write` call, so a caller
    that needs the domain write in a unit of its own -- one that also carries a
    command's receipt -- cannot use it. `save_revision_in`, `sign_opinion_in`,
    `freeze_in`, `file_deliverable_in`, `persist_receipt` and
    `withdraw_source_in` are that unit's half, and the property that makes them
    worth having is that none of them commits: run outside a governed write and
    rolled back, they leave nothing behind.
    """
    conn, case_id = lite.conn, lite.case_id
    author, signer, freezer, filer = (uuid4() for _ in range(4))
    revision = uuid4()

    digest = save_revision_in(
        conn,
        lite.blobs,
        lite.bundle,
        case_id=case_id,
        run_id=lite.run_id,
        actor_id=author,
        narrative=[],
        revision_id=revision,
    )
    assert (
        sign_opinion_in(conn, case_id=case_id, actor_id=signer, revision_id=revision)
        == digest
    )
    assert (
        freeze_in(
            conn,
            lite.blobs,
            lite.bundle,
            case_id=case_id,
            actor_id=freezer,
            revision_id=revision,
        )
        == digest
    )
    receipt = file_deliverable_in(
        conn, case_id=case_id, actor_id=filer, revision_id=revision
    )
    assert persist_receipt(conn, lite.blobs, receipt, "e" * 64).filed_event_sha256 == (
        "e" * 64
    )
    withdraw_source_in(conn, case_id=case_id, source_id=lite.source_id)
    conn.rollback()

    with connect(empty_database) as observer:
        counts = observer.execute(
            "SELECT (SELECT count(*) FROM deliverable_revisions),"
            " (SELECT count(*) FROM deliverable_opinions),"
            " (SELECT count(*) FROM deliverable_publications),"
            " (SELECT count(*) FROM deliverable_receipts),"
            " (SELECT count(*) FROM sources WHERE withdrawn_at IS NOT NULL)"
        ).fetchone()
    assert counts == (0, 0, 0, 0, 0)


def test_the_receipt_names_only_the_latest_of_several_signers(
    lite: _Harness,
) -> None:
    """FP-09, recorded where it bites rather than fixed.

    `one_opinion_per_signer` allows several approvers to sign before the freeze,
    and `revision_signatures` orders by `signed_at DESC`, so the detached
    receipt and the `DELIVERABLE_FILED` payload each carry whoever signed last.
    An earlier co-signer is absent from the portable proof, and the offline
    verifier can prove the independence of one signer out of however many there
    were. Carrying the sorted list is a change to `FiledReceipt` in
    `caos/api/wire.py`, whose `signed_by` is one `UUID`; this test states the
    gap so the fix has somewhere to land.
    """
    from caos.deliverable.filing import filing_payload

    revision = _save(lite)
    cosigner = _actor(lite)
    _sign(lite, revision)
    _sign(lite, revision, cosigner)
    _freeze(lite, revision, _actor(lite))
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=_actor(lite),
        revision_id=revision,
    )
    signers = {_default_signer(lite), cosigner}
    assert receipt.signed_by in signers
    assert {
        who for who, _ in revision_signatures(lite.conn, lite.case_id, revision)
    } == (signers)
    assert filing_payload(receipt)["signed_by"] == str(receipt.signed_by)
    assert json.loads(receipt_bytes(receipt))["signed_by"] == str(receipt.signed_by)
