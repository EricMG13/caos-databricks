"""The pinned route as a LangGraph graph (spec section 4, D5, D6).

One graph per run, built from the pinned `ResolvedRoute`: one node per route
node in dependency order, chained so nodes run one at a time, then a terminal
node that decides COMPLETE or BLOCKED from the store. LangGraph owns
execution, thread identity and checkpoints; the accepted-attempt ledger stays
the only truth for what ran. Every node re-derives its own state from the
store before doing anything, so a resumed thread, a fresh invocation of the
same run, or a crash between nodes all converge on the same answer
(invariant 6): a node that completed is skipped because it is COMPLETE in the
ledger, not because a checkpoint remembered it.

The chain is the dependency order rather than a fan-out of the typed edges
because the frontier is recomputed from the store at each node: by the time a
node is visited every source of every edge into it has been visited, so
"may this node run now" is exactly the legacy frontier question, answered one
node at a time. Running independent nodes at once is future work (next.md N1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from caos.graph.route import ResolvedRoute, dependency_order

FINISH = "finish"
# What a node pass reports back to the graph; the store holds the real state.
ACCEPTED = "ACCEPTED"
SKIPPED = "SKIPPED"
ENDED = "ENDED"


@dataclass
class RunState:
    """The graph's own view of a run: an audit trail, never an authority."""

    run_id: str
    passes: dict[str, str] = field(default_factory=dict)
    ended: str = ""


NodePass = Callable[[str], str]
Finish = Callable[[], str]
Update = dict[str, Any]


class Step(Protocol):
    """A graph node: the state in, a partial update out (LangGraph's shape)."""

    def __call__(self, state: RunState) -> Update: ...


def build_graph(
    route: ResolvedRoute,
    *,
    node_pass: NodePass,
    finish: Finish,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[RunState, None, RunState, RunState]:
    """Compile the run's graph: `node_pass` per route node, then `finish`."""
    graph: StateGraph[RunState, None, RunState, RunState] = StateGraph(RunState)
    order = [node.route_node_id for node in dependency_order(route.nodes, route.edges)]
    for route_node_id in order:
        graph.add_node(route_node_id, _step(route_node_id, node_pass))
    graph.add_node(FINISH, _terminal(finish))
    graph.add_edge(START, order[0] if order else FINISH)
    for position, route_node_id in enumerate(order):
        following = order[position + 1] if position + 1 < len(order) else FINISH
        # A static edge would fire even after a node ended the run, so the
        # step after every node is a routing decision read from the state.
        graph.add_conditional_edges(
            route_node_id, _after(following), {following: following, END: END}
        )
    graph.add_edge(FINISH, END)
    return graph.compile(checkpointer=checkpointer)


def _after(following: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return END if state.ended else following

    return route


def _step(route_node_id: str, node_pass: NodePass) -> Step:
    def step(state: RunState) -> Update:
        outcome = node_pass(route_node_id)
        passes = {**state.passes, route_node_id: outcome}
        if outcome == ENDED:
            # A validated Blocked handoff ended the run; nothing after it runs.
            return {"passes": passes, "ended": "BLOCKED"}
        return {"passes": passes}

    return step


def _terminal(finish: Finish) -> Step:
    def terminal(state: RunState) -> Update:  # the name is the protocol's
        return {"ended": finish()}

    return terminal


def thread_config(run_id: str) -> RunnableConfig:
    """The LangGraph config that names this run's checkpoint thread."""
    return {"configurable": {"thread_id": run_id}}


def initial_state(run_id: str) -> RunState:
    """The state a run starts from; every node adds its pass to it."""
    return RunState(run_id=run_id)
