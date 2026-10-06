"""CP-0's P5 page-coverage claims held to the pages delivered (D112, N156).

LCR7's CP-0 wrote "1-59 shown" for a 67-page credit agreement the host had
delivered whole, judged it cut and held CP-L10. Its stored P5 register is
replayed below verbatim, beside LCR5's and LCR6's accepted ones over the same
document, which said 1-67 and must stay accepted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from test_canonical_execution import route
from test_execution_freshness import _Harness
from test_page_selection import DOCUMENT, PAGED, _line, paged, paged_harness
from test_second_attempt import _checks, _cp0_ledger, _Flawed, _module, _run

from caos.graph.route import ResolvedRoute
from caos.methodology.coverage import (
    MAX_CLAIM_CHARS,
    MAX_P5_LINES,
    CoverageFault,
    coverage_claims,
    coverage_faults,
    coverage_message,
    heading_pages,
    last_heading,
)
from caos.methodology.handoff import MAX_FEEDBACK_CHARS
from caos.store import StoreConnection

__all__ = ["paged", "route"]

# LCR5, caos_qualify_a9aff27767824a51a4c350a687f7490a, attempt 1:
# its P5 verbatim, then the next heading.
LCR5_P5 = (
    "#### P5 \u2014 Parse Jobs\n"
    "\n"
    "| Source ID | Host extractor and profile applied | Delivery | Parse"
    " status and extraction confidence | Coverage shown in evidence |"
    " Fidelity limitations / representation status |\n"
    "|---|---|---|---|---|---|\n"
    "| 3fa72406-cde8-4339-a8fd-a28e91dede91 | caos.plain-text v4;"
    " LEGAL_CLAUSE, LAYOUT_TEXT | WHOLE | COMPLETE; 0.97 | Pages 1\u20136 | No"
    " extraction loss evidenced; signature and Schedule A material"
    " retained; host extraction is sole active content representation |\n"
    "| 3fd9e5f7-5891-4522-bc89-6bbd71022b4c | caos.plain-text v4;"
    " LEGAL_CLAUSE, LAYOUT_TEXT, TABLE_FIRST | WHOLE | COMPLETE; 0.96 |"
    " Pages 1\u201360 | Dense legal structure and tables rendered as text; no"
    " specific lost page or clause evidenced; host extraction is sole"
    " active content representation |\n"
    "| 6cbd2398-48b4-4ddb-a0db-8fdd967f1661 | caos.plain-text v4;"
    " LAYOUT_TEXT, TABLE_FIRST | WHOLE | COMPLETE; 0.98 | Pages 1\u20133 | The"
    " source is a filed summary, not the separate referenced"
    " merger-agreement exhibit; this is a source-scope gap, not a silent"
    " parse substitution |\n"
    "| 79f8739e-75fc-461b-aaad-ea9147ce1403 | caos.plain-text v4;"
    " LEGAL_CLAUSE, TABLE_FIRST | WHOLE | COMPLETE; 0.96 | Pages 1\u20133 |"
    " Consent and amendment text retained; no source-specific extraction"
    " loss evidenced; host extraction is sole active content"
    " representation |\n"
    "| 9c97734a-0ace-4ab4-b542-0e1f2edf0e8e | caos.plain-text v4;"
    " LEGAL_CLAUSE, LAYOUT_TEXT | WHOLE | COMPLETE; 0.97 | Pages 1\u20133 |"
    " Amendment clauses and guarantee/signature material retained; no"
    " source-specific extraction loss evidenced; host extraction is sole"
    " active content representation |\n"
    "| a4d7755f-f66a-4ef2-b8e4-00c02f22b636 | caos.plain-text v4; HYBRID,"
    " LEGAL_CLAUSE, TABLE_FIRST | WHOLE | COMPLETE; 0.94 | Pages 1\u201367 |"
    " Long conformed legal text and schedules are text-rendered; this"
    " source version ends at IA No. 3 and is not the later consolidated"
    " agreement; later amendments remain separate active sources [C23] |\n"
    "| adc25552-f966-4cfc-8774-37567881d601 | caos.plain-text v4; HYBRID,"
    " TABLE_FIRST, LAYOUT_TEXT | WHOLE | COMPLETE; 0.97 | Pages 1\u201326 |"
    " Financial and segment tables are text-rendered; figures remain tied"
    " to source rows and periods; merger agreement exhibit is referenced"
    " but is not part of the delivered source |\n"
    "| fafe69ba-7739-4c60-9bac-371d6d745d86 | caos.plain-text v4;"
    " LEGAL_CLAUSE, TABLE_FIRST | WHOLE | COMPLETE; 0.96 | Pages 1\u20132 |"
    " Amendment and consent material retained; no source-specific"
    " extraction loss evidenced; host extraction is sole active content"
    " representation |\n"
    "\n"
    "#### T1 \u2014 Input Gate\n"
)
LCR5_PAGES = {
    UUID("3fa72406-cde8-4339-a8fd-a28e91dede91"): 6,
    UUID("3fd9e5f7-5891-4522-bc89-6bbd71022b4c"): 60,
    UUID("6cbd2398-48b4-4ddb-a0db-8fdd967f1661"): 3,
    UUID("79f8739e-75fc-461b-aaad-ea9147ce1403"): 3,
    UUID("9c97734a-0ace-4ab4-b542-0e1f2edf0e8e"): 3,
    UUID("a4d7755f-f66a-4ef2-b8e4-00c02f22b636"): 67,
    UUID("adc25552-f966-4cfc-8774-37567881d601"): 26,
    UUID("fafe69ba-7739-4c60-9bac-371d6d745d86"): 2,
}
# LCR6, caos_qualify_f463e399120b4efeaf8997d6d77cb72b, attempt 1:
# its P5 verbatim, then the next heading.
LCR6_P5 = (
    "#### P5 \u2014 Parse Jobs\n"
    "\n"
    "| Source ID | Extractor and delivery | Parse status; extraction"
    " confidence | Coverage and applicable extraction profile | Fidelity"
    " limitations evidenced in the delivered representation |\n"
    "|---|---|---|---|---|\n"
    "| 091f0617-b76e-4ed8-a9ab-0a328842f37d | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High | Whole delivery; page anchors 1\u20136 shown;"
    " LEGAL_CLAUSE / HYBRID | Legal wording and page anchors are present"
    " in delivered text. No source-specific lost clause or unreadable page"
    " is evidenced. |\n"
    "| 1e2db82b-68a8-4f20-8c47-ba9af15b49fa | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High | Whole delivery; page anchors 1\u201367 shown;"
    " LEGAL_CLAUSE / HYBRID | Legal wording, clause references and page"
    " anchors are present in delivered text. Tables and schedules are"
    " represented as text rows; no source-specific lost clause is"
    " evidenced. |\n"
    "| 60e2cda0-5311-4bd3-a75c-460153eefeba | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High for delivered text and tables | Whole delivery;"
    " page anchors 1\u201326 shown; TABLE_FIRST / LAYOUT_TEXT / HYBRID |"
    " Financial tables are rendered as text rows. The filing refers to a"
    " geographic map, but the delivered evidence provides no map values;"
    " no map detail is used as evidence. No other source-specific loss is"
    " evidenced. |\n"
    "| 7560cd4d-3310-4ea7-81fb-d423be409f98 | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High | Whole delivery; page anchors 1\u20133 shown;"
    " LEGAL_CLAUSE / HYBRID | Amendment clauses and page anchors are"
    " present. Consent-form checkboxes are retained as text; no signed"
    " lender consent outcomes are evidenced in the delivered"
    " representation. |\n"
    "| 8f11b4b3-1eb2-4d4d-a60f-9cc22a01e101 | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High | Whole delivery; page anchors 1\u20132 shown;"
    " LEGAL_CLAUSE / HYBRID | Amendment clauses and page anchors are"
    " present. Consent-form checkboxes are retained as text; no signed"
    " lender consent outcomes are evidenced in the delivered"
    " representation. |\n"
    "| bede8aaf-075d-485a-ab6e-6f1703ebcb35 | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High for delivered filing text | Whole delivery; page"
    " anchors 1\u20133 shown; LAYOUT_TEXT / HYBRID | The delivered source is"
    " the filed 8-K disclosure, not the full merger agreement it"
    " references. This is a source-scope gap, not an inferred parse of the"
    " omitted agreement. [C14] |\n"
    "| d09ff06f-5c9e-48ad-bf96-99fe77b400eb | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; High | Whole delivery; page anchors 1\u20133 shown;"
    " LEGAL_CLAUSE / HYBRID | Clauses, signature material and page anchors"
    " are present. No source-specific lost clause is evidenced. |\n"
    "| e2164408-0138-410c-aeb5-7a81986e73c4 | `caos.plain-text` v4; WHOLE"
    " | COMPLETE; Medium-High | Whole delivery; page anchors 1\u201367 shown;"
    " LEGAL_CLAUSE / TABLE_FIRST / HYBRID | Conformed credit-agreement"
    " tables and schedules are represented as text. The conformed"
    " agreement ends at the source\u2019s supplied version lineage; it does not"
    " incorporate the later Fifth Amendment. No source-specific lost"
    " clause is otherwise evidenced. [C7, C12] |\n"
    "\n"
    "**Preparation checks:** PASS \u2014 P3 and P5 each cover all eight"
    " host-record sources exactly once. PASS \u2014 source identity and version"
    " relationships are separated from representation quality. PASS \u2014 page"
    " locators shown in delivered evidence are preserved; hashes, packages"
    " and active-representation selection remain in the host preparation"
    " record. NA \u2014 duplicate replacement and amendment-collapse handling:"
    " no duplicate candidates were identified. PASS \u2014 canonical Markdown"
    " structure checked in this draft; host validation follows the answer.\n"
    "\n"
    "#### T1 \u2014 Input Gate\n"
)
LCR6_PAGES = {
    UUID("091f0617-b76e-4ed8-a9ab-0a328842f37d"): 6,
    UUID("1e2db82b-68a8-4f20-8c47-ba9af15b49fa"): 60,
    UUID("60e2cda0-5311-4bd3-a75c-460153eefeba"): 26,
    UUID("7560cd4d-3310-4ea7-81fb-d423be409f98"): 3,
    UUID("8f11b4b3-1eb2-4d4d-a60f-9cc22a01e101"): 2,
    UUID("bede8aaf-075d-485a-ab6e-6f1703ebcb35"): 3,
    UUID("d09ff06f-5c9e-48ad-bf96-99fe77b400eb"): 3,
    UUID("e2164408-0138-410c-aeb5-7a81986e73c4"): 67,
}
# LCR7, caos_qualify_052f7dece5014eefa3f81838e098c553, attempt 2:
# its P5 verbatim, then the next heading.
LCR7_P5 = (
    "#### P5 \u2014 Parse Jobs\n"
    "\n"
    "| Source ID | Extractor | Delivery and parse profile | Status |"
    " Extraction confidence | Pages covered by delivered evidence |"
    " Fidelity limitations and downstream effect |\n"
    "|---|---|---|---|---|---|---|\n"
    "| 240858df-ba57-4db4-b3d3-db8c86394645 | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / LAYOUT_TEXT | COMPLETE | High | 1\u20133 | Operative text,"
    " parties and page locators are represented in the delivered lines; no"
    " specific flattened table, figure or omitted clause is identified."
    " Available for CP-L10 subject to the missing current Credit"
    " Agreement. [C18] |\n"
    "| 24d9c9e2-72f5-4b09-8866-d72bfaf29de8 | caos.plain-text v4 | WHOLE;"
    " HYBRID / LAYOUT_TEXT | COMPLETE | High | 1\u20133 | The filing summary is"
    " available; the incorporated full merger agreement, schedules and"
    " referenced financing commitment letters are not separate delivered"
    " representations. Do not substitute the summary for them. [C10, C11,"
    " C12] |\n"
    "| 624cf5d0-5d69-42b9-a8d4-1dc73b4c0925 | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / TABLE_FIRST | COMPLETE | High | 1\u20136 |"
    " Supplemental-indenture provisions and Schedule A are represented"
    " with page locators; no specific lost table or clause is identified."
    " [C19] |\n"
    "| 78afa7bc-e6b8-493c-94ed-b85ac8f8a946 | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / HYBRID | COMPLETE | High | 1\u20132 | Amendment provisions"
    " and identified pricing terms are represented; no specific lost"
    " clause is identified. [C16] |\n"
    "| c27bddbf-7ca1-4a83-82ec-dc47f5b2ff49 | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / HYBRID | BLOCKED | Low | 1\u201359 shown | The contents"
    " list Credit Agreement provisions through Sections 9.27, while the"
    " delivered Credit Agreement text ends at the Section 8.16 heading."
    " The remaining representation is not available as usable readiness"
    " content. Do not fall back to the original or treat the missing"
    " sections as reviewed. [C13, C14, C15] |\n"
    "| da3fdc2f-605a-4948-a40a-857d06366a3e | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / HYBRID | COMPLETE | High | 1\u201367 | Indenture text,"
    " exhibits and schedule material are represented in the delivered"
    " pages; the two later supplemental indentures remain separate"
    " sources. [C18, C19] |\n"
    "| e865e6e4-6652-486b-956f-7581a8431bb4 | caos.plain-text v4 | WHOLE;"
    " HYBRID / TABLE_FIRST | COMPLETE | High | 1\u201326 | Financial"
    " statements, debt tables, notes and narrative are represented with"
    " page locators. The filing itself refers to the absent 2025 Form"
    " 10-K; that is a source-set gap, not a reason to treat the 10-Q"
    " extraction as blocked. [C3, C20] |\n"
    "| edfd6bf0-3b9d-478e-bad6-e991fab50cd1 | caos.plain-text v4 | WHOLE;"
    " LEGAL_CLAUSE / HYBRID | COMPLETE | High | 1\u20133 | Amendment text and"
    " signature material are represented; no specific lost clause is"
    " identified. [C17] |\n"
    "\n"
    "#### T1 \u2014 Input Gate\n"
)
LCR7_PAGES = {
    UUID("240858df-ba57-4db4-b3d3-db8c86394645"): 3,
    UUID("24d9c9e2-72f5-4b09-8866-d72bfaf29de8"): 3,
    UUID("624cf5d0-5d69-42b9-a8d4-1dc73b4c0925"): 6,
    UUID("78afa7bc-e6b8-493c-94ed-b85ac8f8a946"): 2,
    UUID("c27bddbf-7ca1-4a83-82ec-dc47f5b2ff49"): 67,
    UUID("da3fdc2f-605a-4948-a40a-857d06366a3e"): 60,
    UUID("e865e6e4-6652-486b-956f-7581a8431bb4"): 26,
    UUID("edfd6bf0-3b9d-478e-bad6-e991fab50cd1"): 3,
}

C27 = UUID("c27bddbf-7ca1-4a83-82ec-dc47f5b2ff49")
# The pages past 59 of `c27bddbf` holding a numbered heading in LCR7's run db
# (`source_blocks`): SECTION 8.07 to 8.15 on page 60, ARTICLE IX and 8.16 to
# 9.04 on 61, ... 9.23 to 9.27 on 66; page 67 is Exhibit B.
LCR7_HEADED = {C27: frozenset(range(60, 67))}


def _every_page(pages: dict[UUID, int]) -> dict[UUID, frozenset[int]]:
    """Every page headed: the strictest reading of the claims alone."""
    return {s: frozenset(range(1, n + 1)) for s, n in pages.items()}


def test_lcr7s_stored_answer_is_held_to_the_credit_agreements_67_pages() -> None:
    """The replay: one fault, the conformed credit agreement, 59 of 67. The
    2032 indenture's "1-67" for its 60 pages is an over-claim, no fault."""
    assert coverage_faults(LCR7_P5, LCR7_PAGES, LCR7_HEADED) == [
        CoverageFault(C27, 59, 67)
    ]
    assert coverage_faults(LCR7_P5, LCR7_PAGES, _every_page(LCR7_PAGES)) == [
        CoverageFault(C27, 59, 67)
    ]
    assert (UUID("da3fdc2f-605a-4948-a40a-857d06366a3e"), 67) in coverage_claims(
        LCR7_P5
    )


