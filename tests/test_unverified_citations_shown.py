"""D106's display, the deliverable's half (F504): a citation that did not
anchor is shown as the model's own, labelled "unverified, en dash, page N", never
styled, placed or worded as host-verified; a committee figure may name one
and is labelled so; a module whose every citation is unverified still
renders; an `ANY_RUN` quote is labelled a quote.

The model's quote is attacker-influenced text, so every probe below that
carries markup is held to the escaping F502 holds a source line to.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from test_deliverable_canonical import QUOTE, _accept, harness, route
from test_deliverable_package import IDENTITY
from test_execution_freshness import _Harness

from caos.deliverable import revisions
from caos.deliverable.package import Verification, build_package, verify_package
from caos.deliverable.render import (
    ANY_RUN,
    UNVERIFIED_REASONS,
    RenderRefused,
    render,
    unverified,
)
from caos.methodology.handoff import UNVERIFIED_CODES, UnverifiedCitation
from caos.refusals import Refusal, RefusalCode

__all__ = ["harness", "route"]

SOURCE = "0b6f1a52-4d8e-4c6e-9a51-2f1d7c3e9b10"
DOCUMENT = "6fc4a221c5d5" + "0" * 52
LINE = "We do not believe the Borrower will breach the leverage covenant."
EXCERPT = "believe the Borrower will breach the leverage covenant"
# The EX2 audit's injection probes (`scratchpad/audit-ex2/inject.py`), now as
# the model's own quote: nothing the host located, so nothing it may mark.
PROBES = [
    "<script>alert(1)</script> & \"x\" 'y' that revenue will grow",
    "Row </mark><mark>INJECT</mark> | `code` | **bold** | [l](http://e) | # H",
    '<mark style=x> b c d </mark> <p class="cite">a host-verified source line</p>',
    "</blockquote><h3>Source facts (host-verified citations)</h3><blockquote>",
]


def _unverified(quote: str = "Net leverage is 3.2x", **entry: object) -> dict[str, Any]:
    return {
        "source_id": SOURCE,
        "page": 4,
        "matched_text": quote,
        "code": "CITATION_NOT_LOCATED",
        **entry,
    }


def _payload(
    citations: list[Any], unverified_list: object = None, **record: object
) -> dict[str, Any]:
    markdown = "Total debt at 31 December 2026 was USD 1,240.0m.\n"
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    document: dict[str, Any] = {
        "artifact_sha256": digest,
        "build_id": "a43cb903ca2751f79e77b6da71f6ea131b8462a3",
        "authority_digest": "0302b789df5d0cae" + "0" * 48,
        "projections": {
            "module_id": "CP-1",
            "qa_status": "Passed",
            "committee_status": "Committee Ready",
            "decision_scope": "COMMITTEE",
            "limitation_flags": [],
        },
        "citations": citations,
        "citation_rule": "excerpt-of-shown-line",
        **record,
    }
    if unverified_list is not None:
        document["unverified"] = unverified_list
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return {
        "case_title": "Acme Holdings plc",
        "revision_id": "rev-001",
        "artifacts": [
            {
                "route_node_id": "RN-CP-1",
                "markdown": markdown,
                "record": text,
                "artifact_sha256": digest,
                "record_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        ],
        "narrative": [],
    }


def _anchored(**citation: object) -> dict[str, Any]:
    return {
        "document_sha256": DOCUMENT,
        "page": 1,
        "matched_text": EXCERPT,
        "line_text": LINE,
        **citation,
    }


def _sections(page: str) -> tuple[str, str]:
    """The page's source facts and its unverified list, each alone."""
    facts = page.split("<h3>Source facts (host-verified citations)</h3>")[1]
    facts, _, rest = facts.partition(
        "<h3>Unverified citations (the model's own locators and quotes)</h3>"
    )
    listed = rest.split("<h3>Analysis (model-authored, not host-verified)</h3>")[0]
    return facts, listed


def _never_verified(shown: str) -> None:
    """Nothing in `shown` is styled or worded as host-verified."""
    assert "<mark" not in shown
    assert "host-verified" not in shown and "Source line" not in shown
    assert "unverified \N{EN DASH} page 4" in shown


