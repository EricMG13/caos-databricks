"""A node's request is bounded by its model's declared context (D116, N157):
FCA3-dec's 4,033,648-byte CP-0 request, inside the transport ceiling, was past
Luna's context and refused 400. Past the bound the largest sources become
declared page maps; a pack that cannot fit is refused before any attempt."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import approve_run, priced
from full_assessment_route_fixtures import ROUTE as FULL_ROUTE
from preflight import context_warnings
from test_canonical_execution import route
from test_canonical_runtime import _answers, _module_provider, _run_route
from test_copilot import (
    LONG_TIER,
    MODEL,
    PRICE,
    FakeRuntime,
    billed,
    listed,
    ready,
    runtime,
)
from test_execution_freshness import _counts, _Harness, _still_running, harness
from test_loop_charges import ESTIMATE, VENDORED
from test_loop_charges import MODEL as SUITE_ENDPOINT

import caos.provider
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.copilot import CREDIT_PRICE_ENV, context_tokens, require_ready
from caos.evidence.ingest import Document, admit_pack
from caos.graph.runtime import Execution, run_route
from caos.methodology import canonical
from caos.methodology.bundle import Bundle, delivered_authority
from caos.methodology.canonical import RETRY_RESERVE_BYTES, check_context
from caos.methodology.executor import Assignment, Delivery
from caos.methodology.invocation import evidence_sizes, prospective_identity
from caos.methodology.selection import GATE_SOURCE_BYTES, gate_view, pack_view
from caos.provider import (
    BYTES_PER_TOKEN_FLOOR,
    CONTEXT_NOT_DECLARED,
    CONTEXT_TOKENS,
    COPILOT_CONTEXT_TOKENS,
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    context_notice,
    request_ceiling,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.runs import start_run

__all__ = ["harness", "ready", "route", "runtime"]

REPO = Path(__file__).resolve().parents[1]
FCA = REPO / "qualification/czr-2026q2-full-credit-assessment"
LUNA = "openai/gpt-6-luna"
# The FCA3-dec request the provider refused, rebuilt offline to the byte.
FCA3_REQUEST = 4_033_648


# --- the bound --------------------------------------------------------------


def _declare(monkeypatch: pytest.MonkeyPatch, model: str, tokens: int) -> None:
    """Declare `model`'s context for this test, beside the pinned ones."""
    declared = MappingProxyType({**CONTEXT_TOKENS, model: tokens})
    monkeypatch.setattr(caos.provider, "CONTEXT_TOKENS", declared)


def test_the_bound_is_the_declared_context_at_three_bytes_a_token() -> None:
    """Pinned (D116), from the router's model listing of 2026-10-05."""
    assert BYTES_PER_TOKEN_FLOOR == 3
    assert CONTEXT_TOKENS == {
        "openai/gpt-6-luna": 1_050_000,
        "openai/gpt-6-luna-pro": 1_050_000,
        "openai/gpt-6-sol": 1_050_000,
        **dict.fromkeys(WORKSPACE, 1_000_000),
    }
    assert request_ceiling(LUNA) == (1_050_000 - MAX_COMPLETION_TOKENS) * 3
    assert request_ceiling(LUNA) == 2_953_392 < FCA3_REQUEST


# D119: the ten approved workspace endpoints and the bundle default, declared
# by the owner on 2026-10-06 at 1,000,000 tokens.
APPROVED = (
    "grok-4-7 claude-sonnet-5-5 gpt-6-luna claude-opus-5-5 gpt-6-sol"
    " deepseek-v4-1-flash gpt-6-astra gemini-3-8-flash glm-5-3 glm-5-3-flash"
).split()
WORKSPACE = (*APPROVED, "databricks-claude-opus-5")
DECLARED_BOUND = 2_803_392


