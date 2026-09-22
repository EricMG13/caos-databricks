"""The contract test for `LITE_CREDIT_22 / LITE_PORTFOLIO_DECISION` (CP-0 ->
CP-L10), the pathway `CLAUDE.md`'s ledger recorded as enabled nowhere because
no contract test proved it.

Two nodes and one REQUIRED edge, `decision_scope: SCREENING_ONLY`, and CP-L10
is the terminal deliverable. Nothing here is new machinery: the route runs
through the same `run_route` -> `ModuleProvider` -> canonical executor ->
vendor validators -> proof -> canonical deliverable path
`tests/test_lite_route_e2e_positive.py` drives for the earnings pathway, over
the same vendor-derived handoffs (`tests/lite_route_fixtures.py`). What is
proven is the pathway: it completes, proves and freezes; its requests fit the
request ceiling; a CP-0 verdict that blocks CP-L10 stops the run before any
further call; and a validated Blocked CP-L10 -- the route's *terminal* -- ends
the run BLOCKED and is recorded as the verdict that did.

CP-L10's owned object `lite_financial_change_screen` has no consumer on this
two-node route, so `named_objects` holds no accepted-object boundary here
(§46.1) and CP-L10 is held by nothing but CP-0's own readiness verdict.

Every provider is deterministic; no live call is made.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import lite_route_fixtures
import pytest
from canonical_fixtures import CATALOG, fields_from_prompt
from lite_route_fixtures import RealisticLiteCompletions
from test_canonical_execution import _node, harness
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_lite_route_e2e_positive import _revision

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import (
    freeze_canonical,
    payload_bytes,
    verify_frozen,
)
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.methodology.invocation import named_objects
from caos.methodology.runner import ModuleProvider
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store import connect
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(node.module_id for node in ROUTE.nodes)
# Every enabled pathway, asserted exactly: a route enabled without its own
# contract test would pass this suite silently.
ENABLED = frozenset(
    {
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_DECISION_LEDGER"),
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
    return resolve_route(CATALOG, *getattr(request, "param", SELECTION))


@pytest.fixture(autouse=True)
def _t8_names_this_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """CP-0's T8 must name exactly the pinned consumers of *this* route.

    `validate_markdown` compares the T8 module set against `gate_expects` --
    every pinned node but CP-0 -- so a handoff naming the earnings route's
    CP-5 is refused `HANDOFF_INCOMPLETE`, which is the check working. The
    shared fixture reads its T8 module set from one constant
    (`canonical_fixtures.PINNED`, the earnings route's), so it is pointed at
    this route's own pinned set, derived from the resolved route rather than
    typed, which is also what `_GATE_INSTRUCTION` asks the gate to report.
    """
    monkeypatch.setattr(
        lite_route_fixtures,
        "PINNED",
        frozenset(node.module_id for node in ROUTE.nodes) - {"CP-0"},
    )


def _provider(
    harness: _Harness, completions: RealisticLiteCompletions
) -> ModuleProvider:
    return ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        harness.route,
        harness.run_id,
    )


def _modules(completions: RealisticLiteCompletions) -> list[str]:
    return [str(fields_from_prompt(p)["module_id"]) for p in completions.prompts]


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


def test_lite_portfolio_route_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    """CP-0 -> CP-L10 completes, both artifacts prove, and the canonical
    deliverable for the run freezes and verifies against its own bytes."""
    assert MODULES == ("CP-0", "CP-L10")
    # The terminal owns an object nothing on this route consumes, so no node
    # is held waiting for an accepted named LITE object (§46.1).
    assert named_objects(harness.bundle, harness.route).accepted_ids == {}

    completions = RealisticLiteCompletions(harness.source_id)
    assert _run_route(harness, _provider(harness, completions)) is None
    assert _status(harness) == "COMPLETE"
    assert _modules(completions) == list(MODULES)
    assert _events(harness, "RUN_COMPLETE") == 1

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 2
    assert proof.citations >= 2
    assert {module for module, _, _ in proof.anchored} == set(MODULES)

    saved = save_revision(
        harness.conn,
        harness.blobs,
        harness.bundle,
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
        node.route_node_id for node in ROUTE.nodes
    ]
    data = payload_bytes(payload)

    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=harness.approver,
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
            harness.bundle,
            replace(_revision(harness), revision_id=BoundaryText.of(str(saved))),
            actor_id=freezer,
        )
        == hashlib.sha256(data).hexdigest()
    )
    verify_frozen(
        harness.conn,
        harness.blobs,
        harness.bundle,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )


def test_lite_portfolio_requests_fit_the_request_ceiling(harness: _Harness) -> None:
    """Both prompts this pathway builds are inside `MAX_REQUEST_BYTES`, so no
    node refuses `CONTEXT_OVER_CEILING` before its attempt (§45.3)."""
    completions = RealisticLiteCompletions(harness.source_id)
    assert _run_route(harness, _provider(harness, completions)) is None
    assert len(completions.prompts) == 2
    assert all(
        len(completions.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in completions.prompts
    )


def test_a_blocked_cp0_verdict_holds_cp_l10_and_calls_nothing_after(
    harness: _Harness,
) -> None:
    """CP-0's T8 verdict is the only thing gating CP-L10 here. BLOCKED leaves
    the frontier empty, so the run ends BLOCKED with CP-L10 never attempted,
    never reserved and never called."""
    completions = RealisticLiteCompletions(
        harness.source_id, readiness={"CP-L10": "BLOCKED"}
    )
    assert _run_route(harness, _provider(harness, completions)) is None
    assert _modules(completions) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert _attempts_at(harness, "CP-L10") == (0, 0)
    assert _counts(harness) == (1, [completions.charge], 1, 1, 1)
    # Nothing was blocked by an *answer*: the frontier simply emptied (§39).
    assert _blocking_verdict(harness) is None


def test_a_validated_blocked_cp_l10_ends_the_run_blocked(harness: _Harness) -> None:
    """The terminal's own validated `Blocked` ends the run: the handoff is
    billed and kept as the attempt's diagnostic, no artifact is accepted, there
    is no retry, and the store records which attempt ended it (§68)."""
    completions = RealisticLiteCompletions(
        harness.source_id, qa_by_module={"CP-L10": "Blocked"}
    )
    assert _run_route(harness, _provider(harness, completions)) is None
    assert _modules(completions) == list(MODULES)
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    # Two calls, two charges, one accepted artifact: CP-L10's is a diagnostic.
    assert _counts(harness) == (2, [completions.charge] * 2, 1, 2, 2)
    blocked = hashlib.sha256(completions.bodies[1].encode()).hexdigest()
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes o JOIN run_attempts t"
            " USING (attempt_id) WHERE o.diagnostic_sha256 = %s"
            " AND t.route_node_id = %s AND NOT EXISTS"
            " (SELECT 1 FROM artifacts a WHERE a.attempt_id = o.attempt_id)",
            (blocked, _node(harness, "CP-L10").route_node_id),
        ).fetchone()
    assert row == (1,)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-L10")


def test_lite_portfolio_is_the_only_newly_enabled_route() -> None:
    """Enabling this pathway enabled exactly this pathway. The disabled-route
    guard (`tests/test_relative_value_route.py`) drives every pathway outside
    this set and proves each refuses; this is the set itself."""
    assert ADAPTER_ROUTES == ENABLED
    assert SELECTION in ADAPTER_ROUTES
