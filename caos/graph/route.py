"""Route resolution: pure, from typed edges, and pinned once.

`docs/DECISIONS.md` §2 is the reason this module is built before anything that
depends on it. The predecessor resolved routes from `navigation.dependencies` --
97 untyped pairs meant for display -- so 25 OPTIONAL and 22 ADVISORY edges were
enforced as mandatory, the single QA_GATE did not gate, and RESTRICTED could not
occur. Nothing here reads that list; the typed set is `profile["edges"]`.

Three rules carry the phase:

*Blocking and soft.* REQUIRED, CONDITIONAL and QA_GATE block. OPTIONAL and
ADVISORY degrade their target to RESTRICTED -- which **runs**, carrying its
limitation forward -- unless the edge's source module is READY or
READY_WITH_LIMITATIONS, at which point the evidence exists and running without it
would discard what the case has.

*Readiness is read, never passed.* It comes from the accepted CP-0 artifact's
readiness rows, typed as a `NodeResult` (`docs/DECISIONS.md` §12, adopting
CAOS-Final §18). A caller able to assert readiness could assert its way past the
gate that measures it.

*Resolution is pure.* No I/O, no clock. The resolved route is digested at the
plan gate and execution reads only the pin, so a replay from the same pins takes
the same path (invariant 10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Any

from caos.methodology.host_pin import HOST_MANIFEST_SHA256
from caos.refusals import Refusal, RefusalCode


class EdgeType(StrEnum):
    """The bundle's words, unchanged (CONTEXT.md)."""

    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    QA_GATE = "QA_GATE"
    OPTIONAL = "OPTIONAL"
    ADVISORY = "ADVISORY"


class NodeState(StrEnum):
    """The bundle's four. RESTRICTED runs; it is not "degraded" or "partial"."""

    COMPLETE = "COMPLETE"
    RUNNABLE = "RUNNABLE"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


BLOCKING = frozenset({EdgeType.REQUIRED, EdgeType.CONDITIONAL, EdgeType.QA_GATE})
SOFT = frozenset({EdgeType.OPTIONAL, EdgeType.ADVISORY})
# The two CP-0 readiness statuses that mean the evidence is there. The other two
# the schema declares -- CONDITIONAL, BLOCKED -- leave a soft edge soft.
READY = frozenset({"READY", "READY_WITH_LIMITATIONS"})

# The run's source-readiness gate. Named once here because three callers need it:
# the reader below, the runtime's artifact fetch, and `ModuleProvider.execute` in
# `caos/methodology/runner.py`, where "only the gate is asked for a verdict" is
# decided. `executor.py` never names it -- the assignment it is handed already
# says what this module must cover.
GATE_MODULE = "CP-0"

# The host's model extension. `SYSTEM_SPEC.md` §6.2: CP-CF is appended at stage
# 100 with synthesised REQUIRED edges naming every artifact owner it reads, so
# CP-2G completing alone does not release it. No catalog is edited.
MODEL_MODULE = "CP-CF"
MODEL_STAGE = 100
MODEL_OWNERS = ("CP-1", "CP-2G", "CP-4")
RESEARCH_STAGE = 99


@dataclass(frozen=True, slots=True)
class RouteNode:
    """One module's place in one route."""

    route_node_id: str
    module_id: str
    stage: int


@dataclass(frozen=True, slots=True)
class Edge:
    """A typed dependency between two modules of this route."""

    source: str
    target: str
    type: EdgeType


