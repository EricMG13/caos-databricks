"""One verification reader behind the proof, the deliverable and the runtime.

Invariants 3, 4 and 11 all pass through the ten-step check of an accepted
artifact. Three readers each ran their own copy and had drifted; now each is a
call site of `verify_accepted` that differs only in whether it re-anchors
(§42.4: the runtime does not), whether it re-reads authority bytes past the
digest cache, and which code it answers at each step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from uuid import UUID

import pytest
from conftest import every_block
from test_canonical_execution import _node, harness, route
from test_canonical_proof import _run
from test_execution_freshness import _Harness

from caos.boundary_text import BoundaryText
from caos.deliverable import canonical as deliverable
from caos.deliverable.canonical import Revision, canonical_payload
from caos.evidence.citations import TokenIndex
from caos.graph.runtime import accepted_artifacts
from caos.methodology import canonical as runtime_reader
from caos.methodology import verification
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.methodology.verification import (
    AcceptedRow,
    PinnedEvidence,
    Step,
    VendorAuthority,
    Verified,
    gate_expects,
    load_vendor_authority,
    verify_accepted,
)
from caos.qualification import proof
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store.source_sets import pinned_live_sources

__all__ = ["harness", "route"]


@pytest.fixture
def ran(harness: _Harness) -> _Harness:
    return _run(harness)


def _row(ran: _Harness, module_id: str) -> AcceptedRow:
    node = _node(ran, module_id)
    row = ran.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id = %s AND route_node_id = %s",
        (ran.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None and row[2] is not None
    return AcceptedRow(
        run_id=ran.run_id,
        route_node_id=node.route_node_id,
        attempt_id=UUID(str(row[0])),
        artifact_sha256=str(row[1]),
        record_sha256=str(row[2]),
    )


def _evidence(ran: _Harness) -> PinnedEvidence:
    sources = pinned_live_sources(ran.conn, ran.run_id)
    return PinnedEvidence(
        sources=sources,
        delivered=every_block(ran.conn, *sources.values()),
        index=TokenIndex(),
    )


def _verify(
    ran: _Harness,
    row: AcceptedRow,
    *,
    reanchor: bool,
    refuse: Callable[[Step], RefusalCode | None] | None = None,
) -> Verified:
    return verify_accepted(
        ran.conn,
        ran.blobs,
        ran.bundle,
        ran.route,
        row,
        vendor=load_vendor_authority(ran.bundle),
        accepted=None,
        verify_authority=True,
        reanchor=_evidence(ran) if reanchor else None,
        refuse=refuse or _mismatch,
    )


def _mismatch(step: Step) -> RefusalCode | None:
    return RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_the_three_readers_verify_through_one_function(
    monkeypatch: pytest.MonkeyPatch, ran: _Harness
) -> None:
    """Each reader is a call site of the one function, not a copy of it."""
    seen: list[str] = []
    real = verification.verify_accepted

    def spy(caller: str, *args: object, **kwargs: object) -> object:
        seen.append(caller)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(proof, "verify_accepted", partial(spy, "proof"))
    monkeypatch.setattr(deliverable, "verify_accepted", partial(spy, "deliverable"))
    monkeypatch.setattr(runtime_reader, "verify_accepted", partial(spy, "runtime"))

    assert_orchestration_proof(ran.conn, ran.blobs, ran.bundle, run_id=ran.run_id)
    ran.conn.rollback()
    revision = Revision(
        ran.case_id, ran.run_id, BoundaryText.of("Acme"), BoundaryText.of("rev-1")
    )
    canonical_payload(ran.conn, ran.blobs, ran.bundle, revision)
    accepted_artifacts(ran.conn, ran.blobs, ran.route, ran.run_id, bundle=ran.bundle)
    ran.conn.rollback()
    nodes = len(ran.route.nodes)
    # The proof and the deliverable read every node; the runtime reads only
    # its readiness nodes (CP-0 and the QA gate's source).
    assert (seen.count("proof"), seen.count("deliverable")) == (nodes, nodes)
    assert 0 < seen.count("runtime") <= nodes


def test_only_a_reanchoring_reader_returns_citations(ran: _Harness) -> None:
    """§42.4: the runtime reads the rectangles recorded at acceptance; the
    proof and the freeze re-locate every quote and get the same rectangles."""
    row = _row(ran, "CP-5")
    unanchored = _verify(ran, row, reanchor=False)
    ran.conn.rollback()
    assert unanchored.citations is None
    anchored = _verify(ran, row, reanchor=True)
    ran.conn.rollback()
    assert anchored.citations == anchored.record.citations
    assert anchored.record == unanchored.record
    assert anchored.projections == unanchored.record.projections
    assert ran.blobs.get(row.artifact_sha256) == anchored.markdown
    assert _decoded_record(anchored.stored) == anchored.record
    # The frontier's reading: the cached digests and the same compiled vendor
    # authority, and the same record either way.
    fresh = load_vendor_authority(ran.bundle)
    cached = verify_accepted(
        ran.conn,
        ran.blobs,
        ran.bundle,
        ran.route,
        row,
        vendor=VendorAuthority(fresh.contract, fresh.catalog),
        accepted=None,
        verify_authority=False,
        reanchor=None,
        refuse=lambda step: None,
    )
    ran.conn.rollback()
    assert (cached.record, cached.citations) == (anchored.record, None)
    gate = _node(ran, "CP-0")
    assert gate_expects(ran.route, gate) == frozenset({"CP-L10", "CP-5"})
    assert gate_expects(ran.route, _node(ran, "CP-5")) == frozenset()


def test_refuse_maps_each_step_to_the_callers_code_or_lets_it_through(
    ran: _Harness,
) -> None:
    """A citation moved to a page it is not on: the step's own code when the
    caller maps it to nothing (the deliverable), the caller's code otherwise
    (the proof). No text in the chain either way."""
    row = _row(ran, "CP-5")
    record = _decoded_record(ran.blobs.get(row.record_sha256))
    moved = replace(
        record,
        citations=(replace(record.citations[0], page=2), *record.citations[1:]),
    )
    row = replace(row, record_sha256=ran.blobs.put(record_bytes(moved)))
    with pytest.raises(Refusal) as own:
        _verify(ran, row, reanchor=True, refuse=lambda step: None)
    ran.conn.rollback()
    assert own.value.code is RefusalCode.CITATION_NOT_LOCATED
    assert own.value.__cause__ is None

    def mapped(step: Step) -> RefusalCode | None:
        assert step is Step.CITATION_ANCHOR
        return RefusalCode.ORCHESTRATION_CITATION_LOST

    with pytest.raises(Refusal) as theirs:
        _verify(ran, row, reanchor=True, refuse=mapped)
    ran.conn.rollback()
    assert theirs.value.code is RefusalCode.ORCHESTRATION_CITATION_LOST
    assert theirs.value.__cause__ is None and theirs.value.__context__ is None


def test_the_runtime_read_still_refuses_a_tampered_sibling_file(
    ran: _Harness,
) -> None:
    """The runtime's accepted read verifies every file of the module's
    authority (`assemble_authority`), not `SKILL.md` alone: a reference file
    beside it, changed on disk under an unchanged manifest, refuses the
    accepted read whatever the per-manifest digest cache already holds. The
    same read serves the Run and Analysis documents and the matrix."""
    from caos.methodology.canonical import accepted_projections

    row = _row(ran, "CP-0")
    # Warm the digest cache first, so only the direct read can catch it.
    assert _verify(ran, row, reanchor=False).citations is None
    ran.conn.rollback()
    skill = ran.bundle.skill_of("CP-0")
    sibling = next(n for n in sorted(skill["relative_file_hashes"]) if n != "SKILL.md")
    path = ran.bundle.root / "skills" / skill["folder_slug"] / sibling
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(Refusal) as refused:
        accepted_projections(
            ran.conn,
            ran.blobs,
            ran.bundle,
            ran.route,
            row,
        )
    ran.conn.rollback()
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
