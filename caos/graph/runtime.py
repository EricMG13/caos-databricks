"""One node at a time over the pinned route; recovery is recomputation.

Execution state *is* the accepted-attempt ledger (legacy decision §3, refined
by D6): LangGraph drives the nodes and checkpoints its own position, but every
pass recomputes `node_states` over the rows that survived, and a node that
completed is not run again because it is COMPLETE, not because something
remembered it. `caos/graph/build.py` is the graph; this module is what each of
its nodes does, and what the terminal node decides.

The order inside one pass is deliberate and is invariant 8's shape:

    check the context  ->  start the attempt  ->  reserve  ->  call  ->  accept

The attempt row exists before the call because it is the identity the call is
charged against. The reservation is taken before the call and commits on its own,
because a call that reached the provider is billable whether or not this process
lived to record it (`caos/store/budget.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver

from caos.blobs import BlobStore
from caos.graph.route import (
    GATE_MODULE,
    EdgeType,
    NamedObjects,
    NodeResult,
    NodeState,
    ResolvedRoute,
    frontier,
    node_states,
)
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import (
    Replayed,
    Verdict,
    accepted_projections,
    blocked_verdict,
    replay_billed,
    second_attempt_due,
    unexplained_charge,
)
from caos.methodology.invocation import named_objects
from caos.methodology.verification import AcceptedRow
from caos.pricing import ModelPrice, priced_request, worst_case
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.budget import ceiling_of, reserve
from caos.store.gates import execution_input

# `artifact_digests` is re-exported: it now lives in the store (no import cycle).
from caos.store.outcomes import (
    accepted_rows,
    execution_reads,
    record_refusal,
    require_idle,
)
from caos.store.outcomes import artifact_digests as artifact_digests
from caos.store.runs import (
    Accepted,
    accept_attempt,
    block_run,
    complete_run,
    run_status,
    start_attempt,
)
from caos.store.work import Lease, holds_lease


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """What one module's execution produced: an artifact, what it cost, and who
    produced it.

    The identity travels beside the charge because they are recorded together
    and for the same reason: a run has to be able to say afterwards what was
    spent and what spent it (invariant 3).
    """

    artifact_sha256: str
    charge: Decimal
    model: str
    generation_id: str
    # A canonical pin's host record and the call's diagnostic body (§42).
    record_sha256: str | None = None
    diagnostic_sha256: str | None = None


class Provider(Protocol):
    """The seam the module provider fills with a real gateway call.

    `model` is the configured model identity the call is billed as; a run's price
    must be for exactly that model.
    """

    @property
    def model(self) -> str: ...

    def check_context(self, route_node_id: str, module_id: str) -> int:
        """Refuse a context the call could not carry (`CONTEXT_OVER_CEILING`),
        before the loop starts an attempt or reserves anything (§45.3), and
        return the size in bytes of the request it would send -- what the
        reservation is priced on (Task 8.2)."""

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        """Call for this reserved attempt and record its own call outcome --
        the charge, the producer identity and the diagnostic address -- before
        returning, as `execute_handoff` does the moment the provider answers.

        The loop does not record it a second time: a call that reached the
        provider must be billed by the unit that made it, because only that
        unit is still running when the answer arrives (invariant 6).
        """


@dataclass(frozen=True, slots=True)
class Execution:
    """How this run executes: who to ask, and what to set aside before asking.

    One thing rather than loose arguments, because none is meaningful without
    the others -- a price with no provider reserves against nothing, and a
    provider with no price is a call invariant 8 forbids. Every call reserves
    `priced_request(price, its own request size)`, never a caller's guess (F06);
    `worst_case(price)` is the run's admission check (Task 8.2, §40).
    """

    provider: Provider
    price: ModelPrice
    bundle: Bundle
    # The worker's claim on this run; None is a direct caller (harness, tests),
    # which may drive only a run that was never enqueued (brief 4.3 D3).
    lease: Lease | None = None
    # Where LangGraph keeps the run's thread and its position between nodes
    # (D6). None -- every direct caller, the harness and the suite -- compiles
    # the graph without one: the store is the truth either way.
    checkpointer: BaseCheckpointSaver[str] | None = None
    # Called before each node's pass; the worker beats its heartbeat here.
    heartbeat: Callable[[], None] | None = None


def run_route(
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    execution: Execution,
) -> None:
    """Run the route to its end, or leave it recoverable.

    Every pass recomputes the frontier from the store rather than advancing an
    index, so this is the same function whether it is starting a run or resuming
    one that died three nodes in. Requires an idle, nonautocommit connection;
    owns its frontier reads and never adopts pending caller writes.
    """
    require_idle(conn)
    # Priced for the configured model, or no attempt at all.
    if execution.price.model != getattr(execution.provider, "model", None):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    _affordable(conn, run_id, execution.price)
    route = _execution_route(conn, run_id, route, execution.bundle)
    # Read once from verified bundle bytes, handed to the pure engine (§46.1).
    named = named_objects(execution.bundle, route)
    from caos.graph.build import build_graph, resume_input, thread_config

    def one_pass(route_node_id: str) -> str:
        if execution.heartbeat is not None:
            execution.heartbeat()
        with message_free():
            return node_pass(
                conn,
                blobs,
                run_id=run_id,
                route=route,
                execution=execution,
                named=named,
                route_node_id=route_node_id,
            ).value

    def one_node(route_node_id: str) -> str:
        # An answer refused `HANDOFF_MALFORMED` earns the node one second
        # attempt (D30, the owner's choice under N32): the node's pass runs
        # once more, and the ledger, not this frame, says the attempt it makes
        # is that one -- reserved and priced like any other, carrying what the
        # checks reported. A second refusal, or any other code, is raised.
        try:
            return one_pass(route_node_id)
        except Refusal as refused:
            if refused.code is not RefusalCode.HANDOFF_MALFORMED or not _second_due(
                conn, run_id, route_node_id
            ):
                raise
        return one_pass(route_node_id)

    def terminal() -> str:
        with message_free():
            return finish(
                conn,
                blobs,
                run_id=run_id,
                route=route,
                execution=execution,
                named=named,
            )

    graph = build_graph(
        route,
        node_pass=one_node,
        finish=terminal,
        checkpointer=execution.checkpointer,
    )
    thread = str(run_id)
    try:
        ended = graph.invoke(
            resume_input(graph, thread),
            config=thread_config(thread) if execution.checkpointer else None,
        )
    except Exception as failed:
        _without_task_notes(failed)
        raise
    if execution.checkpointer is not None and ended.get("ended"):
        # Position only (D6): a thread that reached its end has nothing left
        # to resume from, and the store holds the verdict (F39).
        execution.checkpointer.delete_thread(thread)


@contextmanager
def message_free() -> Iterator[None]:
    """Let a fault leave a graph node with its class but not its message.

    LangGraph persists `repr(exc)` for a failed node in the checkpoint's
    writes (ST-14), and a validator's message may quote a document; the
    worker already writes only the class and the frame. A refusal is its
    typed code alone and passes unchanged.
    """
    try:
        yield
    except Refusal:
        raise
    except Exception as fault:
        fault.args = ()
        raise


# The note LangGraph attaches to an exception leaving a node names the task;
# the typed code is the whole of what a refusal says (legacy §16), so it is
# removed before the exception reaches a caller that reads the message.
_TASK_NOTE = "During task with name"


def _without_task_notes(failed: BaseException) -> None:
    notes = getattr(failed, "__notes__", None)
    if isinstance(notes, list):
        failed.__notes__ = [note for note in notes if not note.startswith(_TASK_NOTE)]


def _affordable(conn: StoreConnection, run_id: UUID, price: ModelPrice) -> None:
    """Refuse a run whose whole ceiling cannot cover one worst-case call.

    Since Task 8.2 each attempt reserves only what its own request costs, so a
    ceiling below one call's worst case is no longer met by the first
    reservation -- a run could start spending on a route it could never afford
    a single full-sized call of. This is where invariant 8 keeps that property.

    It is the run's own ceiling that is read, not what is left of it. Reading
    `remaining` made the check tighten as the run spent, so a run that finished
    when it ran continuously was refused `BUDGET_CEILING_REACHED` on resume, one
    node short, and every retry hit the same refusal -- "resume from accepted
    attempts, never restart" (invariant 6) broken by a guard for invariant 8.
    What refuses an operation the run can no longer pay for is `reserve`, under
    the run row lock, which is where that decision belongs. Found by the Task 8.2
    acceptance review, which reproduced it on the LITE fixture.
    """
    with execution_reads(conn):
        ceiling = ceiling_of(conn, run_id)
    if ceiling < worst_case(price):
        raise Refusal(RefusalCode.BUDGET_CEILING_REACHED)


def _refuse_unexplained(
    conn: StoreConnection,
    run_id: UUID,
    ready: Sequence[str],
    lease: Lease | None,
) -> None:
    """Refuse a ready node already paid for whose answer was never stored.

    `replay_billed` needs a body to settle from; this outcome has none, so the
    next pass would start a fresh attempt and pay for the same node twice with
    nobody choosing to. The lease answer comes first: a caller that lost the
    run is told that before it is told anything about what the run contains,
    which is the order every write in `_run_node` takes.
    """
    if unexplained_charge(conn, run_id=run_id, route_node_ids=ready) is None:
        return
    if not holds_lease(conn, run_id, lease):
        raise Refusal(RefusalCode.LEASE_NOT_HELD)
    raise Refusal(RefusalCode.CALL_OUTCOME_UNEXPLAINED)


class Pass(StrEnum):
    """What one node's pass did, reported to the graph; the store holds the state."""

    SKIPPED = "SKIPPED"  # COMPLETE already, or BLOCKED: nothing to run now
    ACCEPTED = "ACCEPTED"  # an artifact was accepted (live or replayed)
    ENDED = "ENDED"  # a validated Blocked handoff ended the run