@dataclass(frozen=True, slots=True)
class NodeResult:
    """What the engine reads from one accepted artifact, and nothing more.

    A node's presence in the accepted mapping is what makes it COMPLETE; this
    value carries the two facts some nodes' artifacts add. `readiness` is the
    gate's `(module_id, readiness_status)` rows, read only from the CP-0 node;
    `qa_status` is the module's own QA verdict, which meets a QA_GATE edge only
    when it is `Passed` (F03). A canonical record reduces to this, so the
    engine never reads the Markdown.
    """

    readiness: tuple[tuple[str, str], ...] = ()
    qa_status: str | None = None
    # `(module_id, why_now_or_blocker)` for each gate row that is CONDITIONAL or
    # BLOCKED, read from the CP-0 node like `readiness`. No state turns on it:
    # the readiness status alone decides whether a node may run, and this is the
    # reason the gate wrote beside that status, carried so a reader can be told
    # which source the verdict asked for (§61) rather than only that it refused.
    blockers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class NamedObjects:
    """The vendor's named-object boundary, handed in as data (§46.1).

    `owned` maps a module to the object its catalog artifact contract owns, and
    `carried` maps a catalog edge `(source, target)` to the object it declares
    it carries (`accepted_object_id`) -- an input meets the boundary through
    either, since a screen can carry more objects than the one it owns;
    `accepted_ids` maps a module whose verified LITE compatibility block
    retains `NAMED_LITE_OBJECT_ACCEPTED` for this route's profile to the object
    ids it accepts. Read from verified bundle bytes by
    `caos.methodology.invocation.named_objects`, never here: this module
    does no I/O, and nothing here names a module or an object.
    """

    owned: Mapping[str, str]
    accepted_ids: Mapping[str, frozenset[str]]
    carried: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def offers(self, source: str, target: str) -> frozenset[str]:
        """The objects `source`'s accepted artifact offers `target`."""
        return frozenset(
            value
            for value in (self.owned.get(source), self.carried.get((source, target)))
            if value is not None
        )


@dataclass(frozen=True, slots=True)
class RouteExtensions:
    """The host-declared additions to a pathway, which travel together.

    `SYSTEM_SPEC.md` section 4 listed these as separate keyword arguments to
    `resolve_route`; corrected in place by `docs/DECISIONS.md` section 21, which
    also says why. They are one thing -- how this route was extended beyond the
    catalog's own node list -- and each is part of the pinned digest.
    """

    research_brief: Mapping[str, Any] | None = None
    model_extension: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """A closed node list in dependency order, its typed edges, its predicates."""

    profile_id: str
    selection_id: str
    nodes: tuple[RouteNode, ...]
    edges: tuple[Edge, ...]
    predicates: tuple[tuple[str, str], ...] = ()


def resolve_route(
    catalog: Mapping[str, Any],
    profile_id: str,
    selection_id: str,
    *,
    extensions: RouteExtensions | None = None,
    predicates: Mapping[str, str] | None = None,
) -> ResolvedRoute:
    """The pathway's nodes and the typed edges among them. Pure; no I/O.

    `extensions.research_brief` appends CP-DR at stage 99 and
    `extensions.model_extension` appends CP-CF at stage 100, both host-declared
    and neither editing the catalog (`docs/DECISIONS.md` §6).

    An extension naming a module the pathway already runs is refused
    `ROUTE_DUPLICATE_MODULE` by `dependency_order`, rather than appending a
    second node for it. Skipping the append would be the quieter answer and the
    worse one: a caller asking for this pathway *with* a research brief means
    the brief to reach CP-DR, and a route that ignored the extension would say
    nothing about having ignored it.
    """
    extended = extensions or RouteExtensions()
    profile = _profile(catalog, profile_id)
    pathway = _pathway(profile, selection_id)

    nodes = [
        RouteNode(
            route_node_id=str(node["route_node_id"]),
            module_id=str(node["module_id"]),
            stage=int(node["stage"]),
        )
        for node in pathway["nodes"]
    ]
    if extended.research_brief is not None:
        nodes.append(_extension_node(profile_id, selection_id, "CP-DR", RESEARCH_STAGE))
    if extended.model_extension:
        nodes.append(_model_node(profile_id, selection_id, nodes))

    edges = _edges_among(profile, {node.module_id for node in nodes})
    if extended.model_extension:
        edges += tuple(
            Edge(source=owner, target=MODEL_MODULE, type=EdgeType.REQUIRED)
            for owner in MODEL_OWNERS
        )
    frozen = dict(predicates or {})
    if extended.model_extension:
        frozen["host_manifest_sha256"] = HOST_MANIFEST_SHA256
        edges += (Edge(GATE_MODULE, MODEL_MODULE, EdgeType.REQUIRED),)
    return ResolvedRoute(
        profile_id=profile_id,
        selection_id=selection_id,
        nodes=dependency_order(nodes, edges),
        edges=edges,
        predicates=tuple(sorted(frozen.items())),
    )


