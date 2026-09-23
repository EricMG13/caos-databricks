"""Phase 3 exit tests: the phase the predecessor got wrong.

`docs/DECISIONS.md` §2 records what it got wrong and how it was measured. Route
resolution read `navigation.dependencies` -- 97 untyped pairs meant for display --
instead of `profile["edges"]`. The consequences were exact: 25 OPTIONAL and 22
ADVISORY edges were enforced as mandatory, the single QA_GATE did not gate, and
RESTRICTED could not occur at all.

Every test here reads the vendored catalog rather than a fixture, so the numbers
are the build's own (`tests/test_bundle_pin.py` pins them). The soft-edge rule is
the one worth stating twice: OPTIONAL and ADVISORY degrade a target to RESTRICTED
-- which runs and carries its limitation forward -- unless the edge's source
module is READY or READY_WITH_LIMITATIONS in the accepted CP-0 artifact, at which
point the evidence exists and the edge blocks.

Readiness is read from that artifact and never passed in (`docs/DECISIONS.md`
§12, adopting CAOS-Final §18): a caller that could assert readiness could assert
its way past the gate that exists to measure it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from caos.graph.route import (
    Edge,
    EdgeType,
    NamedObjects,
    NodeResult,
    NodeState,
    ResolvedRoute,
    RouteExtensions,
    RouteNode,
    blockers_from,
    dependency_order,
    frontier,
    limitations_of,
    lite_object_unmet,
    node_states,
    predecessors,
    readiness_from,
    resolve_route,
    route_digest,
    waiting_on,
)
from caos.refusals import Refusal, RefusalCode

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-os-credit-os/references"
    / "CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
PROFILE = "FULL_CREDIT_32"
READY = ("READY", "READY_WITH_LIMITATIONS")


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    """The vendored build's own catalog, not a fixture standing in for it."""
    loaded: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return loaded


def _cp0_artifact(**readiness: str) -> NodeResult:
    """A CP-0 result carrying a readiness status per module, as the runtime
    reads it from a claims body or a canonical record."""
    return NodeResult(readiness=tuple(readiness.items()))


def _accept(
    route: ResolvedRoute, *module_ids: str, cp0: NodeResult | None = None
) -> dict[str, NodeResult]:
    """Accepted artifacts keyed by route node, CP-0's carrying the readiness."""
    wanted = set(module_ids)
    accepted: dict[str, NodeResult] = {}
    for node in route.nodes:
        if node.module_id == "CP-0" and ("CP-0" in wanted or cp0 is not None):
            accepted[node.route_node_id] = cp0 if cp0 is not None else _cp0_artifact()
        elif node.module_id in wanted:
            accepted[node.route_node_id] = NodeResult()
    return accepted


def _node_id(route: ResolvedRoute, module_id: str) -> str:
    return next(n.route_node_id for n in route.nodes if n.module_id == module_id)


def _state(
    route: ResolvedRoute, accepted: dict[str, NodeResult], module_id: str
) -> NodeState:
    return node_states(route, accepted)[_node_id(route, module_id)]


def test_the_typed_edges_are_read_not_the_untyped_display_list(
    catalog: dict[str, Any],
) -> None:
    """The predecessor's defect, stated as a test. `navigation.dependencies`
    carries no type, so a route built from it cannot tell REQUIRED from
    ADVISORY -- which is how 47 soft edges became mandatory."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")

    assert {edge.type for edge in route.edges} & {
        EdgeType.OPTIONAL,
        EdgeType.ADVISORY,
    }, "a resolved route carries soft edges; the untyped list cannot express them"


def test_optional_edge_does_not_block(catalog: dict[str, Any]) -> None:
    """CP-1A -> CP-2 is OPTIONAL. With CP-1A unaccepted and not READY, CP-2 is
    RESTRICTED: it runs and carries the limitation, rather than waiting."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", "CP-1", cp0=_cp0_artifact(**{"CP-1A": "BLOCKED"}))

    assert _state(route, accepted, "CP-2") is NodeState.RESTRICTED
    assert _node_id(route, "CP-2") in frontier(route, accepted)