def node_pass(  # noqa: PLR0913 -- one node of one run, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    execution: Execution,
    named: NamedObjects,
    route_node_id: str,
) -> Pass:
    """One node's turn: recompute, settle what was already paid for, run.

    The frontier is recomputed from the store first, so a node that is
    COMPLETE (this pass or an earlier process's) or BLOCKED is skipped. Before
    any attempt, an answer whose bill committed but whose acceptance, block or
    explanation did not (a crash in that gap) is settled from its stored body,
    never paid for twice (D7); a charge whose body was never stored parks the
    run instead of paying for the same node again with nobody choosing to.
    """
    bundle = execution.bundle
    with execution_reads(conn):
        accepted = accepted_artifacts(conn, blobs, route, run_id, bundle=bundle)
        if route_node_id not in frontier(route, accepted, named):
            return Pass.SKIPPED
        replayed = replay_billed(
            conn,
            blobs,
            bundle,
            run_id=run_id,
            route=route,
            route_node_ids=(route_node_id,),
        )
        if replayed is None:
            _refuse_unexplained(conn, run_id, (route_node_id,), execution.lease)
    if replayed is not None:
        settled = _settle(conn, blobs, replayed, run_id=run_id, lease=execution.lease)
        return Pass.ACCEPTED if settled else Pass.ENDED
    ran = _run_node(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        route_node_id=route_node_id,
        execution=execution,
    )
    return Pass.ACCEPTED if ran else Pass.ENDED


