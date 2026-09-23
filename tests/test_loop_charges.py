"""Phase 6 debt: the loop meets a real module and charges what was reported.

`docs/REBUILD_PLAN.md` lists `test_the_loop_charges_what_the_provider_reported`
under Phase 6, owed by Phase 4. Phase 4's loop reserved an estimate and charged
whatever its stub handed back; Phase 5 built the real module execution and the
real provider, which reports `usage.cost`. This is the join, on the canonical
LITE route (Task 3.1 slice f-1a): CP-0, CP-L10, CP-5.

The distinction the test exists for: an estimate is what the run set aside before
the call, and a charge is what the call cost. A ledger that recorded the estimate
would reconcile perfectly against itself and tell nobody what was spent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from canonical_fixtures import (
    CATALOG,
    LITE_PROFILE,
    LITE_SELECTION,
    PINNED,
    QUOTE,
    CanonicalCompletions,
)
from conftest import _url_for, approve_run, priced

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import NodeState, ResolvedRoute, node_states, resolve_route
from caos.graph.runtime import Execution, accepted_artifacts, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import _decoded_record
from caos.methodology.runner import ModuleProvider
from caos.pricing import ModelPrice, priced_request, worst_case
from caos.provider import MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, connect
from caos.store.budget import CEILING
from caos.store.events import events_of
from caos.store.routes import pin_route
from caos.store.runs import (
    Accepted,
    accept_attempt,
    run_status,
    start_attempt,
    start_run,
)

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"
PROFILE = LITE_PROFILE
# Three nodes: CP-0, CP-L10 and CP-5, the canonical route (§42).
SELECTION = LITE_SELECTION

ESTIMATE = Decimal("0.50")
# What the host configured and therefore what answered: fallbacks are off.
MODEL = "a-model/for-the-test"
# Deliberately unlike the estimate, and unlike a round number, so a ledger that
# recorded the wrong one cannot coincidentally agree.
REPORTED = Decimal("0.0000041")

REPORT = b"""Acme Holdings plc annual report 2026
Total debt at 31 December 2026 was USD 1,240.0m
"""


@dataclass
class _Completions(CanonicalCompletions):
    """Valid LITE handoffs at a known cost, the gate saying `verdict` of the rest.

    Whole prompts are kept: the predecessor-chain test below
    (`docs/REBUILD_PLAN.md` Phase 11, "The chain") reads the upstream handoff
    back out of a later node's prompt, and a truncated copy would not carry it.
    """

    charge: Decimal | None = REPORTED
    model: str = MODEL
    generation_id: str = "gen-loop-test"
    verdict: str = "READY"

    def __post_init__(self) -> None:
        if self.verdict != "READY" and not self.readiness:
            self.readiness = dict.fromkeys(PINNED, self.verdict)


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, PROFILE, SELECTION)


@pytest.fixture
def ready(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> tuple[StoreConnection, UUID, UUID, BlobStore]:
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("report.txt"), data=REPORT)],
    )
    # D29: a run is admitted only under a ceiling that covers one worst-case
    # call, which at 4 MiB and TERRA's rates is above the legacy $5 default.
    run_id = start_run(conn, case_id, budget_ceiling=max(CEILING, worst_case(TERRA)))
    conn.commit()
    approve_run(
        conn,
        case_id=case_id,
        run_id=run_id,
        route=route,
        bundle=Bundle(root=VENDORED),
    )
    return conn, run_id, source_id, blobs


def _charges(conn: StoreConnection, run_id: UUID) -> list[Decimal]:
    rows = conn.execute(
        "SELECT amount FROM budget_ledger WHERE run_id = %s ORDER BY charged_at",
        (run_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _reserved(conn: StoreConnection, run_id: UUID) -> list[Decimal]:
    rows = conn.execute(
        "SELECT amount FROM budget_reservations WHERE run_id = %s", (run_id,)
    ).fetchall()
    return [row[0] for row in rows]


def _run(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore],
    route: ResolvedRoute,
    completions: _Completions,
) -> None:
    conn, run_id, _source_id, blobs = ready
    provider = ModuleProvider(
        conn=conn,
        bundle=Bundle(root=VENDORED),
        blobs=blobs,
        completions=completions,
        route=route,
        run_id=run_id,
    )
    run_route(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        execution=Execution(provider, priced(ESTIMATE), provider.bundle),
    )


def test_the_loop_charges_what_the_provider_reported(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """The named test. Reserved the estimate, charged the report.

    Both numbers are in the store afterwards and they are different, which is
    the point: the reservation is what the ceiling was checked against, and the
    charge is what the run actually cost.
    """
    conn, run_id, source_id, _blobs = ready
    _run(ready, route, _Completions(source_id))

    assert run_status(conn, run_id) is RunStatus.COMPLETE
    charges = _charges(conn, run_id)
    assert charges == [REPORTED] * 3, "the ledger holds what the calls cost"
    assert _reserved(conn, run_id) == [ESTIMATE] * 3, "and what was set aside"
    assert REPORTED != ESTIMATE, "a test that compared two equal numbers proves nothing"


def test_an_accepted_artifact_records_the_model_that_produced_it(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """Invariant 3 over the one identity the store did not hold.

    A verdict binds `provider` — a string in a document this repository did not
    write — and nothing could compare it against what the runs behind it called,
    because nothing a run left behind named a model. The charge was recorded and
    the artifact was recorded; who produced them was not.

    The identity is the host's own configuration, not the provider's report of
    itself. `OpenRouter._post` sets `allow_fallbacks: false` precisely so that
    what was asked for is what answered, and reading the model back out of the
    response body would be taking a claim where the host already holds a fact
    (invariant 3).
    """
    conn, run_id, source_id, _blobs = ready
    _run(ready, route, _Completions(source_id))

    recorded = conn.execute(
        "SELECT model, generation_id FROM artifacts WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert [(str(row[0]), str(row[1])) for row in recorded] == [
        (MODEL, "gen-loop-test")
    ] * 3, "one identity per accepted artifact, for every node of the pathway"


def test_the_artifact_is_the_handoff_and_the_record_the_host_built(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """What the loop stores is the exact Markdown handoff, addressed by its
    digest, beside the host's record -- not the provider's body, which is
    untrusted JSON kept only as the call's diagnostic."""
    conn, run_id, source_id, blobs = ready
    completions = _Completions(source_id)
    _run(ready, route, completions)

    row = conn.execute(
        "SELECT a.artifact_sha256, a.record_sha256, o.diagnostic_sha256"
        " FROM artifacts a JOIN call_outcomes o USING (attempt_id)"
        " WHERE a.run_id = %s ORDER BY a.created_at LIMIT 1",
        (run_id,),
    ).fetchone()
    assert row is not None
    artifact, record, diagnostic = (str(value) for value in row)
    assert blobs.get(artifact) == completions.answers[0], "the Markdown, exactly"
    body = completions.bodies[0].encode()
    assert diagnostic == hashlib.sha256(body).hexdigest() != artifact
    stored = _decoded_record(blobs.get(record))

    assert stored.identity.module_id == "CP-0", "the host's module id, not the module's"
    assert stored.artifact_sha256 == artifact
    assert stored.build_id.startswith("99ed0dc3")
    assert len(stored.authority_digest) == 64
    [citation] = stored.citations
    assert citation.matched_text == QUOTE and citation.bboxes, "anchored by the host"


