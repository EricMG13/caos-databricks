"""Append-only persisted qualification evidence and authenticated verdicts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import psycopg

from caos.qualification.harness import Performed, PerformedSet, PreparedCase
from caos.qualification.matrix import REFUSED_ENDINGS, ROW_REFUSALS, MatrixRow
from caos.qualification.verdict import Verdict, read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, rollback_or_close

# The same two sets as a stored document spells them.
_UNMEASURED_CODES = frozenset(code.value for code in ROW_REFUSALS)
_REFUSED_ENDINGS = frozenset(status.value for status in REFUSED_ENDINGS)

# `0019_one_qualification_verdict.sql`. Named here so the refusal that maps
# it and the migration that declares it cannot drift apart silently.
ONE_VERDICT_PER_EVIDENCE = "one_verdict_per_evidence"
# `0018_qualification_verdicts.sql`'s primary key, `(evidence_sha256,
# reviewer_id)`. A twin of an identical in-flight request collides here first,
# and mapping it to a wrong binding answered one of two concurrent identical
# signatures with HTTP 400 (AR-10). Both constraints say the same thing: this
# evidence already carries a verdict.
ONE_VERDICT_PER_REVIEWER = "qualification_verdicts_pkey"
ALREADY_SIGNED = frozenset({ONE_VERDICT_PER_EVIDENCE, ONE_VERDICT_PER_REVIEWER})


@dataclass(frozen=True, slots=True)
class Evidence:
    qualification_set_sha256: str
    performed_sha256: str
    build_id: str
    adapter_version: str
    provider: str
    model: str

    @property
    def sha256(self) -> str:
        return sha256(
            json.dumps(
                asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()


def _answered(row: MatrixRow) -> bool:
    """Whether this row is a result a reviewer could sign QUALIFIED over.

    Every key the case declared has to be answered, and a case may declare
    seven kinds: expected citations, an expected refusal, an expected forecast,
    expected readiness, an expected readiness refusal (§99), expected
    projections and expected register cells. Each
    of the bool-or-None fields is `None` when its kind was not declared and a
    bool when it was, so `is not False` is the test -- a case keyed only by a
    forecast (which `assert_measurable` allows) was otherwise signable with
    that forecast unmet, because nothing here read the field.

    `registers_met` joined that list the day register keys existed, and for the
    same reason: `assert_measurable` counts a register key as a declared
    comparison, so a case keyed only by one would otherwise have been signable
    with the cell wrong. A key the reviewer cannot see missed is a key that
    measures nothing.

    Beside a met refusal `proven` is not read -- a run that stopped at its first
    node proves nothing and says so -- but a row carrying a *reader's* refusal
    is still refused: those codes are the host failing to measure a key, never
    the refusal a case declared, and a snapshot recorded before a refused
    reader answered `False` carries its declared key as `None` (DQ-1).
    """
    if (
        row.forecast_met is False
        or row.ready_met is False
        or row.blocked_met is False
        or row.projections_met is False
        or row.registers_met is False
    ):
        return False
    if row.expected_refusal_met is not None:
        # A conjunct, not a short circuit (F64): keys declared beside an
        # expected refusal are measured too.
        return (
            row.expected_refusal_met
            and not row.missed
            and row.refusal not in ROW_REFUSALS
        )
    return row.proven and not row.missed


def answered_document(row: object) -> bool:
    """`_answered`'s rule, read from a stored row rather than a `MatrixRow`."""
    if not isinstance(row, dict):
        return False
    if any(
        row.get(key) is False
        for key in (
            "forecast_met",
            "ready_met",
            "blocked_met",
            "projections_met",
            "registers_met",
        )
    ):
        return False
    missed = row.get("missed")
    if not isinstance(missed, list):
        return False
    if row.get("expected_refusal_met") is not None:
        return (
            row["expected_refusal_met"] is True
            and not missed
            and row.get("refusal") not in _UNMEASURED_CODES
        )
    return row.get("proven") is True and not missed