@pytest.mark.parametrize("model", WORKSPACE)
def test_a_workspace_endpoint_resolves_to_the_owner_declared_context(
    model: str,
) -> None:
    assert CONTEXT_TOKENS[model] == 1_000_000
    assert request_ceiling(model) == DECLARED_BOUND
    assert DECLARED_BOUND == (1_000_000 - MAX_COMPLETION_TOKENS) * 3
    assert DECLARED_BOUND < MAX_REQUEST_BYTES
    assert context_notice(model) is None


# A routed variant and the suite's own endpoint: each runs under the transport
# ceiling, as before D116.
UNDECLARED: tuple[str, ...] = ("openai/gpt-6-luna:nitro", SUITE_ENDPOINT)


@pytest.mark.parametrize("model", UNDECLARED)
def test_an_endpoint_without_a_declared_context_keeps_the_transport_ceiling(
    model: str,
) -> None:
    """Review round 1: kept on the pre-D116 bound, said once per run."""
    assert request_ceiling(model) == MAX_REQUEST_BYTES
    assert context_notice(model) == f"{CONTEXT_NOT_DECLARED} endpoint={model}"
    assert context_notice(LUNA) is None
    assert context_notice("a\nb") == f"{CONTEXT_NOT_DECLARED} endpoint=-"


@pytest.mark.parametrize("tokens", [MAX_COMPLETION_TOKENS, 0])
def test_a_context_no_wider_than_the_completion_is_refused(
    monkeypatch: pytest.MonkeyPatch, tokens: int
) -> None:
    """A declared context that leaves no room for the prompt is no bound."""
    _declare(monkeypatch, "some/endpoint", tokens)
    with pytest.raises(Refusal) as refused:
        request_ceiling("some/endpoint")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_preflight_warns_of_each_endpoint_without_a_declared_context() -> None:
    """E1 warns, never fails, per endpoint without a declared context."""
    nitro = "openai/gpt-6-luna:nitro"
    assert context_warnings(("claude-opus-5-5", LUNA, "copilot:gpt-6-sol", nitro)) == [
        f"WARNING {name}: no declared context; its requests are bounded by the"
        " transport ceiling alone (D116)"
        for name in (nitro,)
    ]


def test_preflight_is_clean_for_a_configured_approved_endpoint() -> None:
    assert context_warnings(("databricks-claude-opus-5", *APPROVED)) == []


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
    """Only the source past the share bound is mapped; every page kept."""
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
    """A map's own declaration costs bytes: measured again until it fits."""
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
    """At one line a page and still over, the node refuses."""
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
    """N157: past Luna's bound whole, it fits with its largest sources as
    declared page maps, every page of every source still shown."""
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
    """Untouched: same lines, no map (the `prompt` goldens did not move)."""
    fitted = _gate(harness, LUNA)
    assert fitted == _gate(harness, None)
    assert fitted.selection.page_maps == {} and fitted.delivered == list(fitted.pin)


def test_a_pack_that_cannot_fit_is_refused_with_no_attempt_or_reservation(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the runtime: refused before `start_attempt`, nothing reserved."""
    _declare(monkeypatch, SUITE_ENDPOINT, MAX_COMPLETION_TOKENS + 10_000)
    answers = _answers(harness)
    assert _run_route(harness, _module_provider(harness, answers)) is (
        RefusalCode.CONTEXT_OVER_CEILING
    )
    assert answers.calls == 0
    assert _counts(harness) == (0, [], 0, 0, 0)
    _still_running(harness)


@pytest.fixture
def credit_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Copilot model's reservation needs the credit price pinned (R2.2)."""
    monkeypatch.setenv(CREDIT_PRICE_ENV, "0.01,2026-10-01")


@pytest.mark.usefixtures("credit_pinned")
@pytest.mark.parametrize(
    ("model", "notices"),
    [("openai/gpt-6-luna:nitro", 1), ("copilot:claude-opus-5-5", 0)],
)
def test_a_route_runs_to_its_end_with_a_notice_only_when_undeclared(
    harness: _Harness, model: str, notices: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """An undeclared endpoint runs, as before D116, with one stderr notice; a
    Copilot model is declared (MEDIUM-1) and prints none."""
    price = priced(ESTIMATE, model=model)
    answers = replace(_answers(harness), model=model, price=price)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(_module_provider(harness, answers), price, harness.bundle),
    )
    assert answers.calls == len(harness.route.nodes)
    notice = f"{CONTEXT_NOT_DECLARED} endpoint={model}"
    assert capsys.readouterr().err.splitlines().count(notice) == notices


class _BrokenStderr:
    def write(self, text: str) -> int:
        raise OSError(text)


@pytest.mark.usefixtures("credit_pinned")
@pytest.mark.parametrize("broken", [_BrokenStderr(), None], ids=["oserror", "none"])
def test_the_notice_never_fails_a_run(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, broken: object
) -> None:
    """A stderr that cannot take the notice is passed over (F513's fail-open)."""
    model = "openai/gpt-6-luna:nitro"
    price = priced(ESTIMATE, model=model)
    answers = replace(_answers(harness), model=model, price=price)
    monkeypatch.setattr("sys.stderr", broken)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(_module_provider(harness, answers), price, harness.bundle),
    )
    assert answers.calls == len(harness.route.nodes)


