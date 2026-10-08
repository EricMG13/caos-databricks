"""A node's request is bounded by its model's context (D116, N157).

FCA3-dec's CP-0 sent 4,033,648 request bytes to `openai/gpt-6-luna`, inside
the 4 MiB transport ceiling, and the provider refused it with a 400 after two
seconds: the pack was past the model's 1,050,000-token context. The bound is
now the model's declared context less the completion it may return, at
`BYTES_PER_TOKEN_FLOOR` bytes a token; a pack past it shows its largest
sources as declared page maps, and one that cannot fit is refused before any
attempt or reservation.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import SUITE_ENDPOINT, approve_run
from full_assessment_route_fixtures import ROUTE as FULL_ROUTE
from test_canonical_execution import route
from test_canonical_runtime import _answers, _module_provider, _run_route
from test_execution_freshness import _counts, _Harness, _still_running, harness
from test_loop_charges import VENDORED

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.methodology import canonical
from caos.methodology.bundle import Bundle, delivered_authority
from caos.methodology.canonical import RETRY_RESERVE_BYTES, check_context
from caos.methodology.executor import Assignment, Delivery
from caos.methodology.invocation import evidence_sizes, prospective_identity
from caos.methodology.selection import GATE_SOURCE_BYTES, gate_view, pack_view
from caos.provider import (
    BYTES_PER_TOKEN_FLOOR,
    CONTEXT_TOKENS,
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    request_ceiling,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.runs import start_run

__all__ = ["harness", "route"]

REPO = Path(__file__).resolve().parents[1]
FCA = REPO / "qualification/czr-2026q2-full-credit-assessment"
LUNA = "openai/gpt-6-luna"
# The FCA3-dec request the provider refused, rebuilt offline to the byte.
FCA3_REQUEST = 4_033_648


# --- the bound --------------------------------------------------------------


def test_the_bound_is_the_declared_context_at_three_bytes_a_token() -> None:
    """Pinned and declared (D116): the two contexts, the floor, and the bound
    they give; the transport ceiling still caps any wider model."""
    assert BYTES_PER_TOKEN_FLOOR == 3
    assert CONTEXT_TOKENS == {
        "openai/gpt-6-luna": 1_050_000,
        "databricks-claude-opus-5": 1_000_000,
    }
    assert request_ceiling(LUNA) == (1_050_000 - MAX_COMPLETION_TOKENS) * 3
    assert request_ceiling(LUNA) == 2_953_392 < FCA3_REQUEST
    assert request_ceiling("databricks-claude-opus-5") == 2_803_392
    assert request_ceiling(SUITE_ENDPOINT) == MAX_REQUEST_BYTES


@pytest.mark.parametrize("tokens", [None, MAX_COMPLETION_TOKENS, 0])
def test_an_endpoint_without_a_declared_context_is_refused(
    declare_context: Callable[[str, int | None], None], tokens: int | None
) -> None:
    """Fail closed: no declared context, or one no wider than the completion
    it must leave room for, is no bound, and no request is sized against it."""
    declare_context("some/endpoint", tokens)
    with pytest.raises(Refusal) as refused:
        request_ceiling("some/endpoint")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


# --- the fit, pure ------------------------------------------------------------


def _paged(source_id: UUID, pages: int, lines: int, width: int) -> list[Delivery]:
    return [
        Delivery(
            source_id,
            f"b{n:06d}",
            n // lines + 1,
            BoundaryText.of(f"{n:06d} " + "x" * (width - 7)),
        )
        for n in range(pages * lines)
    ]


def _section(view: list[Delivery]) -> int:
    return sum(evidence_sizes(view))


def test_a_pack_within_the_limit_is_measured_once_and_shown_unchanged() -> None:
    pin = _paged(uuid4(), 3, 10, 40) + _paged(uuid4(), 2, 5, 40)
    measured: list[int] = []

    def measure(view: list[Delivery], maps: dict[UUID, dict[str, int]]) -> int:
        measured.append(len(view))
        return _section(view)

    assert pack_view(pin, measure, _section(pin)) == (pin, {})
    assert measured == [len(pin)]


def test_the_largest_source_is_shown_as_its_page_map_first() -> None:
    """Only the source past the one share bound is mapped, by its leading
    lines a page, every page kept; the smaller sources stay whole."""
    big, middle, small = uuid4(), uuid4(), uuid4()
    pin = _paged(big, 4, 30, 60) + _paged(middle, 4, 10, 60) + _paged(small, 1, 5, 60)
    whole = _section(pin)
    limit = whole - _section(_paged(big, 4, 30, 60)) // 2

    shown, maps = pack_view(pin, lambda view, _maps: _section(view), limit)

    assert set(maps) == {big}
    assert maps[big]["pages"] == 4 and maps[big]["lines"] == 120
    assert 1 <= maps[big]["leading_lines_per_page"] < 30
    assert maps[big]["lines_shown"] == 4 * maps[big]["leading_lines_per_page"]
    assert [d for d in shown if d.source_id != big] == [
        d for d in pin if d.source_id != big
    ]
    assert {d.page for d in shown if d.source_id == big} == {1, 2, 3, 4}
    assert _section(shown) <= limit


def test_the_next_largest_is_mapped_once_the_largest_cannot_free_enough() -> None:
    big, middle, small = uuid4(), uuid4(), uuid4()
    pin = _paged(big, 4, 30, 60) + _paged(middle, 4, 20, 60) + _paged(small, 1, 5, 60)
    limit = _section(_paged(middle, 4, 20, 60)) // 2

    shown, maps = pack_view(pin, lambda view, _maps: _section(view), limit)

    assert set(maps) == {big, middle}
    assert maps[big]["leading_lines_per_page"] <= maps[middle]["leading_lines_per_page"]
    assert all(d in shown for d in pin if d.source_id == small)
    assert _section(shown) <= limit


def test_what_the_view_adds_is_measured_again_until_it_fits() -> None:
    """A map's own declaration costs bytes too: the view is measured again
    and cut further, never sent past the limit."""
    big = uuid4()
    pin = _paged(big, 5, 20, 50)
    limit = _section(pin) // 2
    sizes: list[int] = []

    def measure(view: list[Delivery], maps: dict[UUID, dict[str, int]]) -> int:
        size = _section(view) + (300 if maps else 0)
        sizes.append(size)
        return size

    shown, maps = pack_view(pin, measure, limit)
    assert len(sizes) >= 2 and sizes[-1] <= limit < sizes[0]
    assert measure(shown, maps) <= limit


def test_a_pack_that_cannot_fit_at_one_line_a_page_is_refused() -> None:
    """Nothing is cut past the map: when every source is down to one line a
    page and the request is still over, the node refuses."""
    pin = _paged(uuid4(), 3, 10, 40) + _paged(uuid4(), 3, 10, 40)
    views: list[int] = []

    def measure(view: list[Delivery], maps: dict[UUID, dict[str, int]]) -> int:
        views.append(len(view))
        return 10_000 + _section(view)

    with pytest.raises(Refusal) as refused:
        pack_view(pin, measure, 9_999)
    assert refused.value.code is RefusalCode.CONTEXT_OVER_CEILING
    assert refused.value.__context__ is None and refused.value.__cause__ is None
    assert views[-1] == 6  # one line a page of each source, then refused


def test_the_gate_starts_from_its_per_source_bound() -> None:
    """Within the limit, the gate's view is exactly `gate_view` (§98)."""
    pin = _paged(uuid4(), 5, 6, 60) + _paged(uuid4(), 1, 3, 60)
    expected = gate_view(pin, budget=1_500)
    assert pack_view(pin, lambda *_: 0, 1, source_bound=1_500) == expected
    assert expected[1]


