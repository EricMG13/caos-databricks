"""The Boeing and Ford FY2025 10-K texts run by page (§98).

Each is one source larger than a request can carry whole. Measured through the
real extractor, the real bundle and the real prompt builder on the LITE
earnings route: the gate is shown each as its page map and its whole request
fits the ceiling; a consumer handed the pages the gate named fits it too and
its answer is accepted; and the same consumer handed the document whole is
refused `CONTEXT_OVER_CEILING` before any attempt, which is the refusal these
documents met before §98. The documents are the committed sets' own bytes.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import _url_for, approve_run
from test_canonical_execution import _accept, _node, _run, route
from test_execution_freshness import _Harness
from test_loop_charges import VENDORED

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import check_context
from caos.provider import MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.runs import start_run

__all__ = ["route"]

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class TenK:
    """One committed 10-K and the facts about it this module asserts."""

    path: Path
    # The set's CP-0 key, which sits inside the gate's page map, and its page.
    gate_quote: str
    gate_page: int
    # What the gate names for the screen, and the set's CP-L10 key inside it.
    pages: str
    screen_quote: str
    screen_page: int
    # The page map, as measured: leading lines per page, and pages.
    leading: int
    page_count: int


TEN_KS = {
    "BA": TenK(
        REPO / "qualification/ba-fy2025/documents/BA_FY2025_10K.txt",
        "Cash and cash equivalents | $10,921 | | | $13,801 |",
        36,
        "pages 13-40",
        "Total revenues | 89,463 | | | 66,517 | | | 77,794 |",
        33,
        16,
        108,
    ),
    "F": TenK(
        REPO / "qualification/f-fy2025/documents/F_FY2025_10K.txt",
        "Net cash provided by/(used in) operating activities"
        " | 14,918 | | | 15,423 | | | 21,282 |",
        81,
        "pages 22-64",
        "Net cash provided by/(used in) operating activities"
        " | $ | 8,351 | | | $ | 12,931 |",
        57,
        10,
        146,
    ),
}


@pytest.fixture(params=sorted(TEN_KS))
def ten_k(request: pytest.FixtureRequest) -> TenK:
    return TEN_KS[str(request.param)]


@pytest.fixture
def filed(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    route: ResolvedRoute,
    ten_k: TenK,
) -> _Harness:
    conn, case_id = case
    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    blobs = BlobStore(tmp_path / "blobs")
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of(ten_k.path.name),
                data=ten_k.path.read_bytes(),
            )
        ],
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


def _request(harness: _Harness, module_id: str) -> int:
    try:
        return check_context(
            harness.conn,
            harness.bundle,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            node=_node(harness, module_id),
            provider=CanonicalCompletions(harness.source_id),
        )
    finally:
        harness.conn.rollback()


def _gate(harness: _Harness, ten_k: TenK, cell: str) -> CanonicalCompletions:
    completions = CanonicalCompletions(
        harness.source_id,
        quotes=(),
        cited=((harness.source_id, ten_k.gate_quote, ten_k.gate_page),),
        source_files={"CP-L10": cell, "CP-5": cell},
    )
    attempt, result = _run(harness, "CP-0", completions)
    _accept(harness, attempt, result)
    return completions


def test_a_10k_runs_by_page_the_gate_on_its_map_the_screen_on_its_pages(
    filed: _Harness, ten_k: TenK
) -> None:
    assert _request(filed, "CP-0") <= MAX_REQUEST_BYTES
    gate = _gate(filed, ten_k, f"{ten_k.path.name} {ten_k.pages}")
    [prompt] = gate.prompts
    assert '"evidence_delivery": "PAGE_MAP"' in prompt
    assert f'"leading_lines_per_page": {ten_k.leading}' in prompt
    assert f'"pages": {ten_k.page_count}' in prompt

    assert _request(filed, "CP-L10") <= MAX_REQUEST_BYTES
    screen = CanonicalCompletions(
        filed.source_id,
        quotes=(),
        cited=((filed.source_id, ten_k.screen_quote, ten_k.screen_page),),
    )
    attempt, result = _run(filed, "CP-L10", screen)
    _accept(filed, attempt, result)


def test_a_10k_named_whole_for_a_consumer_is_refused_before_any_attempt(
    filed: _Harness, ten_k: TenK
) -> None:
    """What every run of these documents met before §98, and still must."""
    _gate(filed, ten_k, ten_k.path.name)
    with pytest.raises(Refusal) as refused:
        _request(filed, "CP-L10")
    assert refused.value.code is RefusalCode.CONTEXT_OVER_CEILING