# --- a Copilot model's context (R4, D77 addendum 2; MEDIUM-1) --------------


@pytest.mark.parametrize(
    "model", ["copilot:gpt-6-luna", "copilot:claude-opus-5.5@high", MODEL]
)
def test_a_copilot_model_is_declared_at_the_owner_context(model: str) -> None:
    """Every `copilot:` model at the long-context tier the session asks for,
    1,000,000 tokens (owner, 2026-10-06): a host constant, never a listing."""
    assert COPILOT_CONTEXT_TOKENS == 1_000_000
    assert context_tokens(model) == COPILOT_CONTEXT_TOKENS
    assert request_ceiling(model) == DECLARED_BOUND
    assert context_notice(model) is None
    # The gateway's names are the pinned table's, as before.
    assert context_tokens("openai/gpt-6-luna") == 1_050_000


def test_a_pinned_copilot_entry_is_read_under_its_full_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _declare(monkeypatch, "copilot:gpt-6-luna", 300_000)
    assert context_tokens("copilot:gpt-6-luna") == 300_000
    assert request_ceiling("copilot:gpt-6-luna") == _bound(300_000)
    # Another effort is another name, at the declared default.
    assert context_tokens("copilot:gpt-6-luna@high") == COPILOT_CONTEXT_TOKENS


def test_a_pinned_copilot_context_of_one_token_leaves_no_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _declare(monkeypatch, "copilot:gpt-6-luna", 1)
    with pytest.raises(Refusal) as refused:
        request_ceiling("copilot:gpt-6-luna")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def _bound(tokens: int) -> int:
    return min(MAX_REQUEST_BYTES, (tokens - MAX_COMPLETION_TOKENS) * 3)


def test_two_workers_with_different_listings_fit_a_replay_alike(
    fca: _Harness, ready: type[FakeRuntime]
) -> None:
    """MEDIUM-1: a billed answer is replayed by whichever worker reclaims its
    run, and `_replayed_answer` rebuilds the context through `_context`, as
    `_gate` does. Two worker starts whose seats list different long-context
    budgets, each at or above the declared one, fit the same lines: the
    ceiling is the host's, the listing only its floor."""
    fitted = []
    for tokens in (1_000_000, 1_500_000):
        tier = dict(LONG_TIER, maxPromptTokens=tokens)
        ready.offered = [listed(billing=billed(long_context=tier))]
        require_ready({MODEL: PRICE})
        fitted.append(_gate(fca, MODEL))
    first, second = fitted
    assert first == second
    # The bound bit: FCA's CP-0 pack is past 2,803,392 bytes whole.
    assert first.selection.page_maps


def test_a_cli_copilot_model_has_no_ceiling_until_its_transport_is_built() -> None:
    with pytest.raises(Refusal) as refused:
        request_ceiling("copilot-cli:gpt-6-luna")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