def dependency_order(
    nodes: Sequence[RouteNode], edges: Sequence[Edge]
) -> tuple[RouteNode, ...]:
    """Nodes ordered so every edge's source precedes its target.

    Ties break on stage then route node id, so the order is a function of the
    route rather than of dictionary iteration -- which is what lets the digest
    mean something.
    """
    # One node per module, checked before anything is keyed by module. Every
    # reader downstream assumes it -- `node_states` builds its complete set from
    # `module_id`, `readiness_from` returns at the first CP-0 node -- and so did
    # the two dicts below, which is what made a second node for one module
    # disappear into a key collision instead of into a refusal. A closed node
    # list (invariant 10) cannot lose a member that way.
    modules = [node.module_id for node in nodes]
    if len(set(modules)) != len(modules):
        raise Refusal(RefusalCode.ROUTE_DUPLICATE_MODULE)

    incoming = {node.module_id: 0 for node in nodes}
    for edge in edges:
        incoming[edge.target] += 1

    remaining = {node.module_id: node for node in nodes}
    ordered: list[RouteNode] = []
    while remaining:
        ready = sorted(
            (node for module_id, node in remaining.items() if not incoming[module_id]),
            key=lambda node: (node.stage, node.route_node_id),
        )
        if not ready:
            # The catalog is a DAG; a cycle means the pin would never resolve.
            raise Refusal(RefusalCode.ROUTE_HAS_A_CYCLE)
        for node in ready:
            ordered.append(node)
            del remaining[node.module_id]
            for edge in edges:
                if edge.source == node.module_id:
                    incoming[edge.target] -= 1
    return tuple(ordered)


def node_states(
    route: ResolvedRoute,
    accepted: Mapping[str, NodeResult],
    named: NamedObjects | None = None,
) -> dict[str, NodeState]:
    """Each node's state, recomputed from the accepted attempts. Never stored.

    With `named`, a node retaining the named-object boundary is BLOCKED until
    an accepted direct input offers one of its accepted objects (§46.1),
    whatever its edges' types say.
    """
    readiness = readiness_from(route, accepted)
    complete = {
        node.module_id for node in route.nodes if node.route_node_id in accepted
    }
    passed = _qa_passed(route, accepted)

    states = {}
    for node in route.nodes:
        if node.module_id in complete:
            states[node.route_node_id] = NodeState.COMPLETE
            continue
        unmet = _unmet(route, node.module_id, complete, passed)
        state = _state_for(node.module_id, unmet, readiness)
        if named is not None and not _named_object_met(
            route, complete, node.module_id, named
        ):
            state = NodeState.BLOCKED
        states[node.route_node_id] = state
    return states


def lite_object_unmet(
    route: ResolvedRoute,
    accepted: Mapping[str, NodeResult],
    module_id: str,
    named: NamedObjects,
) -> tuple[Edge, ...]:
    """The edges into `module_id` whose source would meet its named-object
    boundary once accepted, while none has been (§46.1).

    `()` when the module retains no boundary or an accepted direct input
    already owns an accepted object. A boundary no source on the route could
    meet is also `()` here, and `node_states` still holds it BLOCKED: the
    reason is the absence of any owner, not an edge.
    """
    complete = {n.module_id for n in route.nodes if n.route_node_id in accepted}
    if _named_object_met(route, complete, module_id, named):
        return ()
    wanted = named.accepted_ids[module_id]
    return tuple(
        edge
        for edge in route.edges
        if edge.target == module_id and named.offers(edge.source, module_id) & wanted
    )


def frontier(
    route: ResolvedRoute,
    accepted: Mapping[str, NodeResult],
    named: NamedObjects | None = None,
) -> list[str]:
    """The nodes that may run now: RUNNABLE and RESTRICTED, in route order."""
    states = node_states(route, accepted, named)
    return [
        node.route_node_id
        for node in route.nodes
        if states[node.route_node_id] in {NodeState.RUNNABLE, NodeState.RESTRICTED}
    ]


