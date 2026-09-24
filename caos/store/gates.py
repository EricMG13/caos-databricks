"""Human approval binds a run's exact host-derived preview and complete input.

Historical previews grant no authority: use also checks live sources and standing.
Runtime must call under its execution-boundary locks and recheck at acceptance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

import psycopg

from caos import methodology
from caos.graph.route import RESEARCH_STAGE, ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_MODULES, ADAPTER_ROUTES, RESEARCH_MODULE
from caos.methodology.vendor import catalog
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, rollback_or_close
from caos.store.audit import GovernedAction, governed_write
from caos.store.events import lock_run
from caos.store.members import Standing, satisfies, standing_of
from caos.store.routes import require_catalog_route
from caos.store.run_inputs import RunInput, _load_run_input, input_fields
from caos.store.source_sets import SourceSet


class Gate(StrEnum):
    """The digest-bound interrupts a run can wait on."""

    SOURCE_SET = "SOURCE_SET"
    RESEARCH_PLAN = "RESEARCH_PLAN"


class GateState(StrEnum):
    """Whether the run may pass, judged against the content that is there now."""

    OPEN = "OPEN"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class GateApproval:
    """One person releasing one gate, over content they can be shown to have
    seen. `preview_sha256` is what they read; `input_fingerprint` is what it was
    computed from."""

    run_id: UUID
    gate: Gate
    actor_id: UUID
    preview_sha256: str
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class GatePreview:
    """Show `content` exactly; submit its digests as expectations, never authority."""

    run_id: UUID
    case_id: UUID
    gate: Gate
    content: str
    preview_sha256: str
    input_fingerprint: str


def gate_preview(conn: StoreConnection, run_id: UUID, gate: Gate) -> GatePreview:
    """Historical content, even after withdrawal; caller owns the read transaction."""
    preview = _preview(conn, run_id, gate)
    if preview is None:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    return preview


def _preview(conn: StoreConnection, run_id: UUID, gate: Gate) -> GatePreview | None:
    loaded = _load_run_input(conn, run_id)
    return None if loaded is None else _historical_preview(*loaded, gate)


def _historical_preview(
    pin: RunInput, route: ResolvedRoute, source: SourceSet, gate: Gate
) -> GatePreview:
    data: dict[str, object] = {
        "format_version": pin.format_version,
        "gate": gate.value,
        "input": {
            **input_fields(pin),
            "run_id": str(pin.run_id),
            "case_id": str(pin.case_id),
        },
    }
    if gate is Gate.SOURCE_SET:
        data["sources"] = [
            {**asdict(member), "source_id": str(member.source_id)}
            for member in source.members
        ]
    else:
        data["route"] = asdict(route)
    content = json.dumps(
        data, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
    )
    return GatePreview(
        pin.run_id,
        pin.case_id,
        gate,
        content,
        sha256(content.encode("utf-8")).hexdigest(),
        pin.input_fingerprint,
    )


def _sources_live(conn: StoreConnection, run_id: UUID) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM run_inputs i JOIN source_set_members m"
            " ON (m.case_id, m.version) = (i.case_id, i.source_version)"
            " LEFT JOIN live_sources s"
            " ON (s.case_id, s.source_id) = (m.case_id, m.source_id)"
            " LEFT JOIN source_extractions e ON e.source_id = s.source_id"
            " WHERE i.run_id = %s AND (s.source_id IS NULL OR"
            " (s.document_sha256, e.extractor_identity, e.output_sha256,"
            " e.extraction_sha256) IS DISTINCT FROM"
            " (m.document_sha256, m.extractor_identity, m.output_sha256,"
            " m.extraction_sha256)) LIMIT 1",
            (run_id,),
        ).fetchone()
        is None
    )


def sources_live(conn: StoreConnection, run_id: UUID) -> bool:
    """Whether every member the run's pin captured is still live and unchanged:
    the predicate approval and execution refuse `EVIDENCE_NOT_AVAILABLE` on."""
    return _sources_live(conn, run_id)


def approve_gate(conn: StoreConnection, approval: GateApproval) -> None:
    """Release a gate, as a governed write requiring APPROVER standing.

    Through `governed_write` rather than beside it: releasing a gate is a human
    decision that a conclusion later rests on, so it is checked at the commit and
    recorded in the case's chain.
    """
    case_id = _case_of(conn, approval.run_id)
    action = GovernedAction(
        case_id=case_id,
        actor_id=approval.actor_id,
        action=f"GATE_RELEASED:{approval.gate.value}",
        requires=Standing.APPROVER,
        payload={
            "run_id": str(approval.run_id),
            "gate": approval.gate.value,
            "preview_sha256": approval.preview_sha256,
            "input_fingerprint": approval.input_fingerprint,
        },
    )

    governed_write(
        conn, action, lambda connection: release_gate_in(connection, approval)
    )


def release_gate_in(conn: StoreConnection, approval: GateApproval) -> None:
    """Release one gate in the caller's governed transaction; never commits.

    The run lock is taken case-first, and a run that is no longer RUNNING
    refuses: releasing a gate on a terminal run authorises nothing it could use.
    """
    if lock_run(conn, approval.run_id) is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    preview = gate_preview(conn, approval.run_id, approval.gate)
    if (approval.preview_sha256, approval.input_fingerprint) != (
        preview.preview_sha256,
        preview.input_fingerprint,
    ):
        raise Refusal(RefusalCode.GATE_APPROVAL_MISMATCH)
    if not _sources_live(conn, approval.run_id):
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)
    conn.execute(
        "INSERT INTO run_gates (run_id, gate, preview_sha256, input_fingerprint,"
        " approved_by) VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (run_id, gate) DO UPDATE SET"
        " preview_sha256 = EXCLUDED.preview_sha256,"
        " input_fingerprint = EXCLUDED.input_fingerprint,"
        " approved_by = EXCLUDED.approved_by, approved_at = now()",
        (
            approval.run_id,
            approval.gate.value,
            approval.preview_sha256,
            approval.input_fingerprint,
            approval.actor_id,
        ),
    )


def gate_state(conn: StoreConnection, run_id: UUID, gate: Gate) -> GateState:
    """Current eligibility in the caller's transaction; corrupt identity refuses."""
    try:
        preview = _preview(conn, run_id, gate)
        if preview is None:
            return GateState.OPEN
        if not _approved(conn, preview) or not _sources_live(conn, run_id):
            return GateState.OPEN
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return GateState.RELEASED