# --- through the host's builders ---------------------------------------------


@pytest.fixture
def fca(case: tuple[StoreConnection, UUID], tmp_path: Path) -> _Harness:
    """FCA's committed CP-0 pack, admitted and pinned on its FULL route."""
    conn, case_id = case
    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    blobs = BlobStore(tmp_path / "blobs")
    [listed] = json.loads((FCA / "qualification.json").read_text())["cases"]
    documents = [
        Document(filename=BoundaryText.of(Path(n).name), data=(FCA / n).read_bytes())
        for n in listed["documents"]
    ]
    admit_pack(conn, blobs, case_id=case_id, documents=documents)
    run_id = start_run(conn, case_id)
    conn.commit()
    approver = approve_run(
        conn, case_id=case_id, run_id=run_id, route=FULL_ROUTE, bundle=bundle
    )
    nil = UUID(int=0)
    return _Harness(
        conn, case_id, run_id, nil, nil, blobs, FULL_ROUTE, bundle, approver, ""
    )


def _gate(harness: _Harness, model: str | None) -> canonical._Context:
    node = harness.route.nodes[0]
    assignment = Assignment(
        node.module_id, harness.run_id, node, harness.route, UUID(int=0), model=model
    )
    identity = prospective_identity(
        harness.conn,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        node=node,
    )
    try:
        return canonical._context(
            harness.conn, harness.blobs, harness.bundle, assignment, identity
        )
    finally:
        harness.conn.rollback()


