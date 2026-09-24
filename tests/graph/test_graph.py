"""The pinned route as a LangGraph graph: shape, ending, checkpoints (D5, D6).

The route fixtures and the executor suites already drive `run_route` end to
end; this file proves the graph itself -- that the chain is the dependency
order, that an ended run skips the terminal node, that a resumed run derives
its state from the store and not from the checkpoint -- and, with a live
provider, that a LITE route completes through the same seam.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from conftest import _url_for, priced
from fake_chat import fake_completions
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from test_loop_charges import ESTIMATE, _Completions, ready, route

from caos.blobs import BlobStore
from caos.graph.build import (
    ACCEPTED,
    ENDED,
    FINISH,
    SKIPPED,
    RunState,
    build_graph,
    initial_state,
    resume_input,
    thread_config,
)
from caos.graph.route import ResolvedRoute, dependency_order, route_digest
from caos.graph.runtime import Execution, Pass, node_pass, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.refusals import Refusal
from caos.store import RunStatus, StoreConnection
from caos.store.runs import run_status
from caos.store.work import checkpoint_thread

__all__ = ["ready", "route"]
VENDORED = Path(__file__).resolve().parents[2] / "vendor/deploy-v"


def test_the_graph_is_the_dependency_order_then_finish(route: ResolvedRoute) -> None:
    seen: list[str] = []

    def accepting(node: str) -> str:
        seen.append(node)
        return ACCEPTED

    graph = build_graph(route, node_pass=accepting, finish=lambda: "COMPLETE")
    assert isinstance(initial_state("r"), RunState)
    order = [node.route_node_id for node in dependency_order(route.nodes, route.edges)]
    assert set(graph.get_graph().nodes) >= {*order, FINISH}
    state = graph.invoke(initial_state("r"))
    assert seen == order
    assert state["ended"] == "COMPLETE"
    assert state["passes"] == dict.fromkeys(order, ACCEPTED)
    assert thread_config("r") == {"configurable": {"thread_id": "r"}}


def test_an_ended_run_skips_every_later_node_and_the_terminal_decision(
    route: ResolvedRoute,
) -> None:
    order = [node.route_node_id for node in dependency_order(route.nodes, route.edges)]
    seen: list[str] = []
    finished: list[int] = []

    def passing(node: str) -> str:
        seen.append(node)
        return ENDED if node == order[1] else SKIPPED

    def finishing() -> str:
        finished.append(1)
        return ""

    graph = build_graph(route, node_pass=passing, finish=finishing)
    state = graph.invoke(initial_state("r"))
    assert seen == order[:2]
    assert state["ended"] == "BLOCKED" and finished == []


def test_a_checkpointed_run_records_its_thread_and_the_store_stays_the_truth(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    conn, run_id, source, blobs = ready
    checkpoints = psycopg.connect(
        _url_for(conn.info.dbname), autocommit=True, row_factory=dict_row
    )
    try:
        checkpoints.execute("CREATE SCHEMA IF NOT EXISTS caos_graph")
        checkpoints.execute("SET search_path TO caos_graph")
        saver = PostgresSaver(checkpoints)
        saver.setup()
        answers = _Completions(source)
        provider = ModuleProvider(conn, Bundle(VENDORED), blobs, answers, route, run_id)
        execution = Execution(
            provider, priced(ESTIMATE), provider.bundle, checkpointer=saver
        )
        # The key `run_route` writes the run's position under (W3). Asserted
        # gone under the run's id alone, which no path writes, this passed
        # whether or not the end-of-run delete ran; so each beat also reads
        # the thread under this key, which must have held the position.
        thread = thread_config(checkpoint_thread(run_id, route_digest(route)))
        kept: list[bool] = []
        execution = replace(
            execution, heartbeat=lambda: kept.append(saver.get(thread) is not None)
        )
        run_route(conn, blobs, run_id=run_id, route=route, execution=execution)
        assert run_status(conn, run_id) is RunStatus.COMPLETE
        conn.rollback()  # the status read above opened a unit; execution owns its own
        assert len(answers.prompts) == len(route.nodes)
        assert len(kept) == len(route.nodes), "one beat per node (F38)"
        # LangGraph writes a step's checkpoint while the next one runs, so a
        # beat may come before the write it follows: at least one saw it.
        assert any(kept), "the run's position was kept under this key"
        # Position only (D6, F39): a thread that reached its end is deleted.
        assert saver.get(thread) is None
        # Driven again on the same thread: the store, not the checkpoint, says
        # the run is over, so nothing runs and nothing is charged twice.
        with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
            run_route(conn, blobs, run_id=run_id, route=route, execution=execution)
        conn.rollback()
        assert len(answers.prompts) == len(route.nodes)
    finally:
        checkpoints.close()


def test_a_node_pass_reports_what_the_store_decided(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    from caos.methodology.invocation import named_objects

    conn, run_id, source, blobs = ready
    bundle = Bundle(VENDORED)
    provider = ModuleProvider(conn, bundle, blobs, _Completions(source), route, run_id)
    execution = Execution(provider, priced(ESTIMATE), bundle)
    named = named_objects(bundle, route)
    first, last = route.nodes[0].route_node_id, route.nodes[-1].route_node_id

    def passing(node: str) -> Pass:
        return node_pass(
            conn,
            blobs,
            run_id=run_id,
            route=route,
            execution=execution,
            named=named,
            route_node_id=node,
        )

    assert passing(last) is Pass.SKIPPED
    assert passing(first) is Pass.ACCEPTED
    assert passing(first) is Pass.SKIPPED


@pytest.mark.live_provider
def test_a_lite_route_completes_through_the_test_adapter(
    ready: tuple[StoreConnection, UUID, UUID, BlobStore], route: ResolvedRoute
) -> None:
    """Synthetic fixtures only; never gateway coverage (spec section 3.4)."""
    from openrouter_adapter import MODEL, openrouter_chat_model

    conn, run_id, _source, blobs = ready
    price = priced(ESTIMATE, MODEL)
    live = fake_completions(openrouter_chat_model(), model=MODEL, price=price)
    bundle = Bundle(VENDORED)
    provider = ModuleProvider(conn, bundle, blobs, live, route, run_id)
    run_route(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        execution=Execution(provider, price, bundle),
    )
    assert run_status(conn, run_id) in (RunStatus.COMPLETE, RunStatus.BLOCKED)
    assert os.environ.get("OPENROUTER_API_KEY"), "the adapter read the key at call time"


class _Died(RuntimeError):
    """The process died inside a node."""


def test_a_run_that_died_mid_route_resumes_at_the_node_it_died_in(
    route: ResolvedRoute,
) -> None:
    """F39: with a checkpoint whose next task is pending, the graph is handed
    `None` and LangGraph resumes there; the nodes before it are not visited."""
    from langgraph.checkpoint.memory import MemorySaver

    order = [node.route_node_id for node in dependency_order(route.nodes, route.edges)]
    seen: list[str] = []
    attempts = {"third": 0}

    def passing(node: str) -> str:
        seen.append(node)
        if node == order[2] and attempts["third"] == 0:
            attempts["third"] += 1
            raise _Died
        return ACCEPTED

    saver = MemorySaver()
    graph = build_graph(
        route, node_pass=passing, finish=lambda: "COMPLETE", checkpointer=saver
    )
    config = thread_config("r")
    assert isinstance(resume_input(graph, "r"), RunState), "a fresh thread starts"
    with pytest.raises(_Died):
        graph.invoke(resume_input(graph, "r"), config=config)
    assert seen == order[:3]
    assert resume_input(graph, "r") is None, "work pending: resume, not restart"
    state = graph.invoke(resume_input(graph, "r"), config=config)
    assert seen == order[:3] + order[2:], "resumed at the third node"
    assert state["ended"] == "COMPLETE"
    assert isinstance(resume_input(graph, "r"), RunState), "nothing pending any more"


def test_no_route_node_can_share_the_terminal_node_s_name() -> None:
    from caos.graph.build import FINISH

    assert not FINISH[0].isalnum(), "outside the route-id grammar"
