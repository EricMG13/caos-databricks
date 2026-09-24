"""The Boeing and Ford FY2025 10-K texts run by page (§98).

Page mode is relative to the request ceiling, so it is proven here at the
legacy 1 MiB ceiling these documents exceed (`legacy_ceiling`); under the 4 MiB
ceiling D29 set, the gate is shown each whole and each fits a consumer whole,
which the last test states.

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

import caos.methodology.invocation
import caos.methodology.selection
import caos.models
import caos.pricing
import caos.provider
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import check_context
from caos.methodology.selection import GATE_SOURCE_BYTES
from caos.provider import MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.runs import start_run

__all__ = ["route"]

REPO = Path(__file__).resolve().parents[1]
# The ceiling these documents were measured against before D29.
LEGACY_CEILING = 1_048_576


@pytest.fixture
def legacy_ceiling(monkeypatch: pytest.MonkeyPatch) -> int:
    """The legacy 1 MiB ceiling, everywhere a module bound it by name."""
    for module in (
        caos.provider,
        caos.pricing,
        caos.models,
        caos.methodology.invocation,
        caos.methodology.selection,
    ):
        monkeypatch.setattr(module, "MAX_REQUEST_BYTES", LEGACY_CEILING)
    monkeypatch.setattr(
        caos.methodology.selection, "GATE_SOURCE_BYTES", 3 * LEGACY_CEILING // 8
    )
    return LEGACY_CEILING


@dataclass(frozen=True, slots=True)
class TenK:
    """One committed 10-K and the facts about it this module asserts."""

    path: Path
    # The set's CP-0 key, which sits inside the gate's page map, and its page:
    # a whole line of the 10-K, as an accepted quote is (N28).
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
        "| Cash and cash equivalents | $10,921 | | | $13,801 | |",
        36,
        "pages 13-40",
        "| Total revenues | 89,463 | | | 66,517 | | | 77,794 | |",
        33,
        16,
        108,
    ),
    "F": TenK(
        REPO / "qualification/f-fy2025/documents/F_FY2025_10K.txt",
        "| Net cash provided by/(used in) operating activities"
        " | 14,918 | | | 15,423 | | | 21,282 | |",
        81,
        "pages 22-64",
        "| Net cash provided by/(used in) operating activities"
        " | $ | 8,351 | | | $ | 12,931 | | | $ | — | | | $ | 21,282 | |",
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
    legacy_ceiling: int, filed: _Harness, ten_k: TenK
) -> None:
    assert _request(filed, "CP-0") <= legacy_ceiling
    gate = _gate(filed, ten_k, f"{ten_k.path.name} {ten_k.pages}")
    [prompt] = gate.prompts
    assert '"evidence_delivery": "PAGE_MAP"' in prompt
    assert f'"leading_lines_per_page": {ten_k.leading}' in prompt
    assert f'"pages": {ten_k.page_count}' in prompt

    assert _request(filed, "CP-L10") <= legacy_ceiling
    screen = CanonicalCompletions(
        filed.source_id,
        quotes=(),
        cited=((filed.source_id, ten_k.screen_quote, ten_k.screen_page),),
    )
    attempt, result = _run(filed, "CP-L10", screen)
    _accept(filed, attempt, result)


def test_a_10k_named_whole_for_a_consumer_is_refused_before_any_attempt(
    legacy_ceiling: int, filed: _Harness, ten_k: TenK
) -> None:
    """What every run of these documents met before §98, and still must."""
    _gate(filed, ten_k, ten_k.path.name)
    with pytest.raises(Refusal) as refused:
        _request(filed, "CP-L10")
    assert refused.value.code is RefusalCode.CONTEXT_OVER_CEILING


def test_under_the_d29_ceiling_a_10k_fits_a_consumer_whole(
    filed: _Harness, ten_k: TenK
) -> None:
    """N31's point, on the committed documents: each 10-K's text is inside the
    gate's share of the 4 MiB request, so the gate is shown it whole, and a
    consumer handed it whole fits the request instead of refusing."""
    assert GATE_SOURCE_BYTES == 3 * MAX_REQUEST_BYTES // 8
    gate = _gate(filed, ten_k, ten_k.path.name)
    [prompt] = gate.prompts
    assert '"evidence_delivery": "PAGE_MAP"' not in prompt
    assert _request(filed, "CP-L10") <= MAX_REQUEST_BYTES
