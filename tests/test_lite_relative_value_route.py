"""The contract test for `LITE_CREDIT_22 / LITE_RELATIVE_VALUE` (CP-0 ->
CP-L10 -> CP-1C), Completion Phase 9 Task 9.2.

Three nodes, three REQUIRED edges, `decision_scope: SCREENING_ONLY`. CP-1C is
a FULL module held behind the named-LITE-object boundary until CP-L10's
`lite_financial_change_screen` is accepted (§46.1); its own contract under
the LITE identity is `tests/test_lite_cp1c_contract.py`. What is proven here
is the pathway: it completes, proves and freezes; its requests fit the request
ceiling; a CP-L10 that is blocked -- by CP-0's verdict or by its own validated
answer -- holds CP-1C with nothing attempted, reserved or called; and a
Restricted CP-L10's limitation reaches CP-1C's prompt and the deliverable.

Every provider is deterministic; no live call is made.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from lite_relative_value_fixtures import (
    LITE_LIMITATION,
    MODULES,
    ROUTE,
    SELECTION,
    LiteRelativeValueCompletions,
)
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_lite_route_e2e_positive import _revision
from test_relative_value_route import harness

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import (
    canonical_payload,
    freeze_canonical,
    payload_bytes,
    verify_frozen,
)
from caos.deliverable.filing import sign_opinion
from caos.deliverable.render import render
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store import connect
from caos.store.members import Standing, grant

__all__ = ["harness"]

# Every enabled pathway, asserted exactly: a route enabled without its own
# contract test would pass this suite silently.
ENABLED = frozenset(
    {
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "RELATIVE_VALUE"),
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
        SELECTION,
    }
)


@pytest.fixture
def route() -> ResolvedRoute:
    """The harness pins this route (overrides the FULL route's fixture)."""
    return resolve_route(CATALOG, *SELECTION)


def _modules(answers: LiteRelativeValueCompletions) -> list[str]:
    return [str(fields_from_prompt(p)["module_id"]) for p in answers.prompts]


def _attempts_at(harness: _Harness, module: str) -> tuple[int, int]:
    """How many attempts and reservations this node has: the spend it caused."""
    node = next(n for n in ROUTE.nodes if n.module_id == module)
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.run_id = %s AND t.route_node_id = %s",
            (harness.run_id, node.route_node_id),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_lite_relative_value_route_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    """CP-0 -> CP-L10 -> CP-1C completes in route order, all three artifacts
    prove, and the canonical deliverable freezes and verifies."""
    assert MODULES == ("CP-0", "CP-L10", "CP-1C")
    answers = LiteRelativeValueCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert _events(harness, "RUN_COMPLETE") == 1
    cp1c = fields_from_prompt(answers.prompts[-1])
    assert {r["module_id"] for r in cp1c["upstream_artifacts_used"]} == {
        "CP-0",
        "CP-L10",
    }

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == proof.citations == 3
    assert {m for m, _, _ in proof.anchored} == set(MODULES)

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
        n.route_node_id for n in ROUTE.nodes
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


def test_lite_relative_value_requests_fit_the_request_ceiling(
    harness: _Harness,
) -> None:
    """All three prompts -- CP-1C's carrying two upstream handoffs and its
    whole FULL authority -- are inside `MAX_REQUEST_BYTES` (§45.3)."""
    answers = LiteRelativeValueCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert len(answers.prompts) == 3
    assert all(
        len(answers.request_bytes(p, json_object=True)) <= MAX_REQUEST_BYTES
        for p in answers.prompts
    )


def test_a_cp0_verdict_blocking_cp_l10_holds_cp1c_and_calls_nothing_after(
    harness: _Harness,
) -> None:
    """CP-0 declares CP-L10 BLOCKED: the frontier empties with CP-L10 and
    CP-1C never attempted, never reserved and never called."""
    answers = LiteRelativeValueCompletions(
        harness.source_id, readiness={"CP-L10": "BLOCKED"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert _attempts_at(harness, "CP-L10") == (0, 0)
    assert _attempts_at(harness, "CP-1C") == (0, 0)
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None


def test_a_validated_blocked_cp_l10_holds_cp1c_and_ends_the_run_blocked(
    harness: _Harness,
) -> None:
    """CP-L10's own validated `Blocked` is billed and kept as a diagnostic,
    accepts nothing, and ends the run: CP-1C, which only an accepted CP-L10
    releases, is never attempted (§68)."""
    answers = LiteRelativeValueCompletions(
        harness.source_id, qa_by_module={"CP-L10": "Blocked"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0", "CP-L10"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _attempts_at(harness, "CP-1C") == (0, 0)
    assert _counts(harness) == (2, [answers.charge] * 2, 1, 2, 2)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-L10")


def test_a_restricted_cp_l10_keeps_its_limitation_in_cp1c_prompt_and_record(
    harness: _Harness,
) -> None:
    """A Restricted CP-L10 still releases CP-1C (its edge is REQUIRED, not a
    QA_GATE), and its limitation travels: in the upstream section of CP-1C's
    prompt, in CP-L10's accepted record, and in the rendered deliverable."""
    answers = LiteRelativeValueCompletions(
        harness.source_id, qa_by_module={"CP-L10": "Restricted"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert LITE_LIMITATION in answers.prompts[-1]
    assert LITE_LIMITATION not in answers.prompts[1]  # CP-L10 did not see it
    payload = canonical_payload(harness.conn, harness.blobs, BUNDLE, _revision(harness))
    harness.conn.rollback()
    [cp_l10] = [
        json.loads(a["record"])["projections"]
        for a in payload["artifacts"]
        if a["route_node_id"] == ROUTE.nodes[1].route_node_id
    ]
    assert cp_l10["qa_status"] == "Restricted"
    assert cp_l10["limitation_flags"] == [LITE_LIMITATION]
    assert LITE_LIMITATION in render(payload).decode()


def test_lite_relative_value_is_the_only_newly_enabled_route() -> None:
    """Enabling this pathway enabled exactly this pathway; the disabled-route
    guard (`tests/test_relative_value_route.py`) drives every other one."""
    assert ADAPTER_ROUTES == ENABLED
    assert SELECTION in ADAPTER_ROUTES
