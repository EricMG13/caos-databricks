"""CF-019 (N107): a withdrawn pinned source refuses typed, never a permanent 500.

Withdrawal stays allowed as built (invariant 1: withdrawal is checked at every
use). What the Report read, a revision save, a freeze, a filing and the filed
read answered once a writer withdrew the source a pinned run used was
`ARTIFACT_RECORD_MISMATCH` -- 500, "an operator must verify the stored record",
for a record nobody can correct. The source is the cause, and
`EVIDENCE_NOT_AVAILABLE` (409, "Pin a live source for the evidence.") is the
code approval and start already refuse on for the same fact.
"""

from __future__ import annotations

from uuid import UUID

from command_fixtures import command_client, command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_governed_write_routes import (
    _approver,
    _case,
    _chain_over_http,
    _digest,
    _post,
    filing_client,
)
from test_revisions import _save

from caos.store.members import Standing

__all__ = ["command_client", "filing_client", "harness", "lite", "route"]

NOT_AVAILABLE = "EVIDENCE_NOT_AVAILABLE"


def _withdraw(client: TestClient, lite: _Harness) -> None:
    writer = member(lite.conn, lite.case_id, Standing.WRITER)
    answer = _post(client, f"{_case(lite)}/sources/{lite.source_id}/withdrawal", writer)
    assert answer.status_code == 200, answer.text


def _step(client: TestClient, lite: _Harness, revision: UUID, tail: str) -> None:
    answer = _post(
        client,
        f"{_case(lite)}/revisions/{revision}/{tail}",
        _approver(lite),
        {"payload_sha256": _digest(lite, revision)},
    )
    assert answer.status_code == 200, (tail, answer.text)


def _refused(answer: Response) -> tuple[int, str | None]:
    body = answer.json()
    return answer.status_code, body.get("code") if isinstance(body, dict) else None


def _read(client: TestClient, lite: _Harness, section: str, revision: UUID) -> Response:
    return client.get(
        f"{_case(lite)}/{section}?run={lite.run_id}&revision={revision}",
        headers=command_headers(member(lite.conn, lite.case_id, Standing.READER)),
    )


def test_the_report_read_of_a_saved_revision_refuses_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _withdraw(filing_client, lite)

    answer = _read(filing_client, lite, "report", revision)

    assert _refused(answer) == (409, NOT_AVAILABLE), answer.text


def test_saving_a_revision_refuses_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    _withdraw(filing_client, lite)
    writer = member(lite.conn, lite.case_id, Standing.WRITER)

    answer = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": None, "narrative": []},
    )

    assert _refused(answer) == (409, NOT_AVAILABLE), answer.text


def test_freezing_refuses_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _step(filing_client, lite, revision, "signature")
    _withdraw(filing_client, lite)

    answer = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        _approver(lite),
        {"payload_sha256": _digest(lite, revision)},
    )

    assert _refused(answer) == (409, NOT_AVAILABLE), answer.text


def test_filing_refuses_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _step(filing_client, lite, revision, "signature")
    _step(filing_client, lite, revision, "freeze")
    _withdraw(filing_client, lite)

    answer = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/filing",
        _approver(lite),
        {"payload_sha256": _digest(lite, revision)},
    )

    assert _refused(answer) == (409, NOT_AVAILABLE), answer.text


def test_the_report_read_of_a_filed_revision_refuses_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    """The Report section re-derives from the run as it stands, filed or not."""
    revision, _run = _chain_over_http(filing_client, lite)
    _withdraw(filing_client, lite)

    answer = _read(filing_client, lite, "report", revision)

    assert _refused(answer) == (409, NOT_AVAILABLE), answer.text


def test_the_filed_committee_read_is_served_from_its_own_bytes_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    """FP-05: a filed record is immutable, so the Committee section proves it
    from its stored receipt and serves it whatever became of the source."""
    revision, _run = _chain_over_http(filing_client, lite)
    _withdraw(filing_client, lite)

    answer = _read(filing_client, lite, "committee", revision)

    assert answer.status_code == 200, answer.text


def _withdraw_uncited(client: TestClient, lite: _Harness) -> None:
    writer = member(lite.conn, lite.case_id, Standing.WRITER)
    answer = _post(
        client, f"{_case(lite)}/sources/{lite.witness_id}/withdrawal", writer
    )
    assert answer.status_code == 200, answer.text


def test_withdrawing_a_member_no_citation_names_changes_nothing(
    filing_client: TestClient, lite: _Harness
) -> None:
    """Invariant 1 is checked where a source is used: a pinned member no record
    cites (the harness's `uncited.txt`) being withdrawn leaves the Report read,
    freeze and the first save as they were."""
    revision = _save(lite)
    _step(filing_client, lite, revision, "signature")
    _withdraw_uncited(filing_client, lite)

    assert _read(filing_client, lite, "report", revision).status_code == 200
    _step(filing_client, lite, revision, "freeze")


def test_a_first_save_succeeds_after_an_uncited_member_is_withdrawn(
    filing_client: TestClient, lite: _Harness
) -> None:
    _withdraw_uncited(filing_client, lite)
    writer = member(lite.conn, lite.case_id, Standing.WRITER)

    answer = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": None, "narrative": []},
    )

    assert answer.status_code == 201, answer.text


def test_the_frozen_committee_read_and_render_refuse_typed_after_a_withdrawal(
    filing_client: TestClient, lite: _Harness
) -> None:
    """A frozen, unfiled revision is re-derived, so a cited source's withdrawal
    refuses it by the same code in Committee and in the render."""
    revision = _save(lite)
    _step(filing_client, lite, revision, "signature")
    _step(filing_client, lite, revision, "freeze")
    _withdraw(filing_client, lite)

    committee = _read(filing_client, lite, "committee", revision)
    render = filing_client.get(
        f"{_case(lite)}/revisions/{revision}/render",
        headers=command_headers(member(lite.conn, lite.case_id, Standing.READER)),
    )

    assert _refused(committee) == (409, NOT_AVAILABLE), committee.text
    assert _refused(render) == (409, NOT_AVAILABLE), render.text