def test_lcr5s_and_lcr6s_accepted_answers_raise_no_fault() -> None:
    """Every row of both is read (8 claims each), and none falls short, even
    with every page headed."""
    for p5, pages in ((LCR5_P5, LCR5_PAGES), (LCR6_P5, LCR6_PAGES)):
        assert len(coverage_claims(p5)) == len(pages) == 8
        assert coverage_faults(p5, pages, _every_page(pages)) == []


def _p5(*cells: str, source: UUID = C27) -> str:
    row = " | ".join((str(source), *cells))
    return f"#### P5 \u2014 Parse Jobs\n\n| Source ID | Pages |\n|---|---|\n| {row} |\n"


def test_only_unclaimed_pages_holding_a_heading_make_a_fault() -> None:
    """Fix round 1: LRV1 claimed 1-58 of 59, and page 59 holds lender
    signatures, no heading: not worth a whole CP-0 retry. C6 claimed 1-34 of
    67, leaving Sections 2.04 to 9.27 out: a fault."""
    lrv1 = _p5("Evidence pages 1\u201358")
    assert coverage_faults(lrv1, {C27: 59}, {C27: frozenset(range(1, 59))}) == []
    assert coverage_faults(lrv1, {C27: 59}, {C27: frozenset({59})}) == [
        CoverageFault(C27, 58, 59)
    ]
    c6 = _p5("Evidence pages 1\u201334")
    assert coverage_faults(c6, {C27: 67}, {C27: frozenset({3, 35, 66})}) == [
        CoverageFault(C27, 34, 67)
    ]
    assert coverage_faults(c6, {C27: 67}, {}) == []