def _approved(conn: StoreConnection, preview: GatePreview) -> bool:
    row = conn.execute(
        "SELECT preview_sha256, input_fingerprint, approved_by FROM run_gates"
        " WHERE run_id = %s AND gate = %s",
        (preview.run_id, preview.gate.value),
    ).fetchone()
    return (
        row is not None
        and row[:2] == (preview.preview_sha256, preview.input_fingerprint)
        and satisfies(
            standing_of(conn, case_id=preview.case_id, user_id=row[2]),
            Standing.APPROVER,
        )
    )


def approved_run_input(
    conn: StoreConnection, run_id: UUID
) -> tuple[RunInput, ResolvedRoute]:
    """Live authority under case/run locks; caller owns the whole transaction.

    Runtime and acceptance integration remain separate. This read is not an
    atomic provider-call claim and does not prove frozen block/token contents.
    """
    try:
        try:
            status = lock_run(conn, run_id)
        except Refusal as refused:
            if refused.code is RefusalCode.RUN_NOT_FOUND:
                raise Refusal(RefusalCode.RUN_INPUT_INVALID) from None
            raise
        if status is not RunStatus.RUNNING:
            raise Refusal(RefusalCode.RUN_NOT_RUNNING)
        loaded = _load_run_input(conn, run_id)
        if loaded is None:
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if not _sources_live(conn, run_id):
            raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)
        for gate in Gate:
            if not _approved(conn, _historical_preview(*loaded, gate)):
                raise Refusal(RefusalCode.GATE_APPROVAL_MISMATCH)
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    pin, route, _source = loaded
    return pin, route


