from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from qualification_fixtures import (
    qualification_performed,
    record_performed_earlier,
    record_runs,
)

import caos.store as store
from caos.qualification.matrix import ROW_REFUSALS, ExpectedCitation, MatrixRow
from caos.qualification.store import (
    ONE_VERDICT_PER_EVIDENCE,
    Evidence,
    PerformedEvidence,
    _answered,
    answered_document,
    assert_store_agrees,
    current_verdict,
    document_complete,
    evidence_at,
    performed_evidence,
    record_evidence,
    record_performed,
    record_verdict,
    verdict_reviewer_id,
)
from caos.qualification.verdict import Verdict, read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, apply_schema, connect


def _evidence() -> Evidence:
    return Evidence("a" * 64, "b" * 64, "build", "adapter", "openrouter", "model")


def _performed() -> PerformedEvidence:
    return qualification_performed()


def _verdict(now: datetime, evidence: Evidence) -> Verdict:
    return read_verdict(
        {
            "provider": evidence.provider + ":" + evidence.model,
            "qualification_set_sha256": evidence.qualification_set_sha256,
            "build_id": evidence.build_id,
            "decided_at": now.isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "reviewer": "Reviewer",
        },
        now=now,
    )


def test_record_evidence_is_idempotent_and_bound(empty_database: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        evidence = _performed().evidence
        assert record_performed(conn, _performed()) == evidence.performed_sha256
        assert record_evidence(conn, evidence) == evidence.sha256
        assert record_evidence(conn, evidence) == evidence.sha256
        assert evidence_at(conn, evidence_sha256=evidence.sha256) == evidence
        assert evidence_at(conn, evidence_sha256="c" * 64) is None
        conn.rollback()


def test_a_detached_performed_hash_cannot_be_recorded(empty_database: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            record_evidence(conn, _evidence())


def test_a_legacy_verdict_without_a_snapshot_is_not_current(
    empty_database: str,
) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    evidence = _evidence()
    verdict = _verdict(now, evidence)
    with connect(empty_database) as conn:
        with patch.object(store, "MIGRATIONS", store.MIGRATIONS[:-1]):
            apply_schema(conn)
        conn.execute(
            "INSERT INTO qualification_evidence"
            " (evidence_sha256,qualification_set_sha256,performed_sha256,build_id,"
            " adapter_version,provider,model) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (evidence.sha256, *asdict(evidence).values()),
        )
        conn.execute(
            "INSERT INTO qualification_verdicts"
            " (evidence_sha256,reviewer_id,reviewer,decided_at,expires_at)"
            " VALUES (%s,%s,%s,%s,%s)",
            (
                evidence.sha256,
                uuid4(),
                verdict.reviewer.value,
                verdict.decided_at,
                verdict.expires_at,
            ),
        )
        conn.commit()
        apply_schema(conn)

        with pytest.raises(Refusal, match=r"^VERDICT_INCOMPLETE$"):
            current_verdict(conn, evidence=evidence, now=now)


def test_a_snapshot_with_different_identity_cannot_back_a_legacy_verdict(
    empty_database: str,
) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    performed = _performed()
    evidence = replace(performed.evidence, model="substituted-model")
    verdict = _verdict(now, evidence)
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed_earlier(conn, performed)
        conn.execute(
            "INSERT INTO qualification_evidence"
            " (evidence_sha256,qualification_set_sha256,performed_sha256,build_id,"
            " adapter_version,provider,model) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (evidence.sha256, *asdict(evidence).values()),
        )
        conn.execute(
            "INSERT INTO qualification_verdicts"
            " (evidence_sha256,reviewer_id,reviewer,decided_at,expires_at)"
            " VALUES (%s,%s,%s,%s,%s)",
            (
                evidence.sha256,
                uuid4(),
                verdict.reviewer.value,
                verdict.decided_at,
                verdict.expires_at,
            ),
        )
        conn.commit()

        assert evidence_at(conn, evidence_sha256=evidence.sha256) is None
        with pytest.raises(Refusal, match=r"^VERDICT_INCOMPLETE$"):
            current_verdict(conn, evidence=evidence, now=now)


def test_performed_evidence_digest_changes_with_the_recorded_outcome() -> None:
    original = _performed()
    [record] = original.performed.performed
    changed = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            performed=(replace(record, status=RunStatus.FAILED),),
        ),
    )

    assert changed.evidence.performed_sha256 != original.evidence.performed_sha256