def test_a_claim_the_parser_cannot_read_is_not_a_fault() -> None:
    pages = {C27: 67}
    for cell in (
        "most pages",
        "pages 2\u201359",
        "1\u201359 and 61\u201367",
        "1\u201359 shown, the rest withheld",
        "p. 59",
        "1\u2013" + "9" * 6,
        "Pages " + " " * MAX_CLAIM_CHARS + "1\u201359",
    ):
        assert coverage_faults(_p5(cell), pages, _every_page(pages)) == [], cell


def test_each_claim_form_the_live_answers_wrote_is_read() -> None:
    for cell, claimed in (
        ("1\u201359 shown", 59),
        ("Pages 1\u201359", 59),
        ("Whole delivery; page anchors 1-59 shown; LEGAL_CLAUSE", 59),
        ("Evidence pages 1\u201434. Schedules are flattened. [C24]", 34),
        ("WHOLE; pages 1 - 57", 57),
    ):
        assert coverage_claims(_p5(cell)) == [(C27, claimed)], cell


def test_only_a_wholly_delivered_source_short_of_its_last_page_is_a_fault() -> None:
    other = uuid4()
    second = _p5("1\u20133", source=other).split("|---|---|\n")[1]
    claims = _p5("1\u201359 shown") + second
    # Its last page, an over-claim, and a source the caller did not pass as
    # whole (a page-mapped one): no fault.
    headed = _every_page({C27: 67, other: 4})
    assert coverage_faults(claims, {C27: 59, other: 4}, headed) == [
        CoverageFault(other, 3, 4)
    ]
    assert coverage_faults(claims, {C27: 58}, headed) == []
    assert coverage_faults(claims, {}, headed) == []