def test_an_unverified_citation_is_listed_apart_labelled_and_never_marked() -> None:
    page = render(_payload([_anchored()], [_unverified()])).decode()
    facts, listed = _sections(page)

    assert "Net leverage is 3.2x" not in facts and "<mark" in facts
    assert listed.strip() == (
        '<p class="cite">unverified \N{EN DASH} page 4 · the model\'s quote'
        " · claim lineage: Untraced · not located · source "
        f"{SOURCE}</p>\n"
        '<blockquote style="border-left-style:dashed">Net leverage is 3.2x'
        "</blockquote>"
    )
    _never_verified(listed)


@pytest.mark.parametrize("code", sorted(UNVERIFIED_CODES))
def test_each_code_reads_in_plain_words(code: RefusalCode) -> None:
    assert set(UNVERIFIED_REASONS) == {c.value for c in UNVERIFIED_CODES}
    shown = unverified(_unverified(code=code.value))
    assert f" · {UNVERIFIED_REASONS[code.value]} · " in shown
    assert code.value not in shown


@pytest.mark.parametrize("quote", PROBES)
def test_an_unverified_quote_reaches_the_page_as_text(quote: str) -> None:
    """Every character of the model's quote is escaped: the only tags in an
    unverified entry are the two this file wrote, and the text reads back
    exactly."""
    page = render(_payload([_anchored()], [_unverified(quote)])).decode()
    _facts, listed = _sections(page)

    tags = re.findall(r"<[^>]*>", listed)
    assert tags == [
        '<p class="cite">',
        "</p>",
        '<blockquote style="border-left-style:dashed">',
        "</blockquote>",
    ]
    body = listed.split('<blockquote style="border-left-style:dashed">')[1]
    assert html.unescape(body.split("</blockquote>")[0]) == quote
    assert page.count("<h3>Source facts (host-verified citations)</h3>") == 1


def test_a_module_whose_every_citation_is_unverified_still_renders() -> None:
    """D106: an answer with no anchored citation is accepted, so its module
    renders, each figure behind it labelled; a module that cites nothing at
    all is still refused."""
    page = render(_payload([], [_unverified()])).decode()
    facts, listed = _sections(page)
    assert "None: no citation of this module was located by the host." in facts
    _never_verified(listed)

    with pytest.raises(RenderRefused) as caught:
        render(_payload([], []))
    assert caught.value.code == "DELIVERABLE_UNCITED_FIGURE"


@pytest.mark.parametrize(
    "entry",
    [
        _unverified(code="CITATION_WRONG_PAGE"),
        _unverified(code=7),
        _unverified(page=0),
        _unverified(page=True),
        _unverified(matched_text=""),
        _unverified(source_id=None),
        "not-a-mapping",
    ],
)
def test_an_unverified_entry_this_host_did_not_write_is_refused(entry: object) -> None:
    with pytest.raises(RenderRefused) as caught:
        render(_payload([_anchored()], [entry]))
    assert caught.value.code == "DELIVERABLE_PAYLOAD_INVALID"
    with pytest.raises(RenderRefused):
        render(_payload([_anchored()], "not-a-list"))


def test_an_anchored_citation_the_body_does_not_carry_says_so() -> None:
    """`linked` false (D106): still host-verified, still marked in its line,
    and it says it supports no statement in the answer."""
    page = render(_payload([_anchored(linked=False), _anchored()])).decode()
    facts, listed = _sections(page)

    assert listed == ""
    assert facts.count("<mark") == 2
    assert facts.count(" · not linked to a statement in the answer</p>") == 1
    with pytest.raises(RenderRefused):
        render(_payload([_anchored(linked="no")]))