def _second_due(conn: StoreConnection, run_id: UUID, route_node_id: str) -> bool:
    """Whether the ledger gives this node its one second attempt now (D30). A
    store that cannot say leaves the original refusal standing."""
    try:
        return second_attempt_due(conn, run_id=run_id, route_node_id=route_node_id)
    except Refusal:
        return False


def finish(  # noqa: PLR0913 -- one run, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    execution: Execution,
    named: NamedObjects,
) -> str:
    """The terminal decision, carrying the accepted set it was decided from.

    §39: success only when every pinned node was accepted; otherwise the run
    ends blocked. Re-derived under `lock_run` by the store, which refuses a
    moved snapshot (`RUN_TERMINAL_STALE`); one more derivation decides again
    from the store, and a second move raises.
    """
    for last in (False, True):
        with execution_reads(conn):
            accepted = accepted_artifacts(
                conn, blobs, route, run_id, bundle=execution.bundle
            )
            states = node_states(route, accepted, named)
        decided = frozenset(accepted)
        complete = all(state is NodeState.COMPLETE for state in states.values())
        try:
            moved = _terminal_move(conn, run_id, execution, complete, decided)
        except Refusal as refusal:
            if refusal.code is not RefusalCode.RUN_TERMINAL_STALE or last:
                raise
            continue
        return _terminal_word(conn, run_id, complete, moved)
    raise Refusal(RefusalCode.RUN_TERMINAL_STALE)


def _terminal_move(
    conn: StoreConnection,
    run_id: UUID,
    execution: Execution,
    complete: bool,
    decided: frozenset[str],
) -> bool:
    if complete:
        return complete_run(conn, run_id, lease=execution.lease, accepted=decided)
    return block_run(conn, run_id, lease=execution.lease, accepted=decided)


def _terminal_word(
    conn: StoreConnection, run_id: UUID, complete: bool, moved: bool
) -> str:
    """The verdict the store made: this call's, or -- when a cancel landed
    between the last node and here -- the one already there, never a verdict
    the graph did not make."""
    if moved:
        return "COMPLETE" if complete else "BLOCKED"
    with execution_reads(conn):
        return run_status(conn, run_id).value