def reachable(route: ResolvedRoute) -> Mapping[str, frozenset[str]]:
    """Every node each node can reach along the route's typed edges.

    Pure, like everything else here, and over **every** edge type rather than
    the blocking ones alone. A soft edge is exactly the case this exists for:
    the frontier may offer a node and one of its own optional upstreams at the
    same time, and that pair is the one that must not run together.
    """
    forward: dict[str, set[str]] = {node.route_node_id: set() for node in route.nodes}
    for edge in route.edges:
        forward.setdefault(edge.source, set()).add(edge.target)
    reach: dict[str, frozenset[str]] = {}

    def walk(node: str) -> frozenset[str]:
        if node in reach:
            return reach[node]
        reach[node] = frozenset()  # a cycle cannot occur; resolution refuses one
        seen: set[str] = set()
        for target in forward.get(node, ()):
            seen.add(target)
            seen |= walk(target)
        reach[node] = frozenset(seen)
        return reach[node]

    for node in route.nodes:
        walk(node.route_node_id)
    return reach


def independent_batch(route: ResolvedRoute, ready: Sequence[str]) -> list[str]:
    """The nodes of `ready` that may be executed at the same time.

    Greedy in route order, which is what keeps it deterministic: the same
    pinned route and the same accepted set choose the same batch, so replay
    takes the same path (invariant 10) even though the nodes overlap in time.

    The rule is that no chosen node reaches another, in either direction. It is
    not a tidiness constraint, it is a money one: `execute_handoff` binds an
    attempt to the upstream accepted when its prompt was built and refuses when
    another of its inputs is accepted during the call, so running a node beside
    one of its own transitive upstreams buys a billed attempt that is then
    thrown away. The frontier can offer such a pair whenever the edge between
    them is soft, because a soft edge does not hold its target back.

    Nodes left out are not lost: they are simply still in the frontier on the
    next pass, which is recomputed from the store like every other pass.
    """
    reach = reachable(route)
    chosen: list[str] = []
    for node in ready:
        related = reach[node]
        if any(other in related or node in reach[other] for other in chosen):
            continue
        chosen.append(node)
    return chosen


def waiting_on(
    route: ResolvedRoute, accepted: Mapping[str, NodeResult], route_node_id: str
) -> tuple[Edge, ...]:
    """Every dependency this node is still waiting for, typed.

    The reason behind a state. A surface reporting BLOCKED with no cause tells a
    reader the run is stuck without telling them what it is stuck on, and the
    types are what separate a node waiting for a module from one waiting for a
    person at the QA gate.

    A node the route does not carry is `ORCHESTRATION_NODE_NOT_IN_ROUTE`. The
    node list is closed (invariant 10), so asking about one outside it is a
    fact about the route rather than an accident -- and the alternative was
    `StopIteration`, which is untyped here and disappears silently if it is
    ever raised inside a generator.
    """
    complete = {
        node.module_id for node in route.nodes if node.route_node_id in accepted
    }
    node = next((n for n in route.nodes if n.route_node_id == route_node_id), None)
    if node is None:
        raise Refusal(RefusalCode.ORCHESTRATION_NODE_NOT_IN_ROUTE)
    return _unmet(route, node.module_id, complete, _qa_passed(route, accepted))


def limitations_of(
    route: ResolvedRoute, accepted: Mapping[str, NodeResult], route_node_id: str
) -> tuple[Edge, ...]:
    """The soft edges a RESTRICTED node is running without.

    A node that carries a limitation forward has to be able to say which one:
    "RESTRICTED" on an artifact with no cause attached is not auditable.
    """
    return tuple(
        edge for edge in waiting_on(route, accepted, route_node_id) if edge.type in SOFT
    )


def predecessors(route: ResolvedRoute, module_id: str) -> tuple[str, ...]:
    """The modules with an edge into this one, in route order.

    Route order rather than edge order, so a prompt assembled from this reads
    in the order the route runs and two runs of the same pin compose the same
    prompt. Edge type is not consulted: a soft edge's source is still a module
    this one was meant to build on, and whether it ran is answered by whether
    it has an accepted artifact.
    """
    sources = {edge.source for edge in route.edges if edge.target == module_id}
    return tuple(node.module_id for node in route.nodes if node.module_id in sources)


def readiness_from(
    route: ResolvedRoute, accepted: Mapping[str, NodeResult]
) -> dict[str, str]:
    """Per-module readiness, read from the accepted gate artifact and nowhere else."""
    for node in route.nodes:
        if node.module_id != GATE_MODULE:
            continue
        result = accepted.get(node.route_node_id)
        return {} if result is None else dict(result.readiness)
    return {}