def test_only_the_p5_register_is_read_and_only_so_far() -> None:
    """A row of P3 or T1 naming pages is not a P5 claim, nor a row past the
    next heading or past `MAX_P5_LINES`."""
    row = f"| {C27} | 1\u201359 |\n"
    p3 = f"#### P3 \u2014 Inventory\n\n{row}\n"
    after = f"{_p5('1\u201367')}\n#### T1 \u2014 Input Gate\n\n{row}"
    assert coverage_faults(p3 + after, {C27: 67}, _every_page({C27: 67})) == []
    padded = "#### P5\n" + "| x | y |\n" * MAX_P5_LINES + row
    assert coverage_claims(padded) == []
    assert coverage_claims(padded.replace("| x | y |\n", "", 1)) == [(C27, 59)]
    # A first cell that is not a source id names no source.
    assert coverage_claims("#### P5\n\n| SRC-05 | 1\u201359 |\n") == []
    assert coverage_claims(f"#### P5\n\n| `{C27}` | 1\u201359 [C3] |\n") == [(C27, 59)]


HEADINGS = [
    (61, "SECTION 8.16. Judgment Currency."),
    (66, "SECTION 9.27. Acknowledgement Regarding Any Supported QFCs."),
    (66, "Section 2.01 hereof shall apply."),
    (66, "Annex A Pricing Grid"),
    (67, "Exhibit B - 2"),
]