def test_optional_edge_blocks_when_source_ready(catalog: dict[str, Any]) -> None:
    """The same edge, the other way. CP-0 says the evidence CP-1A needs is
    READY, so running CP-2 without it would discard evidence the case has."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", "CP-1", cp0=_cp0_artifact(**{"CP-1A": "READY"}))

    assert _state(route, accepted, "CP-2") is NodeState.BLOCKED
    assert _node_id(route, "CP-2") not in frontier(route, accepted)


@pytest.mark.parametrize("status", READY)
def test_both_ready_statuses_harden_a_soft_edge(
    catalog: dict[str, Any], status: str
) -> None:
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", "CP-1", cp0=_cp0_artifact(**{"CP-1A": status}))

    assert _state(route, accepted, "CP-2") is NodeState.BLOCKED


@pytest.mark.parametrize(
    "cp5,released",
    [
        (None, False),
        (NodeResult(), False),
        (NodeResult(qa_status="Not Reviewed"), False),
        (NodeResult(qa_status="Restricted"), True),
        (NodeResult(qa_status="Blocked"), False),
        (NodeResult(qa_status="passed"), False),
        (NodeResult(qa_status="Passed"), True),
    ],
)
def test_qa_gate_blocks_cp6_until_cp5_accepted(
    catalog: dict[str, Any], cp5: NodeResult | None, released: bool
) -> None:
    """F03, pure, as D34 left it. The one QA_GATE in this build, CP-5 -> CP-6.
    Under the predecessor it did not gate, because the untyped list it read had
    no QA_GATE in it. A stored `Passed` or `Restricted` clears it -- the vendor's
    navigator meets the edge on acceptance, and a Restricted CP-5 is accepted
    with its restriction carried; Blocked, Not Reviewed, a miscased verdict, no
    verdict and no artifact all hold CP-6."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    everything_but_cp5 = [
        node.module_id for node in route.nodes if node.module_id not in {"CP-5", "CP-6"}
    ]
    accepted = _accept(route, *everything_but_cp5, cp0=_cp0_artifact())

    assert _state(route, accepted, "CP-6") is NodeState.BLOCKED

    if cp5 is not None:
        accepted[_node_id(route, "CP-5")] = cp5
    cp6 = _node_id(route, "CP-6")
    assert _state(route, accepted, "CP-6") is (
        NodeState.RUNNABLE if released else NodeState.BLOCKED
    )
    assert (cp6 in frontier(route, accepted)) is released
    gate = Edge("CP-5", "CP-6", EdgeType.QA_GATE)
    assert (gate in waiting_on(route, accepted, cp6)) is not released