def blockers_from(
    route: ResolvedRoute, accepted: Mapping[str, NodeResult]
) -> dict[str, str]:
    """Per-module blocker text, from the accepted gate artifact and nowhere else.

    Keyed exactly like `readiness_from`, and holding a module only where the
    gate did not clear it: a module absent here either was cleared or was never
    ruled on, and a reader must not read absence as "no reason given".
    """
    for node in route.nodes:
        if node.module_id != GATE_MODULE:
            continue
        result = accepted.get(node.route_node_id)
        return {} if result is None else dict(result.blockers)
    return {}


NODE_FIELDS = ("route_node_id", "module_id", "stage")
EDGE_FIELDS = ("source", "target", "type")


def route_json(route: ResolvedRoute) -> dict[str, Any]:
    """The route as JSON rows, each in `NODE_FIELDS` / `EDGE_FIELDS` order.

    One spelling of what a serialised route carries, for the two byte forms
    that must never drift apart in content: `route_digest` below hashes these
    rows with its edges sorted, and the stored pin
    (`caos/store/routes.py::_canonical`) keys each row by its field name and
    keeps the route's own edge order. Both forms are pinned -- the digest by
    invariant 10 and by every `run_routes.route_digest` already written, the
    stored shape by every row that must still read back -- so this returns what
    they share and leaves each caller to spell its own shape.
    """
    return {
        "profile_id": route.profile_id,
        "selection_id": route.selection_id,
        "nodes": [
            [node.route_node_id, node.module_id, node.stage] for node in route.nodes
        ],
        "edges": [[edge.source, edge.target, edge.type.value] for edge in route.edges],
        # Passed through rather than coerced to lists: the stored pin is read
        # back and validated, and `list()` over a malformed pair would turn a
        # shape `_decode` refuses into one it accepts.
        "predicates": route.predicates,
    }