def test_the_last_heading_is_the_last_numbered_section_delivered() -> None:
    assert last_heading(HEADINGS) == (
        66,
        "SECTION 9.27. Acknowledgement Regarding Any Supported QFCs.",
    )
    assert last_heading([(1, "ARTICLE IX"), (2, "Item 7. MD&A")]) == (2, "Item 7. MD&A")
    assert last_heading([(1, "Line 0001 of the paged report")]) is None
    assert last_heading([(1, "SECTION 1. " + "x" * 200)]) is None


def test_heading_pages_are_the_pages_last_heading_reads_a_heading_on() -> None:
    assert heading_pages(HEADINGS) == frozenset({61, 66})
    assert heading_pages([(59, "Lender signature block"), (59, "By:")]) == frozenset()


def test_the_message_names_the_source_the_pages_and_the_last_heading() -> None:
    fault = CoverageFault(C27, 59, 67)
    name = "CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt"
    told = coverage_message(fault, name, (66, "SECTION 9.27. Acknowledgement."))
    assert told == (
        f"P5 gives source {C27} ({name}) pages 1-59, but the host delivered it"
        " WHOLE, pages 1-67; its last heading line delivered, on page 66, is"
        ' "SECTION 9.27. Acknowledgement."; correct its P5 row and every'
        " finding, gap and T8 status drawn from the shorter extent"
    )
    assert "last heading" not in coverage_message(fault, name, None)