def document_complete(document: object) -> bool:
    """Whether a stored snapshot is one a reviewer could still sign QUALIFIED.

    `PerformedEvidence.complete` is computed once, by whatever code recorded the
    row, and trusted from then on -- by `record_verdict`, by `current_verdict`
    and by the release pack. So a snapshot recorded complete under a rule since
    corrected (F64 made `_answered` a conjunct) stayed signable, stayed current
    and kept appearing in the pack (FP-03). This re-derives the same rule from
    the document the reviewer signed, so the stored flag is a claim every reader
    checks rather than a fact every reader inherits.

    The same rule as `complete`, over the same fields `_row_document` and
    `_performed_document` write. A document this cannot read is not complete:
    a snapshot nobody can re-derive is not one anybody may sign.
    """
    if not isinstance(document, dict):
        return False
    matrix = document.get("matrix")
    records = document.get("performed")
    if not isinstance(matrix, dict) or not isinstance(records, list) or not records:
        return False
    rows = matrix.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    by_label = {row.get("case_label"): row for row in rows if isinstance(row, dict)}
    return all(_record_finished(record, by_label) for record in records) and all(
        answered_document(row) for row in rows
    )


def _record_finished(record: object, rows: Mapping[object, object]) -> bool:
    """Whether one stored record ended the way its own row allows.

    `complete`'s two waivers, over the document: a case that declared its
    refusal declared the run would not finish, and a case keyed `expects_blocked`
    declared CP-0 would refuse a consumer, which ends the run BLOCKED (§99).
    Anything else has to have reached COMPLETE.

    The first waiver holds only over a run that ended refused. A row claiming a
    met refusal over a COMPLETE run is the shape pre-FP-01 code recorded for a
    run that finished after a stale attempt refusal, and it waived the record's
    status wholesale: re-deriving from the snapshot re-read the old code's
    flag (DQ-3).
    """
    if not isinstance(record, dict):
        return False
    row = rows.get(record.get("case_label"))
    if not isinstance(row, dict):
        return False
    if row.get("expected_refusal_met") is True:
        return record.get("status") in _REFUSED_ENDINGS
    if row.get("blocked_met") is True and record.get("status") == "BLOCKED":
        return True
    return record.get("status") == RunStatus.COMPLETE.value


def _finished(record: Performed, row: MatrixRow | None) -> bool:
    """`_record_finished`'s rule over a `Performed` and its `MatrixRow`."""
    if row is None:
        return False
    # A case that declared its refusal declared that the run would not finish.
    # Demanding COMPLETE of it as well made the key unanswerable by any run this
    # system produces, which is what `docs/REPAIR_PLAN.md` Phase 6 asks for in
    # a deliberately restricted case. Over a run that ended refused, and no
    # other (DQ-3).
    if row.expected_refusal_met:
        return record.status in REFUSED_ENDINGS
    # A case keyed `expects_blocked` declared that CP-0 would refuse a consumer,
    # which ends the run BLOCKED (§99). Waived for that run only: one that
    # failed or was cancelled is not the run declared.
    if row.blocked_met and record.status is RunStatus.BLOCKED:
        return True
    return record.status is RunStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class PerformedEvidence:
    """The immutable host snapshot a reviewer may sign, never a detached hash."""

    prepared: tuple[PreparedCase, ...]
    performed: PerformedSet

    @property
    def document(self) -> dict[str, object]:
        return {
            "prepared": [_prepared_document(item) for item in self.prepared],
            "performed": [
                _performed_document(item) for item in self.performed.performed
            ],
            "matrix": _matrix_document(self.performed),
        }

    @property
    def performed_sha256(self) -> str:
        return _digest(self.document)

    @property
    def complete(self) -> bool:
        """A matrix over runs that finished and answered their keys.

        A matrix alone is not enough. `Assurance` has one reviewer-written
        member, `QUALIFIED`, so a snapshot worth signing is one that could
        carry that word: every run reached `COMPLETE`, and every row either
        met the refusal its case declared or proved every expected citation.
        A run that validly returns a blocked readiness handoff stops with
        nothing in `stopped` and still builds a matrix — rows unproven, every
        key missed — which is the shape both live runs so far have taken, and
        exactly what must not be signable.
        """
        matrix = self.performed.matrix
        if matrix is None:
            return False
        rows = {row.case_label: row for row in matrix.rows}
        return all(
            _finished(record, rows.get(record.case_label))
            for record in self.performed.performed
        ) and all(_answered(row) for row in matrix.rows)

    @property
    def evidence(self) -> Evidence:
        set_sha256, build_id, adapter_version, provider, model = _identity(
            self.prepared, self.performed
        )
        return Evidence(
            set_sha256,
            self.performed_sha256,
            build_id,
            adapter_version,
            provider,
            model,
        )


