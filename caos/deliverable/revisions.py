"""§57: immutable, host-derived revisions and bounded cited narrative."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import Revision, canonical_payload, payload_bytes
from caos.deliverable.render import RenderRefused, render
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction, governed_write
from caos.store.members import Standing


def _is_figure(character: str) -> bool:
    """Whether this character states a quantity, in any script (invariant 11).

    `"0" <= character <= "9"` saw ASCII and nothing else, while `BoundaryText`
    applies NFC, which keeps every other spelling of a digit: fullwidth digits
    pasted from a Japanese or Chinese statement, Arabic-Indic ones, and vulgar
    fractions, Roman numerals and mathematical digits besides -- each stored as
    an uncited figure in committee prose against invariant 11 (FP-06).
    `str.isnumeric` is the whole class: every `isdigit` and `isdecimal`
    character is numeric, and the fractions and numerals that are neither are
    numeric too.

    The rule sees figures, not numbers: a quantity spelled in words ("four
    point two times") has no numeric character, so it saves, files and
    verifies uncited. Reading number words is language work this rule does
    not attempt; the signers' review is what holds prose quantities (N79).
    """
    return character.isnumeric()


def _narrative(value: object, artifacts: list[dict[str, Any]]) -> list[Any]:
    invalid = Refusal(RefusalCode.NARRATIVE_REFERENCE_INVALID)
    if not isinstance(value, list) or len(value) > 64:
        raise invalid
    records = {a["route_node_id"]: json.loads(a["record"]) for a in artifacts}
    result = []
    for paragraph in value:
        if not isinstance(paragraph, list) or not 1 <= len(paragraph) <= 64:
            raise invalid
        result.append([_span(span, records) for span in paragraph])
    return result


def _span(span: object, records: dict[str, Any]) -> dict[str, Any]:
    invalid = Refusal(RefusalCode.NARRATIVE_REFERENCE_INVALID)
    if not isinstance(span, dict):
        raise invalid
    if set(span) == {"text"} and isinstance(span["text"], (str, BoundaryText)):
        text = span["text"]
        text = BoundaryText.of(
            text.value if isinstance(text, BoundaryText) else text, limit=2000
        )
        if any(_is_figure(character) for character in text.value):
            raise Refusal(RefusalCode.NARRATIVE_FIGURE_UNREFERENCED)
        return {"text": text.value}
    if set(span) != {"figure"} or not isinstance(span["figure"], dict):
        raise invalid
    reference = span["figure"]
    if set(reference) != {"route_node_id", "citation_index"}:
        raise invalid
    node, index = reference["route_node_id"], reference["citation_index"]
    if not isinstance(node, str) or type(index) is not int or index < 0:
        raise invalid
    node = BoundaryText.of(node).value
    citations = records.get(node, {}).get("citations", [])
    if index >= len(citations):
        raise invalid
    citation = citations[index]
    return {
        "figure": {
            "route_node_id": node,
            "citation_index": index,
            **{
                key: citation[key]
                for key in ("document_sha256", "page", "matched_text")
            },
        }
    }


def _derive(  # noqa: PLR0913 -- the proof inputs and host-minted identity
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    run_id: UUID,
    revision_id: UUID,
    narrative: object,
) -> bytes:
    row = conn.execute(
        "SELECT title FROM cases WHERE case_id=%s", (case_id,)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    revision = Revision(
        case_id, run_id, BoundaryText.of(str(row[0])), BoundaryText.of(str(revision_id))
    )
    payload = canonical_payload(conn, blobs, bundle, revision, _in_unit=True)
    payload["case_id"] = str(case_id)
    payload["narrative"] = _narrative(narrative, payload["artifacts"])
    return payload_bytes(payload)


def save_revision(  # noqa: PLR0913 -- authority, owner and narrative boundary
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    narrative: object,
) -> UUID:
    """Save only proven route bytes under the case lock; callers supply no digest."""
    revision = uuid4()
    audit: dict[str, Any] = {"revision_id": str(revision), "run_id": str(run_id)}
    action = GovernedAction(case_id, actor_id, "REVISION_SAVED", Standing.WRITER, audit)

    def write(unit: StoreConnection) -> None:
        audit["payload_sha256"] = save_revision_in(
            unit,
            blobs,
            bundle,
            case_id=case_id,
            run_id=run_id,
            actor_id=actor_id,
            narrative=narrative,
            revision_id=revision,
        )

    governed_write(conn, action, write)
    return revision


def save_revision_in(  # noqa: PLR0913 -- authority, owner and narrative boundary
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    narrative: object,
    revision_id: UUID,
) -> str:
    """Derive, store and insert one revision in the caller's governed
    transaction; never commits. Returns the payload digest the audit event and
    the command's receipt both bind.

    The id is the caller's because the receipt has to name it: a command that
    minted one inside its unit could not answer a replay with the same body.
    """
    data = _derive(
        conn,
        blobs,
        bundle,
        case_id=case_id,
        run_id=run_id,
        revision_id=revision_id,
        narrative=narrative,
    )
    renderable(data)
    digest = blobs.put(data)
    conn.execute(
        "INSERT INTO deliverable_revisions"
        " (revision_id,case_id,run_id,payload_sha256,saved_by)"
        " VALUES (%s,%s,%s,%s,%s)",
        (revision_id, case_id, run_id, digest, actor_id),
    )
    return digest


def read_revision(
    conn: StoreConnection, blobs: BlobStore, *, case_id: UUID, revision_id: UUID
) -> dict[str, Any]:
    """Read digest-verified stored bytes in the caller's transaction."""
    row = conn.execute(
        "SELECT run_id,payload_sha256 FROM deliverable_revisions"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, revision_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    payload = json.loads(blobs.get(str(row[1])))
    if (payload.get("case_id"), payload.get("run_id"), payload.get("revision_id")) != (
        str(case_id),
        str(row[0]),
        str(revision_id),
    ):
        raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)
    return dict(payload)


def renderable(data: bytes) -> bytes:
    """The page this build's renderer draws from these payload bytes, or its
    refusal as the render's own code (N77). Save and freeze ask it, not only
    filing: a payload the renderer refuses was saved, signed and frozen, and
    refused only at filing, after two approvals, with the head then closed to
    the draft that could fix it."""
    try:
        return render(json.loads(data))
    except RenderRefused as refused:
        raise Refusal(RefusalCode(refused.code)) from None


def prove_revision(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    revision_id: UUID,
) -> bytes:
    """Re-prove the exact saved bytes in the caller's own unit.

    The caller owns the transaction: a write caller holds the case lock, a
    section read holds none, so its digest comparison refuses a governed write
    that commits mid-read rather than serving bytes this did not prove.
    """
    payload = read_revision(conn, blobs, case_id=case_id, revision_id=revision_id)
    if not isinstance(payload.get("narrative"), list):
        raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)

    narrative = [
        [
            span
            if "text" in span
            else {
                "figure": {
                    key: span["figure"][key]
                    for key in ("route_node_id", "citation_index")
                }
            }
            for span in paragraph
        ]
        for paragraph in payload["narrative"]
    ]
    data = _derive(
        conn,
        blobs,
        bundle,
        case_id=case_id,
        run_id=UUID(payload["run_id"]),
        revision_id=revision_id,
        narrative=narrative,
    )
    if data != payload_bytes(payload):
        raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
    return data
