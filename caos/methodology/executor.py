"""Evidence delivery and stored-identity checks shared by the canonical executor.

The claims executor that once lived here -- `execute_module`, its envelope
parsing and its prompt building -- is retired (`docs/DECISIONS.md` §42.1) and
deleted in slice f-2b. What remains is what `caos/methodology/canonical.py`
still imports: the evidence reader every module call delivers from
(`Delivery`, `_delivered`), the call identity (`Assignment`) and the check that
a pin's adapter matches the executor reading it (`_stored_identity`).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from caos.boundary_text import BoundaryText
from caos.evidence.read import read_run_blocks
from caos.graph.route import ResolvedRoute, RouteNode
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import execution_input
from caos.store.work import Lease

# The skill is the authority and the first delivered file; the vendor validators
# read it. Every delivered file reaches the prompt (§45.1, `invocation.py`).
SKILL = "SKILL.md"


@dataclass(frozen=True, slots=True)
class Delivery:
    """One block of evidence handed to a module, and where it came from.

    `page` is part of "where it came from". A module cites the page the prompt
    named, so a delivery that could not say which page it was read from is one
    whose quotes invariant 11 refuses the moment the block is not on page one.
    """

    source_id: UUID
    block_id: str
    page: int
    text: BoundaryText


@dataclass(frozen=True, slots=True)
class Assignment:
    """What the host hands one module for one node of one run.

    Identity only. What the module reads -- the evidence, the gate's
    expectation and its predecessors' results -- is derived from the run's pins
    inside each executor's own authority unit, so no caller's copy of it
    survives.
    """

    module_id: str
    run_id: UUID
    node: RouteNode
    route: ResolvedRoute
    # The reserved attempt this call is made under.
    attempt_id: UUID
    # The worker's claim the pre-transport check reads; None is a direct caller.
    lease: Lease | None = None


# Every block of the run's pinned source-set version, never the case's live set.
_CAPTURED = (
    "SELECT b.source_id, b.block_id FROM run_inputs i"
    " JOIN source_set_members m"
    " ON (m.case_id, m.version) = (i.case_id, i.source_version)"
    " JOIN source_blocks b ON b.source_id = m.source_id"
    " WHERE i.run_id = %s ORDER BY b.source_id, b.block_id"
)


def captured_blocks(conn: StoreConnection, run_id: UUID) -> dict[UUID, frozenset[str]]:
    """Source to the block ids the run's pin captured: what a node is handed.

    Every citation anchors inside these (invariant 11). Pins only -- no block
    text is read and no withdrawal is judged here; `verify_citations` reads
    tokens from live sources alone, so a withdrawn source still anchors nothing.
    """
    captured: dict[UUID, set[str]] = {}
    for source, block in conn.execute(_CAPTURED, (run_id,)).fetchall():
        captured.setdefault(UUID(str(source)), set()).add(str(block))
    return {source: frozenset(blocks) for source, blocks in captured.items()}


def _delivered(conn: StoreConnection, run_id: UUID) -> list[Delivery]:
    """Every captured block of the run, in one read through the run-bound join.

    The reader counts the pin's captured blocks in the same statement, so a
    delivery short of the pin refuses rather than handing a module a prompt
    built from what a withdrawal left behind.
    """
    return [
        Delivery(source_id, block_id, page, text)
        for source_id, block_id, page, text in read_run_blocks(conn, run_id=run_id)
    ]


def _stored_identity(
    conn: StoreConnection, assignment: Assignment, bundle: Bundle, *, adapter: str
) -> None:
    """Current input with the actual Bundle, the exact pinned route/node, and
    the pinned adapter this executor implements (§42.1): a pin never runs
    under the other adapter, whoever calls."""
    pin, stored = execution_input(conn, assignment.run_id, bundle)
    if pin.adapter_version != adapter:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    if (
        stored != assignment.route
        or assignment.node not in stored.nodes
        or assignment.node.module_id != assignment.module_id
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
