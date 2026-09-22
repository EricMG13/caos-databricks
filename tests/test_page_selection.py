"""Page-level evidence selection on a real run shape (§98).

The gate's `Source files to attach` cell may name pages of a pinned source
(`<filename> pages <first>-<last>`, the bundle's Step I rule 5); the consumer is
then handed those pages of it and nothing else, so a quote of another page of a
delivered source is refused `CITATION_NOT_DELIVERED` -- the refusal the Repair
Phase 3 ledger said no real run could reach. And a source larger than the gate
may be shown whole is shown to CP-0 as its page map (rule 8): the leading lines
of every page, the rest withheld and said to be withheld, never trimmed.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

import pytest
from canonical_fixtures import QUOTE, CanonicalCompletions
from conftest import _url_for, approve_run
from test_canonical_execution import _accept, _node, _refused, _run, route
from test_execution_freshness import _Harness
from test_loop_charges import VENDORED

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute
from caos.methodology import selection
from caos.methodology.canonical import check_context
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.runs import start_run

__all__ = ["route"]

PAGED = "paged.txt"


def _line(n: int) -> str:
    return f"Line {n:04d} of the paged report, set down once."


# Three fixed-pitch pages of sixty lines; the fixtures' quote opens page one.
DOCUMENT = (
    f"{QUOTE} was USD 1,240.0m\n" + "".join(f"{_line(n)}\n" for n in range(1, 180))
).encode()


@pytest.fixture
def paged(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    conn, case_id = case
    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    from caos.methodology.bundle import Bundle

    bundle = Bundle(root)
    blobs = BlobStore(tmp_path / "blobs")
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of(PAGED), data=DOCUMENT)],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    approver = approve_run(
        conn, case_id=case_id, run_id=run_id, route=route, bundle=bundle
    )
    return _Harness(
        conn,
        case_id,
        run_id,
        source_id,
        source_id,
        blobs,
        route,
        bundle,
        approver,
        _url_for(conn.info.dbname),
    )


def _gate(harness: _Harness, **knobs: object) -> CanonicalCompletions:
    completions = CanonicalCompletions(harness.source_id, **knobs)  # type: ignore[arg-type]
    attempt, result = _run(harness, "CP-0", completions)
    _accept(harness, attempt, result)
    return completions


def _evidence_pages(prompt: str) -> set[int]:
    evidence = prompt[prompt.index("\n--- EVIDENCE ") :]
    return {
        int(line.removeprefix("page: "))
        for line in evidence.splitlines()
        if line.startswith("page: ")
    }


def test_a_consumer_named_by_page_is_handed_only_those_pages(paged: _Harness) -> None:
    _gate(paged, source_files={"CP-L10": f"{PAGED} pages 2-3"})
    screen = CanonicalCompletions(
        paged.source_id, quotes=(), cited=((paged.source_id, _line(70), 2),)
    )
    attempt, result = _run(paged, "CP-L10", screen)
    [prompt] = screen.prompts
    assert _evidence_pages(prompt) == {2, 3}
    assert _line(70) in prompt and _line(10) not in prompt
    _accept(paged, attempt, result)


def test_a_quote_of_an_unnamed_page_of_a_named_source_is_not_delivered(
    paged: _Harness,
) -> None:
    """The source is delivered; the page is not. Before §98 only a test that
    deleted a block with the seal disabled could reach this refusal."""
    _gate(paged, source_files={"CP-L10": f"{PAGED} page 2"})
    screen = CanonicalCompletions(
        paged.source_id, quotes=(), cited=((paged.source_id, _line(10), 1),)
    )
    assert _refused(paged, "CP-L10", screen) is RefusalCode.CITATION_NOT_DELIVERED
    [prompt] = screen.prompts
    assert _evidence_pages(prompt) == {2}


def test_a_page_range_past_the_source_refuses_the_consumer_before_any_attempt(
    paged: _Harness,
) -> None:
    _gate(paged, source_files={"CP-L10": f"{PAGED} pages 2-4"})
    screen = CanonicalCompletions(paged.source_id)
    assert _refused(paged, "CP-L10", screen) is RefusalCode.EVIDENCE_DEMAND_UNRESOLVED
    assert screen.prompts == []


def test_a_source_past_the_gate_bound_is_shown_to_cp0_as_its_page_map(
    paged: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every page's leading lines, the rest withheld, and the preparation
    metadata saying so -- the prompt never carries a trimmed line."""
    monkeypatch.setattr(selection, "GATE_SOURCE_BYTES", 1500)
    size = check_context(
        paged.conn,
        paged.bundle,
        paged.blobs,
        run_id=paged.run_id,
        route=paged.route,
        node=_node(paged, "CP-0"),
        provider=CanonicalCompletions(paged.source_id),
    )
    paged.conn.rollback()
    assert size > 0
    completions = _gate(paged)
    [prompt] = completions.prompts
    assert _evidence_pages(prompt) == {1, 2, 3}
    assert _line(1) in prompt and _line(61) in prompt and _line(121) in prompt
    assert _line(59) not in prompt and _line(119) not in prompt
    assert '"evidence_delivery": "PAGE_MAP"' in prompt
    assert '"pages": 3' in prompt


def test_the_gate_cannot_cite_a_line_its_page_map_withheld(
    paged: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "GATE_SOURCE_BYTES", 1500)
    withheld = CanonicalCompletions(
        paged.source_id, cited=((paged.source_id, _line(59), 1),)
    )
    assert _refused(paged, "CP-0", withheld) is RefusalCode.CITATION_NOT_DELIVERED


def test_a_source_within_the_gate_bound_reaches_cp0_whole_and_says_so(
    paged: _Harness,
) -> None:
    """A whole source is labelled WHOLE, not left unlabelled: the 18 September
    2026 VMO2 portfolio run's CP-0 read rule 8 (page maps) onto two releases the
    host had delivered whole, and blocked its consumer for a fidelity it had
    never been denied."""
    completions = _gate(paged)
    [prompt] = completions.prompts
    assert _line(59) in prompt and _line(179) in prompt
    assert '"evidence_delivery": "WHOLE"' in prompt
    assert '"evidence_delivery": "PAGE_MAP"' not in prompt
