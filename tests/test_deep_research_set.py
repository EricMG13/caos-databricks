"""The VMO2 deep-research qualification set is loadable, measurable and pinned.

No run is performed here -- the set's live run is Task 9.4 step 7 and needs the
owner's authorization. What is held is everything checkable without one: the
set loads through the `on_disk` loader the harness uses, measures something and
is unambiguous; its digest is the one `RESULT.md` records; its brief is one the
pin accepts on the pinned route and subject -- judged by the vendor's own
`validate_brief` and `Route`, `supplied_only` (invariant 1); every citation key
anchors exactly once in the real extractor's token index; and the one question
keyed UNRESOLVED names a fact neither document carries.
"""

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

ROOT = Path(__file__).resolve().parents[1] / "qualification/vmo2-fy2025-deep-research"
DIGEST = "09807efb1a3d5d40680d1a9d0e054333537781d7bb4013ecd7670323f817fd9b"
Q3 = "505bf1a0f4181c9cdffeeac7e6af3253d1883788e9cd1a81e65952e008aa17a1"
Q4 = "66055bbb8d27721d07a5e8cb834c9b96a256ada45a0812ea4fb2e7202ee4f64d"


def _pages(data: bytes) -> dict[int, list[str]]:
    pages: dict[int, list[str]] = defaultdict(list)
    for token in PdfExtractor().extract(data):
        pages[token.page].append(token.text)
    return pages


def test_the_deep_research_set_is_measurable_and_carries_its_recorded_digest() -> None:
    qualification = load_qualification_set(ROOT)
    assert_measurable(qualification)
    assert_unambiguous(qualification)
    assert qualification_set_digest(qualification) == DIGEST
    assert DIGEST in (ROOT / "RESULT.md").read_text(encoding="utf-8")
    [case] = qualification.cases
    assert (case.profile_id, case.selection_id) == (
        "LITE_CREDIT_22",
        "LITE_DEEP_RESEARCH",
    )
    assert [hashlib.sha256(d.data).hexdigest() for d in case.documents] == [Q3, Q4]
    assert case.expects_ready == ("CP-DR",)


def test_the_brief_is_one_the_pin_accepts_and_is_supplied_only() -> None:
    """The brief the harness will pin, judged exactly as the pin judges it."""
    [case] = load_qualification_set(ROOT).cases
    assert case.research_brief is not None and case.subject is not None
    brief = json.loads(case.research_brief)
    assert brief["source_mode"] == "supplied_only"
    assert brief["scope_key"] == case.subject.issuer_id
    bound = bound_research_brief(
        cached_contract(BUNDLE),
        catalog(BUNDLE),
        brief=brief,
        route=resolve_route(catalog(BUNDLE), case.profile_id, case.selection_id),
        subject=case.subject,
        run_id="COS-20260918T120000Z-" + "1" * 32,
        cp0_sha256=UNANCHORED_CP0,
        authority_sha256=authority_bundle_sha256(BUNDLE),
    )
    assert [q["question_id"] for q in bound["questions"]] == [
        "RQ-impairment",
        "RQ-undrawn",
        "RQ-rating",
    ]


def test_every_citation_key_anchors_once_in_the_extracted_tokens() -> None:
    [case] = load_qualification_set(ROOT).cases
    documents = {hashlib.sha256(d.data).hexdigest(): d.data for d in case.documents}
    assert case.expects
    for expect in case.expects:
        words = expect.matched_text.split()
        found = [
            (page, start)
            for page, tokens in _pages(documents[expect.document_sha256]).items()
            for start in range(len(tokens) - len(words) + 1)
            if tokens[start : start + len(words)] == words
        ]
        assert len(found) == 1, expect.matched_text


def test_the_unresolved_question_names_a_fact_neither_document_carries() -> None:
    """RQ-rating is keyed UNRESOLVED because the pack cannot answer it: neither
    release names a rating agency or a rating. The two ANSWERED keys are the
    questions the citation keys answer."""
    [case] = load_qualification_set(ROOT).cases
    expected = {k.row_key[0][1]: k.expected for k in case.expects_register}
    assert expected == {
        "RQ-impairment": "ANSWERED",
        "RQ-undrawn": "ANSWERED",
        "RQ-rating": "UNRESOLVED",
    }
    assert {(k.module_id, k.register_id, k.column) for k in case.expects_register} == {
        ("CP-DR", "TDR.3", "resolution_status")
    }
    for document in case.documents:
        words = {
            token.casefold().strip(".,;:()")
            for tokens in _pages(document.data).values()
            for token in tokens
        }
        assert not {"moody's", "fitch", "rating", "ratings"} & words
