"""The desk-wide read grant (Plan 3 Task 4, spec B9): any signed-in user
reads a live book entry's run -- its Analysis, its Model and the pages of
its pinned sources -- without standing on the case, read-only.

The grant is evaluated per request against the live entry at that moment,
for the run the request names and no other: a read without `run`, another
run of the same case, every other section read, the event stream and every
command stay member-only, and a non-member the grant does not reach is
refused exactly as a stranger is today, so its absence says nothing about
which runs have entries.

The run under test is the forecast route's, added by a WRITER
(`test_book_entries.added`).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_headers
from fastapi.testclient import TestClient
from httpx2 import Response
from test_analysis_section import _as, client
from test_book_entries import _withdraw, added
from test_evidence_page import _CountingConnection
from test_execution_freshness import _Harness
from test_forecast_route import harness, route
from test_identity_first import _routes
from test_model_section import pinned_deck

from caos.api import deps
from caos.api.app import app, store_connection
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import analysis as analysis_read
from caos.api.reads import evidence as evidence_read
from caos.api.wire import CLEARS
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.book import entry_run
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run

__all__ = ["added", "client", "harness", "pinned_deck", "route"]

# The reads the grant reaches; every other read under a case stays
# member-only.
_GRANTED_READS = frozenset(
    {
        "/api/v1/cases/{case_id}/analysis",
        "/api/v1/cases/{case_id}/model",
        "/api/v1/cases/{case_id}/runs/{run_id}/sources/{source_id}/pages/{page}",
    }
)
_PARAM = re.compile(r"\{(\w+)\}")
_NOT_FOUND = (
    404,
    {"code": "CASE_NOT_FOUND", "clears": CLEARS[RefusalCode.CASE_NOT_FOUND]},
)


def _section(harness: _Harness, section: str, run: object = None) -> str:
    path = f"/api/v1/cases/{harness.case_id}/{section}"
    return path if run is None else f"{path}?run={run}"


def _page(harness: _Harness, source: object, run: object = None) -> str:
    return (
        f"/api/v1/cases/{harness.case_id}/runs/{run or harness.run_id}"
        f"/sources/{source}/pages/1"
    )


def _read(client: TestClient, harness: _Harness, path: str, user: UUID) -> Response:
    try:
        answer: Response = client.get(path, headers=_as(user))
        return answer
    finally:
        harness.conn.rollback()


def _answer(response: Response) -> tuple[int, Any]:
    return response.status_code, response.json()


def _withdrawn(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    entry_id, digest, writer = added
    body = {"snapshot_sha256": digest, "reason": "ADDED_IN_ERROR", "note": None}
    answer = _withdraw(client, harness, writer, entry_id, body)
    assert answer.status_code == 200, answer.text


def test_a_non_member_reads_an_entry_runs_analysis_and_model(
    client: TestClient,
    harness: _Harness,
    added: tuple[UUID, str, UUID],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The same handoffs and the same model a member reads, and each granted
    read logged by case, run and user with no document text."""
    stranger = uuid4()
    capsys.readouterr()
    for section in ("analysis", "model"):
        path = _section(harness, section, harness.run_id)
        granted = _read(client, harness, path, stranger)
        seen = _read(client, harness, path, harness.approver)
        assert granted.status_code == seen.status_code == 200, granted.text
        body, member_body = granted.json()["body"], seen.json()["body"]
        assert body["displayed_run_id"] == str(harness.run_id)
        withheld = {"latest_run_id", "snapshot_sha256"}
        assert {k: v for k, v in body.items() if k not in withheld} == {
            k: v for k, v in member_body.items() if k not in withheld
        }
    logged = capsys.readouterr().err
    line = (
        f"book_entry_read case={harness.case_id} run={harness.run_id} user={stranger}"
    )
    assert logged.count(line) == 2, logged
    assert entry_run(harness.conn, harness.case_id, harness.run_id) is True
    harness.conn.rollback()