def test_a_module_that_cannot_be_anchored_stops_the_run(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """A refusal inside a node is not a node that quietly produced nothing. The
    attempt and its reservation stay; the run does not complete."""
    conn, run_id, _source_id, _blobs = ready
    completions = _Completions(UUID(int=0))  # cites evidence never delivered

    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        _run(ready, route, completions)

    with connect(_url_for(conn.info.dbname)) as observer:
        # N52: the refusal earns one second attempt, refused the same way;
        # both keep their reservation and bill.
        assert run_status(observer, run_id) is RunStatus.RUNNING
        assert _reserved(observer, run_id) == [ESTIMATE, ESTIMATE]
        assert _charges(observer, run_id) == [REPORTED, REPORTED]
        assert observer.execute("SELECT count(*) FROM call_outcomes").fetchone() == (2,)
        assert observer.execute("SELECT count(*) FROM artifacts").fetchone() == (0,)
    assert len(completions.prompts) == 2


def test_the_loop_hands_each_node_its_predecessors_results(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """CP-0 runs first with no upstream; CP-L10's prompt carries CP-0's accepted
    handoff, exactly as the host stored it."""
    conn, run_id, source_id, _blobs = ready
    completions = _Completions(source_id)
    pin_route(conn, run_id, route)

    _run(ready, route, completions)

    first, second, _third = completions.prompts
    assert "--- UPSTREAM" not in first
    assert "--- UPSTREAM" in second
    assert completions.answers[0].decode() in second


def test_a_predecessor_artifact_of_another_shape_is_refused_not_raised(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """Bytes of a shape the host did not write are a typed refusal.

    Reading a stored predecessor once raised across the provider seam -- from
    inside `_run_node`, after the reservation, out of a boundary whose whole
    contract is that refusals are typed. A canonical row's record that does not
    decode is refused as a mismatch before any call.
    """
    conn, run_id, source_id, blobs = ready
    cp0 = next(node.route_node_id for node in route.nodes if node.module_id == "CP-0")
    accept_attempt(
        conn,
        attempt_id=start_attempt(conn, run_id, cp0),
        accepted=Accepted(
            artifact_sha256=blobs.put(b"---\nnot: a handoff\n---\n"),
            charge=REPORTED,
            model=MODEL,
            generation_id="gen-loop-test",
            record_sha256=blobs.put(b'{"claims": [{"statement": 40}]}'),
        ),
    )
    completions = _Completions(source_id)

    with pytest.raises(Refusal) as caught:
        _run(ready, route, completions)

    assert caught.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    assert completions.prompts == []


def test_a_node_the_gate_blocked_costs_no_call_and_no_charge(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """The verdict decides what runs, driven end to end rather than composed.

    CP-0's T8 register answers BLOCKED for every other node here, so none is
    offered: one call, one reservation, one charge, one attempt row, and a
    BLOCKED run (§39) reporting the rest unrun. A loop that ran them anyway
    would pay a provider for an answer the gate had already refused.
    """
    conn, run_id, source_id, blobs = ready
    completions = _Completions(source_id, verdict="BLOCKED")
    _run(ready, route, completions)

    nodes = {node.module_id: node.route_node_id for node in route.nodes}
    # §39: an empty frontier with unfinished required work is blocked, not done.
    assert run_status(conn, run_id) is RunStatus.BLOCKED
    assert [e.name for e in events_of(conn, run_id)].count("RUN_BLOCKED") == 1
    assert "RUN_COMPLETE" not in [e.name for e in events_of(conn, run_id)]
    assert len(completions.prompts) == 1, "the gate was asked; what it blocked was not"
    assert _charges(conn, run_id) == [REPORTED], "one charge, for the one call"
    assert _reserved(conn, run_id) == [ESTIMATE], "and one reservation behind it"
    assert _attempted(conn, run_id) == [nodes["CP-0"]], "no attempt row at all"
    # No node's verdict ended this run: the frontier emptied. The store names
    # nothing, so the wire cannot claim a blocking node that does not exist.
    assert conn.execute(
        "SELECT count(*) FROM run_blocking_verdicts WHERE run_id = %s", (run_id,)
    ).fetchone() == (0,)
    bundle = Bundle(root=VENDORED)
    states = node_states(
        route, accepted_artifacts(conn, blobs, route, run_id, bundle=bundle)
    )
    for module in PINNED:
        assert states[nodes[module]] is NodeState.BLOCKED, "reported unrun, with cause"

    # Blocked stays blocked: running the route again spends nothing and moves nothing.
    conn.rollback()
    with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
        _run(ready, route, completions)
    assert len(completions.prompts) == 1
    assert run_status(conn, run_id) is RunStatus.BLOCKED
    assert _charges(conn, run_id) == [REPORTED]


def _attempted(conn: StoreConnection, run_id: UUID) -> list[str]:
    rows = conn.execute(
        "SELECT route_node_id FROM run_attempts WHERE run_id = %s ORDER BY started_at",
        (run_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


# What a real frontier model costs per token: $3/M input, $15/M output. At this
# price one worst-case call is over $4, which is why a $5 run could not finish
# a three-node route while every attempt reserved the byte ceiling (§40).
TERRA = ModelPrice(MODEL, Decimal("0.000003"), Decimal("0.000015"), date(2026, 9, 17))


def test_a_small_prompt_reserves_its_priced_cost_not_the_byte_ceiling(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """Completion O09: the reservation is priced on the request, not on §38.

    `MAX_REQUEST_BYTES` bounds what the transport allows; it is not what this
    prompt is. A reservation measured on the bytes the provider will actually
    send is still an upper bound on the call -- a token is at least one byte --
    and it is the bound that lets three nodes run under one $5 ceiling.
    """
    conn, run_id, source_id, blobs = ready
    completions = _Completions(source_id)
    provider = ModuleProvider(
        conn=conn,
        bundle=Bundle(root=VENDORED),
        blobs=blobs,
        completions=completions,
        route=route,
        run_id=run_id,
    )
    run_route(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        execution=Execution(provider, TERRA, provider.bundle),
    )

    assert run_status(conn, run_id) is RunStatus.COMPLETE
    reserved = _reserved(conn, run_id)
    assert len(reserved) == len(completions.prompts) == 3
    # These prompts carry the whole delivered authority, so they are large --
    # about 210 KB each -- and still a fifth of the transport ceiling, which is
    # the gap this task stopped paying for.
    assert max(len(prompt.encode()) for prompt in completions.prompts) < (
        MAX_REQUEST_BYTES // 4
    )
    assert all(amount < Decimal("3.64") for amount in reserved), reserved
    assert sum(reserved) < CEILING, "three nodes fit one default ceiling"
    # Exactly the priced cost of the request that was sent, not an estimate.
    assert reserved == [
        priced_request(TERRA, len(completions.request_bytes(prompt, json_object=True)))
        for prompt in completions.prompts
    ]
    assert all(amount < worst_case(TERRA) for amount in reserved)


def test_a_reservation_below_its_request_answers_a_code_of_its_own() -> None:
    """The context is unchanged; the reservation no longer covers it. Borrowing
    `CONTEXT_OVER_CEILING` told the reader "Deliver less context to the module",
    an act that is neither possible here nor what is wrong. The host's own
    reservation disagreeing with the host's own rebuilt request is not the
    caller's request being wrong (400), and the same attempt meets the same
    reservation later (not 503): a permanent 500 whose clearance is a new
    attempt, which reserves for the request it sends."""
    from caos.api.app import _STATUS, PERMANENT
    from caos.api.wire import CLEARS

    code = RefusalCode.RESERVATION_BELOW_REQUEST
    assert _STATUS[code] == 500
    assert code in PERMANENT
    assert CLEARS[code] != CLEARS[RefusalCode.CONTEXT_OVER_CEILING]
    assert "context" not in CLEARS[code].lower()
    assert "attempt" in CLEARS[code].lower()


def test_a_prompt_rebuilt_larger_than_the_one_priced_is_refused_before_the_call(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore],
    route: ResolvedRoute,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion O09's hazard: the loop prices one prompt, the attempt builds another.

    `check_context` builds and prices the request before `start_attempt`, and the
    attempt unit builds its own again under that attempt's identity. If the
    second is larger than the first, the call goes out under a reservation too
    small for it -- invariant 8's "no provider call without a reservation" met in
    form and not in substance, which is exactly what pricing the request rather
    than the transport ceiling could have cost. `_within_reservation` re-prices
    the request about to be sent against the price its reservation was taken
    under, so the refusal lands before the provider is reached.

    The second build is made larger here rather than waited for: the one
    sequential loop cannot produce it today, and a test that can only be written
    once concurrent workers exist is a test of nothing now.
    """
    from caos.methodology import canonical

    conn, run_id, source_id, blobs = ready
    completions = _Completions(source_id)
    real = canonical._prompt
    builds = 0

    def padded(*args: object, **kwargs: object) -> str:
        nonlocal builds
        builds += 1
        prompt = real(*args, **kwargs)  # type: ignore[arg-type]
        # Every build after the priced one grows. A byte would do; a kilobyte
        # makes the refusal unambiguous at any price this fixture could carry.
        return prompt if builds == 1 else prompt + ("\n# padding" * 128)

    monkeypatch.setattr(canonical, "_prompt", padded)
    provider = ModuleProvider(
        conn=conn,
        bundle=Bundle(root=VENDORED),
        blobs=blobs,
        completions=completions,
        route=route,
        run_id=run_id,
    )
    with pytest.raises(Refusal, match=r"^RESERVATION_BELOW_REQUEST$"):
        run_route(
            conn,
            blobs,
            run_id=run_id,
            route=route,
            execution=Execution(provider, TERRA, provider.bundle),
        )

    assert builds == 2, "the loop priced one prompt and the attempt rebuilt it"
    assert completions.prompts == [], "the provider was reached"
    assert conn.execute("SELECT count(*) FROM budget_ledger").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM call_outcomes").fetchone() == (0,)