def performed_evidence(
    *, prepared: tuple[PreparedCase, ...], performed: PerformedSet
) -> PerformedEvidence:
    """Bind a returned performed set to the exact pins that produced it."""
    _identity(prepared, performed)
    return PerformedEvidence(prepared, performed)


def record_performed(conn: StoreConnection, performed: PerformedEvidence) -> str:
    """Persist one immutable performed snapshot before its evidence is recorded.

    FP-24: `PerformedEvidence.complete` is a pure property -- it cannot read
    `call_outcomes` -- so it does not know whether each run's recorded
    producer agrees with the prepared model. That comparison used to run only
    at signing (`_models_recorded`, via `assert_store_agrees`); the same rule
    now also gates the `complete` flag persisted here, so a case whose
    producer never matches does not count complete before any reviewer ever
    sees it.
    """
    evidence = performed.evidence
    document = performed.document
    digest = evidence.performed_sha256
    complete = performed.complete and _models_confirmed(
        conn,
        runs=tuple(record.run_id for record in performed.performed.performed),
        model=evidence.model,
    )
    conn.execute(
        "INSERT INTO qualification_performed"
        " (performed_sha256,qualification_set_sha256,build_id,adapter_version,"
        " provider,model,complete,performed_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (performed_sha256) DO NOTHING",
        (
            digest,
            evidence.qualification_set_sha256,
            evidence.build_id,
            evidence.adapter_version,
            evidence.provider,
            evidence.model,
            complete,
            json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
        ),
    )
    row = conn.execute(
        "SELECT qualification_set_sha256,build_id,adapter_version,provider,model,"
        " complete,performed_json FROM qualification_performed"
        " WHERE performed_sha256=%s",
        (digest,),
    ).fetchone()
    if row != (
        evidence.qualification_set_sha256,
        evidence.build_id,
        evidence.adapter_version,
        evidence.provider,
        evidence.model,
        complete,
        document,
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return digest


def record_evidence(conn: StoreConnection, evidence: Evidence) -> str:
    """Persist exactly one identity row; a conflicting replay refuses."""
    performed = conn.execute(
        "SELECT qualification_set_sha256,build_id,adapter_version,provider,model"
        " FROM qualification_performed WHERE performed_sha256=%s",
        (evidence.performed_sha256,),
    ).fetchone()
    if performed != (
        evidence.qualification_set_sha256,
        evidence.build_id,
        evidence.adapter_version,
        evidence.provider,
        evidence.model,
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    digest = evidence.sha256
    conn.execute(
        "INSERT INTO qualification_evidence"
        " (evidence_sha256,qualification_set_sha256,performed_sha256,build_id,"
        " adapter_version,provider,model) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (evidence_sha256) DO NOTHING",
        (
            digest,
            evidence.qualification_set_sha256,
            evidence.performed_sha256,
            evidence.build_id,
            evidence.adapter_version,
            evidence.provider,
            evidence.model,
        ),
    )
    row = conn.execute(
        "SELECT qualification_set_sha256,performed_sha256,build_id,adapter_version,"
        " provider,model FROM qualification_evidence WHERE evidence_sha256=%s",
        (digest,),
    ).fetchone()
    if row != (
        evidence.qualification_set_sha256,
        evidence.performed_sha256,
        evidence.build_id,
        evidence.adapter_version,
        evidence.provider,
        evidence.model,
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return digest


def evidence_at(conn: StoreConnection, *, evidence_sha256: str) -> Evidence | None:
    """Return the exact stored evidence identity, never a similar candidate."""
    row = conn.execute(
        "SELECT e.qualification_set_sha256,e.performed_sha256,e.build_id,"
        " e.adapter_version,e.provider,e.model FROM qualification_evidence e"
        " JOIN qualification_performed p ON p.performed_sha256=e.performed_sha256"
        " AND (p.qualification_set_sha256,p.build_id,p.adapter_version,"
        " p.provider,p.model)=(e.qualification_set_sha256,e.build_id,"
        " e.adapter_version,e.provider,e.model)"
        " WHERE e.evidence_sha256=%s",
        (evidence_sha256,),
    ).fetchone()
    if row is None:
        return None
    set_digest, performed_digest, build_id, adapter_version, provider, model = row
    evidence = Evidence(
        qualification_set_sha256=set_digest,
        performed_sha256=performed_digest,
        build_id=build_id,
        adapter_version=adapter_version,
        provider=provider,
        model=model,
    )
    if evidence.sha256 != evidence_sha256:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return evidence


def _identity(
    prepared: tuple[PreparedCase, ...], performed: PerformedSet
) -> tuple[str, str, str, str, str]:
    """The single identity used by both the snapshot and its evidence row."""
    if (
        type(prepared) is not tuple
        or not prepared
        or type(performed) is not PerformedSet
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    first = prepared[0]
    if any(type(item) is not PreparedCase for item in prepared):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    identity = (
        first.qualification_set_sha256,
        first.input.build_id,
        first.input.adapter_version,
        first.provider,
        first.model,
    )
    if any(
        (
            item.qualification_set_sha256,
            item.input.build_id,
            item.input.adapter_version,
            item.provider,
            item.model,
        )
        != identity
        for item in prepared
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    records = performed.performed
    if len(records) > len(prepared) or any(
        (record.case_label, record.run_id) != (item.case_label, item.input.run_id)
        for record, item in zip(records, prepared, strict=False)
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    matrix = performed.matrix
    if matrix is not None and (
        len(records) != len(prepared)
        or any(record.stopped is not None for record in records)
        or matrix.qualification_set_sha256 != identity[0]
        or matrix.build_id != identity[1]
        or [row.case_label for row in matrix.rows]
        != [item.case_label for item in prepared]
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return identity


def _prepared_document(item: PreparedCase) -> dict[str, object]:
    pin = item.input
    return {
        "case_label": item.case_label,
        "run_id": str(pin.run_id),
        "case_id": str(pin.case_id),
        "source_version": pin.source_version,
        "source_fingerprint": pin.source_fingerprint,
        "route_digest": pin.route_digest,
        "build_id": pin.build_id,
        "manifest_sha256": pin.manifest_sha256,
        "adapter_version": pin.adapter_version,
        "input_fingerprint": pin.input_fingerprint,
        "subject": None
        if pin.subject is None
        else {
            "issuer_id": pin.subject.issuer_id,
            "issuer_name": pin.subject.issuer_name,
            "reporting_period": pin.subject.reporting_period,
            "analysis_date": pin.subject.analysis_date,
        },
        "cos_run_id": pin.cos_run_id,
    }


def _performed_document(item: Performed) -> dict[str, object]:
    proof = item.proof
    return {
        "case_label": item.case_label,
        "run_id": str(item.run_id),
        "status": item.status.value,
        "stopped": None if item.stopped is None else item.stopped.value,
        "proof": None
        if proof is None
        else {
            "run_id": str(proof.run_id),
            "route_digest": proof.route_digest,
            "build_id": proof.build_id,
            "artifacts": proof.artifacts,
            "citations": proof.citations,
            "anchored": [list(value) for value in sorted(proof.anchored)],
        },
        "refusal": None if item.refusal is None else item.refusal.value,
        "unrun": [
            {
                "route_node_id": unrun.route_node_id,
                "state": unrun.state.value,
                "attempts": [
                    {
                        "attempt_id": str(attempt.attempt_id),
                        "reserved": attempt.reserved,
                        "outcome": attempt.outcome,
                        "charged": attempt.charged,
                        "model": attempt.model,
                        "generation_id": attempt.generation_id,
                    }
                    for attempt in unrun.attempts
                ],
            }
            for unrun in item.unrun
        ],
    }


def _matrix_document(performed: PerformedSet) -> dict[str, object] | None:
    matrix = performed.matrix
    if matrix is None:
        return None
    return {
        "qualification_set_sha256": matrix.qualification_set_sha256,
        "build_id": matrix.build_id,
        "rows": [_row_document(row) for row in matrix.rows],
    }


def _row_document(row: MatrixRow) -> dict[str, object]:
    """One matrix row. `blocked_met` joins only when declared (§99), so every
    snapshot stored before it serialises -- and digests -- exactly as it did."""
    document: dict[str, object] = {
        "case_label": row.case_label,
        "proven": row.proven,
        "refusal": None if row.refusal is None else row.refusal.value,
        "met": [
            [
                citation.module_id,
                citation.document_sha256,
                citation.matched_text,
            ]
            for citation in row.met
        ],
        "missed": [
            [
                citation.module_id,
                citation.document_sha256,
                citation.matched_text,
            ]
            for citation in row.missed
        ],
        "forecast_met": row.forecast_met,
        "expected_refusal_met": row.expected_refusal_met,
        # The reading that decided answerability travels with it: a
        # reviewer re-deriving `complete` from this document has to be
        # able to see a readiness miss, or a snapshot refused because
        # CP-0 gated a module reads as the model citing nothing.
        "ready_met": row.ready_met,
        "projections_met": row.projections_met,
        "registers_met": row.registers_met,
    }
    if row.blocked_met is not None:
        document["blocked_met"] = row.blocked_met
    return document


def _digest(document: dict[str, object]) -> str:
    return sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _snapshot_records(document: object) -> tuple[tuple[UUID, dict[str, Any]], ...]:
    """Each performed record the stored snapshot names, with its run id read,
    or a refused binding.

    `qualification_performed.performed_json` is the only place an evidence row
    reaches its runs: no column joins `qualification_evidence` to `runs`, and
    the snapshot document is what the reviewer signed, so the run ids it names
    are the ones the comparison below is owed. A document this function cannot
    read is a snapshot nobody may sign, never an empty run set that passes.
    """
    if not isinstance(document, dict):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    records = document.get("performed")
    if not isinstance(records, list) or not records:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    runs: list[tuple[UUID, dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict) or "run_id" not in record:
            raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
        try:
            runs.append((UUID(str(record["run_id"])), record))
        except ValueError:
            raise Refusal(RefusalCode.VERDICT_BINDING_INVALID) from None
    return tuple(runs)


def _proven_artifacts(record: Mapping[str, Any]) -> int | None:
    """The artifact count the record's proof covered, or None with no proof."""
    proof = record.get("proof")
    if proof is None:
        return None
    if not isinstance(proof, dict) or type(proof.get("artifacts")) is not int:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return int(proof["artifacts"])


def assert_store_agrees(conn: StoreConnection, *, document: object, model: str) -> None:
    """Refuse unless the store still holds the runs the snapshot says it does.

    Everything else a reader re-derives comes from the snapshot itself -- its
    digest, its rows, its flags -- so a self-consistent snapshot, evidence row
    and verdict inserted straight into the tables over a run the store holds
    RUNNING with no artifact was signed, current, and relayed QUALIFIED by the
    release pack (DQ-3, FP-03's forged-row half). Each run's status and the
    count of artifacts its proof covered are the store's facts, compared here,
    and the models the runs called are `_models_recorded`'s. A keyed digest that
    only the host can mint is what would refuse a forger who can also write
    `runs` (`next.md`).
    """
    records = _snapshot_records(document)
    held = {
        UUID(str(run_id)): (str(status), int(artifacts))
        for run_id, status, artifacts in conn.execute(
            "SELECT r.run_id,r.status,"
            " (SELECT count(*) FROM artifacts a WHERE a.run_id=r.run_id)"
            " FROM runs r WHERE r.run_id = ANY(%s)",
            ([run_id for run_id, _record in records],),
        ).fetchall()
    }
    for run_id, record in records:
        status, artifacts = held.get(run_id, (None, None))
        proven = _proven_artifacts(record)
        if status != record.get("status") or (
            proven is not None and proven != artifacts
        ):
            raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    _models_recorded(conn, runs=tuple(run_id for run_id, _ in records), model=model)


def _models_recorded(
    conn: StoreConnection, *, runs: tuple[UUID, ...], model: str
) -> None:
    """Refuse unless no run contradicts the model the verdict names, and one
    confirms it.

    `evidence.model` is what the harness was configured with; what the runs
    called is `call_outcomes.model` beside each accepted artifact (§25), and
    invariant 3 says the host owns identity -- so a reviewer's `provider`
    binding is checked against the store's fact, not against the caller's
    configuration.

    It is "no run contradicts" rather than "every run confirms" because a
    signable snapshot may legitimately contain a run that accepted nothing.
    `PerformedEvidence.complete` waives the COMPLETE requirement for a case
    whose declared refusal was met, and a run whose first node returns a
    validated Blocked verdict ends BLOCKED with a billed attempt, a
    `call_outcomes` row and no artifact -- so the join below returns no row for
    it. Demanding every run appear refused exactly the case
    `docs/REPAIR_PLAN.md` Phase 6 asks for, the deliberately restricted one,
    and refused it as a *wrong binding* when the bindings were right. One
    unsignable case poisons the whole set. Found by the Completion Phase 8
    confidence review, which built the snapshot and reproduced it.

    Every artifact-bearing run is still checked against the store's fact, and
    an empty result still refuses: a snapshot in which nothing was ever
    produced names no producer, which is what this comparison exists to catch.
    """
    rows = conn.execute(
        "SELECT DISTINCT o.run_id,o.model FROM call_outcomes o"
        " JOIN artifacts a ON a.attempt_id=o.attempt_id"
        " WHERE o.run_id = ANY(%s)",
        (list(runs),),
    ).fetchall()
    if not rows or any(row[1] != model for row in rows):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)


def _models_confirmed(
    conn: StoreConnection, *, runs: tuple[UUID, ...], model: str
) -> bool:
    """`_models_recorded`'s rule, answered rather than raised (FP-24): whether
    every run's recorded producer agrees with the prepared model, reused so
    `record_performed` can hold the persisted `complete` flag to it too."""
    try:
        _models_recorded(conn, runs=runs, model=model)
    except Refusal:
        return False
    return True


def record_verdict(
    conn: StoreConnection,
    *,
    evidence: Evidence,
    reviewer_id: UUID,
    verdict: Verdict,
) -> None:
    """Store one reviewer decision over already-persisted exact evidence."""
    # Split once, from the left, and compare the pair: `provider + ":" + model`
    # is not injective, so `("openrouter:x", "m")` and `("openrouter", "x:m")`
    # produced one string and each satisfied the other's binding (FP-13).
    signed = verdict.provider.value.split(":", 1)
    if (
        verdict.qualification_set_sha256 != evidence.qualification_set_sha256
        or signed != [evidence.provider, evidence.model]
        or verdict.build_id != evidence.build_id
        # N44: the coarse four above can agree for two different snapshots of
        # the same set, build and provider -- `performed_sha256` and
        # `adapter_version` differ, so `evidence.sha256` does. The document
        # must name the one exact evidence identity it was read against.
        or verdict.evidence_sha256 != evidence.sha256
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    snapshot = conn.execute(
        "SELECT complete,performed_json,recorded_at FROM qualification_performed"
        " WHERE performed_sha256=%s",
        (evidence.performed_sha256,),
    ).fetchone()
    if snapshot is None or snapshot[0] is not True:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    # The stored flag is a claim, and the digest is the key: both are re-derived
    # from the document itself rather than inherited (FP-03). An inserted row
    # with self-consistent unkeyed digests still has to re-digest to its own key
    # and to re-derive as a signable snapshot.
    if _digest(snapshot[1]) != evidence.performed_sha256 or not document_complete(
        snapshot[1]
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    # A decision cannot predate what it decides on: a verdict dated 300 days
    # before its snapshot was recorded was accepted, current and relayed with
    # that date (FP-13, DQ-13).
    if verdict.decided_at < snapshot[2]:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    assert_store_agrees(conn, document=snapshot[1], model=evidence.model)
    digest = record_evidence(conn, evidence)
    try:
        conn.execute(
            "INSERT INTO qualification_verdicts"
            " (evidence_sha256,reviewer_id,reviewer,decided_at,expires_at)"
            " VALUES (%s,%s,%s,%s,%s)",
            (
                digest,
                reviewer_id,
                verdict.reviewer.value,
                verdict.decided_at,
                verdict.expires_at,
            ),
        )
    except psycopg.errors.UniqueViolation as violation:
        # `0019_one_qualification_verdict.sql`: this evidence is already signed,
        # which is a different thing from a wrong binding and says so. Matched
        # by constraint name, not by message text: a message is the server's
        # locale and version, and a second unique index on this table must not
        # inherit this code by accident.
        rollback_or_close(conn)
        if violation.diag.constraint_name in ALREADY_SIGNED:
            raise Refusal(RefusalCode.VERDICT_ALREADY_RECORDED) from None
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID) from None
    except psycopg.Error:
        # Any other driver fault is the store failing, not the document: a 400
        # here told a reviewer whose bindings were right to correct them.
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


def current_verdict(
    conn: StoreConnection,
    *,
    evidence: Evidence,
    now: datetime,
) -> Verdict:
    """Read only the current verdict bound to the exact requested evidence."""
    row = conn.execute(
        "SELECT q.reviewer,q.decided_at,q.expires_at,e.qualification_set_sha256,"
        " e.build_id,e.provider,e.model,p.performed_json,p.recorded_at"
        " FROM qualification_verdicts q"
        " JOIN qualification_evidence e USING (evidence_sha256)"
        " JOIN qualification_performed p ON p.performed_sha256=e.performed_sha256"
        " AND (p.qualification_set_sha256,p.build_id,p.adapter_version,"
        " p.provider,p.model)=(e.qualification_set_sha256,e.build_id,"
        " e.adapter_version,e.provider,e.model)"
        " WHERE q.evidence_sha256=%s AND p.complete",
        (evidence.sha256,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.VERDICT_INCOMPLETE)
    reviewer, decided_at, expires_at, set_digest, build_id, provider, model = row[:7]
    held, performed_at = row[7:]
    # The snapshot re-digests to the key it is stored under, and re-derives as
    # one a reviewer could sign (FP-03). A document that does not re-digest is a
    # row nobody wrote through `record_performed`, which is a wrong binding; one
    # that re-digests and no longer re-derives is a snapshot recorded under a
    # rule since corrected, which is exactly an incomplete one.
    if _digest(held) != evidence.performed_sha256:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    if not document_complete(held):
        raise Refusal(RefusalCode.VERDICT_INCOMPLETE)
    if (set_digest, build_id, provider, model) != (
        evidence.qualification_set_sha256,
        evidence.build_id,
        evidence.provider,
        evidence.model,
    ) or decided_at < performed_at:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    # Every reader of a verdict re-checks the store's facts, not only the
    # signer (DQ-3): a row inserted without `record_verdict` meets them here.
    assert_store_agrees(conn, document=held, model=model)
    return read_verdict(
        {
            "provider": provider + ":" + model,
            "qualification_set_sha256": set_digest,
            "build_id": build_id,
            "decided_at": decided_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reviewer": reviewer,
            "evidence_sha256": evidence.sha256,
        },
        now=now,
    )


def verdict_reviewer_id(conn: StoreConnection, *, evidence_sha256: str) -> UUID | None:
    """The authenticated actor who recorded the verdict over this evidence, or
    None when none is stored (CF-027).

    Read beside `current_verdict` rather than folded into it: `Verdict` is
    exactly the six bindings a reviewer signed (`caos/qualification/verdict.py`),
    and the signer's own identity is store provenance the document never
    carried, the way `record_verdict` records it and `scripts/release_pack.py`
    already reads it. `evidence_sha256` is unique here
    (`0019_one_qualification_verdict.sql`), so there is at most one row to find.
    """
    row = conn.execute(
        "SELECT reviewer_id FROM qualification_verdicts WHERE evidence_sha256=%s",
        (evidence_sha256,),
    ).fetchone()
    return None if row is None else row[0]
