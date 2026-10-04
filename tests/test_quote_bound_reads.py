"""NB2 review, Important 1: a stored quote longer than the wire's bound never
fails a read with a validation error (INTERNAL_FAULT).

The reviewer's probe is a 70,011-character quote. As an unverified quote it
can no longer be stored (NB1's cap: longer than any evidence line,
`HANDOFF_MALFORMED`) and a record holding one does not decode, so every read
and the save boundary answer the record's typed refusal. As an anchored
quote -- an `ANY_RUN` quote is any run of its page, and the codec bounds no
quote's length -- it decodes, and every read serves it cut at `QUOTE_CHARS`,
ending "…(truncated)" (`wire.bounded`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Mapping, Sequence
from uuid import UUID

import pytest
import test_deliverable_canonical as canonical
from fastapi.testclient import TestClient
from httpx2 import Response
from test_analysis_section import _analysis, _as, client
from test_deliverable_canonical import _accept, harness, route
from test_execution_freshness import _Harness
from test_unverified_citations_shown import _save

from caos.api.reads.reports import _figure, _unverified
from caos.api.wire import (
    QUOTE_CHARS,
    TRUNCATED,
    LineView,
    NarrativeFigure,
    NarrativeUnverified,
    bounded,
)
from caos.evidence.citations import (
    ANY_RUN,
    AnchoredCitation,
    Citation,
    CitationRule,
    verify_citations,
)
from caos.methodology.handoff import UnverifiedCitation
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

__all__ = ["client", "harness", "route"]

PROBE = "Total debt " + "x" * 70000  # the reviewer's 70,011 characters
DOCUMENT = "6fc4a221c5d5" + "0" * 52
SOURCE = "0b6f1a52-4d8e-4c6e-9a51-2f1d7c3e9b10"


def test_bounded_cuts_visibly_at_the_wire_bound() -> None:
    assert len(PROBE) == 70011
    cut = bounded(PROBE)
    assert len(cut) == QUOTE_CHARS and cut.endswith(TRUNCATED)
    assert cut.startswith("Total debt xxx")
    assert bounded("short") == "short"
    line = LineView.of(None, PROBE, ANY_RUN)
    assert line.excerpt == cut and not line.recorded


@pytest.fixture
def long_anchored(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> Iterator[_Harness]:
    """LITE accepted, CP-5's one citation an anchored quote of 70,011
    characters (its record decodes: the codec bounds no quote's length)."""
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10")
    real = verify_citations

    def lengthened(
        conn: StoreConnection,
        *,
        delivered: Mapping[UUID, frozenset[str]],
        citations: Sequence[Citation],
        rule: CitationRule = ANY_RUN,
    ) -> list[AnchoredCitation]:
        found = real(conn, delivered=delivered, citations=citations, rule=rule)
        return [dataclasses.replace(each, matched_text=PROBE) for each in found]

    monkeypatch.setattr(canonical, verify_citations.__name__, lengthened)
    _accept(harness, "CP-5")
    yield harness


def _get(client: TestClient, lite: _Harness, path: str) -> Response:
    response = client.get(path, headers=_as(lite.approver))
    lite.conn.rollback()
    return response


def test_every_read_serves_a_long_anchored_quote_cut(
    client: TestClient, long_anchored: _Harness
) -> None:
    lite = long_anchored
    analysis = _get(client, lite, _analysis(lite.case_id, lite.run_id))
    assert analysis.status_code == 200, analysis.json()
    [fact] = next(
        h["source_facts"]
        for h in analysis.json()["body"]["handoffs"]
        if h["module_id"] == "CP-5"
    )
    assert fact["matched_text"] == bounded(PROBE)
    assert fact["line"]["excerpt"] == bounded(PROBE)
    for path in (
        f"/api/v1/cases/{lite.case_id}/model?run={lite.run_id}",
        "/api/v1/book",
    ):
        response = _get(client, lite, path)
        assert response.status_code == 200, (path, response.json())


def test_the_report_and_committee_figures_are_cut_too() -> None:
    """Report and Committee serve a saved narrative through the same two
    builders (`_narrative_view`): each cuts the quote, and the result is the
    wire's."""
    record = {
        "citations": [{"bboxes": [], "linked": False, "line_text": None}],
        "unverified": [{"linked": False}],
    }
    figure = _figure(
        {
            "route_node_id": "RN",
            "citation_index": 0,
            "document_sha256": DOCUMENT,
            "page": 1,
            "matched_text": PROBE,
        },
        {"RN": "c" * 64},
        {"RN": record},
        {DOCUMENT: (UUID(SOURCE), None)},
    )
    assert figure is not None
    shown = NarrativeFigure.model_validate(figure)
    assert shown.matched_text == bounded(PROBE) and shown.linked is False
    assert shown.line.excerpt == bounded(PROBE)
    entry = _unverified(
        {
            "route_node_id": "RN",
            "unverified_index": 0,
            "source_id": SOURCE,
            "page": 3,
            "matched_text": PROBE,
            "code": "CITATION_NOT_LOCATED",
        },
        {"RN": "c" * 64},
        {"RN": record},
    )
    unverified = NarrativeUnverified.model_validate(entry)
    assert unverified.matched_text == bounded(PROBE) and unverified.linked is False


def test_a_long_anchored_quote_is_refused_at_save_by_its_proof(
    long_anchored: _Harness,
) -> None:
    """Save re-derives the payload, re-anchoring every record citation: a
    quote no page carries is refused by its typed code, never a crash."""
    with pytest.raises(Refusal) as caught:
        _save(long_anchored, [])
    assert caught.value.code != RefusalCode.INTERNAL_FAULT


@pytest.fixture
def long_unverified(harness: _Harness) -> _Harness:
    """CP-5's record holds the probe as an unverified quote: written by hand
    past NB1's cap, as no producer can, so it does not decode."""
    entry = UnverifiedCitation(
        harness.source_id, 3, PROBE, RefusalCode.CITATION_NOT_LOCATED
    )
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10")
    _accept(harness, "CP-5", False, (entry,))
    return harness


def test_a_long_unverified_quote_is_the_records_typed_refusal(
    client: TestClient, long_unverified: _Harness
) -> None:
    lite = long_unverified
    for path in (
        _analysis(lite.case_id, lite.run_id),
        f"/api/v1/cases/{lite.case_id}/model?run={lite.run_id}",
    ):
        response = _get(client, lite, path)
        assert response.json()["code"] == "ARTIFACT_RECORD_MISMATCH", path
    book = _get(client, lite, "/api/v1/book")
    assert book.status_code == 200
    [row] = book.json()["body"]["rows"]
    assert row["refusal"]["code"] == "ARTIFACT_RECORD_MISMATCH"
    with pytest.raises(Refusal) as caught:
        _save(lite, [])
    assert caught.value.code == RefusalCode.ARTIFACT_RECORD_MISMATCH