def _settle(
    conn: StoreConnection,
    blobs: BlobStore,
    replayed: Replayed,
    *,
    run_id: UUID,
    lease: Lease | None,
) -> bool:
    """Act on a replayed verdict with no call. Returns False once the run ended.

    ANSWERED accepts the stored answer under its original bill; BLOCKED ends the
    run as a live Blocked handoff does (a node's own verdict, so no snapshot);
    REFUSED writes the explanation once and refuses with its code, so the
    caller stops and a retry makes one new attempt instead of replaying it.
    """
    if replayed.verdict is Verdict.BLOCKED:
        block_run(conn, run_id, lease=lease, verdict=replayed.attempt_id)
        return False
    outcome = replayed.outcome
    if replayed.verdict is Verdict.REFUSED or outcome is None:
        code = replayed.code or RefusalCode.PROVIDER_RESPONSE_INVALID
        record_refusal(conn, attempt_id=replayed.attempt_id, code=code, lease=lease)
        raise Refusal(code)
    stored: tuple[str, str] | None = None
    try:
        stored = blobs.put(outcome.markdown), blobs.put(outcome.record)
    except (OSError, Refusal):
        pass  # raised below, outside the handler: no context carried
    if stored is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    accept_attempt(
        conn,
        attempt_id=replayed.attempt_id,
        accepted=Accepted(
            artifact_sha256=stored[0],
            charge=outcome.charge,
            model=outcome.model,
            generation_id=outcome.generation_id,
            diagnostic_sha256=outcome.diagnostic_sha256,
            record_sha256=stored[1],
        ),
        lease=lease,
    )
    return True


def accepted_artifacts(
    conn: StoreConnection,
    blobs: BlobStore,
    route: ResolvedRoute,
    run_id: UUID,
    *,
    bundle: Bundle | None = None,
) -> dict[str, NodeResult]:
    """The run's accepted attempts, keyed by route node, as typed results.

    Only CP-0's and the QA gate source's bodies are fetched. `node_states` reads
    readiness and QA clearance from those and needs nothing but presence from the
    others, so fetching every payload
    would be a blob read per node per pass for data nobody looks at -- the ~8x
    shape `docs/AI_CODE_QUALITY.md` section 1 measures.

    One query for the rows. A row without its host record refuses
    `ARTIFACT_RECORD_MISMATCH`: no artifact is read as a claims body (§42.1).
    Per readiness node, readiness and `qa_status` come from its record,
    verified against its Markdown under `bundle` (§42.4) -- the host
    identity's queries, two blob reads and the vendor validators, per pass.
    Without a bundle such a row refuses `ORCHESTRATION_ARTIFACT_UNREADABLE`.
    """
    qa_sources = {e.source for e in route.edges if e.type is EdgeType.QA_GATE}
    readiness_nodes = {
        node.route_node_id
        for node in route.nodes
        if node.module_id == GATE_MODULE or node.module_id in qa_sources
    }
    accepted: dict[str, NodeResult] = {}
    rows = accepted_rows(conn, run_id)
    # The one reading every verified row's lineage is compared with.
    pairs = {node_id: (digest, record) for node_id, _a, digest, record in rows}
    for node_id, attempt, digest, record in rows:
        if record is None:
            raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
        if node_id not in readiness_nodes:
            accepted[node_id] = NodeResult()
        elif bundle is None:
            raise Refusal(RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE)
        else:
            projections = accepted_projections(
                conn,
                blobs,
                bundle,
                route,
                AcceptedRow(
                    run_id=run_id,
                    route_node_id=node_id,
                    attempt_id=attempt,
                    artifact_sha256=digest,
                    record_sha256=record,
                ),
                accepted=pairs,
            )
            accepted[node_id] = NodeResult(
                readiness=tuple(projections.readiness),
                qa_status=projections.qa_status,
                blockers=tuple(projections.blockers),
            )
    return accepted


def _explain_live(
    conn: StoreConnection, attempt_id: UUID, refused: Refusal, lease: Lease | None
) -> None:
    """Write why a recorded call's answer was refused, once (D7). A store that
    cannot take the explanation leaves it unwritten -- the caller keeps the
    original refusal, and the next pass's replay explains the stored answer."""
    try:
        record_refusal(conn, attempt_id=attempt_id, code=refused.code, lease=lease)
    except Refusal as fault:
        if fault.code not in _STORE_FAULTS:
            raise


