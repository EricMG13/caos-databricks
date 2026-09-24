"""Offline qualification keys for FULL_CREDIT_32 / DEEP_RESEARCH."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from canonical_fixtures import BUNDLE

from caos.evidence.pdf import PdfExtractor
from caos.graph.route import resolve_route
from caos.methodology.vendor import authority_bundle_sha256, cached_contract, catalog
from caos.qualification.matrix import (
    assert_measurable,
    assert_unambiguous,
    qualification_set_digest,
)
from caos.qualification.on_disk import load_qualification_set
from caos.store.run_inputs import UNANCHORED_CP0, bound_research_brief

ROOT = (
    Path(__file__).resolve().parents[1] / "qualification/vmo2-fy2025-full-deep-research"
)
LITE_ROOT = (
    Path(__file__).resolve().parents[1] / "qualification/vmo2-fy2025-deep-research"
)
DIGEST = "6e617e8ced5f874ecef59f30bd813f9be06de8c6a2674a2f9c461f2346964f23"
LITE_DIGEST = "1881fcf6818e623322b52679268906a624d9ad4b4026c759f74bdcf9435e9bdd"
Q3 = "505bf1a0f4181c9cdffeeac7e6af3253d1883788e9cd1a81e65952e008aa17a1"
Q4 = "66055bbb8d27721d07a5e8cb834c9b96a256ada45a0812ea4fb2e7202ee4f64d"


def _pages(data: bytes) -> dict[int, list[str]]:
    pages: dict[int, list[str]] = defaultdict(list)
    for token in PdfExtractor().extract(data):
        pages[token.page].append(token.text)
    return pages


def test_full_deep_research_set_is_measurable_and_pinned_without_moving_lite() -> None:
    assert {
        path.relative_to(ROOT).as_posix() for path in ROOT.rglob("*") if path.is_file()
    } == {
        "RESULT.md",
        "qualification.json",
        "documents/Virgin-Media-O2-Q3-2025-Earnings-Release.pdf",
        "documents/Virgin-Media-O2-Q4-2025-Earnings-Release.pdf",
    }
    qualification = load_qualification_set(ROOT)
    assert_measurable(qualification)
    assert_unambiguous(qualification)
    assert qualification_set_digest(qualification) == DIGEST
    assert DIGEST in (ROOT / "RESULT.md").read_text(encoding="utf-8")
    [case] = qualification.cases
    assert (case.profile_id, case.selection_id) == (
        "FULL_CREDIT_32",
        "DEEP_RESEARCH",
    )
    assert [hashlib.sha256(d.data).hexdigest() for d in case.documents] == [Q3, Q4]
    assert case.expects_ready == ("CP-DR",)
    assert qualification_set_digest(load_qualification_set(LITE_ROOT)) == LITE_DIGEST


def test_full_route_accepts_the_same_supplied_only_brief() -> None:
    [case] = load_qualification_set(ROOT).cases
    [lite_case] = load_qualification_set(LITE_ROOT).cases
    assert case.research_brief == lite_case.research_brief
    assert case.research_brief is not None and case.subject is not None
    brief = json.loads(case.research_brief)
    assert brief["source_mode"] == "supplied_only"
    bound = bound_research_brief(
        cached_contract(BUNDLE),
        catalog(BUNDLE),
        brief=brief,
        route=resolve_route(catalog(BUNDLE), case.profile_id, case.selection_id),
        subject=case.subject,
        run_id="COS-20260919T120000Z-" + "1" * 32,
        cp0_sha256=UNANCHORED_CP0,
        authority_sha256=authority_bundle_sha256(BUNDLE),
    )
    assert [q["question_id"] for q in bound["questions"]] == [
        "RQ-impairment",
        "RQ-undrawn",
        "RQ-rating",
    ]


def test_full_keys_are_the_document_derived_cp_dr_contract() -> None:
    [case] = load_qualification_set(ROOT).cases
    assert case.expects_projection
    assert [
        (key.module_id, key.field, key.value) for key in case.expects_projection
    ] == [("CP-DR", "decision_scope", "FULL")]
    assert case.expects
    assert [key.document_sha256 for key in case.expects] == [Q4, Q4]
    documents = {hashlib.sha256(d.data).hexdigest(): d.data for d in case.documents}
    for expect in case.expects:
        words = expect.matched_text.split()
        found = [
            (page, start)
            for page, tokens in _pages(documents[expect.document_sha256]).items()
            for start in range(len(tokens) - len(words) + 1)
            if tokens[start : start + len(words)] == words
        ]
        assert len(found) == 1, expect.matched_text


def test_full_register_keys_answer_two_questions_and_leave_rating_unresolved() -> None:
    [case] = load_qualification_set(ROOT).cases
    expected = {key.row_key[0][1]: key.expected for key in case.expects_register}
    assert expected == {
        "RQ-impairment": "ANSWERED",
        "RQ-undrawn": "ANSWERED",
        "RQ-rating": "UNRESOLVED",
    }
    assert {
        (key.module_id, key.register_id, key.column) for key in case.expects_register
    } == {("CP-DR", "TDR.3", "resolution_status")}
    for document in case.documents:
        words = {
            token.casefold().strip(".,;:()")
            for tokens in _pages(document.data).values()
            for token in tokens
        }
        assert not {"moody's", "fitch", "rating", "ratings"} & words
