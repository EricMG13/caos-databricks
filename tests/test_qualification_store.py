from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from qualification_fixtures import qualification_performed, record_runs

import caos.store as store
from caos.qualification.matrix import ExpectedCitation
from caos.qualification.store import (
    ONE_VERDICT_PER_EVIDENCE,
    Evidence,
    PerformedEvidence,
    current_verdict,
    evidence_at,
    performed_evidence,
    record_evidence,
    record_performed,
    record_verdict,
)
from caos.qualification.verdict import Verdict, read_verdict
from caos.refusals import Refusal
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
        record_performed(conn, performed)
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
        record_performed(conn, incomplete)
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
        record_performed(conn, blocked)
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
    refused = performed_evidence(
        prepared=original.prepared,
        performed=replace(
            original.performed,
            matrix=replace(
                matrix,
                rows=(replace(row, proven=False, expected_refusal_met=True),),
            ),
        ),
    )

    assert refused.complete is True


def test_record_verdict_binds_the_reviewer_and_evidence(empty_database: str) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _performed()
        evidence = performed.evidence
        record_performed(conn, performed)
        record_runs(conn, performed)
        reviewer = uuid4()
        record_verdict(
            conn,
            evidence=evidence,
            reviewer_id=reviewer,
            verdict=_verdict(now, evidence),
        )
        assert current_verdict(conn, evidence=evidence, now=now)


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
        record_performed(conn, performed)
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
        record_performed(conn, performed)
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
        record_performed(conn, performed)
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