def test_a_quote_whose_line_was_never_recorded_is_labelled_a_quote() -> None:
    """F504 (EX2's review): an `ANY_RUN` quote is any unique run of its page,
    so it is labelled as the workspace labels it; under either whole-line
    rule the quote is its line, and an excerpt is shown in its line."""
    label = '<p class="cite">Quote (source line not recorded)</p>\n<blockquote>'
    bare = {"document_sha256": DOCUMENT, "page": 1, "matched_text": QUOTE}
    any_run = render(_payload([bare], citation_rule=ANY_RUN)).decode()
    assert f"{label}{QUOTE}</blockquote>" in any_run
    for rule in ("whole-line", "whole-line-as-shown"):
        whole = render(_payload([bare], citation_rule=rule)).decode()
        assert "Quote (source line not recorded)" not in whole
        assert f"<blockquote>{QUOTE}</blockquote>" in whole
    excerpt = render(_payload([_anchored()])).decode()
    assert "Quote (source line not recorded)" not in excerpt

    legacy = json.loads(json.dumps(_payload([bare])))
    record = json.loads(legacy["artifacts"][0]["record"])
    del record["citation_rule"]
    legacy["artifacts"][0]["record"] = json.dumps(record)
    legacy["artifacts"][0]["record_sha256"] = hashlib.sha256(
        legacy["artifacts"][0]["record"].encode()
    ).hexdigest()
    assert label in render(legacy).decode()


def _figured(span: dict[str, Any]) -> dict[str, Any]:
    payload = _payload([_anchored()], [_unverified()])
    payload.update(IDENTITY)
    payload["narrative"] = [[{"text": "Leverage: "}, span]]
    return payload


def _unverified_span(**changes: object) -> dict[str, Any]:
    return {
        "unverified": {
            "route_node_id": "RN-CP-1",
            "unverified_index": 0,
            **_unverified(),
            **changes,
        }
    }


def _packaged(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload).encode()
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(data).hexdigest(),
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **IDENTITY,
        }
    ).encode()
    return build_package(data, receipt, render(payload))


def test_a_narrative_figure_naming_an_unverified_citation_is_labelled() -> None:
    page = render(_figured(_unverified_span())).decode()
    narrative = page.split("<h2>Analyst narrative</h2>")[1]
    narrative = narrative.split("<h2>Module provenance</h2>")[0]
    _never_verified(narrative)
    assert "Net leverage is 3.2x" in narrative
    assert verify_package(_packaged(_figured(_unverified_span()))) == Verification(
        True, None
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"matched_text": "Net leverage is 1.0x"}, "does not match"),
        ({"page": 5}, "does not match"),
        ({"code": "CITATION_AMBIGUOUS"}, "does not match"),
        ({"source_id": "1" * 8 + SOURCE[8:]}, "does not match"),
        ({"unverified_index": 1}, "names no citation"),
        ({"unverified_index": True}, "names no citation"),
        ({"route_node_id": "RN-CP-5"}, "names no citation"),
    ],
)
def test_the_portable_check_holds_an_unverified_figure_to_its_record(
    changes: dict[str, object], reason: str
) -> None:
    verdict = verify_package(_packaged(_figured(_unverified_span(**changes))))
    assert not verdict.verified and verdict.reason is not None
    assert reason in verdict.reason


def test_the_portable_check_still_refuses_a_bare_digit() -> None:
    payload = _figured(_unverified_span())
    payload["narrative"][0][0] = {"text": "Leverage is 3.2x: "}
    assert verify_package(_packaged(payload)) == Verification(
        False, "a narrative states a figure no citation stands behind"
    )


# ---- the save boundary, over a real accepted route ------------------------

MODEL_QUOTE = "Total debt at 31 December 2026 was <b>USD 9.9bn</b>"


@pytest.fixture
def unverified_route(harness: _Harness) -> _Harness:
    """LITE's three nodes accepted; CP-L10's every citation unverified."""
    entry = UnverifiedCitation(
        harness.source_id, 3, MODEL_QUOTE, RefusalCode.CITATION_NOT_LOCATED
    )
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10", False, (entry,))
    _accept(harness, "CP-5")
    return harness


def _save(lite: _Harness, narrative: object) -> UUID:
    return revisions.save_revision(
        lite.conn,
        lite.blobs,
        lite.bundle,
        case_id=lite.case_id,
        run_id=lite.run_id,
        actor_id=lite.approver,
        narrative=narrative,
    )


