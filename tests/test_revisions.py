"""Saved revisions originate only from proven accepted route artifacts."""

from __future__ import annotations

import inspect
import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from test_deliverable_canonical import QUOTE, harness, lite, route
from test_execution_freshness import _Harness

from caos.deliverable import revisions
from caos.refusals import Refusal

__all__ = ["harness", "lite", "route"]


def _save(lite: _Harness, narrative: object = None) -> UUID:
    return revisions.save_revision(
        lite.conn,
        lite.blobs,
        lite.bundle,
        case_id=lite.case_id,
        run_id=lite.run_id,
        actor_id=lite.approver,
        narrative=[] if narrative is None else narrative,
    )


def _read(lite: _Harness, revision: UUID) -> dict[str, Any]:
    result = revisions.read_revision(
        lite.conn, lite.blobs, case_id=lite.case_id, revision_id=revision
    )
    lite.conn.rollback()
    return result


def test_a_revision_is_saved_from_accepted_artifacts_and_cannot_be_supplied(
    lite: _Harness,
) -> None:
    revision = _save(lite)
    assert isinstance(revision, UUID)
    payload = _read(lite, revision)
    assert payload["revision_id"] == str(revision)
    assert payload["case_id"] == str(lite.case_id)
    assert [a["route_node_id"] for a in payload["artifacts"]] == [
        n.route_node_id for n in lite.route.nodes
    ]
    assert not {"payload", "payload_sha256", "revision_id"} & set(
        inspect.signature(revisions.save_revision).parameters
    )


def test_a_saved_revision_row_and_blob_are_immutable(lite: _Harness) -> None:
    revision = _save(lite)
    for statement in (
        "UPDATE deliverable_revisions SET saved_by = saved_by",
        "DELETE FROM deliverable_revisions",
        "TRUNCATE deliverable_revisions CASCADE",
    ):
        with pytest.raises(psycopg.Error):
            lite.conn.execute(statement)
        lite.conn.rollback()
    payload = _read(lite, revision)
    row = lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_revisions WHERE revision_id=%s",
        (revision,),
    ).fetchone()
    lite.conn.rollback()
    assert row is not None
    assert json.loads(lite.blobs.get(row[0])) == payload


def test_a_digit_in_narrative_text_is_refused_and_a_figure_enters_by_reference(
    lite: _Harness,
) -> None:
    with pytest.raises(Refusal) as caught:
        _save(lite, [[{"text": "Debt is 42"}]])
    assert caught.value.code.value == "NARRATIVE_FIGURE_UNREFERENCED"
    node = lite.route.nodes[0].route_node_id
    revision = _save(
        lite,
        [
            [
                {"text": "Debt: "},
                {"figure": {"route_node_id": node, "citation_index": 0}},
            ]
        ],
    )
    figure = _read(lite, revision)["narrative"][0][1]["figure"]
    assert figure["matched_text"] == QUOTE
    assert figure["route_node_id"] == node
    assert figure["page"] == 1


@pytest.mark.parametrize(
    "reference",
    [
        {"route_node_id": "missing", "citation_index": 0},
        {"route_node_id": "CP-0", "citation_index": -1},
        {"route_node_id": "CP-0", "citation_index": True},
    ],
)
def test_an_unknown_figure_reference_is_refused(
    lite: _Harness, reference: dict[str, object]
) -> None:
    with pytest.raises(Refusal) as caught:
        _save(lite, [[{"figure": reference}]])
    assert caught.value.code.value == "NARRATIVE_REFERENCE_INVALID"


def test_restricted_status_and_limitations_are_in_the_saved_payload(
    lite: _Harness,
) -> None:
    payload = _read(lite, _save(lite))
    facts = json.loads(payload["artifacts"][1]["record"])["projections"]
    assert facts["qa_status"] == "Restricted"
    assert facts["limitation_flags"] == ["Interim period only"]
    assert facts["decision_scope"] == "SCREENING_ONLY"