_STORE_FAULTS = frozenset(
    {
        RefusalCode.BLOB_ADDRESS_INVALID,
        RefusalCode.BLOB_DIGEST_MISMATCH,
        RefusalCode.BLOB_NOT_FOUND,
        RefusalCode.STORE_UNAVAILABLE,
        RefusalCode.STORE_NOT_TRANSACTIONAL,
    }
)


def _run_node(  # noqa: PLR0913 -- one node of one run, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    route_node_id: str,
    execution: Execution,
) -> bool:
    """One try at one node. One attempt row, one reservation, one acceptance.

    Returns False when a validated Blocked handoff ended the run BLOCKED: the
    bill and diagnostic are already recorded, nothing is accepted, no retry.
    """
    module_id = next(
        node.module_id for node in route.nodes if node.route_node_id == route_node_id
    )
    # Per call as well as per run: a provider whose model moved is unpriced.
    if execution.price.model != getattr(execution.provider, "model", None):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    # The whole prompt is built and bounded while nothing is started or set
    # aside: an over-ceiling context costs no attempt, reservation or call.
    measured = execution.provider.check_context(route_node_id, module_id)
    lease = execution.lease
    attempt_id = start_attempt(conn, run_id, route_node_id, lease=lease)
    # Priced on the request that was just built and bounded, not on the
    # transport ceiling: the attempt unit rebuilds the prompt and refuses to
    # call if its own request costs more than this (`_within_reservation`).
    reserve(
        conn,
        attempt_id,
        priced_request(execution.price, measured),
        price=execution.price,
        lease=lease,
    )

    _execution_route(conn, run_id, route, execution.bundle)
    refused: Refusal | None = None
    result: ProviderResult | None = None
    try:
        result = execution.provider.execute(
            route_node_id, module_id, attempt_id=attempt_id
        )
    except Refusal as refusal:
        refused = refusal
    if refused is not None and refused.code is not RefusalCode.HANDOFF_BLOCKED:
        # A recorded call's answer is explained once, so no retry replays it
        # (D7); an attempt with no recorded call writes nothing.
        _explain_live(conn, attempt_id, refused, lease)
        raise refused
    if result is None:
        _end_blocked(
            conn,
            blobs,
            run_id=run_id,
            route=route,
            node=route_node_id,
            execution=execution,
        )
        return False

    _execution_route(conn, run_id, route, execution.bundle)
    # ponytail: the executor recorded this outcome with the call, and `_accept`
    # commits exactly it before it enters `_accept_artifact`, so no accepted
    # artifact can be unbilled; a record here as well would be a knowing no-op
    # costing a COMMIT and two row locks. Ceiling: a provider that returns
    # without having billed its own call loses that call outright to a crash
    # before acceptance -- `replay_billed` needs the joined ledger row and a
    # stored body, `unexplained_charge` needs the outcome row, so neither
    # matches and the node is re-attempted and paid for again with nobody
    # deciding to. Nothing inside the acceptance unit can reach that window;
    # only a record adjacent to the call can, which is where this one is.
    accept_attempt(
        conn,
        attempt_id=attempt_id,
        accepted=Accepted(
            artifact_sha256=result.artifact_sha256,
            charge=result.charge,
            model=result.model,
            generation_id=result.generation_id,
            diagnostic_sha256=result.diagnostic_sha256,
            record_sha256=result.record_sha256,
        ),
        lease=lease,
    )
    return True


def _end_blocked(  # noqa: PLR0913 -- one node of one run, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    node: str,
    execution: Execution,
) -> None:
    """End the run BLOCKED on a validated Blocked handoff (brief correction 6).

    The raised code is not trusted: the verdict is re-derived from the stored
    bill and response body by the same `replay_billed` crash recovery uses,
    and a Blocked claim it does not confirm is an ordinary refusal. The attempt
    it confirms is what the transition records as the reason (§68): this is
    the last moment the answer can be judged, since `check_attempt` refuses a
    replay once the run is no longer RUNNING.
    """
    with execution_reads(conn):
        blocked = blocked_verdict(
            conn,
            blobs,
            execution.bundle,
            run_id=run_id,
            route=route,
            route_node_ids=(node,),
        )
    if blocked is None:
        raise Refusal(RefusalCode.HANDOFF_BLOCKED)
    block_run(conn, run_id, lease=execution.lease, verdict=blocked)


def _execution_route(
    conn: StoreConnection,
    run_id: UUID,
    requested: ResolvedRoute,
    bundle: Bundle,
) -> ResolvedRoute:
    """Return current stored authority from one bounded, lock-owning read unit."""
    with execution_reads(conn):
        _input, stored = execution_input(conn, run_id, bundle)
        if stored != requested:
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        return stored