def test_an_incomplete_snapshot_cannot_receive_a_verdict(empty_database: str) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    original = _performed()
    incomplete = performed_evidence(
        prepared=original.prepared,
        performed=replace(original.performed, matrix=None),
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed_earlier(conn, incomplete)
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            record_verdict(
                conn,
                evidence=incomplete.evidence,
                reviewer_id=uuid4(),
                verdict=_verdict(now, incomplete.evidence),
            )


def test_a_blocked_unproven_matrix_cannot_receive_a_verdict(
    empty_database: str,
) -> None:
    """A run that validly refused to start is not a run a reviewer may sign.

    A blocked readiness handoff is accepted, so the set stops with nothing
    recorded in `stopped` and a matrix is still built — every row unproven,
    every expected citation missed. `Assurance` has one reviewer-written
    member, so signing that snapshot would say QUALIFIED over a run that
    produced no artifact at all.
    """
    now = datetime(2026, 9, 15, tzinfo=UTC)
    original = _performed()
    [record] = original.performed.performed
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    blocked = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            performed=(replace(record, status=RunStatus.BLOCKED),),
            matrix=replace(
                matrix,
                rows=(
                    replace(
                        row,
                        proven=False,
                        missed=(ExpectedCitation("CP-0", "c" * 64, "quoted text"),),
                    ),
                ),
            ),
        ),
    )

    assert blocked.complete is False
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed_earlier(conn, blocked)
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            record_verdict(
                conn,
                evidence=blocked.evidence,
                reviewer_id=uuid4(),
                verdict=_verdict(now, blocked.evidence),
            )


def test_a_completed_run_that_missed_a_key_cannot_receive_a_verdict(
    empty_database: str,
) -> None:
    """Finishing the route is not the same as answering the key."""
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    missed = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(
                matrix,
                rows=(
                    replace(
                        row,
                        missed=(ExpectedCitation("CP-0", "c" * 64, "quoted text"),),
                    ),
                ),
            ),
        ),
    )

    assert missed.complete is False


def test_a_case_whose_forecast_was_not_met_cannot_receive_a_verdict() -> None:
    """A forecast is a key too, and nothing was reading it.

    `assert_measurable` admits a case keyed only by a forecast, and such a case
    has no expected citations to miss — so with `complete` consulting only
    `proven`, `missed` and `expected_refusal_met`, its row was signable with
    the forecast unmet. `forecast_met` is `None` when none was declared, so the
    test is `is not False` rather than truthiness.
    """
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    unmet = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, forecast_met=False),)),
        ),
    )

    assert unmet.complete is False
    met = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, forecast_met=True),)),
        ),
    )
    assert met.complete is True


def test_a_case_whose_gate_refused_a_module_cannot_receive_a_verdict() -> None:
    """A gate that wrongly refuses a module is invisible to a citation key.

    The module never runs, so it cites nothing, and every key aimed at it reads
    as the model failing to find evidence when the truth is the model was never
    asked. `ready_met` is the host's own readiness projection, and a snapshot
    where CP-0 gated a module the set said must run is not signable.
    """
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    gated = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, ready_met=False),)),
        ),
    )

    assert gated.complete is False
    allowed = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, ready_met=True),)),
        ),
    )
    assert allowed.complete is True


def test_a_case_whose_modules_concluded_otherwise_cannot_receive_a_verdict() -> None:
    """The conclusion key is the one that measures the analysis.

    A citation key asks whether a module's handful of quotes happened to
    include a line. This asks what it concluded — and a snapshot where a module
    reached the wrong conclusion is not signable however well it quoted.
    """
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    wrong = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, projections_met=False),)),
        ),
    )

    assert wrong.complete is False
    right = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, projections_met=True),)),
        ),
    )
    assert right.complete is True


def test_a_case_that_met_the_refusal_it_declared_is_complete() -> None:
    """A set may declare a refusal as its answer; meeting it is a result.

    This asserts the rule over a hand-built row.
    `test_a_case_that_declared_the_block_it_expected_is_signable` asserts the
    path, over a real blocked run, which is what closed the gap this docstring
    used to describe.
    """
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    [record] = original.performed.performed
    refused = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            performed=(replace(record, status=RunStatus.BLOCKED),),
            matrix=replace(
                matrix,
                rows=(replace(row, proven=False, expected_refusal_met=True),),
            ),
        ),
    )

    assert refused.complete is True
    assert document_complete(refused.document) is True