def route_digest(route: ResolvedRoute) -> str:
    """The digest pinned at the plan gate. A function of the route alone."""
    rows = route_json(route)
    rows["edges"] = sorted(rows["edges"])
    rows["predicates"] = [list(pair) for pair in rows["predicates"]]
    canonical = dumps(rows, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _state_for(
    module_id: str, unmet: tuple[Edge, ...], readiness: Mapping[str, str]
) -> NodeState:
    """The gate's verdict first, then the soft-edge rule.

    The gate decides whether a module may run at all: CONDITIONAL and BLOCKED
    are both "not cleared", and the difference between them is the reason, which
    the verdict carries and this does not need. READY_WITH_LIMITATIONS runs and
    carries the limitation forward, which is what RESTRICTED means. A module the
    verdict does not mention -- every module, until the gate is accepted -- is
    left to its edges.
    """
    own = readiness.get(module_id)
    if own is not None and own not in READY:
        return NodeState.BLOCKED
    for edge in unmet:
        if edge.type in BLOCKING:
            return NodeState.BLOCKED
        if readiness.get(edge.source) in READY:
            # The evidence this soft edge would have carried exists. Running
            # without it would discard what the case already has.
            return NodeState.BLOCKED
    if own == "READY_WITH_LIMITATIONS":
        return NodeState.RESTRICTED
    return NodeState.RESTRICTED if unmet else NodeState.RUNNABLE


def _unmet(
    route: ResolvedRoute, module_id: str, complete: set[str], passed: set[str]
) -> tuple[Edge, ...]:
    """Edges into this module not yet met. A QA_GATE edge is met by its
    source's validated `Passed`, never by the source merely being accepted (F03).
    """
    return tuple(
        edge
        for edge in route.edges
        if edge.target == module_id
        and (
            edge.source not in complete
            or (edge.type is EdgeType.QA_GATE and edge.source not in passed)
        )
    )


def _named_object_met(
    route: ResolvedRoute, complete: set[str], module_id: str, named: NamedObjects
) -> bool:
    """True unless `module_id` retains the boundary and no accepted direct
    input offers one of the object ids it accepts."""
    wanted = named.accepted_ids.get(module_id)
    if wanted is None:
        return True
    return any(
        edge.target == module_id
        and edge.source in complete
        and bool(named.offers(edge.source, module_id) & wanted)
        for edge in route.edges
    )


def _qa_passed(route: ResolvedRoute, accepted: Mapping[str, NodeResult]) -> set[str]:
    """Modules whose accepted artifact carries the QA outcome `Passed`."""
    return {
        node.module_id
        for node in route.nodes
        if (result := accepted.get(node.route_node_id)) is not None
        and result.qa_status == "Passed"
    }


def _profile(catalog: Mapping[str, Any], profile_id: str) -> Mapping[str, Any]:
    profiles = catalog.get("profiles")
    if not isinstance(profiles, Mapping) or profile_id not in profiles:
        raise Refusal(RefusalCode.ROUTE_PROFILE_UNKNOWN)
    profile = profiles[profile_id]
    if not isinstance(profile, Mapping):
        raise Refusal(RefusalCode.ROUTE_PROFILE_UNKNOWN)
    return profile


def _pathway(profile: Mapping[str, Any], selection_id: str) -> Mapping[str, Any]:
    pathways = profile.get("pathways")
    if not isinstance(pathways, Mapping) or selection_id not in pathways:
        raise Refusal(RefusalCode.ROUTE_SELECTION_UNKNOWN)
    pathway = pathways[selection_id]
    if not isinstance(pathway, Mapping):
        raise Refusal(RefusalCode.ROUTE_SELECTION_UNKNOWN)
    return pathway


def _edges_among(profile: Mapping[str, Any], modules: set[str]) -> tuple[Edge, ...]:
    """`profile["edges"]`, restricted to this route's nodes. Never
    `navigation.dependencies`, which carries no type at all.

    A CONDITIONAL edge is refused rather than resolved. Invariant 10 freezes a
    route's predicates and nothing evaluates them, so such an edge would pin a
    route whose target blocks whatever the evidence says -- and a reader of the
    pin would take the frozen predicate for an enforced condition. The vendored
    catalog declares none (`tests/test_bundle_pin.py::test_the_vendored_catalog_
    carries_no_edge_this_engine_cannot_evaluate`), so this refuses at the first
    upstream build that puts one **on a resolved route**: the membership filter
    above runs first, so an edge whose source or target is outside the resolved
    node set is skipped like any other out-of-route edge, and a build carrying
    one off every pathway refuses nothing. That is the right scope -- an edge no
    pin carries misleads no reader of a pin -- and it is the scope the ledger
    entry states. The docstring said "introduces one" until the Task 10.2
    acceptance review read the two against the code. `CONDITIONAL` stays in `BLOCKING`
    and in the bundle's vocabulary (CONTEXT.md): it remains a CP-0 *verdict*,
    and only an *edge* of that type is refused.
    """
    edges: list[Edge] = []
    for edge in profile["edges"]:
        if edge["source"] not in modules or edge["target"] not in modules:
            continue
        edge_type = EdgeType(edge["type"])
        if edge_type is EdgeType.CONDITIONAL:
            raise Refusal(RefusalCode.ROUTE_EDGE_UNSUPPORTED)
        edges.append(
            Edge(
                source=str(edge["source"]),
                target=str(edge["target"]),
                type=edge_type,
            )
        )
    return tuple(edges)


def _extension_node(
    profile_id: str, selection_id: str, module_id: str, stage: int
) -> RouteNode:
    return RouteNode(
        route_node_id=f"RN-{profile_id}-{selection_id}-{stage}-{module_id}",
        module_id=module_id,
        stage=stage,
    )


def _model_node(
    profile_id: str, selection_id: str, nodes: Sequence[RouteNode]
) -> RouteNode:
    """CP-CF, refused unless every artifact owner it reads is on the route.

    Refusing here is the point: dropping the edge instead would run CP-CF on
    inputs that are not there, and pinning it would put that into the digest a
    replay is bound to.
    """
    present = {node.module_id for node in nodes}
    if not set(MODEL_OWNERS) <= present:
        raise Refusal(RefusalCode.ROUTE_EXTENSION_OWNER_MISSING)
    return _extension_node(profile_id, selection_id, MODEL_MODULE, MODEL_STAGE)