def test_wrong_case_and_incomplete_routes_cannot_be_saved(harness: _Harness) -> None:
    with pytest.raises(Refusal) as caught:
        _save(harness)
    assert caught.value.code.value == "DELIVERABLE_PAYLOAD_INVALID"
    with pytest.raises(Refusal) as caught:
        revisions.save_revision(
            harness.conn,
            harness.blobs,
            harness.bundle,
            case_id=harness.case_id,
            run_id=uuid4(),
            actor_id=harness.approver,
            narrative=[],
        )
    assert caught.value.code.value == "RUN_NOT_FOUND"


def test_typed_narrative_renders_resolved_figures_and_restrictions(
    lite: _Harness,
) -> None:
    from caos.deliverable.render import render

    revision = _save(
        lite,
        [
            [
                {"text": "Debt: "},
                {
                    "figure": {
                        "route_node_id": lite.route.nodes[0].route_node_id,
                        "citation_index": 0,
                    }
                },
            ]
        ],
    )
    payload = _read(lite, revision)
    page = render(payload)
    assert page == render(json.loads(json.dumps(payload)))
    assert b"Analyst narrative" in page and QUOTE.encode() in page
    assert b"Interim period only" in page


def test_an_empty_text_span_renders_from_a_valid_saved_revision(lite: _Harness) -> None:
    from caos.deliverable.render import render

    payload = _read(lite, _save(lite, [[{"text": ""}, {"text": "Assessment"}]]))
    assert b"<div>Assessment</div>" in render(payload)


@pytest.mark.parametrize(
    "narrative",
    [
        "unstructured",
        False,
        [[{"text": "ok", "extra": "bad"}]],
        [[]],
        [[{"text": "a" * 2001}]],
        [[{"text": "a"}]] * 65,
        [[{"text": "a"}] * 65],
        [[{"text": "bad\u202e"}]],
    ],
)
def test_invalid_or_over_ceiling_narrative_leaves_no_revision(
    lite: _Harness, narrative: object
) -> None:
    with pytest.raises(Refusal):
        _save(lite, narrative)
    assert lite.conn.execute(
        "SELECT count(*) FROM deliverable_revisions"
    ).fetchone() == (0,)


# Code points rather than literals: a fullwidth digit in this file is the
# confusable RUF001 refuses, and the point of the case is what it is.
FIGURES_IN_OTHER_SCRIPTS = (
    "Net leverage is " + chr(0xFF14) + "." + chr(0xFF12) + "x",  # fullwidth
    "Headroom " + chr(0x0664) + chr(0x0665) + "%",  # Arabic-Indic
    "About " + chr(0x00BD) + " of the facility",  # vulgar fraction
    "Tranche " + chr(0x2163) + " matures first",  # Roman numeral
    "Leverage " + chr(0x1D7D2) + "x",  # mathematical digit
)


@pytest.mark.parametrize("prose", FIGURES_IN_OTHER_SCRIPTS)
def test_a_figure_in_any_script_is_still_an_uncited_figure(
    lite: _Harness, prose: str
) -> None:
    """FP-06: `"0" <= character <= "9"` saw ASCII digits and nothing else.

    `BoundaryText` applies NFC, which keeps fullwidth digits pasted from a
    Japanese or Chinese statement, Arabic-Indic ones, and vulgar fractions,
    Roman numerals and mathematical digits -- so each of these was stored as an
    uncited figure in committee prose, against invariant 11.
    """
    with pytest.raises(Refusal, match="NARRATIVE_FIGURE_UNREFERENCED"):
        _save(lite, [[{"text": prose}]])
    lite.conn.rollback()


def test_prose_carrying_no_quantity_still_saves(lite: _Harness) -> None:
    """The rule is quantities, not non-ASCII: a letter is not a figure."""
    assert _save(lite, [[{"text": "Le levier reste " + chr(0x00EE) + "ntact"}]])
