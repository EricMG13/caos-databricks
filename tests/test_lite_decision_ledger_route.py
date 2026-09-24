"""The contract test for `LITE_CREDIT_22 / LITE_DECISION_LEDGER` (CP-0 -> CP-8).

Two nodes and one REQUIRED edge, `decision_scope: SCREENING_ONLY`, and CP-8
is the terminal deliverable: it post-mortems a recorded decision against a
later outcome. Nothing here is new machinery -- the route runs through the same
`run_route` -> `ModuleProvider` -> canonical executor -> vendor validators ->
proof -> canonical deliverable path every enabled pathway uses. What is proven
is the pathway: it completes, proves and freezes over a two-document pack (the
T0 decision record and the T1 outcome, one citation from each); its requests
fit the request ceiling; a CP-0 verdict that blocks CP-8 stops the run before
any further call; and a validated Blocked CP-8 -- which its own gate requires
when no decision record is available, rather than a thesis reconstructed after
the fact -- ends the run BLOCKED and is recorded as the verdict that did.

CP-8's LITE compatibility block is `PROFILE_AGNOSTIC` with no accepted LITE
object, so `named_objects` holds no boundary here and CP-8 is held by nothing
but CP-0's readiness verdict. Every provider is deterministic; no live call is
made.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, fields_from_prompt, skill
from canonical_route_fixtures import (
    LEDGER_FILENAMES,
    LEDGER_MODULES,
    LEDGER_PACK,
    LEDGER_QUOTES,
    LEDGER_ROUTE,
    LEDGER_SELECTION,
    LedgerCompletions,
)
from conftest import _url_for, priced
from test_canonical_execution import _node
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES, read_record, validate_markdown
from caos.methodology.invocation import host_identity, named_objects
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import RefusalCode
from caos.store import StoreConnection, connect
from caos.store.gates import Gate, approve_gate
from caos.store.members import Standing, grant
from caos.store.routes import pin_route
from caos.store.run_inputs import RunSubject, pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set

# Every enabled pathway, asserted exactly: a route enabled without its own
# contract test would pass this suite silently.
ENABLED = frozenset(
    {
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
        LEDGER_SELECTION,
        ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "LIQUIDITY_REVIEW"),
        ("FULL_CREDIT_32", "EARNINGS_UPDATE"),
        ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
        ("FULL_CREDIT_32", "DECISION_LEDGER"),
        ("FULL_CREDIT_32", "COVENANT_REFINANCING"),
        ("FULL_CREDIT_32", "PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "MARKET_DISLOCATION"),
        ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING"),
        ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING"),
        ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN"),
        ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING"),
    }
)


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    return resolve_route(CATALOG, *getattr(request, "param", LEDGER_SELECTION))


@pytest.fixture
def harness(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    """A pinned, approved decision-ledger run over the memo and the outcome.

    `source_id` is the T0 decision record and `witness_id` the T1 outcome:
    the harness's two admitted documents, in that order.
    """
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    memo, outcome = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of(LEDGER_FILENAMES[name]),
                data=LEDGER_PACK[name],
            )
            for name in ("memo", "outcome")
        ],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    source_set = snapshot_source_set(conn, case_id)
    pin_route(conn, run_id, route)
    pin_run_input(
        conn,
        run_id,
        source_set.version,
        BUNDLE,
        subject=RunSubject("ACME", "Acme Holdings plc", "FY2025", "2026-09-08"),
    )
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, run_id, approver, gate))
    return _Harness(
        conn,
        case_id,
        run_id,
        memo,
        outcome,
        blobs,
        route,
        BUNDLE,
        approver,
        _url_for(conn.info.dbname),
    )


def _modules(answers: LedgerCompletions) -> list[str]:
    return [str(fields_from_prompt(p)["module_id"]) for p in answers.prompts]


def run_completed(
    harness: _Harness, answers: LedgerCompletions | None = None
) -> LedgerCompletions:
    answers = answers or LedgerCompletions(harness.source_id, harness.witness_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(LEDGER_MODULES)
    return answers


def _attempts_at(harness: _Harness, module_id: str) -> tuple[int, int]:
    """How many attempts and reservations this node has: the spend it caused."""
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.route_node_id = %s",
            (_node(harness, module_id).route_node_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_lite_decision_ledger_route_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    """CP-0 -> CP-8 completes, both artifacts prove, and the canonical
    deliverable for the run freezes and verifies against its own bytes."""
    assert LEDGER_MODULES == ("CP-0", "CP-8")
    # CP-8 is PROFILE_AGNOSTIC with no accepted LITE object (§46.1).
    assert named_objects(harness.bundle, harness.route).accepted_ids == {}

    run_completed(harness)
    assert _events(harness, "RUN_COMPLETE") == 1
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 2
    assert proof.citations == 3
    assert {m for m, _, _ in proof.anchored} == set(LEDGER_MODULES)

    saved = save_revision(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    payload = read_revision(
        harness.conn, harness.blobs, case_id=harness.case_id, revision_id=saved
    )
    harness.conn.rollback()
    assert [a["route_node_id"] for a in payload["artifacts"]] == [
        n.route_node_id for n in LEDGER_ROUTE.nodes
    ]
    data = payload_bytes(payload)
    # FP-33: the signer must be independent of the actor who saved the
    # narrative (`harness.approver`), so a fresh approver signs here.
    signer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=signer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=signer,
        revision_id=saved,
    )
    freezer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=freezer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    assert (
        freeze_canonical(
            harness.conn,
            harness.blobs,
            BUNDLE,
            replace(_revision(harness), revision_id=BoundaryText.of(str(saved))),
            actor_id=freezer,
        )
        == hashlib.sha256(data).hexdigest()
    )
    verify_frozen(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )


def test_cp8_contract_validates_identifies_projects_and_anchors(
    harness: _Harness,
) -> None:
    """CP-8's accepted record binds the host identity, projects the pathway's
    SCREENING_ONLY scope, names CP-0 as its one upstream, and anchors one quote
    in each document: the thesis as recorded, the outcome as realised."""
    run_completed(harness)
    node = _node(harness, "CP-8")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    ident = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=LEDGER_ROUTE,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=ident,
    )
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-8"),
        harness.blobs.get(artifact),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert record.projections == projection
    assert projection.module_id == "CP-8"
    assert projection.decision_scope == "SCREENING_ONLY"
    assert {r.module_id for r in ident.upstream} == {"CP-0"}
    assert {(c.document_sha256, c.matched_text) for c in record.citations} == {
        (hashlib.sha256(LEDGER_PACK[document]).hexdigest(), quote)
        for document, quote in LEDGER_QUOTES["CP-8"]
    }
    assert all(c.bboxes for c in record.citations)
    harness.conn.rollback()


def test_cp8_contract_refuses_an_unanchored_quote(harness: _Harness) -> None:
    """A realised outcome the T1 document does not carry is refused before an
    artifact exists: CP-8 may not cite an outcome its source does not support."""
    _document, quote = LEDGER_QUOTES["CP-8"][-1]
    answers = LedgerCompletions(
        harness.source_id,
        harness.witness_id,
        quotes_by_module={"CP-8": quote + " fabricated"},
    )
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.CITATION_NOT_LOCATED
    )
    assert harness.conn.execute(
        "SELECT count(*) FROM artifacts WHERE route_node_id=%s",
        (_node(harness, "CP-8").route_node_id,),
    ).fetchone() == (0,)
    harness.conn.rollback()


def test_lite_decision_ledger_requests_fit_the_request_ceiling(
    harness: _Harness,
) -> None:
    """Both prompts this pathway builds are inside `MAX_REQUEST_BYTES`, so no
    node refuses `CONTEXT_OVER_CEILING` before its attempt (§45.3)."""
    answers = run_completed(harness)
    assert len(answers.prompts) == 2
    assert all(
        len(answers.request_bytes(p, json_object=True)) <= MAX_REQUEST_BYTES
        for p in answers.prompts
    )


def test_a_blocked_cp0_verdict_holds_cp8_and_calls_nothing_after(
    harness: _Harness,
) -> None:
    """CP-0's T8 verdict is the only thing gating CP-8 here. BLOCKED leaves the
    frontier empty, so the run ends BLOCKED with CP-8 never attempted, never
    reserved and never called."""
    answers = LedgerCompletions(
        harness.source_id, harness.witness_id, readiness={"CP-8": "BLOCKED"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert _attempts_at(harness, "CP-8") == (0, 0)
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    # Nothing was blocked by an *answer*: the frontier simply emptied (§39).
    assert _blocking_verdict(harness) is None


def test_a_validated_blocked_cp8_ends_the_run_blocked(harness: _Harness) -> None:
    """CP-8's own gate: with no decision record to attribute it is `Blocked`,
    never a thesis reconstructed after the fact. The terminal's validated
    Blocked handoff is billed and kept as the attempt's diagnostic, no artifact
    is accepted, there is no retry, and the store records which attempt ended
    the run (§68)."""
    answers = LedgerCompletions(
        harness.source_id, harness.witness_id, qa_by_module={"CP-8": "Blocked"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == list(LEDGER_MODULES)
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert _counts(harness) == (2, [answers.charge] * 2, 1, 2, 2)
    blocked = hashlib.sha256(answers.bodies[1].encode()).hexdigest()
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes o JOIN run_attempts t"
            " USING (attempt_id) WHERE o.diagnostic_sha256 = %s"
            " AND t.route_node_id = %s AND NOT EXISTS"
            " (SELECT 1 FROM artifacts a WHERE a.attempt_id = o.attempt_id)",
            (blocked, _node(harness, "CP-8").route_node_id),
        ).fetchone()
    assert row == (1,)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-8")


def test_lite_decision_ledger_is_the_only_newly_enabled_route() -> None:
    """Enabling this pathway enabled exactly this pathway. The disabled-route
    guard (`tests/test_relative_value_route.py`) drives every pathway outside
    this set and proves each refuses; this is the set itself."""
    assert ADAPTER_ROUTES == ENABLED
    assert LEDGER_SELECTION in ADAPTER_ROUTES
