"""The authenticated, exact-evidence qualification read.

Qualification spans a set of cases, so it deliberately is not attached to a
case section or case-scoped standing.  The browser must name the immutable
evidence digest it wants to display; this route never chooses a nearby verdict.
"""

from __future__ import annotations

from re import fullmatch

from fastapi import APIRouter

from caos.api.deps import IDENTITY_FIRST, Caller, Store
from caos.api.identity import GlobalRole
from caos.api.wire import QualificationRead, QualificationState
from caos.qualification.store import Evidence, current_verdict, evidence_at
from caos.qualification.verdict import Verdict
from caos.refusals import Refusal, RefusalCode

# Database time and exact evidence lookup, then the current-verdict lookup.
IO_BUDGET = 3
router = APIRouter()


@router.get(
    "/api/v1/qualification/{evidence_sha256}",
    response_model=QualificationRead,
    dependencies=[IDENTITY_FIRST],
)
def read_qualification(
    actor: Caller, evidence_sha256: str, conn: Store
) -> QualificationRead:
    """Return a state for one frozen evidence digest and nothing broader."""
    _digest(evidence_sha256)
    if actor.role is GlobalRole.READER:
        return _read(evidence_sha256, QualificationState.RESTRICTED)
    row = conn.execute("SELECT now()").fetchone()
    if row is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    [now] = row
    evidence = evidence_at(conn, evidence_sha256=evidence_sha256)
    if evidence is None:
        return _read(evidence_sha256, QualificationState.UNQUALIFIED)
    try:
        verdict = current_verdict(conn, evidence=evidence, now=now)
    except Refusal as refusal:
        if refusal.code not in {
            RefusalCode.VERDICT_INCOMPLETE,
            RefusalCode.VERDICT_EXPIRED,
        }:
            if refusal.code is RefusalCode.VERDICT_BINDING_INVALID:
                return _read(evidence_sha256, QualificationState.UNAVAILABLE)
            raise
        return _read(evidence_sha256, QualificationState.UNQUALIFIED, evidence)
    return _read(evidence_sha256, QualificationState.QUALIFIED, evidence, verdict)


def _digest(value: str) -> None:
    if fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)


def _read(
    evidence_sha256: str,
    state: QualificationState,
    evidence: Evidence | None = None,
    verdict: Verdict | None = None,
) -> QualificationRead:
    """Keep restricted and absent identities metadata-free."""
    if evidence is None or verdict is None:
        return QualificationRead(
            evidence_sha256=evidence_sha256,
            state=state,
            qualification_set_sha256=None,
            performed_sha256=None,
            build_id=None,
            adapter_version=None,
            provider=None,
            model=None,
            reviewer=None,
            decided_at=None,
            expires_at=None,
        )
    # `current_verdict` is the single validator that keeps this object current.
    return QualificationRead(
        evidence_sha256=evidence_sha256,
        state=state,
        qualification_set_sha256=evidence.qualification_set_sha256,
        performed_sha256=evidence.performed_sha256,
        build_id=evidence.build_id,
        adapter_version=evidence.adapter_version,
        provider=evidence.provider,
        model=evidence.model,
        reviewer=verdict.reviewer.value,
        decided_at=verdict.decided_at,
        expires_at=verdict.expires_at,
    )