def test_a_met_refusal_over_a_run_that_completed_is_not_complete() -> None:
    """DQ-3: the waiver held whatever the record said, and the same row over a
    COMPLETE run is the shape pre-FP-01 code recorded for a run that finished
    after a stale attempt refusal. Re-derivation re-read that flag, so the
    stale snapshot signed, stayed current and qualified its pathway."""
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    stale = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(matrix, rows=(replace(row, expected_refusal_met=True),)),
        ),
    )
    [record] = stale.performed.performed
    assert record.status is RunStatus.COMPLETE
    assert stale.complete is False
    assert document_complete(stale.document) is False


def test_record_verdict_binds_the_reviewer_and_evidence(empty_database: str) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        evidence = performed.evidence
        record_performed_earlier(conn, performed)
        record_runs(conn, performed)
        reviewer = uuid4()
        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=reviewer,
            verdict=_verdict(now, evidence),
        )
        assert current_verdict(conn, evidence=evidence, now=now)


def test_verdict_reviewer_id_is_the_authenticated_signer_or_none(
    empty_database: str,
) -> None:
    """CF-027. The signer's own identity is store provenance the six-binding
    document never carried (`caos/qualification/verdict.py`), so it is read
    beside `current_verdict` rather than off its `Verdict`."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        evidence = performed.evidence
        record_performed_earlier(conn, performed)
        record_runs(conn, performed)

        assert verdict_reviewer_id(conn, evidence_sha256=evidence.sha256) is None

        reviewer = uuid4()
        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=reviewer,
            verdict=_verdict(now, evidence),
        )

        assert verdict_reviewer_id(conn, evidence_sha256=evidence.sha256) == reviewer
        assert verdict_reviewer_id(conn, evidence_sha256="f" * 64) is None


@pytest.mark.parametrize("recorded", ["another-model", None])
def test_a_verdict_is_refused_unless_every_run_recorded_the_model_it_names(
    empty_database: str, recorded: str | None
) -> None:
    """`evidence.model` is what the harness configured; `call_outcomes.model`
    is what the run called (§25). The verdict binds the second."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        evidence = performed.evidence
        record_performed_earlier(conn, performed)
        record_runs(conn, performed, model=recorded, outcome=recorded is not None)
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            record_verdict(
                conn,
                evidence=evidence,
                reviewer_id=uuid4(),
                verdict=_verdict(now, evidence),
            )


