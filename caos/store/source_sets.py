"""Immutable source snapshots; historical membership is not read authority."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from caos.boundary_text import BoundaryText
from caos.digest import canonical_digest
from caos.evidence.extract import ExtractorIdentity
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, committed_unit
from caos.store.cases import lock_case


@dataclass(frozen=True, slots=True)
class SourceSetMember:
    source_id: UUID
    document_sha256: str
    filename: str
    admitted_at: str
    extractor_identity: str
    output_sha256: str
    extraction_sha256: str


@dataclass(frozen=True, slots=True)
class SourceSet:
    case_id: UUID
    version: int
    fingerprint: str
    members: tuple[SourceSetMember, ...]


def _valid_member(member: SourceSetMember) -> bool:
    identity = json.loads(member.extractor_identity)
    timestamp = datetime.fromisoformat(member.admitted_at)
    return (
        ExtractorIdentity(**identity).canonical() == member.extractor_identity
        and BoundaryText.of(member.filename).value == member.filename
        and timestamp.tzinfo is not None
        and timestamp.astimezone(UTC).isoformat() == member.admitted_at
        and all(
            re.fullmatch("[0-9a-f]{64}", digest)
            for digest in (
                member.document_sha256,
                member.output_sha256,
                member.extraction_sha256,
            )
        )
        and canonical_digest(
            {
                "format_version": 1,
                "document_sha256": member.document_sha256,
                "extractor_identity": identity,
                "output_sha256": member.output_sha256,
            }
        )
        == member.extraction_sha256
    )


def _fingerprint(case_id: UUID, members: tuple[SourceSetMember, ...]) -> str:
    """Validate stored provenance before using it as snapshot authority."""
    try:
        valid = all(_valid_member(member) for member in members)
        digest = canonical_digest(
            {
                "format_version": 1,
                "case_id": str(case_id),
                "members": [
                    {**asdict(member), "source_id": str(member.source_id)}
                    for member in sorted(members, key=lambda m: m.source_id)
                ],
            }
        )
    except (Refusal, TypeError, ValueError, AttributeError, OverflowError):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None
    if not valid or not members or len({m.source_id for m in members}) != len(members):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return digest


def load_source_set(
    conn: StoreConnection, case_id: UUID, version: int
) -> SourceSet | None:
    """Load exactly one case/version; caller owns the read transaction."""
    header = conn.execute(
        "SELECT fingerprint, member_count FROM source_set_versions"
        " WHERE case_id = %s AND version = %s",
        (case_id, version),
    ).fetchone()
    if header is None:
        return None
    members = tuple(
        SourceSetMember(*row)
        for row in conn.execute(
            "SELECT source_id, document_sha256, filename, admitted_at,"
            " extractor_identity, output_sha256, extraction_sha256"
            " FROM source_set_members"
            " WHERE case_id = %s AND version = %s ORDER BY source_id",
            (case_id, version),
        ).fetchall()
    )
    if len(members) != header[1] or _fingerprint(case_id, members) != header[0]:
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return SourceSet(case_id, version, header[0], members)


def snapshot_source_set(conn: StoreConnection, case_id: UUID) -> SourceSet:
    """Own and finish the transaction, including replay; commit setup first."""
    try:
        with committed_unit(conn):
            result = snapshot_in(conn, case_id)
    except OverflowError:
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None
    return result


def snapshot_in(conn: StoreConnection, case_id: UUID) -> SourceSet:
    """`snapshot_source_set`'s write in the caller's transaction; never commits."""
    lock_case(conn, case_id)
    rows = conn.execute(
        "SELECT s.source_id, s.document_sha256, s.filename, s.admitted_at,"
        " e.extractor_identity, e.output_sha256, e.extraction_sha256"
        " FROM live_sources s LEFT JOIN source_extractions e USING (source_id)"
        " WHERE s.case_id = %s ORDER BY s.source_id",
        (case_id,),
    ).fetchall()
    if not rows:
        raise Refusal(RefusalCode.SOURCE_PACK_EMPTY)
    members = tuple(
        SourceSetMember(
            row[0],
            row[1],
            row[2],
            row[3].astimezone(UTC).isoformat(),
            row[4],
            row[5],
            row[6],
        )
        for row in rows
    )
    fingerprint = _fingerprint(case_id, members)
    latest = conn.execute(
        "SELECT version FROM source_set_versions WHERE case_id = %s"
        " ORDER BY version DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    previous = None if latest is None else load_source_set(conn, case_id, latest[0])
    if previous is not None and previous.fingerprint == fingerprint:
        return previous
    version = 1 if previous is None else previous.version + 1
    conn.execute(
        "INSERT INTO source_set_versions VALUES (%s, %s, 1, %s, %s)",
        (case_id, version, fingerprint, len(members)),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO source_set_members"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(case_id, version, *asdict(member).values()) for member in members],
        )
    return SourceSet(case_id, version, fingerprint, members)


def pinned_live_sources(conn: StoreConnection, run_id: UUID) -> dict[str, UUID]:
    """Document digest to source id: the run's captured members still usable now.

    The one reader of a run's evidence for everything proven after the call --
    the orchestration proof and the canonical deliverable. A captured member
    counts only while it is live and its document and extraction identity are
    still the ones the pin captured (invariant 1: withdrawal is checked at every
    use); a source admitted after the pin is never a member.

    A document captured under several such members resolves to the lowest
    source id when all of them carry one extraction output -- identical tokens,
    so identical rectangles, whichever copy a call cited -- and to none when
    their outputs differ, since a digest cannot say which rectangles it meant.
    Caller owns the read transaction.
    """
    rows = conn.execute(
        "SELECT m.document_sha256, m.source_id, m.output_sha256 FROM run_inputs i"
        " JOIN source_set_members m"
        " ON (m.case_id, m.version) = (i.case_id, i.source_version)"
        " JOIN live_sources s ON (s.case_id, s.source_id) = (m.case_id, m.source_id)"
        " JOIN source_extractions e ON e.source_id = s.source_id"
        " WHERE i.run_id = %s AND (s.document_sha256, e.extractor_identity,"
        " e.output_sha256, e.extraction_sha256) = (m.document_sha256,"
        " m.extractor_identity, m.output_sha256, m.extraction_sha256)"
        " ORDER BY m.source_id",
        (run_id,),
    ).fetchall()
    resolved: dict[str, UUID] = {}
    outputs: dict[str, set[str]] = {}
    for document, source, output in rows:
        resolved.setdefault(str(document), UUID(str(source)))
        outputs.setdefault(str(document), set()).add(str(output))
    return {doc: source for doc, source in resolved.items() if len(outputs[doc]) == 1}


@dataclass(frozen=True, slots=True)
class CaseSource:
    """One source of a case, admitted or withdrawn, with its set versions."""

    source_id: UUID
    filename: str
    document_sha256: str
    admitted_at: datetime
    withdrawn_at: datetime | None
    # The stored canonical identity; None for a source admitted before
    # extraction provenance was recorded (UNKNOWN, never today's adapter).
    extractor_identity: str | None
    set_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CaseSetVersion:
    version: int
    fingerprint: str
    member_count: int


@dataclass(frozen=True, slots=True)
class CaseSources:
    """What a case holds, bounded: `truncated` when either list met `limit`."""

    sources: tuple[CaseSource, ...]
    set_versions: tuple[CaseSetVersion, ...]
    truncated: bool


def case_sources(conn: StoreConnection, *, case_id: UUID, limit: int) -> CaseSources:
    """Every source of a case -- withdrawal read live -- and its set versions.

    Two queries whatever the size. Sources are listed in admission order, at
    most `limit`; set versions are the newest `limit`, ascending, and each
    source names only its versions among those. This is a listing, not
    snapshot authority: membership is not re-verified here (`load_source_set`
    is what does that). Caller owns the read transaction.
    """
    versions = conn.execute(
        "SELECT version, fingerprint, member_count FROM source_set_versions"
        " WHERE case_id = %s ORDER BY version DESC LIMIT %s",
        (case_id, limit + 1),
    ).fetchall()
    kept = versions[:limit]
    oldest = int(kept[-1][0]) if kept else 1
    rows = conn.execute(
        "SELECT s.source_id, s.filename, s.document_sha256, s.admitted_at,"
        " s.withdrawn_at, e.extractor_identity,"
        " ARRAY(SELECT m.version FROM source_set_members m"
        "  WHERE m.case_id = s.case_id AND m.source_id = s.source_id"
        "  AND m.version >= %s ORDER BY m.version DESC LIMIT %s)"
        " FROM sources s LEFT JOIN source_extractions e USING (source_id)"
        " WHERE s.case_id = %s ORDER BY s.admitted_at, s.source_id LIMIT %s",
        (oldest, limit, case_id, limit + 1),
    ).fetchall()
    return CaseSources(
        sources=tuple(
            CaseSource(
                source_id=row[0],
                filename=row[1],
                document_sha256=row[2],
                admitted_at=row[3],
                withdrawn_at=row[4],
                extractor_identity=row[5],
                set_versions=tuple(sorted(int(v) for v in row[6])),
            )
            for row in rows[:limit]
        ),
        set_versions=tuple(
            CaseSetVersion(int(row[0]), row[1], int(row[2]))
            for row in reversed(versions[:limit])
        ),
        truncated=len(rows) > limit or len(versions) > limit,
    )
