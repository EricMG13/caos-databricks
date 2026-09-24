"""Where the frontier loop meets a real module.

Phase 4 built a loop that asked a `Provider` for an artifact and a charge. Phase 5
built the thing that actually produces one: verified authority, a provider call,
a canonical envelope, citations anchored in the host's token index. This is the
join `test_the_loop_charges_what_the_provider_reported` proves.

The charge is the one the provider reported, never the estimate. They are
different numbers answering different questions: the estimate is what the run set
aside before the call so the ceiling could be checked (invariant 8), and the
charge is what the call cost. A ledger recording the estimate would reconcile
perfectly against itself and tell nobody what was spent.

What is stored as the artifact is the conforming Markdown handoff `execute_handoff`
(`caos/methodology/canonical.py`) produced and its host record, both addressed
by digest -- not the provider's raw body, which was untrusted text the host has
already replaced (invariant 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from caos.blobs import BlobStore
from caos.graph.route import ResolvedRoute, RouteNode
from caos.graph.runtime import ProviderResult
from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import check_context, execute_handoff
from caos.methodology.executor import Assignment
from caos.pricing import ModelPrice
from caos.provider import CompletionProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.outcomes import check_call, execution_reads
from caos.store.run_inputs import load_run_input
from caos.store.work import Lease


@dataclass(frozen=True)
class ModuleProvider:
    """A `runtime.Provider` that runs a real module.

    Holds what a module execution needs and the loop does not know about: the
    store, the bundle that is authority, the blob store artifacts are read from
    and written to, the provider that answers, the pinned route and the run.
    What the module reads is derived from the run's pins by `execute_handoff`,
    never chosen here.
    """

    conn: StoreConnection
    bundle: Bundle
    blobs: BlobStore
    completions: CompletionProvider
    route: ResolvedRoute
    run_id: UUID
    # The lease `run_route` writes under; both pre-transport checks read it.
    lease: Lease | None = None

    @property
    def model(self) -> str:
        """The configured model identity this provider's calls are billed as."""
        return self.completions.model

    @property
    def price(self) -> ModelPrice | None:
        """The dated price its completions charge at, or None for completions
        that report money rather than a price (`pricing.bills_at`)."""
        stated = getattr(self.completions, "price", None)
        return stated if isinstance(stated, ModelPrice) else None

    def check_context(self, route_node_id: str, module_id: str) -> int:
        """Build and bound the node's whole prompt before any attempt exists,
        and report the request size the reservation is priced on."""
        node = self._node(route_node_id, module_id)
        return check_context(
            self.conn,
            self.bundle,
            self.blobs,
            run_id=self.run_id,
            route=self.route,
            node=node,
            provider=self.completions,
        )

    def _node(self, route_node_id: str, module_id: str) -> RouteNode:
        nodes = [
            n
            for n in self.route.nodes
            if (n.route_node_id, n.module_id) == (route_node_id, module_id)
        ]
        if len(nodes) != 1:
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        return nodes[0]

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        """Check attempt identity, name the pinned node; `execute_handoff` checks
        again and derives what the module reads."""
        with execution_reads(self.conn):
            check_call(
                self.conn,
                attempt_id=attempt_id,
                run_id=self.run_id,
                route_node_id=route_node_id,
                lease=self.lease,
            )
            pin = load_run_input(self.conn, self.run_id)
        node = self._node(route_node_id, module_id)
        if pin is None:
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        # One adapter executes (§42.1): any other pin refuses before the call,
        # and `execute_handoff` refuses it again under its own read unit.
        if pin.adapter_version != CANONICAL_ADAPTER_VERSION:
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        assignment = Assignment(
            module_id, self.run_id, node, self.route, attempt_id, self.lease
        )
        handoff = execute_handoff(
            self.conn,
            self.bundle,
            self.blobs,
            assignment=assignment,
            provider=self.completions,
        )
        # Billed before analysis; a write failing here accepts nothing.
        artifact, record = self.blobs.put_both(handoff.markdown, handoff.record)
        return ProviderResult(
            artifact_sha256=artifact,
            charge=handoff.charge,
            model=handoff.model,
            generation_id=handoff.generation_id,
            record_sha256=record,
            diagnostic_sha256=handoff.diagnostic_sha256,
        )
