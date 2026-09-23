"""Append-only persisted qualification evidence and authenticated verdicts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

import psycopg

from caos.qualification.harness import Performed, PerformedSet, PreparedCase
from caos.qualification.matrix import MatrixRow
from caos.qualification.verdict import Verdict, read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, rollback_or_close

# `0019_one_qualification_verdict.sql`. Named here so the refusal that maps
# it and the migration that declares it cannot drift apart silently.
ONE_VERDICT_PER_EVIDENCE = "one_verdict_per_evidence"


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
        return row.expected_refusal_met and not row.missed
    return row.proven and not row.missed


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
        for record in self.performed.performed:
            row = rows.get(record.case_label)
            if row is None:
                return False
            # A case that declared its refusal declared that the run would not
            # finish. Demanding COMPLETE of it as well made the key
            # unanswerable by any run this system produces, which is what
            # `docs/REPAIR_PLAN.md` Phase 6 asks for in a deliberately
            # restricted case.
            if row.expected_refusal_met:
                continue
            # A case keyed `expects_blocked` declared that CP-0 would refuse a
            # consumer, which ends the run BLOCKED (§99). Waived for that run
            # only: one that failed or was cancelled is not the run declared.
            if row.blocked_met and record.status is RunStatus.BLOCKED:
                continue
            if record.status is not RunStatus.COMPLETE:
                return False
        return all(_answered(row) for row in matrix.rows)

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
    """Persist one immutable performed snapshot before its evidence is recorded."""
    evidence = performed.evidence
    document = performed.document
    digest = evidence.performed_sha256
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
            performed.complete,
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
        performed.complete,
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
        (digest, *asdict(evidence).values()),
    )
    row = conn.execute(
        "SELECT qualification_set_sha256,performed_sha256,build_id,adapter_version,"
        " provider,model FROM qualification_evidence WHERE evidence_sha256=%s",
        (digest,),
    ).fetchone()
    if row != tuple(asdict(evidence).values()):
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
    evidence = Evidence(*row)
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


def _snapshot_runs(document: object) -> tuple[UUID, ...]:
    """The run ids the stored snapshot names, or a refused binding.

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
    runs: list[UUID] = []
    for record in records:
        if not isinstance(record, dict) or "run_id" not in record:
            raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
        try:
            runs.append(UUID(str(record["run_id"])))
        except ValueError:
            raise Refusal(RefusalCode.VERDICT_BINDING_INVALID) from None
    return tuple(runs)


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


def record_verdict(
    conn: StoreConnection,
    *,
    evidence: Evidence,
    reviewer_id: UUID,
    verdict: Verdict,
) -> None:
    """Store one reviewer decision over already-persisted exact evidence."""
    if (
        verdict.qualification_set_sha256 != evidence.qualification_set_sha256
        or (verdict.provider.value != evidence.provider + ":" + evidence.model)
        or verdict.build_id != evidence.build_id
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    snapshot = conn.execute(
        "SELECT complete,performed_json FROM qualification_performed"
        " WHERE performed_sha256=%s",
        (evidence.performed_sha256,),
    ).fetchone()
    if snapshot is None or snapshot[0] is not True:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    _models_recorded(conn, runs=_snapshot_runs(snapshot[1]), model=evidence.model)
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
        if violation.diag.constraint_name == ONE_VERDICT_PER_EVIDENCE:
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
        " e.build_id,e.provider,e.model FROM qualification_verdicts q"
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
    reviewer, decided_at, expires_at, set_digest, build_id, provider, model = row
    if (set_digest, build_id, provider, model) != (
        evidence.qualification_set_sha256,
        evidence.build_id,
        evidence.provider,
        evidence.model,
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return read_verdict(
        {
            "provider": provider + ":" + model,
            "qualification_set_sha256": set_digest,
            "build_id": build_id,
            "decided_at": decided_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reviewer": reviewer,
        },
        now=now,
    )