def execution_input(
    conn: StoreConnection, run_id: UUID, bundle: Bundle
) -> tuple[RunInput, ResolvedRoute]:
    """Require the actual executing Bundle/host adapter beside live authority.

    `RUN_INPUT_INVALID` for a pin of another build, manifest or adapter (a
    `claims-json-v1` pin among them); `HANDOFF_MODULE_UNSUPPORTED` for a route
    with a module the adapter does not own (§42.2); `ROUTE_IDENTITY_INVALID`
    for a pinned route that is not the pinned build's own catalog resolution
    of its pathway (CF-025) -- before any attempt, reservation or call, since
    every executing caller reads this first.
    """
    pin, route = approved_run_input(conn, run_id)
    if not isinstance(bundle, Bundle):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    if (pin.build_id, pin.manifest_sha256, pin.adapter_version) != (
        bundle.build_id,
        bundle.manifest_sha256,
        methodology.CANONICAL_ADAPTER_VERSION,
    ):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    require_adapter_route(route)
    require_catalog_route(route, catalog(bundle))
    return pin, route


def require_adapter_route(route: ResolvedRoute) -> None:
    """Refuse a route the canonical adapter does not own every module of (§42.2),
    or a pathway of its modules no contract test proves (work item 6).

    Pinning, gates and resolution stay general; execution and acceptance do not.
    """
    from caos.methodology.host import verify_extension

    verify_extension(route)
    # The research extension (§6) appends CP-DR at stage 99 without the
    # predecessor and consumer edges the vendor's own `routing.Route`
    # synthesises from the brief's questions, so a run on it would take a path
    # the bundle's navigation would not (§96). CP-DR is executed only where a
    # catalog pathway carries it natively, and no such pathway is enabled yet.
    if any(
        node.module_id == RESEARCH_MODULE and node.stage == RESEARCH_STAGE
        for node in route.nodes
    ):
        raise Refusal(RefusalCode.HANDOFF_MODULE_UNSUPPORTED)
    if (route.profile_id, route.selection_id) not in ADAPTER_ROUTES or any(
        node.module_id not in ADAPTER_MODULES for node in route.nodes
    ):
        raise Refusal(RefusalCode.HANDOFF_MODULE_UNSUPPORTED)


def source_set_fingerprint(conn: StoreConnection, case_id: UUID) -> str:
    """A digest over the case's live sources.

    Compatibility only, not an enforced run pin; new snapshots use source_sets.
    Order-independent, because the order documents were admitted in is not a
    change to the evidence and must not reopen a gate. Over `live_sources`, so a
    withdrawal moves this compatibility digest. Approval uses complete pins and
    checks current withdrawal separately.
    """
    rows = conn.execute(
        "SELECT document_sha256 FROM live_sources WHERE case_id = %s"
        " ORDER BY document_sha256",
        (case_id,),
    ).fetchall()
    digest = sha256()
    for row in rows:
        digest.update(str(row[0]).encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def withdraw_source(
    conn: StoreConnection, *, case_id: UUID, source_id: UUID, actor_id: UUID
) -> None:
    """Withdraw a source. Invariant 1's second half.

    Never a delete: a run that already cited this document has to stay
    explicable, so the row keeps its place and leaves `live_sources`. Every later
    `read_evidence` refuses because it reads through that view, and every gate
    bound to that captured member reopens because the member is no longer live.
    """
    action = GovernedAction(
        case_id=case_id,
        actor_id=actor_id,
        action="SOURCE_WITHDRAWN",
        requires=Standing.WRITER,
        payload={"source_id": str(source_id)},
    )

    governed_write(
        conn,
        action,
        lambda unit: withdraw_source_in(unit, case_id=case_id, source_id=source_id),
    )


def withdraw_source_in(
    conn: StoreConnection, *, case_id: UUID, source_id: UUID
) -> None:
    """Withdraw in the caller's governed transaction; never commits."""
    withdrawn = conn.execute(
        "UPDATE sources SET withdrawn_at = now()"
        " WHERE source_id = %s AND case_id = %s AND withdrawn_at IS NULL",
        (source_id, case_id),
    ).rowcount
    if not withdrawn:
        # Already withdrawn, another case's, or no source at all: nothing was
        # withdrawn, so the chain must not say something was. One code for the
        # three, as `read_evidence` gives one -- the difference between them is
        # not this caller's to learn from a refusal.
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)


def _case_of(conn: StoreConnection, run_id: UUID) -> UUID:
    try:
        row = conn.execute(
            "SELECT case_id FROM runs WHERE run_id = %s", (run_id,)
        ).fetchone()
    except psycopg.Error:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except BaseException:
        rollback_or_close(conn)
        raise
    if row is None:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    return UUID(str(row[0]))
