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
from pathlib import Path
from uuid import UUID

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import _url_for, approve_run
from test_canonical_execution import _accept, _node, _run, route
from test_delivered_authority import VENDORED
from test_execution_freshness import _Harness
from test_loop_charges import REPORT

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import _Reader
from caos.evidence.extract import LINES_PER_PAGE
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import Replayed, Verdict, replay_billed
from caos.methodology.executor import captured_blocks
from caos.methodology.handoff import _decoded_record
from caos.qualification.proof import assert_orchestration_proof
from caos.store import StoreConnection
from caos.store.runs import start_run
from caos.store.source_sets import pinned_live_sources

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
        captured_blocks(harness.conn, harness.run_id),
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
