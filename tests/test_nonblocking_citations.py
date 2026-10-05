"""D106: a citation fault refuses the citation, never the answer.

The owner's rulings of 4 October 2026: a citation that does not anchor is
kept, unverified, in a list of its own; an anchored one the body does not
carry is kept, not linked to a statement; structural refusals and their
guided retries are unchanged; keys are met by anchored citations only.
Invariant 11's "coordinate-anchored or refused" holds of every citation.
"""

from __future__ import annotations

import dataclasses
import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from canonical_fixtures import QUOTE
from test_handoff_record import CP0, _stored
from test_handoff_record import _record as _built

from caos.evidence.citations import (
    EXCERPT,
    WHOLE_LINE,
    AnchoredCitation,
    Citation,
    CitationRule,
    TokenIndex,
    within_line,
)
from caos.methodology import verification
from caos.methodology.handoff import (
    MAX_CITATIONS,
    UNVERIFIED_CODES,
    CanonicalRecord,
    UnverifiedCitation,
    _decoded_record,
    _lines_held,
    read_record,
    record_bytes,
    unverified_citation,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

SOURCE = UUID("6da212c6-65a1-46b3-9e5c-7ed56acccd18")
LINE = f"{QUOTE} and the rest of its line"
EXCERPTED = " ".join(LINE.split()[1:])
LOST = UnverifiedCitation(
    SOURCE, 3, "A sentence no line carries", RefusalCode.CITATION_NOT_LOCATED
)


def _excerpt_record(**changes: object) -> CanonicalRecord:
    """An `EXCERPT` record with one anchored excerpt, as D105 writes it."""
    [found] = _built().citations
    anchored = dataclasses.replace(found, matched_text=EXCERPTED, line_text=LINE)
    values: dict[str, object] = {"citation_rule": EXCERPT, "citations": (anchored,)}
    values.update(changes)
    return _built(**values)


def test_a_record_keeps_unverified_citations_apart_and_reads_back_as_written(
    tmp_path: Path,
) -> None:
    """The record's `unverified` list is its own field, never mixed into
    `citations`; an anchored citation the body does not carry is written
    `linked: false`; both read back as written, byte for byte, and the
    anchored EXCERPT citation still holds its line beside an unverified one
    (`_lines_held`, `within_line`)."""
    [anchored] = _excerpt_record().citations
    unlinked = dataclasses.replace(anchored, linked=False)
    record = _excerpt_record(citations=(unlinked,), unverified=(LOST,))
    data = record_bytes(record)
    document = json.loads(data)
    assert document["unverified"] == [
        {
            "source_id": str(SOURCE),
            "page": 3,
            "matched_text": "A sentence no line carries",
            "code": "CITATION_NOT_LOCATED",
        }
    ]
    assert document["citations"][0]["linked"] is False
    assert len(document["citations"]) == 1
    decoded = _decoded_record(data)
    assert decoded == record and record_bytes(decoded) == data
    _lines_held(decoded.citations, decoded.citation_rule)
    assert within_line(unlinked.matched_text, LINE)
    blobs, artifact, sha = _stored(tmp_path, record)
    read = read_record(blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0)
    assert read.unverified == (LOST,) and read.citations == (unlinked,)


def test_a_record_stored_before_d106_reads_and_writes_as_it_did() -> None:
    """Absent `unverified` is empty and absent `linked` is linked: a record
    without either is the bytes it always was, under every rule."""
    for record in (_built(), _excerpt_record(), _built(citation_rule=WHOLE_LINE)):
        data = record_bytes(record)
        document = json.loads(data)
        assert "unverified" not in document
        assert all("linked" not in c for c in document["citations"])
        decoded = _decoded_record(data)
        assert decoded.unverified == () and all(c.linked for c in decoded.citations)
        assert record_bytes(decoded) == data


def test_a_record_of_unverified_citations_alone_reads_back() -> None:
    """An answer with no anchored citation is accepted (D106); its record
    holds none, and one holding neither kind does not read."""
    record = _excerpt_record(citations=(), unverified=(LOST,))
    assert _decoded_record(record_bytes(record)) == record
    with pytest.raises(ValueError):
        record_bytes(_excerpt_record(citations=()))


_LOST_JSON = {
    "source_id": str(SOURCE),
    "page": 3,
    "matched_text": "A sentence no line carries",
    "code": "CITATION_NOT_LOCATED",
}
_NO_STORE = cast(StoreConnection, None)


def _edited(
    edit: Callable[[Any], object], record: CanonicalRecord | None = None
) -> bytes:
    """`record`'s bytes (an excerpt record with one unverified citation by
    default) with one edit to the decoded document."""
    if record is None:
        record = _excerpt_record(unverified=(LOST,))
    document = json.loads(record_bytes(record))
    edit(document)
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.__setitem__("unverified", []),
        lambda d: d["citations"][0].__setitem__("linked", True),
        lambda d: d["citations"][0].__setitem__("linked", 0),
        lambda d: d["unverified"][0].__setitem__("code", "HANDOFF_MALFORMED"),
        lambda d: d["unverified"][0].__setitem__("code", ["CITATION_NOT_LOCATED"]),
        lambda d: d["unverified"][0].__setitem__("source_id", str(SOURCE).upper()),
        lambda d: d["unverified"][0].__setitem__("page", 0),
        lambda d: d["unverified"][0].__setitem__("matched_text", " "),
        lambda d: d["unverified"][0].__setitem__("matched_text", "bell \u0007"),
        lambda d: d["unverified"][0].__setitem__("matched_text", "Cafe\u0301"),
        lambda d: d["unverified"][0].__setitem__("extra", 1),
        lambda d: d["unverified"][0].pop("code"),
        lambda d: d.__setitem__("unverified", [d["unverified"][0]] * MAX_CITATIONS),
    ],
)
def test_a_record_this_host_did_not_write_does_not_read(
    edit: Callable[[Any], object],
) -> None:
    """Each D106 field has one spelling: an empty `unverified`, a `linked`
    other than false, a code that is no citation fault, a locator or quote
    the wire would refuse or that is not as it crosses `BoundaryText`, more
    than `MAX_CITATIONS` in all, or either field outside `EXCERPT`."""
    with pytest.raises((ValueError, TypeError)):
        _decoded_record(_edited(edit))


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.__setitem__("unverified", [_LOST_JSON]),
        lambda d: d["citations"][0].__setitem__("linked", False),
    ],
)
def test_only_an_excerpt_record_holds_d106_fields(
    edit: Callable[[Any], object],
) -> None:
    """Only an answer accepted since D106 can hold an unverified citation or
    an unlinked one, and it is under `EXCERPT`: under an earlier rule either
    is not this host's, read or written."""
    whole = _built(citation_rule=WHOLE_LINE)
    assert _decoded_record(_edited(lambda _d: None, whole)) == whole
    with pytest.raises(ValueError):
        _decoded_record(_edited(edit, whole))
    with pytest.raises(ValueError):
        record_bytes(dataclasses.replace(whole, unverified=(LOST,)))


