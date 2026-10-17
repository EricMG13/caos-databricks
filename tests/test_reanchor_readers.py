"""D94: every reader of a re-anchored citation reaches the live verdict.

A node is handed the pages its gate row names, while the run's pin captures
every page. A line the node cites on the wrong page is anchored at the one
page it was given that holds it -- even though the run captured another copy
on a page the node never saw. Live acceptance, `replay_billed`, the
orchestration proof and the deliverable's reader must agree on that record:
the readers check the stored coordinate (and that the cited page holds no
such line) rather than search the run's whole capture again.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import _url_for, approve_run, tamper
from test_canonical_execution import _accept, _node, _run, route
from test_delivered_authority import VENDORED
from test_execution_freshness import _Harness
from test_loop_charges import REPORT

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import _Reader
from caos.evidence.citations import Citation, TokenIndex, verify_stored_citations
from caos.evidence.extract import LINES_PER_PAGE
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import (
    Replayed,
    Verdict,
    _pinned_members,
    replay_billed,
)
from caos.methodology.executor import captured_blocks
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.run_inputs import load_run_input
from caos.store.runs import start_run
from caos.store.source_sets import load_source_set, pinned_live_sources

__all__ = ["route"]

DUPLICATE = "Net leverage was 3.4x at year end."


def _page(lines: list[str]) -> list[str]:
    return lines + [""] * (LINES_PER_PAGE - len(lines))


# Page 1 is the fixture report, pages 2 and 3 each carry DUPLICATE.
PAGED = "\n".join(
    _page(REPORT.decode().splitlines()) + _page([DUPLICATE]) + _page([DUPLICATE])
).encode()


@pytest.fixture
def paged(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    conn, case_id = case
    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    blobs = BlobStore(tmp_path / "blobs")
    source_id, witness_id = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(filename=BoundaryText.of("report.txt"), data=PAGED),
            Document(filename=BoundaryText.of("uncited.txt"), data=b"Witness.\n"),
        ],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    approver = approve_run(
        conn, case_id=case_id, run_id=run_id, route=route, bundle=bundle
    )
    return _Harness(
        conn,
        case_id,
        run_id,
        source_id,
        witness_id,
        blobs,
        route,
        bundle,
        approver,
        _url_for(conn.info.dbname),
    )


def test_live_replay_proof_and_deliverable_agree_on_a_reanchored_citation(
    paged: _Harness,
) -> None:
    harness = paged
    gate = CanonicalCompletions(
        harness.source_id, source_files={"CP-L10": "report.txt pages 1-2"}
    )
    attempt, result = _run(harness, "CP-0", gate)
    _accept(harness, attempt, result)
    screen = CanonicalCompletions(
        harness.source_id, cited=((harness.source_id, DUPLICATE, 1),)
    )
    attempt, result = _run(harness, "CP-L10", screen)
    [prompt] = screen.prompts
    assert prompt.count(DUPLICATE) == 1  # page 3 was never handed to the node
    # Live: anchored at page 2, the one page it was given holding the line.
    assert result.record_sha256 is not None
    live = _decoded_record(harness.blobs.get(result.record_sha256))
    [moved] = [c for c in live.citations if c.matched_text == DUPLICATE]
    assert (moved.page, moved.cited_page) == (2, 1)
    # Crash replay of the billed, unaccepted answer: the same record.
    node = _node(harness, "CP-L10").route_node_id
    replayed = replay_billed(
        harness.conn,
        harness.blobs,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        route_node_ids=[node],
    )
    harness.conn.rollback()
    assert isinstance(replayed, Replayed) and replayed.verdict is Verdict.ANSWERED
    assert replayed.outcome is not None
    assert replayed.outcome.record == harness.blobs.get(result.record_sha256)
    _accept(harness, attempt, result)
    # The proof re-checks it over every captured block, page 3 included.
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert ("CP-L10", moved.document_sha256, DUPLICATE) in proof.anchored
    # So does the deliverable's reader.
    reader = _Reader(
        harness.conn,
        harness.blobs,
        harness.bundle,
        harness.route,
        pinned_live_sources(harness.conn, harness.run_id),
        harness.run_id,
    )
    rows = harness.conn.execute(
        "SELECT t.route_node_id, a.attempt_id, a.artifact_sha256, a.record_sha256"
        " FROM artifacts a JOIN run_attempts t USING (attempt_id)"
        " WHERE a.run_id = %s",
        (harness.run_id,),
    ).fetchall()
    reader.pairs = {str(r[0]): (str(r[2]), str(r[3])) for r in rows}
    for route_node_id, attempt_id, artifact, record in rows:
        [found] = [n for n in harness.route.nodes if n.route_node_id == route_node_id]
        _markdown, stored = reader.proven(
            harness.run_id, found, UUID(str(attempt_id)), str(artifact), str(record)
        )
        assert stored == harness.blobs.get(str(record))
    harness.conn.rollback()


def test_proof_and_deliverable_refuse_a_citation_of_a_block_the_node_was_not_given(
    paged: _Harness,
) -> None:
    """N130: the run captured page 3, CP-L10 was handed pages 1-2. A stored
    record that cites page 3 anchors in the run's capture, not in the node's
    own delivery, so both readers refuse it where live acceptance would have."""
    harness = paged
    gate = CanonicalCompletions(
        harness.source_id, source_files={"CP-L10": "report.txt pages 1-2"}
    )
    attempt, result = _run(harness, "CP-0", gate)
    _accept(harness, attempt, result)
    screen = CanonicalCompletions(
        harness.source_id, cited=((harness.source_id, DUPLICATE, 1),)
    )
    attempt, result = _run(harness, "CP-L10", screen)
    _accept(harness, attempt, result)
    assert result.record_sha256 is not None
    record = _decoded_record(harness.blobs.get(result.record_sha256))
    [moved] = [c for c in record.citations if c.matched_text == DUPLICATE]
    assert moved.page == 2
    # The same record, its citation moved onto page 3 with page 3's own
    # rectangles: captured by the run, never given to the node.
    [onto_three] = verify_stored_citations(
        harness.conn,
        delivered=captured_blocks(harness.conn, harness.run_id),
        citations=[(Citation(harness.source_id, 3, DUPLICATE), 1)],
        index=TokenIndex(),
        rule=record.citation_rule,
    )
    harness.conn.rollback()
    forged = harness.blobs.put(
        record_bytes(
            replace(
                record,
                citations=tuple(
                    replace(onto_three, linked=c.linked, marker=c.marker)
                    if c is moved
                    else c
                    for c in record.citations
                ),
            )
        )
    )
    tamper(
        harness.conn,
        "UPDATE artifacts SET record_sha256 = %s WHERE record_sha256 = %s",
        (forged, result.record_sha256),
    )
    harness.conn.commit()
    with pytest.raises(Refusal) as lost:
        assert_orchestration_proof(
            harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
        )
    harness.conn.rollback()
    assert lost.value.code is RefusalCode.ORCHESTRATION_CITATION_LOST
    reader = _Reader(
        harness.conn,
        harness.blobs,
        harness.bundle,
        harness.route,
        pinned_live_sources(harness.conn, harness.run_id),
        harness.run_id,
    )
    node = _node(harness, "CP-L10")
    rows = harness.conn.execute(
        "SELECT t.route_node_id, a.attempt_id, a.artifact_sha256, a.record_sha256"
        " FROM artifacts a JOIN run_attempts t USING (attempt_id)"
        " WHERE a.run_id = %s",
        (harness.run_id,),
    ).fetchall()
    reader.pairs = {str(r[0]): (str(r[2]), str(r[3])) for r in rows}
    [(_, _, artifact, row)] = [r for r in rows if r[0] == node.route_node_id]
    with pytest.raises(Refusal) as undelivered:
        reader.proven(harness.run_id, node, attempt, str(artifact), str(row))
    harness.conn.rollback()
    assert undelivered.value.code is RefusalCode.CITATION_NOT_DELIVERED


def test_the_pinned_members_are_the_source_sets_own_and_a_run_without_a_pin_has_none(
    paged: _Harness,
) -> None:
    """`node_delivery` selects over the members `_pinned_members` reads in one
    statement: the same ones `load_source_set` verifies, in the same order."""
    harness = paged
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None and len(source_set.members) == 2
    assert _pinned_members(harness.conn, harness.run_id) == source_set.members
    with pytest.raises(Refusal) as unpinned:
        _pinned_members(harness.conn, uuid4())
    harness.conn.rollback()
    assert unpinned.value.code is RefusalCode.RUN_INPUT_INVALID