def test_a_message_past_the_cut_drops_the_heading_then_the_name() -> None:
    """Fix round 1: `_bounded` cuts at `MAX_FEEDBACK_CHARS`, so a long name
    and a 160-character heading would cut the closing instruction."""
    fault = CoverageFault(C27, 59, 67)
    heading = (66, "SECTION 9.27. " + "A" * 146)
    end = "drawn from the shorter extent"
    long_name = "n" * 200 + ".txt"
    told = coverage_message(fault, long_name, heading)
    assert len(told) <= MAX_FEEDBACK_CHARS and told.endswith(end)
    assert long_name in told and "last heading" not in told
    # The same pair within the cut keeps both.
    short = coverage_message(fault, "a.txt", heading)
    assert heading[1] in short and short.endswith(end)
    huge = "n" * 600 + ".txt"
    told = coverage_message(fault, huge, heading)
    assert len(told) <= MAX_FEEDBACK_CHARS and told.endswith(end)
    assert huge not in told and str(C27) in told


def _short_of(source: UUID, claim: str) -> Callable[[str], str]:
    """A flaw replacing the answer's P5 table with one row for `source`."""

    def flaw(body: str) -> str:
        wire = json.loads(body)
        markdown, found = re.subn(
            r"(#### P5\n\n)(?:\|.*\n)+",
            rf"\g<1>| Source ID | Delivery | Pages |\n|---|---|---|\n"
            rf"| {source} | WHOLE | {claim} |\n",
            wire["canonical_markdown"],
            count=1,
        )
        assert found == 1
        wire["canonical_markdown"] = markdown
        return json.dumps(wire)

    return flaw