def test_an_unverified_citation_is_kept_only_as_it_crosses_the_boundary() -> None:
    """The quote is stored NFC, as `BoundaryText` gives it; one that will
    not cross, hides text, or is kept for a code that is no citation fault
    refuses the answer `HANDOFF_MALFORMED`, a host text check."""
    decomposed = "Cafe\u0301 revenue rose"
    kept = unverified_citation(
        Citation(SOURCE, 2, decomposed), RefusalCode.CITATION_AMBIGUOUS
    )
    assert kept.matched_text == unicodedata.normalize("NFC", decomposed)
    assert (kept.page, kept.code) == (2, RefusalCode.CITATION_AMBIGUOUS)
    for quote, code in (
        ("bell \u0007 here", RefusalCode.CITATION_NOT_LOCATED),
        ("hidden\u200b text", RefusalCode.CITATION_NOT_LOCATED),
        ("right \u202e left", RefusalCode.CITATION_NOT_DELIVERED),
        ("a fine quote", RefusalCode.EVIDENCE_NOT_AVAILABLE),
    ):
        with pytest.raises(Refusal) as refused:
            unverified_citation(Citation(SOURCE, 1, quote), code)
        assert refused.value.code is RefusalCode.HANDOFF_MALFORMED
    for code in UNVERIFIED_CODES:
        assert (
            unverified_citation(Citation(SOURCE, 1, "a fine quote"), code).code is code
        )


def test_a_re_anchoring_reader_carries_linked_and_never_locates_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_reanchored` (the proof's and the freeze's) locates the anchored list
    only and compares it with `linked` carried as recorded; the unverified
    list is never asked for, so no reader turns one into a located one."""
    [anchored] = _excerpt_record().citations
    record = _excerpt_record(
        citations=(dataclasses.replace(anchored, linked=False),), unverified=(LOST,)
    )
    asked: list[Citation] = []

    def located(
        _conn: StoreConnection,
        *,
        delivered: Mapping[UUID, frozenset[str]],
        citations: Sequence[tuple[Citation, int | None]],
        index: TokenIndex,
        rule: CitationRule,
    ) -> list[AnchoredCitation]:
        asked.extend(citation for citation, _cited in citations)
        return [dataclasses.replace(c, linked=True) for c in record.citations]

    monkeypatch.setattr(verification, "verify_stored_citations", located)
    evidence = verification.PinnedEvidence({"c" * 64: SOURCE}, {}, TokenIndex())
    kept = verification._reanchored(_NO_STORE, record, evidence, lambda _step: None)
    assert kept == record.citations and not kept[0].linked
    assert [c.matched_text for c in asked] == [EXCERPTED]
