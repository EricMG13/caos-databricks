"""D107's display, the wire's half (F506): each citation is served with the
`[C<n>]` marker its module's body cites it by, so the workspace draws that
marker as a chip; and a saved artifact carries what its markers name, each
marked record citation as a figure the source drawer opens and each marked
unverified one, whose chip opens nothing. A record accepted before markers
holds none, and its artifact names none.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_analysis_section import _analysis, _as, client
from test_deliverable_canonical import _accept, harness, route
from test_execution_freshness import _Harness
from test_revision_sections import _get
from test_unverified_citations_shown import MODEL_QUOTE, _save

from caos.api.wire import NarrativeFigure, NarrativeUnverified, ReportArtifact
from caos.methodology.handoff import UnverifiedCitation
from caos.refusals import RefusalCode

__all__ = ["client", "harness", "route"]


@pytest.fixture
def marked_route(harness: _Harness) -> _Harness:
    """LITE accepted; CP-L10's record is D107's: [C1] anchored, [C2] not."""
    entry = UnverifiedCitation(
        harness.source_id, 3, MODEL_QUOTE, RefusalCode.CITATION_NOT_LOCATED
    )
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10", False, (entry,), True)
    _accept(harness, "CP-5")
    return harness


def _handoffs(client: TestClient, lite: _Harness) -> dict[str, dict[str, Any]]:
    response = client.get(
        _analysis(lite.case_id, lite.run_id), headers=_as(lite.approver)
    )
    lite.conn.rollback()
    assert response.status_code == 200, response.json()
    return {h["module_id"]: h for h in response.json()["body"]["handoffs"]}


def test_each_citation_is_served_with_its_marker(
    client: TestClient, marked_route: _Harness
) -> None:
    handoffs = _handoffs(client, marked_route)
    assert [f["marker"] for f in handoffs["CP-L10"]["source_facts"]] == [1]
    assert [e["marker"] for e in handoffs["CP-L10"]["unverified_facts"]] == [2]
    # Before D107 no citation holds one, and none is invented.
    assert [f["marker"] for f in handoffs["CP-0"]["source_facts"]] == [None]


def test_a_saved_artifact_carries_what_its_markers_name(
    client: TestClient, marked_route: _Harness
) -> None:
    lite = marked_route
    node = lite.route.nodes[1].route_node_id
    revision = _save(lite, [[{"text": "Debt is as filed."}]])
    body = _get(client, lite, revision, "report")
    artifacts = {a["route_node_id"]: a for a in body["artifacts"]}
    for artifact in artifacts.values():
        ReportArtifact.model_validate(artifact)
    marked = artifacts[node]
    (figure,) = marked["figures"]
    assert NarrativeFigure.model_validate(figure).marker == 1
    assert figure["record_sha256"] == marked["record_sha256"]
    assert (figure["citation_index"], figure["source_id"]) == (0, str(lite.source_id))
    # The drawer shows the whole line, the excerpt marked, from the record.
    assert figure["line"]["recorded"] is True
    assert figure["line"]["excerpt"] == "Total debt at 31 December 2026 was USD"
    (entry,) = marked["unverified"]
    assert NarrativeUnverified.model_validate(entry).marker == 2
    assert (entry["unverified_index"], entry["page"]) == (0, 3)
    assert entry["matched_text"] == MODEL_QUOTE
    # A record from before markers names nothing a chip could open.
    first = artifacts[lite.route.nodes[0].route_node_id]
    assert (first["figures"], first["unverified"]) == ([], [])
