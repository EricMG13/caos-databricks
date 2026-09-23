"""Positive end-to-end proofs for the LITE route (Task 3.4 brief, slice 3.4c).

Drives realistic, vendor-derived handoffs (`tests/lite_route_fixtures.py`)
through the real runtime -- `run_route` -> `ModuleProvider` -> the canonical
executor -> the vendor validators -> `assert_orchestration_proof` -> the
canonical deliverable -- rather than hand-building records the way
`tests/test_deliverable_canonical.py`'s `_accept` helper does. §45.6 and §46
are the read-model and named-object rules this slice proves in the round trip;
§39's "Restricted is usable but not QA-cleared" is proven for a route that
carries no CP-6 QA_GATE by showing nothing in the run, the proof or the
deliverable reports any clearance beyond CP-5's own stated `qa_status`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

from canonical_fixtures import CATALOG, fields_from_prompt
from conftest import priced
from lite_route_fixtures import CONFLICT_TEXT, RealisticLiteCompletions
from test_canonical_execution import harness, route
from test_execution_freshness import _Harness
from test_loop_charges import ESTIMATE

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import (
    Revision,
    canonical_payload,
    freeze_canonical,
    payload_bytes,
    verify_frozen,
)
from caos.deliverable.filing import sign_opinion
from caos.deliverable.package import build_package, verify_package
from caos.deliverable.render import render
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.runner import ModuleProvider
from caos.provider import MAX_COMPLETION_TOKENS
from caos.qualification.proof import assert_orchestration_proof
from caos.store.members import Standing, grant

__all__ = ["harness", "route"]

LITE = resolve_route(CATALOG, "LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")
REVISION = "rev-lite-e2e-positive-001"


def _run(harness: _Harness, completions: RealisticLiteCompletions) -> None:
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        harness.route,
        harness.run_id,
    )
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(provider, priced(ESTIMATE), harness.bundle),
    )


def _revision(harness: _Harness) -> Revision:
    return Revision(
        harness.case_id,
        harness.run_id,
        BoundaryText.of("Acme Holdings plc"),
        BoundaryText.of(REVISION),
    )


def _module_of(prompt: str) -> str:
    return str(fields_from_prompt(prompt)["module_id"])


def test_realistic_lite_route_completes_proves_and_freezes(harness: _Harness) -> None:
    """CP-0 -> CP-L10 -> CP-5 completes over realistic handoffs; the run's
    orchestration proof holds for all three artifacts with anchored citations;
    the canonical payload builds, freezes, verifies, and its package verifies
    with nothing but the standard library."""
    completions = RealisticLiteCompletions(harness.source_id)
    _run(harness, completions)

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 3
    assert proof.citations >= 3
    assert {module for module, _, _ in proof.anchored} == {"CP-0", "CP-L10", "CP-5"}

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
        n.route_node_id for n in LITE.nodes
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
    digest = freeze_canonical(
        harness.conn,
        harness.blobs,
        harness.bundle,
        replace(_revision(harness), revision_id=BoundaryText.of(str(saved))),
        actor_id=freezer,
    )
    assert digest == hashlib.sha256(data).hexdigest()

    verify_frozen(
        harness.conn,
        harness.blobs,
        harness.bundle,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )

    receipt = json.dumps(
        {
            "payload_sha256": digest,
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **{key: payload[key] for key in ("case_id", "run_id", "revision_id")},
        }
    ).encode()
    package = build_package(data, receipt, render(payload))
    # `verify_package` imports nothing from this repository but `hashlib`,
    # `json`, `zipfile` and the pure render -- no store connection needed.
    assert verify_package(package).verified


def test_realistic_fixture_handoffs_fit_the_completion_cap(harness: _Harness) -> None:
    """§46.2: every realistic wire body
    this run's provider actually produced fits under it. A fixture that grew
    past the cap would make every route run over it refuse
    `PROVIDER_OUTPUT_TRUNCATED` before ever reaching the assertions below."""
    completions = RealisticLiteCompletions(harness.source_id)
    _run(harness, completions)

    assert len(completions.bodies) == 3
    for body in completions.bodies:
        assert len(body.encode("utf-8")) <= MAX_COMPLETION_TOKENS


def test_restricted_cp_l10_limitations_survive_a_passed_cp5_into_the_deliverable(
    harness: _Harness,
) -> None:
    """A Restricted CP-L10 keeps its limitation flags on the page even though
    the downstream CP-5 (a soft ADVISORY consumer) itself validates Passed."""
    completions = RealisticLiteCompletions(
        harness.source_id, qa_by_module={"CP-L10": "Restricted", "CP-5": "Passed"}
    )
    _run(harness, completions)

    payload = canonical_payload(
        harness.conn, harness.blobs, harness.bundle, _revision(harness)
    )
    text = render(payload).decode()

    assert "QA status: Restricted" in text
    assert "QA status: Passed" in text
    assert "<li>Only one source report was delivered</li>" in text
    # Every LITE handoff is a screen, whatever its own written committee status.
    assert text.count("SCREENING ONLY: a screen, not committee clearance") == 3


def test_neither_restriction_nor_conflict_is_qa_clearance(harness: _Harness) -> None:
    """§39: a Restricted or conflicted CP-L10 is usable, not QA-cleared. This
    route carries no CP-6 QA_GATE to release, so the guarantee under test is
    that nothing the host writes -- the run's own state, the orchestration
    proof, or the deliverable -- ever asserts clearance; the only qa_status
    text on the page is each module's own, verbatim."""
    completions = RealisticLiteCompletions(
        harness.source_id, qa_by_module={"CP-L10": "Restricted"}
    )
    _run(harness, completions)

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 3

    payload = canonical_payload(
        harness.conn, harness.blobs, harness.bundle, _revision(harness)
    )
    text = render(payload).decode()

    # The host never claims clearance: "clearance" appears only inside the
    # fixed screening-only label, and the word "cleared" never appears at all.
    assert text.count("clearance") == text.count(
        "SCREENING ONLY: a screen, not committee clearance"
    )
    assert "cleared" not in text.lower()
    # The exact qa_status values on the page are the modules' own, in route
    # order: CP-0 and CP-5 each validated Passed, CP-L10 Restricted.
    assert [
        line for line in text.splitlines() if line.startswith('<p class="status">QA')
    ] == [
        '<p class="status">QA status: Passed</p>',
        '<p class="status">QA status: Restricted</p>',
        '<p class="status">QA status: Passed</p>',
    ]