def test_the_one_verdict_constraint_is_mapped_by_name_not_by_message(
    empty_database: str,
) -> None:
    """`0019_one_qualification_verdict.sql` is the only unique violation this
    insert can raise that means "already signed", and it is matched by the
    constraint name the migration declares."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        evidence = performed.evidence
        record_performed_earlier(conn, performed)
        record_runs(conn, performed)
        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=uuid4(),
            verdict=_verdict(now, evidence),
        )
        conn.commit()
        with pytest.raises(Refusal, match=r"^VERDICT_ALREADY_RECORDED$"):
            record_verdict(
                conn,
                evidence=evidence,
                reviewer_id=uuid4(),
                verdict=_verdict(now, evidence),
            )
        declared = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conname=%s",
            (ONE_VERDICT_PER_EVIDENCE,),
        ).fetchall()
        conn.rollback()
        assert declared == [(ONE_VERDICT_PER_EVIDENCE,)]


def test_a_set_holding_a_case_that_accepted_nothing_is_still_signable(
    empty_database: str,
) -> None:
    """A deliberately restricted case must not make the whole set unsignable.

    `PerformedEvidence.complete` waives the COMPLETE requirement for a case
    whose declared refusal was met, and such a run can end BLOCKED at its first
    node having accepted no artifact at all. The model comparison read
    `call_outcomes` joined to `artifacts`, so that run contributed no row and
    "every run confirms the model" refused the snapshot `complete` had just
    called signable -- reporting a wrong binding when the bindings were right,
    and poisoning every other case in the set with it.

    The rule is now "no run contradicts, and at least one confirms". Every
    artifact-bearing run is still checked against the store's fact, so invariant
    3 is untouched, and a snapshot in which nothing at all was produced still
    refuses: it names no producer.

    Found by the Completion Phase 8 confidence review, which built the snapshot
    and reproduced the refusal.
    """
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = qualification_performed(blocked_label="restricted")
        evidence = performed.evidence
        assert performed.complete is True, "the snapshot a reviewer is offered"
        record_performed_earlier(conn, performed)
        record_runs(conn, performed, accepted_nothing="restricted")

        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=uuid4(),
            verdict=_verdict(now, evidence),
        )

        assert current_verdict(conn, evidence=evidence, now=now)


def _with(
    original: PerformedEvidence, *, status: RunStatus, blocked_met: bool | None = None
) -> PerformedEvidence:
    """The one-case snapshot with its run status and matrix row replaced."""
    [record] = original.performed.performed
    matrix = original.performed.matrix
    assert matrix is not None
    [only] = matrix.rows
    return performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            performed=(replace(record, status=status),),
            matrix=replace(matrix, rows=(replace(only, blocked_met=blocked_met),)),
        ),
    )


def test_a_declared_readiness_refusal_that_happened_is_signable() -> None:
    """§99: a case keyed `expects_blocked` declared that the run would end
    BLOCKED at CP-0's gate. Demanding COMPLETE of it too would make the key
    unanswerable -- the reason a met `expected_refusal` is waived."""
    assert _with(_performed(), status=RunStatus.BLOCKED, blocked_met=True).complete


def test_a_declared_readiness_refusal_that_did_not_happen_is_not_signable() -> None:
    """The gate cleared the module: the declared refusal was missed, whatever
    else the run did."""
    for status in (RunStatus.COMPLETE, RunStatus.BLOCKED):
        assert not _with(_performed(), status=status, blocked_met=False).complete


@pytest.mark.parametrize(
    "status", [RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.RUNNING]
)
def test_a_met_readiness_refusal_waives_only_a_blocked_run(status: RunStatus) -> None:
    """The waiver is for the run the key declared: one that ended BLOCKED. A run
    that failed, was cancelled or is still going is not that run."""
    assert not _with(_performed(), status=status, blocked_met=True).complete


def test_the_blocked_key_is_in_the_snapshot_only_when_declared() -> None:
    """§99 digest stability: a row with no `expects_blocked` serialises exactly
    as it did before the field existed, so every stored performed digest still
    verifies; a declared one travels with the snapshot a reviewer signs."""
    original = _performed()
    matrix = original.document["matrix"]
    assert isinstance(matrix, dict)
    [row] = matrix["rows"]
    assert set(row) == {
        "case_label",
        "proven",
        "refusal",
        "met",
        "missed",
        "forecast_met",
        "expected_refusal_met",
        "ready_met",
        "projections_met",
        "registers_met",
    }
    declared = _with(original, status=RunStatus.BLOCKED, blocked_met=True)
    declared_matrix = declared.document["matrix"]
    assert isinstance(declared_matrix, dict)
    assert declared_matrix["rows"][0]["blocked_met"] is True
    undeclared = _with(original, status=RunStatus.BLOCKED)
    assert declared.performed_sha256 != undeclared.performed_sha256


def test_a_refusal_met_beside_a_missed_key_is_not_complete(
    empty_database: str,
) -> None:
    """F64: keys declared beside an expected refusal are measured too."""
    original = _performed()
    matrix = original.performed.matrix
    assert matrix is not None
    [row] = matrix.rows
    both = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(
                matrix,
                rows=(
                    replace(
                        row,
                        expected_refusal_met=True,
                        missed=(ExpectedCitation("CP-0", "c" * 64, "quoted text"),),
                    ),
                ),
            ),
        ),
    )
    assert both.complete is False


def test_the_stored_complete_flag_is_re_derived_from_the_document(
    empty_database: str,
) -> None:
    """FP-03: `complete` was computed once and trusted from then on.

    The migrations block UPDATE and DELETE but not INSERT, so a snapshot
    recorded complete by older code -- or written straight in with
    self-consistent unkeyed digests -- stayed signable, stayed current and kept
    appearing in the release pack. Both readers now re-derive the rule from the
    document the reviewer signed.
    """
    import json as _json

    from caos.qualification.store import answered_document, document_complete

    original = _performed()
    assert document_complete(original.document) is True
    matrix = original.document["matrix"]
    assert isinstance(matrix, dict)
    assert answered_document(matrix["rows"][0]) is True

    unfinished = _with(original, status=RunStatus.FAILED)
    assert document_complete(unfinished.document) is False
    forged = unfinished.evidence
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.execute(
            "INSERT INTO qualification_performed"
            " (performed_sha256,qualification_set_sha256,build_id,adapter_version,"
            " provider,model,complete,performed_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                forged.performed_sha256,
                forged.qualification_set_sha256,
                forged.build_id,
                forged.adapter_version,
                forged.provider,
                forged.model,
                True,
                _json.dumps(unfinished.document, sort_keys=True, separators=(",", ":")),
            ),
        )
        assert conn.execute(
            "SELECT complete FROM qualification_performed"
        ).fetchone() == (True,)
        now = datetime.now(UTC)
        with pytest.raises(Refusal, match="VERDICT_BINDING_INVALID"):
            record_verdict(
                conn,
                evidence=forged,
                reviewer_id=uuid4(),
                verdict=_verdict(now, forged),
            )
        conn.rollback()


def test_a_verdict_binds_provider_and_model_as_a_pair(empty_database: str) -> None:
    """FP-13: `provider + ":" + model` is not injective, so a document naming
    `openrouter:x` and `m` satisfied evidence naming `openrouter` and `x:m`."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        record_performed_earlier(conn, performed)
        evidence = performed.evidence
        now = datetime.now(UTC)
        slid = read_verdict(
            {
                "provider": evidence.provider.rsplit("/", 1)[0]
                + "/"
                + evidence.provider.rsplit("/", 1)[1]
                + ":"
                + evidence.model,
                "qualification_set_sha256": evidence.qualification_set_sha256,
                "build_id": evidence.build_id,
                "decided_at": now.isoformat(),
                "expires_at": (now + timedelta(days=1)).isoformat(),
                "reviewer": "Reviewer",
            },
            now=now,
        )
        # The identity above is the right one, so it binds.
        assert slid.provider.value == evidence.provider + ":" + evidence.model
        moved = replace(
            evidence,
            provider=evidence.provider + ":" + evidence.model.split("/")[0],
            model=evidence.model.split("/", 1)[1],
        )
        with pytest.raises(Refusal, match="VERDICT_BINDING_INVALID"):
            record_verdict(conn, evidence=moved, reviewer_id=uuid4(), verdict=slid)
        conn.rollback()