# The paged report with a numbered heading on page 3, in place of line 150.
HEADING = "SECTION 3.01. Final Provisions."
SECTIONED = DOCUMENT.replace(f"{_line(150)}\n".encode(), f"{HEADING}\n".encode())


@pytest.fixture
def sectioned(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    return paged_harness(case, tmp_path, route, SECTIONED)


def test_a_short_coverage_claim_refuses_the_gate_and_its_retry_is_told(
    sectioned: _Harness,
) -> None:
    """D112: the gate answer giving its whole three-page source pages 1-2 is
    refused `HANDOFF_MALFORMED` at acceptance; the guided retry is told the
    source, the pages delivered and the heading on page 3, and the corrected
    answer is accepted and the route completes."""
    assert SECTIONED.count(b"\n") == 180 and HEADING.encode() in SECTIONED
    answers = CanonicalCompletions(sectioned.source_id)
    assert (
        _run(
            sectioned,
            _Flawed(answers, flaw=_short_of(sectioned.source_id, "1\u20132 shown")),
        )
        is None
    )
    assert [_module(prompt) for prompt in answers.prompts] == [
        "CP-0",
        "CP-0",
        "CP-L10",
        "CP-5",
    ]
    line = (
        f"host coverage check: P5 gives source {sectioned.source_id} ({PAGED})"
        " pages 1-2, but the host delivered it WHOLE, pages 1-3; its last"
        f' heading line delivered, on page 3, is "{HEADING}"; correct its P5'
        " row and every finding, gap and T8 status drawn from the shorter"
        " extent"
    )
    assert line not in answers.prompts[0]
    assert line in _checks(answers.prompts[1])
    assert _cp0_ledger(sectioned) == (2, 2, ["HANDOFF_MALFORMED"], 1)


def test_a_full_coverage_claim_is_accepted_first_time(sectioned: _Harness) -> None:
    answers = CanonicalCompletions(sectioned.source_id)
    flawed = _Flawed(answers, flaw=_short_of(sectioned.source_id, "Pages 1\u20133"))
    assert _run(sectioned, flawed) is None
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-L10", "CP-5"]
    assert _cp0_ledger(sectioned) == (1, 1, [], 1)


def test_a_short_claim_leaving_out_no_heading_is_accepted(paged: _Harness) -> None:
    """Fix round 1, end to end: the paged report has no heading line, so its
    page 3 left out of "1-2 shown" costs no retry."""
    assert last_heading((1, line) for line in DOCUMENT.decode().splitlines()) is None
    answers = CanonicalCompletions(paged.source_id)
    flawed = _Flawed(answers, flaw=_short_of(paged.source_id, "1\u20132 shown"))
    assert _run(paged, flawed) is None
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-L10", "CP-5"]
    assert _cp0_ledger(paged) == (1, 1, [], 1)