def test_restricted_node_runs_and_carries_limitation(catalog: dict[str, Any]) -> None:
    """RESTRICTED is the bundle's word and it means *runs*. The node is in the
    frontier, and it can say which unmet edge restricted it -- a limitation that
    reached an artifact without naming its cause would be unauditable."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", "CP-1", cp0=_cp0_artifact(**{"CP-1A": "BLOCKED"}))
    cp2 = _node_id(route, "CP-2")

    assert cp2 in frontier(route, accepted)

    unmet = limitations_of(route, accepted, cp2)
    assert unmet, "a RESTRICTED node names what it is missing"
    assert {edge.source for edge in unmet} <= {"CP-1A", "CP-1B", "CP-1C", "CP-1D"}
    assert all(edge.type in {EdgeType.OPTIONAL, EdgeType.ADVISORY} for edge in unmet)


def test_dependency_order_refuses_a_cycle() -> None:
    """The catalog is a DAG. A cycle would mean a route that never resolves, and
    a pin nothing could execute -- so it is refused rather than ordered around."""
    nodes = [RouteNode("RN-A", "CP-A", 1), RouteNode("RN-B", "CP-B", 2)]
    edges = [
        Edge("CP-A", "CP-B", EdgeType.REQUIRED),
        Edge("CP-B", "CP-A", EdgeType.REQUIRED),
    ]

    with pytest.raises(Refusal) as caught:
        dependency_order(nodes, edges)

    assert caught.value.code is RefusalCode.ROUTE_HAS_A_CYCLE


def test_dependency_order_refuses_two_nodes_for_one_module() -> None:
    """A route is one node per module, and this is where that is enforced.

    Every reader downstream assumes it. `node_states` builds its complete set
    from `module_id`, `readiness_from` returns at the first CP-0 node, and
    `_unmet` resolves edges by module. Nothing said so, and the ordering below
    keyed its own bookkeeping by module too -- so a second node for one module
    did not collide with the rule, it collided with a dict key, and one of the
    two simply stopped existing.

    Refused rather than collapsed. Invariant 10 calls the resolved route a
    closed node list; a list that loses members to a key collision is not
    closed, and the loss reaches the digest a replay is bound to.
    """
    nodes = [
        RouteNode("RN-EARLY-CP-A", "CP-A", 1),
        RouteNode("RN-LATE-CP-A", "CP-A", 9),
    ]

    with pytest.raises(Refusal) as caught:
        dependency_order(nodes, [])

    assert caught.value.code is RefusalCode.ROUTE_DUPLICATE_MODULE


def test_an_extension_naming_a_module_the_pathway_already_runs_is_refused(
    catalog: dict[str, Any],
) -> None:
    """The reachable half of the rule above, on the vendored catalog.

    DEEP_RESEARCH already runs CP-DR. Asking for the research extension on it
    appended a second CP-DR, and the pathway's own node -- the one whose
    `route_node_id` the pathway declared -- vanished: three nodes in, two out,
    no refusal. The surviving node carried the extension's stage and id, so the
    pinned route named a node the pathway never declared while dropping one it
    did.

    `test_the_research_extension_appends_cp_dr_without_editing_the_catalog`
    missed it by running on LIQUIDITY_REVIEW, which carries no CP-DR: the test
    picked the pathway where appending is safe.

    Refusing is the useful answer rather than skipping the append. Someone
    asking for this pathway *with* a brief means the brief to reach CP-DR, and
    silently not appending would discard it as surely as silently dropping a
    node did.
    """
    with pytest.raises(Refusal) as caught:
        resolve_route(
            catalog,
            PROFILE,
            "DEEP_RESEARCH",
            extensions=RouteExtensions(research_brief={"question": "refinancing"}),
        )

    assert caught.value.code is RefusalCode.ROUTE_DUPLICATE_MODULE


def test_readiness_is_read_only_from_the_cp0_artifact(catalog: dict[str, Any]) -> None:
    """`docs/DECISIONS.md` §12, adopting CAOS-Final §18: readiness is read from
    the accepted CP-0 artifact and never passed in.

    A readiness claim inside some other module's artifact is not readiness. If it
    were, any module could harden the soft edges that feed it and assert its way
    past the gate that exists to measure whether the evidence is there.
    """
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    smuggled = {_node_id(route, "CP-1"): _cp0_artifact(**{"CP-1A": "READY"})}

    assert readiness_from(route, smuggled) == {}

    honest = _accept(route, "CP-0", cp0=_cp0_artifact(**{"CP-1A": "READY"}))
    assert readiness_from(route, honest) == {"CP-1A": "READY"}


def test_blockers_are_read_only_from_the_cp0_artifact(catalog: dict[str, Any]) -> None:
    """`blockers_from` is keyed exactly like `readiness_from` and read from the
    same place: a blocker text inside another module's artifact is not the gate's
    condition, and a route with no accepted CP-0 states none.

    Absence is not "no reason given": the gate holds a row only for a module it
    did not clear, so a cleared module is simply absent here.
    """
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    asked = "The FY2025 audited consolidated statements are not in the pinned set."
    gate = NodeResult(
        readiness=(("CP-1A", "CONDITIONAL"), ("CP-1C", "READY")),
        blockers=(("CP-1A", asked),),
    )

    assert blockers_from(route, {_node_id(route, "CP-1"): gate}) == {}

    honest = _accept(route, "CP-0", cp0=gate)
    assert blockers_from(route, honest) == {"CP-1A": asked}
    assert blockers_from(route, {}) == {}
    assert readiness_from(route, honest) == {"CP-1A": "CONDITIONAL", "CP-1C": "READY"}


def test_readiness_from_skips_nodes_before_the_cp0_one(catalog: dict[str, Any]) -> None:
    """CP-0 need not be `route.nodes[0]`: the search walks past whatever precedes
    it rather than assuming its position."""
    route = ResolvedRoute(
        profile_id="p",
        selection_id="s",
        nodes=(RouteNode("RN-1", "CP-1", 1), RouteNode("RN-0", "CP-0", 0)),
        edges=(),
    )
    accepted = {"RN-0": _cp0_artifact(**{"CP-1A": "READY"})}

    assert readiness_from(route, accepted) == {"CP-1A": "READY"}


def test_readiness_from_a_route_with_no_cp0_node_is_empty(
    catalog: dict[str, Any],
) -> None:
    route = ResolvedRoute(
        profile_id="p",
        selection_id="s",
        nodes=(RouteNode("RN-1", "CP-1", 1),),
        edges=(),
    )

    assert readiness_from(route, {}) == {}


def test_a_profile_entry_that_is_not_a_mapping_is_refused() -> None:
    catalog = {"profiles": {"BAD": ["not", "a", "mapping"]}}

    with pytest.raises(Refusal) as caught:
        resolve_route(catalog, "BAD", "whatever")

    assert caught.value.code is RefusalCode.ROUTE_PROFILE_UNKNOWN


def test_a_pathway_entry_that_is_not_a_mapping_is_refused() -> None:
    catalog = {"profiles": {"P": {"pathways": {"BAD": ["not", "a", "mapping"]}}}}

    with pytest.raises(Refusal) as caught:
        resolve_route(catalog, "P", "BAD")

    assert caught.value.code is RefusalCode.ROUTE_SELECTION_UNKNOWN


def test_a_node_with_every_edge_met_is_runnable(catalog: dict[str, Any]) -> None:
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", cp0=_cp0_artifact())

    assert _state(route, accepted, "CP-1") is NodeState.RUNNABLE


def test_an_accepted_node_is_complete(catalog: dict[str, Any]) -> None:
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted = _accept(route, "CP-0", cp0=_cp0_artifact())

    assert _state(route, accepted, "CP-0") is NodeState.COMPLETE
    assert _node_id(route, "CP-0") not in frontier(route, accepted)


def test_the_first_frontier_is_cp0_alone(catalog: dict[str, Any]) -> None:
    """Nothing has been accepted, so nothing has readiness. Every other node
    waits on a REQUIRED edge from CP-0."""
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")

    assert frontier(route, {}) == [_node_id(route, "CP-0")]


def test_dependency_order_puts_every_edge_before_its_target(
    catalog: dict[str, Any],
) -> None:
    route = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    position = {node.module_id: index for index, node in enumerate(route.nodes)}

    for edge in route.edges:
        assert position[edge.source] < position[edge.target], (
            f"{edge.source} must be resolved before {edge.target}"
        )


def test_resolved_route_is_pinned_and_replays_identically(
    catalog: dict[str, Any],
) -> None:
    """Invariant 10. Resolution is a pure function of pinned inputs, so the same
    inputs digest the same and execution reading only the pin takes the same
    path. A digest that moved would mean a replay was a different run."""
    first = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    second = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")

    assert route_digest(first) == route_digest(second)
    assert [n.route_node_id for n in first.nodes] == [
        n.route_node_id for n in second.nodes
    ]

    other = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")
    assert route_digest(other) != route_digest(first)


def test_the_research_extension_appends_cp_dr_without_editing_the_catalog(
    catalog: dict[str, Any],
) -> None:
    plain = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")
    extended = resolve_route(
        catalog,
        PROFILE,
        "LIQUIDITY_REVIEW",
        extensions=RouteExtensions(research_brief={"question": "refinancing"}),
    )

    assert "CP-DR" not in {node.module_id for node in plain.nodes}
    assert "CP-DR" in {node.module_id for node in extended.nodes}
    assert route_digest(extended) != route_digest(plain)


def test_cp_cf_waits_for_all_required_owners(catalog: dict[str, Any]) -> None:
    """`SYSTEM_SPEC.md` §6.2: the extension synthesises REQUIRED edges from
    CP-1, CP-2G and CP-4, which name every artifact owner CP-CF reads. CP-2G
    completing alone does not release it."""
    route = resolve_route(
        catalog,
        PROFILE,
        "FULL_CREDIT_ASSESSMENT",
        extensions=RouteExtensions(model_extension=True),
    )
    owners = {"CP-1", "CP-2G", "CP-4"}

    incoming = {edge.source for edge in route.edges if edge.target == "CP-CF"}
    assert owners <= incoming

    accepted = _accept(route, "CP-0", "CP-1", "CP-2G", cp0=_cp0_artifact())
    assert _state(route, accepted, "CP-CF") is NodeState.BLOCKED

    accepted[_node_id(route, "CP-4")] = NodeResult()
    assert _state(route, accepted, "CP-CF") is NodeState.RUNNABLE


def test_the_extension_appends_cp_cf_alone(catalog: dict[str, Any]) -> None:
    """Phase 7's named test. CP-CF is placed; CP-MODEL is not.

    `docs/DECISIONS.md` §14 (adopting CAOS-Final §48) is why: no workbook build,
    so no CP-MODEL, and the model extension that once placed both now places one.
    A route that quietly carried CP-MODEL would be pinned into the digest the
    plan gate binds, and every replay would carry a module the host cannot run.
    """
    plain = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    extended = resolve_route(
        catalog,
        PROFILE,
        "FULL_CREDIT_ASSESSMENT",
        extensions=RouteExtensions(model_extension=True),
    )

    added = {node.module_id for node in extended.nodes} - {
        node.module_id for node in plain.nodes
    }

    assert added == {"CP-CF"}, "one module, and it is CP-CF"
    assert "CP-MODEL" not in {node.module_id for node in extended.nodes}
    # It is part of what the gate digests, so a replay takes the extended route
    # rather than re-deciding whether to extend it.
    assert route_digest(extended) != route_digest(plain)


def test_model_extension_refuses_missing_owner(catalog: dict[str, Any]) -> None:
    """COVENANT_REFINANCING carries CP-1 and CP-4 but no CP-2G. An extended
    route missing a required owner is refused during resolution, before pinning
    -- rather than dropping the edge or running CP-CF on missing inputs."""
    with pytest.raises(Refusal) as caught:
        resolve_route(
            catalog,
            PROFILE,
            "COVENANT_REFINANCING",
            extensions=RouteExtensions(model_extension=True),
        )

    assert caught.value.code is RefusalCode.ROUTE_EXTENSION_OWNER_MISSING


def test_an_unknown_pathway_is_refused(catalog: dict[str, Any]) -> None:
    with pytest.raises(Refusal) as caught:
        resolve_route(catalog, PROFILE, "NO_SUCH_PATHWAY")

    assert caught.value.code is RefusalCode.ROUTE_SELECTION_UNKNOWN


def test_an_unknown_profile_is_refused(catalog: dict[str, Any]) -> None:
    with pytest.raises(Refusal) as caught:
        resolve_route(catalog, "NO_SUCH_PROFILE", "FULL_CREDIT_ASSESSMENT")

    assert caught.value.code is RefusalCode.ROUTE_PROFILE_UNKNOWN


def test_a_node_the_route_does_not_carry_is_a_typed_refusal(
    catalog: dict[str, Any],
) -> None:
    """`waiting_on` is what a surface asks for the reason behind a state.

    Asked for a node the route does not carry it raised `StopIteration` -- an
    untyped escape from the one module whose whole contract is typed refusals,
    and the exception that disappears silently if it is ever raised inside a
    generator. The answer is the code the proof already uses for exactly this
    fact.
    """
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")

    with pytest.raises(Refusal) as caught:
        waiting_on(route, {}, "RN-no-such-node")

    assert caught.value.code is RefusalCode.ORCHESTRATION_NODE_NOT_IN_ROUTE


def test_a_module_the_gate_blocked_never_becomes_runnable(
    catalog: dict[str, Any],
) -> None:
    """CP-0 is the gate: a module it did not clear is BLOCKED whatever the
    edges say, so the run makes no call and no charge for it."""
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")
    accepted = _accept(
        route,
        "CP-0",
        cp0=_cp0_artifact(**{"CP-1": "BLOCKED", "CP-2": "READY", "CP-2D": "READY"}),
    )

    states = node_states(route, accepted)

    assert states[_node_id(route, "CP-1")] is NodeState.BLOCKED
    assert _node_id(route, "CP-1") not in frontier(route, accepted)


def test_a_conditional_verdict_blocks_like_a_blocked_one(
    catalog: dict[str, Any],
) -> None:
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")
    accepted = _accept(
        route,
        "CP-0",
        cp0=_cp0_artifact(**{"CP-1": "CONDITIONAL", "CP-2": "READY", "CP-2D": "READY"}),
    )

    assert node_states(route, accepted)[_node_id(route, "CP-1")] is NodeState.BLOCKED


def test_ready_with_limitations_runs_as_restricted(catalog: dict[str, Any]) -> None:
    """RESTRICTED runs and carries its limitation forward (CONTEXT.md); it is
    not a refusal."""
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")
    accepted = _accept(
        route,
        "CP-0",
        cp0=_cp0_artifact(
            **{"CP-1": "READY_WITH_LIMITATIONS", "CP-2": "READY", "CP-2D": "READY"}
        ),
    )

    states = node_states(route, accepted)

    assert states[_node_id(route, "CP-1")] is NodeState.RESTRICTED
    assert _node_id(route, "CP-1") in frontier(route, accepted)


def test_readiness_applies_only_once_the_gate_is_accepted(
    catalog: dict[str, Any],
) -> None:
    """Before the gate has run there is no verdict to apply, and the edges are
    what keep the route behind CP-0."""
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")

    states = node_states(route, {})

    assert states[_node_id(route, "CP-0")] is NodeState.RUNNABLE
    assert states[_node_id(route, "CP-1")] is NodeState.BLOCKED


def test_a_nodes_predecessors_are_its_edge_sources_in_route_order(
    catalog: dict[str, Any],
) -> None:
    """CP-2D carries a REQUIRED edge from each of CP-0, CP-1 and CP-2 in this
    pathway. `expected` is built from `route.edges` and `route.nodes` directly
    -- not by calling `predecessors` a second time -- so this compares the
    function's output against an independently derived value rather than a
    re-derivation of itself: a real check that the returned set of modules is
    the pinned catalog's own answer for CP-2D, not an assumption taken on
    faith.

    It does not pin the *order* claim by itself: for this pathway CP-0, CP-1
    and CP-2 sort identically whether by route position, by edge-declaration
    order in `profile["edges"]`, or by plain alphabetical order, so an
    implementation using any of those instead of route order would still
    satisfy this test.
    `test_predecessors_use_route_order_not_edge_or_alphabetical_order` below
    is the one built so the three hypotheses disagree.
    """
    route = resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW")

    assert predecessors(route, "CP-0") == ()
    assert "CP-1" in predecessors(route, "CP-2D")

    sources = {edge.source for edge in route.edges if edge.target == "CP-2D"}
    expected = tuple(
        node.module_id for node in route.nodes if node.module_id in sources
    )

    assert predecessors(route, "CP-2D") == expected


def test_predecessors_use_route_order_not_edge_or_alphabetical_order() -> None:
    """A hand-built route where the three candidate orderings disagree.

    The catalog-based test above cannot distinguish route order from
    edge-declaration order or from alphabetical order, because its three
    predecessor ids happen to sort the same way under all three. Here
    `nodes` puts "B" before "A" while `edges` declares A's edge first and
    "A" sorts first alphabetically, so edge order and alphabetical order
    both give `("A", "B")` and only route order gives the `("B", "A")` this
    asserts. An implementation returning `tuple(sorted(sources))`, or one
    walking `route.edges` in declaration order, fails this test and passes
    the one above -- which is the gap this test closes.

    `route.nodes` need not name "T" for `predecessors` to answer: the
    function never looks the target up, it only uses `module_id` to filter
    edges by target, so the fixture leaves it out.
    """
    route = ResolvedRoute(
        profile_id="P",
        selection_id="S",
        nodes=(RouteNode("RN-B", "B", 1), RouteNode("RN-A", "A", 2)),
        edges=(Edge("A", "T", EdgeType.REQUIRED), Edge("B", "T", EdgeType.REQUIRED)),
    )

    assert predecessors(route, "T") == ("B", "A")


def test_a_named_object_boundary_blocks_until_an_accepted_input_owns_one() -> None:
    """§46.1 as data: T's only input edge is soft, so without the boundary T
    runs RESTRICTED beside an unrun S; with it T is BLOCKED until S, which
    owns an accepted object, is accepted. An input owning another object
    meets nothing."""
    route = ResolvedRoute(
        profile_id="P",
        selection_id="S",
        nodes=(RouteNode("RN-S", "S", 1), RouteNode("RN-T", "T", 2)),
        edges=(Edge("S", "T", EdgeType.ADVISORY),),
    )
    named = NamedObjects(owned={"S": "obj"}, accepted_ids={"T": frozenset({"obj"})})
    edge = route.edges[0]

    assert node_states(route, {})["RN-T"] is NodeState.RESTRICTED
    assert node_states(route, {}, named)["RN-T"] is NodeState.BLOCKED
    assert frontier(route, {}, named) == ["RN-S"]
    assert lite_object_unmet(route, {}, "T", named) == (edge,)
    done = {"RN-S": NodeResult()}
    assert node_states(route, done, named)["RN-T"] is NodeState.RUNNABLE
    assert lite_object_unmet(route, done, "T", named) == ()
    other = NamedObjects(owned={"S": "else"}, accepted_ids=named.accepted_ids)
    assert node_states(route, done, other)["RN-T"] is NodeState.BLOCKED
    assert lite_object_unmet(route, done, "T", other) == ()
    assert lite_object_unmet(route, {}, "S", named) == ()


def test_an_object_carried_by_the_edge_meets_a_named_boundary() -> None:
    route = ResolvedRoute(
        profile_id="P",
        selection_id="S",
        nodes=(RouteNode("RN-S", "S", 1), RouteNode("RN-T", "T", 2)),
        edges=(Edge("S", "T", EdgeType.ADVISORY),),
    )
    named = NamedObjects(
        owned={"S": "owned"},
        accepted_ids={"T": frozenset({"carried"})},
        carried={("S", "T"): "carried"},
    )
    done = {"RN-S": NodeResult()}
    assert node_states(route, done, named)["RN-T"] is NodeState.RUNNABLE
    assert lite_object_unmet(route, {}, "T", named) == (route.edges[0],)


def _one_edge_profile(edge_type: str) -> dict[str, Any]:
    """The smallest catalog `resolve_route` accepts: two modules, one typed edge.

    Hand-built rather than mutated from the vendored catalog, because the point
    is an edge type the vendored catalog does not declare.
    """
    return {
        "profiles": {
            "P": {
                "pathways": {
                    "S": {
                        "nodes": [
                            {"route_node_id": "RN-A", "module_id": "A", "stage": 1},
                            {"route_node_id": "RN-B", "module_id": "B", "stage": 2},
                        ]
                    }
                },
                "edges": [{"source": "A", "target": "B", "type": edge_type}],
            }
        }
    }


def test_a_profile_with_a_conditional_edge_is_refused_at_resolution() -> None:
    """Invariant 10 freezes predicates and nothing evaluates them, so a
    CONDITIONAL edge would pin a route whose target blocks whatever the evidence
    says -- the state a reader of the pin would read as a condition enforced.
    `_edges_among` refuses before the `Edge` is built, so nothing is resolved
    and nothing can be pinned. CONDITIONAL stays in `BLOCKING` and in the
    bundle's vocabulary (CONTEXT.md); what is refused is a *route* carrying one.
    """
    with pytest.raises(Refusal) as refused:
        resolve_route(_one_edge_profile("CONDITIONAL"), "P", "S")

    assert refused.value.code is RefusalCode.ROUTE_EDGE_UNSUPPORTED


@pytest.mark.parametrize("edge_type", ["REQUIRED", "QA_GATE", "OPTIONAL", "ADVISORY"])
def test_the_four_edge_types_this_engine_evaluates_still_resolve(
    edge_type: str,
) -> None:
    """The guard is one type, not a narrowing of the other four: the same
    profile resolves for every type `_edges_among` does accept."""
    route = resolve_route(_one_edge_profile(edge_type), "P", "S")

    assert route.edges == (Edge("A", "B", EdgeType(edge_type)),)