def test_a_signature_may_not_stand_for_longer_than_the_cap() -> None:
    """FP-13: `expires_at` had only to be after `decided_at`, so a verdict could
    be written to be current for a century."""
    from caos.qualification.verdict import MAX_VALIDITY

    now = datetime.now(UTC)
    evidence = _evidence()
    document = {
        "provider": evidence.provider + ":" + evidence.model,
        "qualification_set_sha256": evidence.qualification_set_sha256,
        "build_id": evidence.build_id,
        "decided_at": now.isoformat(),
        "expires_at": (now + MAX_VALIDITY + timedelta(seconds=1)).isoformat(),
        "reviewer": "Reviewer",
    }
    with pytest.raises(Refusal, match="VERDICT_BINDING_INVALID"):
        read_verdict(document, now=now)
    document["expires_at"] = (now + MAX_VALIDITY).isoformat()
    assert read_verdict(document, now=now).expires_at == now + MAX_VALIDITY


@pytest.mark.parametrize("code", sorted(code.value for code in ROW_REFUSALS))
def test_a_row_a_reader_refused_is_not_answered_beside_a_met_refusal(
    code: str,
) -> None:
    """DQ-1, for a snapshot already stored: a row written before a refused
    reader answered `False` carries its declared key as `None`, which reads as
    "not declared". None of the reader codes is a refusal a case may declare,
    so a row carrying one is refused however its refusal key was met."""
    row = {
        "case_label": "case",
        "proven": False,
        "refusal": code,
        "met": [],
        "missed": [],
        "forecast_met": None,
        "expected_refusal_met": True,
        "ready_met": None,
        "projections_met": None,
        "registers_met": None,
    }
    assert answered_document(row) is False
    assert answered_document({**row, "refusal": None}) is True
    matrix_row = MatrixRow(
        case_label="case",
        proven=False,
        refusal=RefusalCode(code),
        met=(),
        missed=(),
        forecast_met=None,
        expected_refusal_met=True,
    )
    assert _answered(matrix_row) is False
    assert _answered(replace(matrix_row, refusal=None)) is True


