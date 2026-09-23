"""The Analysis section read (Task 4.1, slice 4.1e).

Every accepted handoff of the displayed run, in route order, each read through
`accepted_handoff`: the record must bind its exact Markdown, the identity the
store rebuilds, this build and the accepted lineage, and nothing is re-anchored
(§42.4). Each is labelled per §46.3 -- `source_facts` are the host-verified
citations with withdrawal read live, `model_analysis` is the model's exact
Markdown, and `host_calculation` is `NONE`. Beside the Markdown, each serves
the tagged tables it carries, read from those same bytes by the bundle's own
reader (`caos.methodology.tables`): exact text, and `Decimal` figures where the
bundle reads a figure -- or no table and a typed reason. Nothing is stored and
the Markdown stays the authority. A node without an accepted handoff
is listed as pending with its recomputed state and makes the document partial;
on a run a validated Blocked verdict ended, `blocked_by` names which of those
nodes answered, because a Blocked verdict accepts nothing (§68).
A run of another case, an unknown and a malformed run are one `RUN_NOT_FOUND`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RunQuery,
    Store,
    VisibleCase,
)
from caos.api.wire import (
    AnalysisBody,
    AnalysisDocument,
    BlockedByView,
    CellView,
    Chrome,
    CitationView,
    HandoffView,
    PendingNode,
    RectView,
    RunSubjectView,
    SectionNote,
    ServedRole,
    Subject,
    TableView,
)
from caos.blobs import BlobStore
from caos.deliverable.render import SCREENING_ONLY
from caos.evidence.citations import AnchoredCitation
from caos.graph.route import (
    MODEL_MODULE,
    NodeResult,
    NodeState,
    ResolvedRoute,
    node_states,
)
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import accepted_handoff
from caos.methodology.handoff import CanonicalRecord
from caos.methodology.invocation import named_objects
from caos.methodology.tables import HandoffTable, handoff_tables
from caos.methodology.vendor import cached_contract
from caos.methodology.verification import AcceptedRow
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.routes import resolved_route

# Fixed: standing; the case title, `now()`, latest run and the displayed run's
# ownership in one row; the subject; the pinned route (`resolved_route`); the
# accepted artifacts; the cited sources; the displayed run's own status, which
# is what tells a run that stopped from one still working, and -- in the same
# row -- the verdict that ended it. Then, per accepted handoff, the host
# identity `accepted_handoff` rebuilds (as app's `CANONICAL_READINESS_IO`), and
# for CP-CF's the re-proof of its four owner inputs on top.
#
# Declared for the longest route a run can pin, not for a LITE run of three
# (ED-7): the budget is a bound only if no pinned route exceeds it, and the
# ten-node forecast route cost 149 against the 37 once declared here. The
# longest is FULL_CREDIT_ASSESSMENT with the model extension, twenty nodes,
# CP-CF among them (`tests/test_analysis_section.py` resolves every pathway to
# check). Measured per handoff on one, three and ten handoffs, the forecast
# route's CP-CF included (`tests/test_analysis_section.py`,
# `tests/test_model_section.py`).
FIXED_IO = 7
PER_HANDOFF_IO = 10
MODEL_PROOFS_IO = 42
LONGEST_ROUTE_NODES = 20
IO_BUDGET = FIXED_IO + LONGEST_ROUTE_NODES * PER_HANDOFF_IO + MODEL_PROOFS_IO
# Blob reads, which no store budget counted: the artifact and its record per
# accepted handoff, each downloaded and hashed once per request however many
# of the lineage and record readers ask for it (`BlobStore.remembering`).
PER_HANDOFF_BLOBS = 2
BLOB_BUDGET = LONGEST_ROUTE_NODES * PER_HANDOFF_BLOBS
# A handoff's tables cost neither: they are read from the Markdown this request
# already downloaded and verified, by the contract `accepted_handoff` compiled.

router = APIRouter()


@router.get(
    "/api/v1/cases/{case_id}/analysis",
    response_model=AnalysisDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_analysis(  # noqa: PLR0913 -- identity, path, query, then the stores
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    standing: VisibleCase,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> AnalysisDocument:
    """The order of the parameters is load-bearing: identity, the path, the
    query and the caller's visibility of the case, then the store."""
    row = conn.execute(
        "SELECT title, now(),"
        " (SELECT run_id FROM runs WHERE case_id = c.case_id"
        "  ORDER BY created_at DESC, run_id DESC LIMIT 1),"
        " EXISTS (SELECT 1 FROM runs WHERE run_id = %s::uuid AND case_id = c.case_id)"
        " FROM cases c WHERE c.case_id = %s",
        (run, case_id),
    ).fetchone()
    if row is None:  # standing on a case row that is gone: still not readable
        raise Refusal(RefusalCode.CASE_NOT_FOUND)
    title, observed_at, latest, owned = row
    if run is not None and not owned:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    displayed = run if run is not None else latest

    handoffs: list[HandoffView] = []
    pending: list[PendingNode] = []
    subject: RunSubjectView | None = None
    notes: list[SectionNote] = []
    route = None if displayed is None else resolved_route(conn, displayed)
    # Read as the stored string, the way `reads/run.py` reads it: the column
    # holds exactly the five the wire declares. The blocking verdict rides the
    # same row rather than a second round trip -- it is one left join against a
    # table with at most one row per run, and reading it here keeps the
    # declared budget the shape it was measured in.
    displayed_status = None
    blocking: tuple[object, object] | None = None
    if displayed is not None:
        found = conn.execute(
            "SELECT r.status, v.attempt_id, a.route_node_id FROM runs r"
            " LEFT JOIN run_blocking_verdicts v ON v.run_id = r.run_id"
            " LEFT JOIN run_attempts a ON a.attempt_id = v.attempt_id"
            " WHERE r.run_id = %s",
            (displayed,),
        ).fetchone()
        if found is not None:
            displayed_status = found[0]
            blocking = None if found[1] is None else (found[1], found[2])
    blocked_by = None
    if displayed is not None and route is None:
        notes.append(SectionNote.ROUTE_NOT_PINNED)
    elif displayed is not None and route is not None:
        subject = _subject(conn, displayed)
        handoffs, pending = _handoffs(conn, blobs, bundle, route, displayed)
        if pending:
            notes.append(SectionNote.HANDOFFS_PENDING)
        if displayed_status == "BLOCKED" and blocking is not None:
            blocked_by = _blocked_by(route, blocking)
    return AnalysisDocument(
        chrome=Chrome(
            subject=Subject(case_id=case_id, title=title),
            served_role=ServedRole(global_role=actor.role, standing=standing),
            actions=[],
        ),
        body=AnalysisBody(
            case_id=case_id,
            latest_run_id=latest,
            displayed_run_id=displayed,
            subject=subject,
            displayed_run_status=displayed_status,
            blocked_by=blocked_by,
            handoffs=handoffs,
            pending=pending,
        ),
        observed_at=observed_at,
        observed_empty=displayed is None,
        status="partial" if notes else "complete",
        notes=notes,
    )