def _request(harness: _Harness, model: str) -> int:
    node = harness.route.nodes[0]
    try:
        return check_context(
            harness.conn,
            harness.bundle,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            node=node,
            provider=CanonicalCompletions(UUID(int=0), model=model),
        )
    finally:
        harness.conn.rollback()


def test_fcas_cp0_pack_now_fits_luna_by_mapping_its_largest_sources(
    fca: _Harness,
) -> None:
    """N157 on the committed FCA set: the request the transport ceiling let
    through, past Luna's context, now fits it with the largest sources shown
    as declared page maps, and every page of every source still shown."""
    assert fca.route.nodes[0].module_id == "CP-0"
    whole = _request(fca, SUITE_ENDPOINT)
    assert request_ceiling(LUNA) < whole <= MAX_REQUEST_BYTES

    fitted = _request(fca, LUNA)
    assert fitted <= request_ceiling(LUNA) - RETRY_RESERVE_BYTES

    unfitted, context = _gate(fca, None), _gate(fca, LUNA)
    assert unfitted.selection.page_maps == {}
    maps = context.selection.page_maps
    shares: dict[UUID, int] = {}
    for item, size in zip(
        unfitted.delivered, evidence_sizes(unfitted.delivered), strict=True
    ):
        shares[item.source_id] = shares.get(item.source_id, 0) + size
    largest = sorted(shares, key=shares.__getitem__, reverse=True)
    assert set(maps) == set(largest[: len(maps)]) and largest[0] in maps
    assert max(shares.values()) < GATE_SOURCE_BYTES  # the per-source bound never fired
    pages = {(d.source_id, d.page) for d in unfitted.delivered}
    assert {(d.source_id, d.page) for d in context.delivered} == pages
    assert context.delivered == [
        d for d in unfitted.delivered if d in context.delivered
    ]

    node = fca.route.nodes[0]
    prompt = canonical._prompt(
        fca.bundle,
        Assignment("CP-0", fca.run_id, node, fca.route, UUID(int=0), model=LUNA),
        prospective_identity(
            fca.conn, fca.bundle, run_id=fca.run_id, route=fca.route, node=node
        ),
        context,
        delivered_authority(fca.bundle, "CP-0"),
    )
    fca.conn.rollback()
    assert prompt.count('"evidence_delivery": "PAGE_MAP"') == len(maps)
    assert "Step I rules 5 and 8 say how to attach it by page" in prompt


def test_a_small_pack_is_handed_exactly_as_before(harness: _Harness) -> None:
    """A pack well inside Luna's bound is not touched: same lines, no map.
    (Every module's prompt over a small pack is held byte for byte by the
    `prompt` goldens, which D116 did not move.)"""
    fitted = _gate(harness, LUNA)
    assert fitted == _gate(harness, None)
    assert fitted.selection.page_maps == {} and fitted.delivered == list(fitted.pin)


def test_a_pack_that_cannot_fit_is_refused_with_no_attempt_or_reservation(
    harness: _Harness, declare_context: Callable[[str, int | None], None]
) -> None:
    """Through the runtime: a model whose context cannot carry even the
    gate's authority beside one line a page refuses before `start_attempt`,
    so nothing is reserved, called or charged."""
    declare_context(SUITE_ENDPOINT, MAX_COMPLETION_TOKENS + 10_000)
    answers = _answers(harness)
    assert _run_route(harness, _module_provider(harness, answers)) is (
        RefusalCode.CONTEXT_OVER_CEILING
    )
    assert answers.calls == 0
    assert _counts(harness) == (0, [], 0, 0, 0)
    _still_running(harness)


def test_an_endpoint_with_no_declared_context_runs_nothing(
    harness: _Harness, declare_context: Callable[[str, int | None], None]
) -> None:
    """The suite's endpoint withdrawn: refused before any attempt (D116)."""
    declare_context(SUITE_ENDPOINT, None)
    answers = _answers(harness)
    assert _run_route(harness, _module_provider(harness, answers)) is (
        RefusalCode.PROVIDER_NOT_CONFIGURED
    )
    assert answers.calls == 0
    assert _counts(harness) == (0, [], 0, 0, 0)