def test_a_non_member_cannot_read_another_run_of_the_same_case(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    other = start_run(harness.conn, harness.case_id)
    harness.conn.commit()
    stranger = uuid4()
    for section in ("analysis", "model"):
        path = _section(harness, section, other)
        assert _answer(_read(client, harness, path, stranger)) == _NOT_FOUND
    page = _page(harness, harness.source_id, other)
    assert _answer(_read(client, harness, page, stranger)) == _NOT_FOUND
    assert entry_run(harness.conn, harness.case_id, other) is False
    harness.conn.rollback()


def test_a_non_member_cannot_read_without_a_run_parameter(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """The entry's run is the case's latest, and still: no `run`, no grant."""
    stranger = uuid4()
    for section in ("analysis", "model"):
        path = _section(harness, section)
        assert _answer(_read(client, harness, path, stranger)) == _NOT_FOUND


def test_a_withdrawn_entry_no_longer_grants(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Evaluated per request: the read after the withdrawal is refused."""
    stranger = uuid4()
    paths = [
        _section(harness, "analysis", harness.run_id),
        _section(harness, "model", harness.run_id),
        _page(harness, harness.source_id),
    ]
    assert all(_read(client, harness, p, stranger).status_code == 200 for p in paths)
    _withdrawn(client, harness, added)
    for path in paths:
        assert _answer(_read(client, harness, path, stranger)) == _NOT_FOUND, path
    assert entry_run(harness.conn, harness.case_id, harness.run_id) is False
    harness.conn.rollback()


def test_a_non_member_reads_a_pinned_source_page_of_the_entry_run_only(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """No stored citation index exists, so the bound is the run's pinned
    source set (the task's ruling, a `Dn` at PR time; spec B9 says cited,
    and the narrower bound is `next.md` scope): a pinned source's page reads
    as a member's does -- the cited report and the uncited witness alike; a
    source of the case the run never pinned is the same `PAGE_NOT_AVAILABLE`
    a member gets; another run is the case refused."""
    conn = harness.conn
    stranger = uuid4()
    # `report.txt` is the one the run's handoffs cite; `uncited.txt` (the
    # witness) is pinned and cited by none, and still reads under the grant.
    for source in (harness.source_id, harness.witness_id):
        pinned = _page(harness, source)
        granted, seen = (
            _read(client, harness, pinned, u) for u in (stranger, harness.approver)
        )
        assert granted.status_code == 200, granted.text
        assert _answer(granted)[1]["body"] == _answer(seen)[1]["body"]
    [later] = admit_pack(
        conn,
        harness.blobs,
        case_id=harness.case_id,
        documents=[
            Document(
                filename=BoundaryText.of("later.txt"), data=b"Admitted after the pin.\n"
            )
        ],
    )
    conn.commit()
    unpinned = _page(harness, later)
    refused = (
        404,
        {
            "code": "PAGE_NOT_AVAILABLE",
            "clears": CLEARS[RefusalCode.PAGE_NOT_AVAILABLE],
        },
    )
    assert _answer(_read(client, harness, unpinned, harness.approver)) == refused
    assert _answer(_read(client, harness, unpinned, stranger)) == refused
    other = start_run(conn, harness.case_id)
    conn.commit()
    other_page = _page(harness, harness.source_id, other)
    assert _answer(_read(client, harness, other_page, stranger)) == _NOT_FOUND


def test_a_granted_read_serves_no_actions(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Visibly read-only: no standing, no actions, no digest an Add to Book
    could bind, and no id of the case's other runs."""
    newer = start_run(harness.conn, harness.case_id)
    harness.conn.commit()
    stranger = uuid4()
    for section in ("analysis", "model"):
        path = _section(harness, section, harness.run_id)
        document = _read(client, harness, path, stranger).json()
        assert document["chrome"]["served_role"] == {
            "global_role": "READER",
            "standing": None,
        }
        assert document["chrome"]["actions"] == []
        assert document["body"]["latest_run_id"] is None
        member = _read(client, harness, path, harness.approver).json()
        assert member["chrome"]["served_role"]["standing"] == "APPROVER"
        assert member["body"]["latest_run_id"] == str(newer)
    model = _read(client, harness, _section(harness, "model", harness.run_id), stranger)
    assert model.json()["body"]["snapshot_sha256"] is None
    member_model = _read(
        client, harness, _section(harness, "model", harness.run_id), harness.approver
    )
    assert member_model.json()["body"]["snapshot_sha256"] == added[1]


def _filled(path: str, harness: _Harness, entry_id: UUID) -> str:
    """`path` with every id the entry's: its case, its run, its own id, its
    pinned source; anything else a fresh id."""
    known = {
        "case_id": harness.case_id,
        "run_id": harness.run_id,
        "entry_id": entry_id,
        "source_id": harness.source_id,
        "page": 1,
        "gate": "source-set",
    }
    return _PARAM.sub(lambda m: str(known.get(m.group(1), uuid4())), path)


def _case_routes(*, reads: bool) -> list[tuple[str, str]]:
    """Every route under a case, as `test_identity_first` reaches them
    through the routers the app includes: its reads or its commands."""
    return sorted(
        (method, route.path)
        for route in _routes()
        if "{case_id}" in route.path
        for method in route.methods or ()
        if (method == "GET") is reads
    )


def test_run_report_committee_deliverable_and_events_stay_member_only(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Every read under a case but the three the grant reaches refuses a
    non-member naming the entry's run, as it refuses a stranger."""
    stranger = uuid4()
    member_only = [
        path for _m, path in _case_routes(reads=True) if path not in _GRANTED_READS
    ]
    assert {
        "/api/v1/cases/{case_id}/run",
        "/api/v1/cases/{case_id}/report",
        "/api/v1/cases/{case_id}/committee",
        "/api/v1/cases/{case_id}/revisions/{revision_id}/render",
        "/api/v1/cases/{case_id}/revisions/{revision_id}/package",
        "/api/v1/cases/{case_id}/events",
        "/api/v1/cases/{case_id}/upload",
    } <= set(member_only)
    query = f"?run={harness.run_id}&revision={uuid4()}"
    for path in member_only:
        url = _filled(path, harness, added[0]) + query
        assert _answer(_read(client, harness, url, stranger)) == _NOT_FOUND, path


def test_commands_never_accept_the_grant(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Every command under a case, naming the entry's run, refuses a
    non-member ANALYST as it refuses a stranger, and writes nothing."""
    stranger = uuid4()
    commands = _case_routes(reads=False)
    assert ("POST", "/api/v1/cases/{case_id}/runs/{run_id}/book-entry") in commands
    before = _rows(harness.conn)
    for method, path in commands:
        # The admission reads a multipart pack, every other command JSON.
        body: dict[str, Any] = (
            {"files": [("document", ("note.txt", b"A note.\n", "text/plain"))]}
            if path.endswith("/sources")
            else {"json": {}}
        )
        answer = client.request(
            method,
            _filled(path, harness, added[0]),
            headers=command_headers(stranger),
            **body,
        )
        harness.conn.rollback()
        assert _answer(answer) == _NOT_FOUND, (method, path)
    assert _rows(harness.conn) == before


def _rows(conn: StoreConnection) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT (SELECT count(*) FROM audit_events),"
        " (SELECT count(*) FROM book_entries WHERE withdrawn_at IS NULL),"
        " (SELECT count(*) FROM runs), (SELECT count(*) FROM sources),"
        " (SELECT count(*) FROM case_members)"
    ).fetchone()
    conn.rollback()
    assert row is not None
    return tuple(row)


def test_a_non_member_the_grant_does_not_reach_learns_nothing(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Refusal parity: a run with no entry, an unknown run, no run, a revoked
    member, and another case's entry run named under this case are each the
    answer a stranger gets for an unknown case -- status, code and body."""
    conn = harness.conn
    other = start_run(conn, harness.case_id)
    elsewhere = create_case(conn, title=BoundaryText.of("Another case"))
    conn.commit()
    revoked = uuid4()
    grant(conn, case_id=harness.case_id, user_id=revoked, standing=Standing.READER)
    revoke(conn, case_id=harness.case_id, user_id=revoked)
    conn.commit()
    stranger = uuid4()
    for section in ("analysis", "model"):
        baseline = _answer(
            _read(client, harness, f"/api/v1/cases/{uuid4()}/{section}", stranger)
        )
        assert baseline == _NOT_FOUND
        asked = [
            (_section(harness, section, other), stranger),
            (_section(harness, section, uuid4()), stranger),
            (_section(harness, section), stranger),
            (_section(harness, section, other), revoked),
            (f"/api/v1/cases/{elsewhere}/{section}?run={harness.run_id}", stranger),
        ]
        for path, user in asked:
            assert _answer(_read(client, harness, path, user)) == baseline, path
    pages = [
        _page(harness, harness.source_id, other),
        _page(harness, harness.source_id, uuid4()),
        f"/api/v1/cases/{elsewhere}/runs/{harness.run_id}/sources/"
        f"{harness.source_id}/pages/1",
    ]
    for path in pages:
        assert _answer(_read(client, harness, path, stranger)) == _NOT_FOUND, path
    assert entry_run(conn, elsewhere, harness.run_id) is False
    conn.rollback()


def test_a_revoked_member_still_reads_the_entry_run_under_the_grant(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """A revoked member is a non-member: the grant reaches them as anyone,
    read-only, and nothing of the standing they held is served."""
    conn = harness.conn
    former = uuid4()
    grant(conn, case_id=harness.case_id, user_id=former, standing=Standing.WRITER)
    revoke(conn, case_id=harness.case_id, user_id=former)
    conn.commit()
    path = _section(harness, "analysis", harness.run_id)
    document = _read(client, harness, path, former).json()
    assert document["chrome"]["served_role"]["standing"] is None


def test_the_granted_reads_meet_their_declared_budgets(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """A granted read pays the one live-entry lookup a member's does not;
    the page read folds it into the row it already reads."""
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    stranger = uuid4()
    member_count = []
    for user in (harness.approver, stranger):
        counter.executed = 0
        path = _section(harness, "analysis", harness.run_id)
        assert _read(client, harness, path, user).status_code == 200
        member_count.append(counter.executed)
    assert member_count[1] == member_count[0] + deps.GRANT_IO
    assert member_count[1] <= analysis_read.IO_BUDGET
    assert deps.IO_BUDGET == 1 + deps.GRANT_IO
    counter.executed = 0
    assert (
        _read(client, harness, _page(harness, harness.source_id), stranger).status_code
        == 200
    )
    assert counter.executed == evidence_read.IO_BUDGET


def test_visible_run_answers_standing_first_then_the_grant(
    harness: _Harness, added: tuple[UUID, str, UUID], capsys: pytest.CaptureFixture[str]
) -> None:
    """A member's standing whatever the run; for anyone else `Grant.BOOK`
    only for the named live entry run, else the private `CASE_NOT_FOUND`;
    `reads` is `readable`'s floor and `book_grant` the one log line."""
    conn, case_id, run_id = harness.conn, harness.case_id, harness.run_id
    member = Actor(harness.approver, GlobalRole.READER)
    stranger = Actor(uuid4(), GlobalRole.ADMIN)
    assert deps.visible_run(member, case_id, None, conn) is Standing.APPROVER
    capsys.readouterr()
    assert deps.visible_run(stranger, case_id, run_id, conn) is deps.Grant.BOOK
    assert capsys.readouterr().err == (
        f"book_entry_read case={case_id} run={run_id} user={stranger.user_id}\n"
    )
    for run in (None, uuid4()):
        with pytest.raises(Refusal) as caught:
            deps.visible_run(stranger, case_id, run, conn)
        assert caught.value.code is RefusalCode.CASE_NOT_FOUND
    conn.rollback()
    assert list(deps.Grant) == [deps.Grant.BOOK]
    assert deps.granted(deps.Grant.BOOK)
    assert not any(deps.granted(standing) for standing in Standing)
    assert all(deps.reads(standing) for standing in Standing)
    assert not deps.reads(None)
    assert deps.book_grant(case_id, run_id, stranger.user_id) is deps.Grant.BOOK


def _issuer_and_title(harness: _Harness) -> tuple[str, str]:
    row = harness.conn.execute(
        "SELECT e.issuer_name, c.title FROM book_entries e"
        " JOIN cases c USING (case_id) WHERE e.run_id = %s",
        (harness.run_id,),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    return str(row[0]), str(row[1])


def test_a_granted_read_names_the_entry_issuer_not_the_case(
    client: TestClient, harness: _Harness, added: tuple[UUID, str, UUID]
) -> None:
    """Fix round 1, audit L1: the case title is member-only (the Directory
    lists only cases the caller stands on, the Book serves no title), so a
    granted read's subject is titled with the entry's issuer name, which
    the Book already shows the desk -- never the case title."""
    issuer, title = _issuer_and_title(harness)
    assert issuer != title
    stranger = uuid4()
    for section in ("analysis", "model"):
        path = _section(harness, section, harness.run_id)
        granted = _read(client, harness, path, stranger)
        assert granted.status_code == 200, granted.text
        assert granted.json()["chrome"]["subject"] == {
            "case_id": str(harness.case_id),
            "title": issuer,
        }
        assert title not in granted.text
        member = _read(client, harness, path, harness.approver).json()
        assert member["chrome"]["subject"]["title"] == title


def test_a_grant_whose_entry_is_gone_by_the_case_row_is_refused(
    client: TestClient,
    harness: _Harness,
    added: tuple[UUID, str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issuer name is read in the case row, after the grant: an entry
    withdrawn between the two leaves no issuer to name, and the read is the
    stranger's `CASE_NOT_FOUND` -- never a document titled with nothing, nor
    the case title in its place."""
    _withdrawn(client, harness, added)
    # The grant as it was answered an instant before the withdrawal.
    monkeypatch.setattr(deps, "entry_run", lambda *_ids: True)
    stranger = uuid4()
    for section in ("analysis", "model"):
        path = _section(harness, section, harness.run_id)
        assert _answer(_read(client, harness, path, stranger)) == _NOT_FOUND, section