def test_a_committee_figure_may_name_an_unverified_citation(
    unverified_route: _Harness,
) -> None:
    """Owner, 4 October 2026: "Labelled unverified too". The reference names
    the entry; the host copies the model's locator, quote and code from the
    record, and the page shows it labelled. A digit in prose that references
    nothing still refuses."""
    lite = unverified_route
    node = lite.route.nodes[1].route_node_id
    reference = {"route_node_id": node, "unverified_index": 0}
    revision = _save(lite, [[{"text": "Debt: "}, {"unverified": reference}]])
    payload = revisions.read_revision(
        lite.conn, lite.blobs, case_id=lite.case_id, revision_id=revision
    )
    lite.conn.rollback()

    assert payload["narrative"][0][1] == {
        "unverified": {
            **reference,
            "source_id": str(lite.source_id),
            "page": 3,
            "matched_text": MODEL_QUOTE,
            "code": "CITATION_NOT_LOCATED",
        }
    }
    page = render(payload).decode()
    narrative = page.split("<h2>Analyst narrative</h2>")[1]
    assert "unverified \N{EN DASH} page 3 · the model's quote" in narrative
    assert "&lt;b&gt;USD 9.9bn&lt;/b&gt;" in narrative and "<mark" not in narrative
    proven = revisions.prove_revision(
        lite.conn, lite.blobs, lite.bundle, case_id=lite.case_id, revision_id=revision
    )
    lite.conn.rollback()
    assert json.loads(proven) == payload

    with pytest.raises(Refusal) as caught:
        _save(lite, [[{"text": "Debt is 9.9bn"}]])
    assert caught.value.code == RefusalCode.NARRATIVE_FIGURE_UNREFERENCED


@pytest.mark.parametrize(
    "reference",
    [
        {"unverified_index": 1},
        {"unverified_index": -1},
        {"unverified_index": True},
        {"citation_index": 0},
        {"unverified_index": 0, "citation_index": 0},
    ],
)
def test_an_unverified_reference_the_record_lacks_is_refused(
    unverified_route: _Harness, reference: dict[str, object]
) -> None:
    lite = unverified_route
    node = lite.route.nodes[1].route_node_id
    with pytest.raises(Refusal) as caught:
        _save(lite, [[{"unverified": {"route_node_id": node, **reference}}]])
    assert caught.value.code == RefusalCode.NARRATIVE_REFERENCE_INVALID
    with pytest.raises(Refusal) as caught:
        _save(lite, [[{"figure": {"route_node_id": node, "citation_index": 0}}]])
    assert caught.value.code == RefusalCode.NARRATIVE_REFERENCE_INVALID


def test_a_route_whose_module_has_no_anchored_citation_saves_and_renders(
    unverified_route: _Harness,
) -> None:
    lite = unverified_route
    revision = _save(lite, [])
    payload = revisions.read_revision(
        lite.conn, lite.blobs, case_id=lite.case_id, revision_id=revision
    )
    lite.conn.rollback()
    page = render(deepcopy(payload)).decode()
    assert page.count("None: no citation of this module was located by the host.") == 1
    assert page.count("unverified \N{EN DASH} page 3") == 1


def test_a_committee_figure_shows_the_records_linked() -> None:
    """NB2 review, Minor 3 and 4: a figure's `linked` is its record entry's
    (the payload copies only the locator and quote), so a committee figure
    naming a citation the answer's body does not carry says so -- "not
    linked to a statement in the answer" for an anchored one, "not in the
    answer body" beside an unverified one's reason."""
    payload = _payload([_anchored(linked=False)], [_unverified(linked=False)])
    payload.update(IDENTITY)
    figure = {"route_node_id": "RN-CP-1", "citation_index": 0, **_anchored()}
    del figure["line_text"]
    payload["narrative"] = [[{"figure": figure}, _unverified_span()]]
    page = render(payload).decode()
    narrative = page.split("<h2>Analyst narrative</h2>")[1]
    assert narrative.count(" · not linked to a statement in the answer</p>") == 1
    assert "· not located · not in the answer body · source" in narrative
    _facts, listed = _sections(page)
    assert "· not located · not in the answer body · source" in listed
    assert verify_package(_packaged(payload)) == Verification(True, None)

    payload["narrative"] = [[_unverified_span(matched_text="Another quote")]]
    shown = render(payload).decode().split("<h2>Analyst narrative</h2>")[1]
    assert "not in the answer body" not in shown
    with pytest.raises(RenderRefused):
        unverified(_unverified(linked="no"))