def test_a_disclosed_conflict_is_byte_identical_in_cp5_prompt_proof_and_deliverable_with_no_host_resolution(  # noqa: E501 -- semantic RED name from the brief
    harness: _Harness,
) -> None:
    """CP-L10's disclosed leverage conflict (`CONFLICT_TEXT`) travels
    unmodified: into CP-5's own prompt (the upstream section carries CP-L10's
    accepted handoff verbatim, §45.1), into the stored CP-L10 Markdown the
    orchestration proof proves, and (HTML-escaped, but not otherwise changed)
    into the rendered deliverable. Nothing the host writes claims it was
    resolved."""
    completions = RealisticLiteCompletions(harness.source_id)
    _run(harness, completions)

    assert_orchestration_proof(
        harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
    )
    harness.conn.rollback()

    cp5_prompt = next(p for p in completions.prompts if _module_of(p) == "CP-5")
    assert CONFLICT_TEXT in cp5_prompt

    node = next(n for n in harness.route.nodes if n.module_id == "CP-L10")
    row = harness.conn.execute(
        "SELECT artifact_sha256 FROM artifacts"
        " WHERE run_id = %s AND route_node_id = %s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    stored_markdown = harness.blobs.get(str(row[0])).decode("utf-8")
    assert CONFLICT_TEXT in stored_markdown

    payload = canonical_payload(
        harness.conn, harness.blobs, harness.bundle, _revision(harness)
    )
    text = render(payload).decode()
    # CONFLICT_TEXT carries no HTML-special characters, so its escaped form in
    # the page is byte-identical to the source text.
    assert CONFLICT_TEXT in text
    assert "resolved" not in text.lower()
