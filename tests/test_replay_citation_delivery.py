"""`scripts/replay_citation_delivery.py`: stored citations against D152's R2 (N231 3).

Run on the `paged` fixture of `test_reanchor_readers`: the run captured pages
1-3, CP-L10 was handed pages 1-2 and cites a line that page 3 also holds. An
honest record is located in what the node was handed; the same record forged
onto page 3 is located only in the run's whole capture, which is the case the
rule refuses and the replay counts.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import tamper
from test_canonical_execution import _accept, _node, _run, route
from test_execution_freshness import _Harness
from test_qualify_reclaim import server
from test_reanchor_readers import DUPLICATE, paged

from caos.evidence.citations import Citation, TokenIndex, verify_stored_citations
from caos.methodology.executor import captured_blocks
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.store.runs import start_run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import qualify
import replay_citation_delivery as replay

__all__ = ["paged", "route", "server"]


def _accepted(harness: _Harness) -> str:
    """CP-0 and CP-L10 accepted, CP-L10 citing `DUPLICATE`; its record's digest."""
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
    return result.record_sha256


def _forge_onto_page_three(harness: _Harness, digest: str) -> None:
    """The record's citation moved onto page 3: captured, never handed."""
    record = _decoded_record(harness.blobs.get(digest))
    [moved] = [c for c in record.citations if c.matched_text == DUPLICATE]
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
        (forged, digest),
    )
    harness.conn.commit()


def _replayed(harness: _Harness) -> dict[str, object]:
    return replay.replay_database(
        harness.url, "fixture", harness.blobs, harness.bundle
    ).report()


def test_a_record_located_in_its_own_delivery_is_counted_handed(
    paged: _Harness,
) -> None:
    _accepted(paged)

    report = _replayed(paged)

    assert report["accepted_runs"] == 1 and report["nodes"] == 2
    citations = report["citations"]
    assert isinstance(citations, dict)
    assert citations["handed"] >= 1
    assert citations["not_handed"] == citations["not_located"] == 0
    assert report["runs_with_not_handed"] == [] and report["unreadable"] == {}


def test_a_citation_of_a_block_the_node_was_not_handed_is_counted_by_id_only(
    paged: _Harness,
) -> None:
    digest = _accepted(paged)
    _forge_onto_page_three(paged, digest)

    report = _replayed(paged)

    citations = report["citations"]
    assert isinstance(citations, dict)
    assert citations["not_handed"] == 1 and citations["not_located"] == 0
    flagged_runs = report["runs_with_not_handed"]
    assert isinstance(flagged_runs, list)
    [flagged] = flagged_runs
    node = _node(paged, "CP-L10").route_node_id
    assert flagged["run_id"] == str(paged.run_id)
    [entry] = flagged["not_handed"]
    assert entry["route_node_id"] == node and entry["citation"] >= 1
    assert entry["code"] == "CITATION_NOT_DELIVERED"
    # Counts and ids: no document text reaches the report.
    assert DUPLICATE not in json.dumps(report)


def test_a_connection_is_read_only_and_a_write_is_refused(paged: _Harness) -> None:
    _accepted(paged)
    with replay.read_only(paged.url) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("UPDATE artifacts SET record_sha256 = record_sha256")
    still = paged.conn.execute("SELECT count(*) FROM artifacts").fetchone()
    paged.conn.rollback()
    assert still == (2,)


def test_a_server_that_does_not_report_read_only_is_refused(
    paged: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        replay, "READ_ONLY_OPTION", "-c default_transaction_read_only=off"
    )
    with pytest.raises(replay.NotReadOnly), replay.read_only(paged.url):
        pass


def test_a_run_without_a_pinned_route_is_skipped_with_its_code(
    paged: _Harness,
) -> None:
    unpinned = start_run(paged.conn, paged.case_id)
    paged.conn.commit()
    with replay.read_only(paged.url) as conn:
        skipped = replay.replay_run(conn, paged.blobs, paged.bundle, unpinned)
    assert skipped.skipped == "ORCHESTRATION_ROUTE_NOT_PINNED"
    assert skipped.nodes == 0 and not skipped.citations


def test_a_database_with_no_accepted_run_replays_nothing(
    paged: _Harness,
) -> None:
    assert _replayed(paged)["accepted_runs"] == 0


def test_main_prints_the_report_and_names_only_a_code_on_a_bad_server(
    paged: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    digest = _accepted(paged)
    _forge_onto_page_three(paged, digest)
    name = paged.conn.info.dbname
    monkeypatch.setenv("CAOS_QUALIFY_POSTGRES_URL", paged.url)
    blob_root = str(paged.blobs.root)

    assert replay.main([name, "--blob-root", blob_root]) == 0

    [report] = json.loads(capsys.readouterr().out)["databases"]
    assert report["database"] == name and report["citations"]["not_handed"] == 1

    monkeypatch.delenv("CAOS_QUALIFY_POSTGRES_URL")
    assert replay.main([name, "--blob-root", blob_root]) == 2
    secret = "s3cr3t" + os.urandom(4).hex()
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", f"postgresql://u:{secret}%zz@127.0.0.1:1/x"
    )
    assert replay.main([name, "--blob-root", blob_root]) == 2
    err = capsys.readouterr().err
    assert "STORE_UNAVAILABLE" in err and secret not in err


def test_the_harness_databases_are_listed_by_the_names_it_mints(
    server: tuple[str, list[str]],
) -> None:
    admin_url, made = server
    held, _ = qualify._create_database(admin_url)
    made.append(held)

    assert held in replay.qualify_databases(admin_url)
    assert replay.database_url(admin_url, held).endswith(f"/{held}")


def test_the_accepted_runs_are_listed_and_a_run_replay_carries_its_ids(
    paged: _Harness,
) -> None:
    _accepted(paged)
    with replay.read_only(paged.url) as conn:
        assert replay.accepted_run_ids(conn) == [paged.run_id]
        run = replay.replay_run(conn, paged.blobs, paged.bundle, paged.run_id)
    assert isinstance(run, replay.RunReplay) and run.run_id == str(paged.run_id)
    database = replay.DatabaseReplay("fixture", [run])
    assert isinstance(database, replay.DatabaseReplay)
    assert database.report()["accepted_runs"] == 1
