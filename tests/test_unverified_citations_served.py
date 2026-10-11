"""D106's display, the wire's half: the Analysis read serves a handoff's
unverified citations apart from its source facts, as recorded and never with
a line, a rectangle or a located document; a source fact says whether the
answer's body carries it (`linked`); a saved narrative serves an unverified
figure as the model's locator; and a draft names one by its own reference.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_analysis_section import _analysis, _as, client
from test_deliverable_canonical import harness, route
from test_execution_freshness import _Harness
from test_revision_sections import _get
from test_unverified_citations_shown import MODEL_QUOTE, _save, unverified_route

from caos.api.commands.deliverable import _spans
from caos.api.wire import (
    NarrativeDraft,
    NarrativeUnverified,
    NarrativeUnverifiedRef,
    UnverifiedCitationView,
)
from caos.refusals import Refusal, RefusalCode

__all__ = ["client", "harness", "route", "unverified_route"]


def test_the_analysis_read_serves_unverified_citations_apart(
    client: TestClient, unverified_route: _Harness
) -> None:
    lite = unverified_route
    response = client.get(
        _analysis(lite.case_id, lite.run_id), headers=_as(lite.approver)
    )
    lite.conn.rollback()
    assert response.status_code == 200, response.json()
    handoffs = {h["module_id"]: h for h in response.json()["body"]["handoffs"]}

    assert handoffs["CP-L10"]["source_facts"] == []
    assert handoffs["CP-L10"]["unverified_facts"] == [
        {
            "source_id": str(lite.source_id),
            "page": 3,
            "matched_text": MODEL_QUOTE,
            "code": "CITATION_NOT_LOCATED",
            "linked": True,
            "marker": None,
        }
    ]
    for module in ("CP-0", "CP-5"):
        assert handoffs[module]["unverified_facts"] == []
        assert [f["linked"] for f in handoffs[module]["source_facts"]] == [True]


def test_an_unverified_view_carries_no_line_rectangle_or_document() -> None:
    """Nothing on it could be shown as host-verified, and only the three
    anchoring faults leave a citation unverified."""
    assert set(UnverifiedCitationView.model_fields) == {
        "source_id",
        "page",
        "matched_text",
        "code",
        "linked",
        "marker",
    }
    view = {
        "source_id": "0b6f1a52-4d8e-4c6e-9a51-2f1d7c3e9b10",
        "page": 2,
        "matched_text": "q",
        "code": "CITATION_AMBIGUOUS",
        "linked": False,
        "marker": 3,
    }
    assert UnverifiedCitationView.model_validate(view).page == 2
    for wrong in (
        {"code": "HANDOFF_MALFORMED"},
        {"page": 0},
        {"line": None},
        {"marker": 0},
    ):
        with pytest.raises(ValidationError):
            UnverifiedCitationView.model_validate({**view, **wrong})


def test_a_saved_unverified_figure_is_served_as_the_models_locator(
    client: TestClient, unverified_route: _Harness
) -> None:
    lite = unverified_route
    node = lite.route.nodes[1].route_node_id
    reference = {"route_node_id": node, "unverified_index": 0}
    revision = _save(lite, [[{"text": "Debt: "}, {"unverified": reference}]])

    body = _get(client, lite, revision, "report")
    span = body["narrative"][0][1]
    record = next(a for a in body["artifacts"] if a["route_node_id"] == node)
    assert span["text"] is None and span["figure"] is None
    assert NarrativeUnverified.model_validate(span["unverified"]).page == 3
    assert span["unverified"] == {
        **reference,
        "module_id": "CP-L10",
        "record_sha256": record["record_sha256"],
        "source_id": str(lite.source_id),
        "page": 3,
        "matched_text": MODEL_QUOTE,
        "code": "CITATION_NOT_LOCATED",
        "linked": True,
        "marker": None,
    }


def test_a_draft_names_an_unverified_citation_by_its_own_reference() -> None:
    reference = NarrativeUnverifiedRef(route_node_id="RN-CP-1", unverified_index=2)
    drafted = _spans(
        [
            [
                NarrativeDraft(text="Leverage: ", figure=None, unverified=None),
                NarrativeDraft(text=None, figure=None, unverified=reference),
            ]
        ]
    )
    assert drafted == [
        [
            {"text": "Leverage: "},
            {"unverified": {"route_node_id": "RN-CP-1", "unverified_index": 2}},
        ]
    ]
    for both in (
        NarrativeDraft(text="x", figure=None, unverified=reference),
        NarrativeDraft(text=None, figure=None, unverified=None),
    ):
        with pytest.raises(Refusal) as caught:
            _spans([[both]])
        assert caught.value.code == RefusalCode.NARRATIVE_REFERENCE_INVALID
