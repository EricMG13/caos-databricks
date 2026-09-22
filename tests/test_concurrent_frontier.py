"""Completion Phase 13.1: a wide frontier finishes in the longest node's time.

The plan writes this as `await gather(...)` and the ledger entry as "the `for`
becomes a `gather`". What it turns out to need first is a rule the spec does
not state: **which** ready nodes may run beside each other. The frontier offers
every node whose *blocking* inputs are met, and a soft edge does not block --
so the frontier can offer a node together with one of its own optional
upstreams, and `execute_handoff` refuses an attempt whose input was accepted
while its call was in flight. Running that pair together buys a billed attempt
that is thrown away, which is money spent with nobody choosing to spend it.

`independent_batch` is that rule, and it is pure: the same pinned route and the
same accepted set choose the same batch, so replay takes the same path
(invariant 10) even though the nodes overlap in time.
"""

from __future__ import annotations

from caos.graph.route import (
    Edge,
    EdgeType,
    ResolvedRoute,
    RouteNode,
    independent_batch,
    reachable,
)


def _route(*edges: tuple[str, str, EdgeType]) -> ResolvedRoute:
    """A route over the nodes the edges mention, in the order first seen."""
    names: list[str] = []
    for source, target, _type in edges:
        for name in (source, target):
            if name not in names:
                names.append(name)
    return ResolvedRoute(
        profile_id="p",
        selection_id="s",
        nodes=tuple(
            RouteNode(name, f"CP-{name}", index) for index, name in enumerate(names)
        ),
        edges=tuple(Edge(source, target, type) for source, target, type in edges),
    )


def test_reachability_is_transitive_and_over_every_edge_type() -> None:
    """A soft edge is exactly the case this exists for, so it counts. Reading
    only the blocking edges would call the pair this rule protects independent,
    which is the one wrong answer available."""
    route = _route(
        ("A", "B", EdgeType.REQUIRED),
        ("B", "C", EdgeType.OPTIONAL),
        ("D", "E", EdgeType.ADVISORY),
    )

    reach = reachable(route)

    assert reach["A"] == {"B", "C"}
    assert reach["B"] == {"C"}
    assert reach["C"] == frozenset()
    assert reach["D"] == {"E"}


def test_a_node_does_not_run_beside_its_own_transitive_upstream() -> None:
    """The money rule. `A -> B` soft means the frontier offers both, and an
    attempt for B whose input A is accepted mid-call is billed and refused."""
    route = _route(("A", "B", EdgeType.OPTIONAL))

    assert independent_batch(route, ["A", "B"]) == ["A"]


def test_a_node_does_not_run_beside_an_indirect_upstream_either() -> None:
    """Two hops is the same hazard as one: B's acceptance moves A's inputs
    whether or not the edge between them is direct."""
    route = _route(("A", "B", EdgeType.REQUIRED), ("B", "C", EdgeType.OPTIONAL))

    assert independent_batch(route, ["A", "C"]) == ["A"]


def test_genuinely_unrelated_nodes_run_together() -> None:
    """Without this the rule could be satisfied by always returning one node,
    which would make the loop sequential again and the phase's exit check
    unmeetable while every other test here still passed."""
    route = _route(
        ("A", "B", EdgeType.REQUIRED),
        ("C", "D", EdgeType.REQUIRED),
        ("E", "F", EdgeType.REQUIRED),
    )

    assert independent_batch(route, ["A", "C", "E"]) == ["A", "C", "E"]


def test_the_batch_is_chosen_in_route_order_so_replay_takes_the_same_path() -> None:
    """Invariant 10 survives the nodes overlapping in time: what changes is
    when they run, never which. The greedy choice is over `ready`, which the
    frontier already yields in route order."""
    route = _route(("A", "B", EdgeType.OPTIONAL), ("A", "C", EdgeType.OPTIONAL))

    assert independent_batch(route, ["A", "B", "C"]) == ["A"]
    # B and C do not reach one another, so with A already accepted they pair.
    assert independent_batch(route, ["B", "C"]) == ["B", "C"]


def test_a_node_left_out_is_not_lost_it_is_next_passs_frontier() -> None:
    """The rule drops nodes rather than reordering or refusing them, and the
    loop recomputes the frontier from the store every pass, so a dropped node
    is offered again as soon as the one it waited for is accepted."""
    route = _route(("A", "B", EdgeType.OPTIONAL))

    first = independent_batch(route, ["A", "B"])
    assert first == ["A"]
    assert independent_batch(route, ["B"]) == ["B"]


def test_an_empty_frontier_batches_to_nothing() -> None:
    assert independent_batch(_route(("A", "B", EdgeType.REQUIRED)), []) == []