def _blocked_by(route: ResolvedRoute, blocking: tuple[object, object]) -> BlockedByView:
    """The node whose validated Blocked verdict ended this run, as the
    transition recorded it (§68) -- read, never re-derived, exactly as
    `reads/run.py` reads it. A node the pinned route does not carry is a store
    the pins do not describe, refused rather than served under a guessed
    module.
    """
    attempt, node_id = blocking
    node = next((n for n in route.nodes if n.route_node_id == str(node_id)), None)
    if node is None:
        raise Refusal(RefusalCode.ORCHESTRATION_NODE_NOT_IN_ROUTE)
    return BlockedByView(
        route_node_id=node.route_node_id,
        module_id=node.module_id,
        attempt_id=UUID(str(attempt)),
    )


def _subject(conn: StoreConnection, run_id: UUID) -> RunSubjectView | None:
    """The pinned run subject, or None for a run pinned without one."""
    row = conn.execute(
        "SELECT issuer_id, issuer_name, reporting_period, analysis_date"
        " FROM run_inputs WHERE run_id = %s AND issuer_id IS NOT NULL",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    issuer_id, issuer_name, period, analysis_date = (str(value) for value in row)
    return RunSubjectView(
        issuer_id=issuer_id,
        issuer_name=issuer_name,
        reporting_period=period,
        analysis_date=analysis_date,
    )


def _handoffs(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    run_id: UUID,
) -> tuple[list[HandoffView], list[PendingNode]]:
    """Accepted handoffs in route order, then every other node with its state.

    A row without its record, or whose record no longer binds, refuses
    `ARTIFACT_RECORD_MISMATCH` (503): the server's own bytes failed.
    """
    rows = {
        str(node): (UUID(str(attempt)), str(artifact), record, created)
        for node, attempt, artifact, record, created in conn.execute(
            "SELECT route_node_id, attempt_id, artifact_sha256, record_sha256,"
            " created_at FROM artifacts WHERE run_id = %s",
            (run_id,),
        ).fetchall()
    }
    pairs = {
        node: (artifact, None if record is None else str(record))
        for node, (_attempt, artifact, record, _created) in rows.items()
    }
    read: list[tuple[str, str, CanonicalRecord, bytes, object]] = []
    for node in route.nodes:
        if node.route_node_id not in rows:
            continue
        attempt, artifact, record_sha, created = rows[node.route_node_id]
        if record_sha is None:
            raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
        markdown, record = accepted_handoff(
            conn,
            blobs,
            bundle,
            route,
            AcceptedRow(
                run_id=run_id,
                route_node_id=node.route_node_id,
                attempt_id=attempt,
                artifact_sha256=artifact,
                record_sha256=str(record_sha),
            ),
            accepted=pairs,
        )
        read.append((node.route_node_id, str(record_sha), record, markdown, created))

    documents = _cited_documents(conn, run_id, [r for _n, _s, r, _m, _c in read])
    handoffs = [
        _handoff_view(
            node_id, sha, record, markdown.decode("utf-8"), created, documents, bundle
        )
        for node_id, sha, record, markdown, created in read
    ]
    accepted = {
        node_id: NodeResult(
            readiness=tuple(record.projections.readiness),
            qa_status=record.projections.qa_status,
        )
        for node_id, _s, record, _m, _c in read
    }
    states = node_states(route, accepted, named_objects(bundle, route))
    pending = [
        PendingNode(
            route_node_id=node.route_node_id,
            module_id=node.module_id,
            state=states[node.route_node_id],
        )
        for node in route.nodes
        if node.route_node_id not in accepted
        and states[node.route_node_id] is not NodeState.COMPLETE
    ]
    return handoffs, pending


def _cited_documents(
    conn: StoreConnection, run_id: UUID, records: list[CanonicalRecord]
) -> dict[str, tuple[UUID, str, object]]:
    """Source, filename and live withdrawal for every cited document, in one
    query. The source is the one those facts are read from, so a citation's
    page is addressed by the same pinned member its label names.

    Among the run's pinned members, a live source is preferred, so a document
    withdrawn under one copy and still live under another reads live. A cited
    document no member names is the record disagreeing with the store.
    """
    cited = sorted({c.document_sha256 for r in records for c in r.citations})
    if not cited:
        return {}
    found = {
        str(document): (UUID(str(source_id)), str(filename), withdrawn_at)
        for document, source_id, filename, withdrawn_at in conn.execute(
            "SELECT DISTINCT ON (s.document_sha256) s.document_sha256, s.source_id,"
            " s.filename, s.withdrawn_at FROM run_inputs i JOIN source_set_members m"
            " ON (m.case_id, m.version) = (i.case_id, i.source_version)"
            " JOIN sources s ON (s.case_id, s.source_id) = (m.case_id, m.source_id)"
            " WHERE i.run_id = %s AND s.document_sha256 = ANY(%s)"
            " ORDER BY s.document_sha256, s.withdrawn_at IS NOT NULL, s.source_id",
            (run_id, cited),
        ).fetchall()
    }
    if set(found) != set(cited):
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
    return found


def _handoff_view(  # noqa: PLR0913 -- one accepted handoff and its lookups
    route_node_id: str,
    record_sha256: str,
    record: CanonicalRecord,
    markdown: str,
    accepted_at: object,
    documents: dict[str, tuple[UUID, str, object]],
    bundle: Bundle,
) -> HandoffView:
    projections = record.projections
    # The contract `accepted_handoff` compiled for this manifest, read again.
    derived = handoff_tables(cached_contract(bundle), markdown)
    return HandoffView(
        route_node_id=route_node_id,
        module_id=projections.module_id,
        artifact_sha256=record.artifact_sha256,
        record_sha256=record_sha256,
        accepted_at=accepted_at,  # type: ignore[arg-type]
        qa_status=projections.qa_status,
        committee_status=projections.committee_status,
        confidence_score=projections.confidence_score,
        confidence_band=projections.confidence_band,
        limitation_flags=list(projections.limitation_flags),
        validation_warnings=list(projections.validation_warnings),
        decision_scope=projections.decision_scope,
        screening_only=projections.decision_scope == SCREENING_ONLY,
        source_facts=[_citation(c, documents) for c in record.citations],
        # Model-authored and rendered as text, never as markup (§46.3).
        model_analysis=markdown,
        host_calculation=(
            "CP_CF_FORECAST" if projections.module_id == MODEL_MODULE else "NONE"
        ),
        tables=[_table_view(table) for table in derived.tables],
        tables_unavailable_reason=derived.unavailable_reason,
    )


def _table_view(table: HandoffTable) -> TableView:
    return TableView(
        table_id=table.table_id,
        columns=list(table.columns),
        rows=[
            [CellView(text=cell.text, value=cell.value) for cell in row]
            for row in table.rows
        ],
    )


def _citation(
    citation: AnchoredCitation, documents: dict[str, tuple[UUID, str, object]]
) -> CitationView:
    source_id, filename, withdrawn_at = documents[citation.document_sha256]
    return CitationView(
        document_sha256=citation.document_sha256,
        source_id=source_id,
        filename=filename,
        page=citation.page,
        matched_text=citation.matched_text,
        rects=[RectView(x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1) for b in citation.bboxes],
        withdrawn_at=withdrawn_at,  # type: ignore[arg-type]
    )