def test_a_verdict_over_runs_the_store_does_not_hold_is_refused(
    empty_database: str,
) -> None:
    """DQ-3 (FP-03's forged-row half): every reader re-derived the snapshot
    from the snapshot. A self-consistent snapshot, evidence and verdict inserted
    straight into the tables over a run the store holds RUNNING with no
    artifact was current and relayed QUALIFIED. The runs' status and the
    artifacts the proof counted are the store's facts, and both are compared."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    performed = _performed()
    evidence = performed.evidence
    [case] = performed.prepared
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed_earlier(conn, performed)
        record_runs(conn, performed)
        verdict = _verdict(now, evidence)
        record_verdict(conn, evidence=evidence, reviewer_id=uuid4(), verdict=verdict)
        conn.commit()
        assert_store_agrees(conn, document=performed.document, model=evidence.model)
        assert current_verdict(conn, evidence=evidence, now=now)
        # CF-091: runs.status is guarded against a terminal move now; this
        # forges exactly that move to prove the app's own read still catches
        # it, so the trigger -- not what this test is about -- is set aside.
        assert conn.info.dbname.startswith("caos_test_")
        conn.execute("ALTER TABLE runs DISABLE TRIGGER runs_status_terminal_once")
        conn.execute(
            "UPDATE runs SET status='RUNNING' WHERE run_id=%s", (case.input.run_id,)
        )
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            current_verdict(conn, evidence=evidence, now=now)
        conn.rollback()
        # One more accepted artifact than the proof in the snapshot counted.
        attempt = uuid4()
        conn.execute(
            "INSERT INTO run_attempts (attempt_id,run_id,route_node_id)"
            " VALUES (%s,%s,'CP-L10')",
            (attempt, case.input.run_id),
        )
        conn.execute(
            "INSERT INTO artifacts (attempt_id,run_id,case_id,artifact_sha256,"
            "route_node_id,model,generation_id) VALUES (%s,%s,%s,%s,'CP-L10',%s,%s)",
            (
                attempt,
                case.input.run_id,
                case.input.case_id,
                "2" * 64,
                evidence.model,
                "gen-2",
            ),
        )
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            assert_store_agrees(conn, document=performed.document, model=evidence.model)
        conn.rollback()


def test_a_verdict_decided_before_its_snapshot_was_recorded_is_refused(
    empty_database: str,
) -> None:
    """DQ-13 (FP-13's backdating half): `decided_at` had only to be at or
    before now, so a decision dated 300 days before the snapshot it signs was
    accepted, current and relayed with that date; and no row kept when a
    verdict was written. Both readers refuse the first, and `recorded_at`
    keeps the second."""
    performed = _performed()
    evidence = performed.evidence
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed(conn, performed)
        record_runs(conn, performed)
        conn.commit()
        row = conn.execute("SELECT recorded_at FROM qualification_performed").fetchone()
        assert row is not None
        [recorded] = row
        early = recorded - timedelta(days=300)
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            record_verdict(
                conn,
                evidence=evidence,
                reviewer_id=uuid4(),
                verdict=_verdict(early, evidence),
            )
        conn.rollback()
        # A row written before the rule, by any path, is not current either.
        record_evidence(conn, evidence)
        conn.execute(
            "INSERT INTO qualification_verdicts"
            " (evidence_sha256,reviewer_id,reviewer,decided_at,expires_at)"
            " VALUES (%s,%s,'Reviewer',%s,%s)",
            (evidence.sha256, uuid4(), early, early + timedelta(days=366)),
        )
        with pytest.raises(Refusal, match=r"^VERDICT_BINDING_INVALID$"):
            current_verdict(conn, evidence=evidence, now=recorded)
        conn.rollback()

        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=uuid4(),
            verdict=_verdict(recorded, evidence),
        )
        assert current_verdict(conn, evidence=evidence, now=recorded)
        kept = conn.execute(
            "SELECT recorded_at >= %s FROM qualification_verdicts", (recorded,)
        ).fetchone()
        conn.rollback()
        assert kept == (True,)
