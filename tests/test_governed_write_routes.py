"""Task 12.1: the seven governed writes reach the wire (O20).

Membership, withdrawal and the whole filing chain were store functions no
request path reached. Each is now one command through the shared envelope, so
what these prove is not that the store still works -- `tests/test_filing_chain.py`
and `tests/test_members.py` hold that -- but the three things a route adds:
the identity the caller may assert, the digest the request binds, and the
receipt a retry replays.

The three-actor rule is checked here over HTTP because that is where it can be
evaded: the Report section composes the control from what it can see, and a
signer whose browser still shows "Freeze" is refused at commit, under the case
lock, by the store and not by the view.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_client, command_headers, member
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx2 import Response
from test_deliverable_canonical import _accept, harness, lite, route
from test_execution_freshness import _Harness
from test_revisions import _save
from test_run_commands import _Counting

from caos.api.app import app, methodology_bundle, store_connection
from caos.api.commands import deliverable, members
from caos.api.commands._request import require_case_admin
from caos.api.deps import actor_from_request
from caos.api.reads import reports as reports_read
from caos.boundary_text import BoundaryText
from caos.deliverable.filing import Receipt, filing_payload, sign_opinion
from caos.refusals import Refusal
from caos.store import StoreConnection, connect
from caos.store.audit import audit_trail, digest_of
from caos.store.commands import (
    REQUEST_KEY,
    _WithRequest,
    payload_digests,
    record_receipt,
)
from caos.store.members import Standing, standing_of
from caos.store.runs import create_case, start_run

__all__ = ["command_client", "harness", "lite", "route"]


@pytest.fixture
def filing_client(command_client: TestClient, lite: _Harness) -> TestClient:
    """The command client over the harness's own bundle and accepted run."""
    app.dependency_overrides[methodology_bundle] = lambda: lite.bundle
    return command_client


def _post(
    client: TestClient, path: str, user: UUID, body: dict[str, Any] | None = None
) -> Response:
    answer: Response = client.post(
        path, headers=command_headers(user), json={} if body is None else body
    )
    return answer


def _approver(lite: _Harness) -> UUID:
    return member(lite.conn, lite.case_id, Standing.APPROVER)


def _digest(lite: _Harness, revision: UUID) -> str:
    row = lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_revisions WHERE revision_id=%s",
        (revision,),
    ).fetchone()
    lite.conn.rollback()
    assert row is not None
    return str(row[0])


def _case(lite: _Harness) -> str:
    return f"/api/v1/cases/{lite.case_id}"


# --- membership -------------------------------------------------------------


def test_an_administrator_grants_and_revokes_standing_over_http(
    command_client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    admin = member(conn, case_id, Standing.ADMIN)
    newcomer = uuid4()

    granted = _post(
        command_client,
        f"/api/v1/cases/{case_id}/members",
        admin,
        {"user_id": str(newcomer), "standing": "WRITER"},
    )
    assert (granted.status_code, granted.json()["standing"]) == (201, "WRITER")
    conn.rollback()
    assert standing_of(conn, case_id=case_id, user_id=newcomer) is Standing.WRITER
    conn.rollback()

    revoked = _post(
        command_client, f"/api/v1/cases/{case_id}/members/{newcomer}/revocation", admin
    )
    assert revoked.status_code == 200
    conn.rollback()
    assert standing_of(conn, case_id=case_id, user_id=newcomer) is None
    conn.rollback()


def test_revoking_a_user_who_holds_no_standing_writes_no_event(
    command_client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """`withdraw_source`'s rule, one table over: nothing was revoked, so the
    chain must not say something was."""
    conn, case_id = case
    admin = member(conn, case_id, Standing.ADMIN)
    before = conn.execute("SELECT count(*) FROM audit_events").fetchone()
    conn.rollback()

    answer = _post(
        command_client, f"/api/v1/cases/{case_id}/members/{uuid4()}/revocation", admin
    )

    assert (answer.status_code, answer.json()["code"]) == (400, "REQUEST_INVALID")
    after = conn.execute("SELECT count(*) FROM audit_events").fetchone()
    receipts = conn.execute("SELECT count(*) FROM command_requests").fetchone()
    conn.rollback()
    assert (after, receipts) == (before, (0,))


# --- withdrawal -------------------------------------------------------------


def test_withdrawing_a_source_over_http_takes_it_out_of_the_live_set(
    command_client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    writer = member(conn, case_id, Standing.WRITER)
    admitted = command_client.post(
        f"/api/v1/cases/{case_id}/sources",
        headers=command_headers(writer),
        files=[("document", ("report.txt", b"Total debt was USD 1,240.0m\n", "x"))],
    )
    [source_id] = admitted.json()["source_ids"]

    answer = _post(
        command_client,
        f"/api/v1/cases/{case_id}/sources/{source_id}/withdrawal",
        writer,
    )

    assert (answer.status_code, answer.json()["source_id"]) == (200, source_id)
    live = conn.execute(
        "SELECT count(*) FROM live_sources WHERE case_id=%s", (case_id,)
    ).fetchone()
    conn.rollback()
    assert live == (0,)
    again = _post(
        command_client,
        f"/api/v1/cases/{case_id}/sources/{source_id}/withdrawal",
        writer,
    )
    assert (again.status_code, again.json()["code"]) == (409, "EVIDENCE_NOT_AVAILABLE")


# --- the filing chain -------------------------------------------------------


def test_a_revision_is_saved_from_the_run_and_never_from_the_request(
    filing_client: TestClient, lite: _Harness
) -> None:
    writer = member(lite.conn, lite.case_id, Standing.WRITER)

    answer = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": None, "narrative": []},
    )

    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["run_id"] == str(lite.run_id)
    assert _digest(lite, UUID(body["revision_id"])) == body["payload_sha256"]


def test_a_signer_who_then_freezes_is_refused_at_commit(
    filing_client: TestClient, lite: _Harness
) -> None:
    """The three-actor rule. The control was offered; the commit refuses."""
    revision = _save(lite)
    digest = _digest(lite, revision)
    signer = _approver(lite)
    signed = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/signature",
        signer,
        {"payload_sha256": digest},
    )
    assert signed.status_code == 200, signed.text

    frozen = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        signer,
        {"payload_sha256": digest},
    )

    assert (frozen.status_code, frozen.json()["code"]) == (
        400,
        "APPROVER_NOT_INDEPENDENT",
    )
    publications = lite.conn.execute(
        "SELECT count(*) FROM deliverable_publications"
    ).fetchone()
    lite.conn.rollback()
    assert publications == (0,)


def test_a_signer_or_the_freezer_who_then_files_is_refused_at_commit(
    filing_client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    digest = _digest(lite, revision)
    signer, freezer = _approver(lite), _approver(lite)
    assert (
        _post(
            filing_client,
            f"{_case(lite)}/revisions/{revision}/signature",
            signer,
            {"payload_sha256": digest},
        ).status_code
        == 200
    )
    assert (
        _post(
            filing_client,
            f"{_case(lite)}/revisions/{revision}/freeze",
            freezer,
            {"payload_sha256": digest},
        ).status_code
        == 200
    )

    for actor in (signer, freezer):
        refused = _post(
            filing_client,
            f"{_case(lite)}/revisions/{revision}/filing",
            actor,
            {"payload_sha256": digest},
        )
        assert refused.json()["code"] == "APPROVER_NOT_INDEPENDENT", refused.text

    filer = _approver(lite)
    filed = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/filing",
        filer,
        {"payload_sha256": digest},
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["filed_by"] == str(filer)
    receipts = lite.conn.execute("SELECT count(*) FROM deliverable_receipts").fetchone()
    lite.conn.rollback()
    assert receipts == (1,), "the filing event's detached receipt rides its unit"


# --- digest-bound conflicts, driven with two connections --------------------


def test_a_save_that_raced_another_save_refuses_rather_than_committing(
    filing_client: TestClient, lite: _Harness, empty_database: str
) -> None:
    """Both drafts were written against the same latest revision; one lands."""
    writer = member(lite.conn, lite.case_id, Standing.WRITER)
    path = f"{_case(lite)}/runs/{lite.run_id}/revisions"
    seen: dict[str, Any] = {"expected_revision_id": None, "narrative": []}

    first = _post(filing_client, path, writer, seen)
    assert first.status_code == 201, first.text
    second = _post(filing_client, path, writer, seen)

    assert (second.status_code, second.json()["code"]) == (
        409,
        "COMMAND_EXPECTATION_STALE",
    )
    with connect(empty_database) as observer:
        rows = observer.execute(
            "SELECT count(*) FROM deliverable_revisions WHERE run_id=%s",
            (lite.run_id,),
        ).fetchone()
    assert rows == (1,)


def test_a_freeze_against_a_digest_that_is_not_the_revisions_refuses(
    filing_client: TestClient, lite: _Harness
) -> None:
    """An expectation check, and deliberately not a race.

    A revision is immutable by trigger (`0015_revisions.sql`), so nothing can
    move the bytes under a freeze; the only thing that can move is whether it is
    already frozen, and that is raced on four connections in
    `tests/test_postgres_races.py`. What this proves is the other half of
    invariant 5 -- that an approver acting on bytes other than the ones in front
    of them is refused -- and a literal digest is the whole of that case.
    """
    revision = _save(lite)
    digest = _digest(lite, revision)
    _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/signature",
        _approver(lite),
        {"payload_sha256": digest},
    )

    answer = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        _approver(lite),
        {"payload_sha256": "b" * 64},
    )

    assert answer.json()["code"] == "DELIVERABLE_MOVED_SINCE_SIGNING", answer.text


def test_a_superseded_revision_refuses_signature_freeze_and_filing(
    filing_client: TestClient, lite: _Harness
) -> None:
    """CF-026: a revision that is no longer the run's head must not be signed,
    frozen or filed, even though its stored digest still matches exactly what
    the caller reviewed. `save` already refuses a stale draft this way
    (`COMMAND_EXPECTATION_STALE`); the same code is reused here because the
    shape is the same -- the actor's expectation of what is current no longer
    holds."""
    superseded = _save(lite)
    stale_digest = _digest(lite, superseded)
    _save(lite)  # a fresh head; `superseded` is no longer the run's newest

    for path in (
        f"{_case(lite)}/revisions/{superseded}/signature",
        f"{_case(lite)}/revisions/{superseded}/freeze",
        f"{_case(lite)}/revisions/{superseded}/filing",
    ):
        answer = _post(
            filing_client, path, _approver(lite), {"payload_sha256": stale_digest}
        )
        assert (answer.status_code, answer.json()["code"]) == (
            409,
            "COMMAND_EXPECTATION_STALE",
        ), answer.text


def test_a_filing_against_a_digest_that_is_no_longer_the_frozen_one_refuses(
    filing_client: TestClient, lite: _Harness
) -> None:
    """The same expectation check, and the same deliberate gap: the frozen
    digest is the revision's, which cannot move. A second filing is what can
    race, and that is `DELIVERABLE_ALREADY_FILED` on two connections.
    """
    revision = _save(lite)
    digest = _digest(lite, revision)
    _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/signature",
        _approver(lite),
        {"payload_sha256": digest},
    )
    _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        _approver(lite),
        {"payload_sha256": digest},
    )

    answer = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/filing",
        _approver(lite),
        {"payload_sha256": "c" * 64},
    )

    assert answer.json()["code"] == "DELIVERABLE_MOVED_SINCE_SIGNING", answer.text


# --- receipts ---------------------------------------------------------------


def test_every_new_command_replays_its_receipt_and_commits_nothing_twice(
    filing_client: TestClient, lite: _Harness
) -> None:
    conn, case_id = lite.conn, lite.case_id
    admin = member(conn, case_id, Standing.ADMIN)
    newcomer = uuid4()
    revision = _save(lite)
    digest = _digest(lite, revision)
    signer = _approver(lite)
    freezer = _approver(lite)
    _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/signature",
        signer,
        {"payload_sha256": digest},
    )
    _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        freezer,
        {"payload_sha256": digest},
    )
    filer = _approver(lite)
    sent: list[tuple[str, UUID, dict[str, Any]]] = [
        (
            f"{_case(lite)}/members",
            admin,
            {"user_id": str(newcomer), "standing": "READER"},
        ),
        (
            f"{_case(lite)}/revisions/{revision}/filing",
            filer,
            {"payload_sha256": digest},
        ),
    ]
    for path, actor, body in sent:
        headers = command_headers(actor)
        first = filing_client.post(path, headers=headers, json=body)
        assert first.status_code in (200, 201), first.text
        events = conn.execute("SELECT count(*) FROM audit_events").fetchone()
        conn.rollback()

        again = filing_client.post(path, headers=headers, json=body)

        assert again.headers["idempotency-replayed"] == "true"
        assert again.json() == first.json()
        after = conn.execute("SELECT count(*) FROM audit_events").fetchone()
        conn.rollback()
        assert after == events, path


_FILING = ("SAVE_REVISION", "SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE")
# The three-actor progression below walks sign/freeze/file on one fixed
# revision; SAVE_REVISION is deliberately not among them there because sending
# it while it is offered would supersede that same revision (CF-026) and stale
# every step after it. Its own offered/refused parity is walked separately,
# once the chain is filed and no further state on `revision` is needed.
_SIGNING = ("SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE")
_PATH = {
    "SIGN_OPINION": "signature",
    "FREEZE_DELIVERABLE": "freeze",
    "FILE_DELIVERABLE": "filing",
}


def _shown(
    client: TestClient, lite: _Harness, revision: UUID, actor: UUID
) -> dict[str, str | None]:
    """The Report section's judgement of its four controls, for this actor."""
    answer = client.get(
        f"{_case(lite)}/report?run={lite.run_id}&revision={revision}",
        headers=command_headers(actor),
    )
    assert answer.status_code == 200, answer.text
    return {
        view["action"]: view["refusal"] and view["refusal"]["code"]
        for view in answer.json()["chrome"]["actions"]
    }


def _send(
    client: TestClient, lite: _Harness, revision: UUID, actor: UUID, action: str
) -> Response:
    digest = _digest(lite, revision)
    if action == "SAVE_REVISION":
        return _post(
            client,
            f"{_case(lite)}/runs/{lite.run_id}/revisions",
            actor,
            {"expected_revision_id": str(revision), "narrative": []},
        )
    return _post(
        client,
        f"{_case(lite)}/revisions/{revision}/{_PATH[action]}",
        actor,
        {"payload_sha256": digest},
    )


def test_every_filing_control_the_report_shows_answers_as_it_was_shown(
    filing_client: TestClient, lite: _Harness
) -> None:
    """Step 5's gate for this section: a control shown available succeeds and a
    control shown refused refuses with exactly the code shown -- walked over
    every state the chain distinguishes, judged by the document read
    immediately before each command is sent.

    All three the walk touches are exercised on one fixed revision, and once
    at the end, CF-026's own control -- SAVE_REVISION is offered while it is
    still the head and refused, with the code `save` has always answered a
    stale draft, once it is superseded."""
    signer, freezer, filer = (_approver(lite) for _ in range(3))
    revision = _save(lite)

    def walk(actor: UUID, action: str) -> None:
        shown = _shown(filing_client, lite, revision, actor)[action]
        answer = _send(filing_client, lite, revision, actor, action)
        if shown is None:
            assert answer.status_code in (200, 201), (action, answer.text)
        else:
            assert answer.json()["code"] == shown, (action, answer.text)

    # Unsigned: freeze and file are refused, the sign is not.
    for action in _SIGNING:
        walk(freezer, action)
    walk(signer, "SIGN_OPINION")
    # Signed: the signer is offered neither the freeze nor the filing.
    for action in _SIGNING:
        walk(signer, action)
    walk(freezer, "FREEZE_DELIVERABLE")
    # Frozen: the signer and the freezer are refused the filing; a third is not.
    for actor in (signer, freezer, filer):
        walk(actor, "FILE_DELIVERABLE")
    # Filed: every one of the three is refused, each with its own code.
    for action in _SIGNING:
        walk(filer, action)
    # And a member below the floor is refused every one of them.
    reader = member(lite.conn, lite.case_id, Standing.READER)
    assert set(_shown(filing_client, lite, revision, reader).values()) == {
        "NOT_AUTHORISED"
    }

    # CF-026: filed and still the run's head, a save is offered and succeeds.
    writer = member(lite.conn, lite.case_id, Standing.WRITER)
    assert _shown(filing_client, lite, revision, writer)["SAVE_REVISION"] is None
    superseding = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": str(revision), "narrative": []},
    )
    assert superseding.status_code == 201, superseding.text
    # Superseded, every one of the three the walk exercised is now shown, and
    # refused, exactly as a stale save always has been.
    stale = _shown(filing_client, lite, revision, filer)
    assert {stale[action] for action in _SIGNING} == {"COMMAND_EXPECTATION_STALE"}
    for action in _SIGNING:
        answer = _send(filing_client, lite, revision, filer, action)
        assert answer.json()["code"] == "COMMAND_EXPECTATION_STALE", (
            action,
            answer.text,
        )


def _unsaved(client: TestClient, lite: _Harness, actor: UUID) -> Response:
    """The Report for the run with no revision named, as the workspace opens it."""
    answer: Response = client.get(
        f"{_case(lite)}/report?run={lite.run_id}", headers=command_headers(actor)
    )
    return answer


def _judged(document: dict[str, Any]) -> dict[str, str | None]:
    return {
        view["action"]: view["refusal"] and view["refusal"]["code"]
        for view in document["chrome"]["actions"]
    }


def test_a_run_with_no_revision_is_served_a_report_that_offers_its_first_save(
    filing_client: TestClient, lite: _Harness
) -> None:
    """The filing chain's front door. Without a revision the Report names the
    run's accepted artifacts as a save would carry them and offers the save
    that makes the first revision; after it, the same address serves the head.
    """
    conn = lite.conn
    approver = _approver(lite)
    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted

    first = _unsaved(filing_client, lite, approver)

    assert first.status_code == 200, first.text
    assert counted.executed == reports_read.IO_BUDGET["unsaved"]
    document = first.json()
    body = document["body"]
    # Accepted artifacts are shown, so the section is not an empty observation.
    assert document["observed_empty"] is False
    assert (body["revision_id"], body["payload_sha256"], body["narrative"]) == (
        None,
        None,
        [],
    )
    assert body["displayed_run_id"] == str(lite.run_id)
    assert [a["route_node_id"] for a in body["artifacts"]] == [
        n.route_node_id for n in lite.route.nodes
    ]
    assert _judged(document) == {
        "SAVE_REVISION": None,
        "SIGN_OPINION": "DELIVERABLE_NOT_FOUND",
        "FREEZE_DELIVERABLE": "DELIVERABLE_NOT_FOUND",
        "FILE_DELIVERABLE": "DELIVERABLE_NOT_FOUND",
    }

    saved = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        approver,
        {"expected_revision_id": body["revision_id"], "narrative": []},
    )

    assert saved.status_code == 201, saved.text
    head = _unsaved(filing_client, lite, approver).json()
    assert head["body"]["revision_id"] == saved.json()["revision_id"]
    assert head["observed_empty"] is False
    assert _judged(head)["SAVE_REVISION"] is None
    assert _judged(head)["SIGN_OPINION"] is None


def test_a_first_save_the_run_cannot_derive_is_shown_refused_with_its_code(
    command_client: TestClient, harness: _Harness
) -> None:
    """A run with a pinned node unaccepted cannot be saved, and the Report says
    so with the code the save answers rather than offering it. It serves no
    artifact either: nothing it could show has been proven."""
    app.dependency_overrides[methodology_bundle] = lambda: harness.bundle
    _accept(harness, "CP-0")
    writer = member(harness.conn, harness.case_id, Standing.WRITER)

    document = _unsaved(command_client, harness, writer)

    assert document.status_code == 200, document.text
    assert document.json()["body"]["artifacts"] == []
    shown = _judged(document.json())["SAVE_REVISION"]
    assert shown == "DELIVERABLE_PAYLOAD_INVALID"
    answer = _post(
        command_client,
        f"{_case(harness)}/runs/{harness.run_id}/revisions",
        writer,
        {"expected_revision_id": None, "narrative": []},
    )
    assert answer.json()["code"] == shown


def test_a_report_without_a_revision_is_private_to_the_runs_case(
    filing_client: TestClient, lite: _Harness
) -> None:
    """No revision named, the run is what is selected, so an unknown run and a
    run of another case get the one answer a run section gives either."""
    approver = _approver(lite)
    other = create_case(lite.conn, BoundaryText.of("Other case"))
    foreign = start_run(lite.conn, other)
    lite.conn.commit()
    for run in (uuid4(), foreign, None):
        path = f"{_case(lite)}/report" + ("" if run is None else f"?run={run}")
        answer = filing_client.get(path, headers=command_headers(approver))
        assert answer.status_code == 404, answer.text
        assert answer.json()["code"] == "RUN_NOT_FOUND"


def test_each_new_command_meets_its_declared_store_budget(
    filing_client: TestClient, lite: _Harness
) -> None:
    """Each filing command's declared cost is measured, and met exactly.

    Freeze is measured beside save because it pays the same price: `freeze_in`
    re-proves the revision under the lock, which is the whole payload
    derivation again. The membership commands still share one ceiling.

    The withdrawal is sent last on purpose: it takes the run's one source out
    of the live set, and every later derivation of this run's payload would
    then refuse -- which is invariant 1 working, and would make the earlier
    measurements measurements of a refusal.
    """
    conn, case_id = lite.conn, lite.case_id
    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted
    signer, freezer, filer = (_approver(lite) for _ in range(3))
    original = _save(lite)
    writer = member(conn, case_id, Standing.WRITER)
    admin = member(conn, case_id, Standing.ADMIN)
    target = member(conn, case_id, Standing.READER)

    # The save below supersedes `original` (CF-026), so sign, freeze and file
    # are measured on the revision it names, not the one that composed it; its
    # own cost is measured here, ahead of the loop, for the same reason.
    counted.executed = 0
    saved = _post(
        filing_client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": str(original), "narrative": []},
    )
    assert saved.status_code == 201, saved.text
    assert counted.executed == deliverable.SAVE_IO
    revision = UUID(saved.json()["revision_id"])
    digest = saved.json()["payload_sha256"]

    # The filing commands each declare their own cost and are held to it
    # exactly, as every section read is: a ceiling shared by four commands let
    # the signature grow from fourteen round trips to sixty unnoticed.
    exact = [
        (
            deliverable.SIGN_IO,
            f"{_case(lite)}/revisions/{revision}/signature",
            signer,
            {"payload_sha256": digest},
        ),
        (
            deliverable.FREEZE_IO,
            f"{_case(lite)}/revisions/{revision}/freeze",
            freezer,
            {"payload_sha256": digest},
        ),
        (
            deliverable.FILE_IO,
            f"{_case(lite)}/revisions/{revision}/filing",
            filer,
            {"payload_sha256": digest},
        ),
    ]
    bounded = [
        (
            members.IO_BUDGET,
            f"{_case(lite)}/members",
            admin,
            {"user_id": str(uuid4()), "standing": "READER"},
        ),
        (members.IO_BUDGET, f"{_case(lite)}/members/{target}/revocation", admin, {}),
        (
            members.IO_BUDGET,
            f"{_case(lite)}/sources/{lite.source_id}/withdrawal",
            writer,
            {},
        ),
    ]
    for held_exactly, sent in ((True, exact), (False, bounded)):
        for budget, path, actor, body in sent:
            counted.executed = 0
            answer = filing_client.post(path, headers=command_headers(actor), json=body)
            assert answer.status_code in (200, 201), (path, answer.text)
            if held_exactly:
                assert counted.executed == budget, (path, counted.executed)
            else:
                assert 0 < counted.executed <= budget, (path, counted.executed)
    assert deliverable.IO_BUDGET == max(
        deliverable.SAVE_IO,
        deliverable.SIGN_IO,
        deliverable.FREEZE_IO,
        deliverable.FILE_IO,
    )


def _chain_over_http(client: TestClient, lite: _Harness) -> tuple[UUID, UUID]:
    """Save, sign, freeze and file one revision entirely over the wire."""
    writer = member(lite.conn, lite.case_id, Standing.WRITER)
    saved = _post(
        client,
        f"{_case(lite)}/runs/{lite.run_id}/revisions",
        writer,
        {"expected_revision_id": _latest_revision(lite), "narrative": []},
    )
    assert saved.status_code == 201, saved.text
    revision = UUID(saved.json()["revision_id"])
    digest = saved.json()["payload_sha256"]
    for tail in ("signature", "freeze", "filing"):
        answer = _post(
            client,
            f"{_case(lite)}/revisions/{revision}/{tail}",
            _approver(lite),
            {"payload_sha256": digest},
        )
        assert answer.status_code == 200, (tail, answer.text)
    return revision, lite.run_id


def _latest_revision(lite: _Harness) -> str | None:
    row = lite.conn.execute(
        "SELECT revision_id FROM deliverable_revisions WHERE case_id=%s AND run_id=%s"
        " ORDER BY saved_at DESC, revision_id DESC LIMIT 1",
        (lite.case_id, lite.run_id),
    ).fetchone()
    lite.conn.rollback()
    return None if row is None else str(row[0])


def _committee(
    client: TestClient, lite: _Harness, revision: UUID, actor: UUID
) -> Response:
    answer: Response = client.get(
        f"{_case(lite)}/committee?run={lite.run_id}&revision={revision}",
        headers=command_headers(actor),
    )
    return answer


def test_a_deliverable_filed_over_http_reads_back_from_the_committee_section(
    filing_client: TestClient, lite: _Harness
) -> None:
    """The act and its proof are one contract, and the routes are only half of
    it: a filing these commands make must verify through the reader that serves
    it, or the deliverable is unreadable for good -- `audit_events`,
    `deliverable_opinions` and `deliverable_publications` are all immutable.
    """
    reader = member(lite.conn, lite.case_id, Standing.READER)
    revision, _run = _chain_over_http(filing_client, lite)

    answer = _committee(filing_client, lite, revision, reader)

    assert answer.status_code == 200, answer.text
    body = answer.json()["body"]
    assert body["state"] == "filed"
    assert body["receipt"]["revision_id"] == str(revision)

    # And the event itself, not only the 200: the filing's audit payload is the
    # one `filing_payload` rebuilds, under the envelope's form.
    served = body["receipt"]
    receipt = Receipt(
        case_id=UUID(served["case_id"]),
        run_id=UUID(served["run_id"]),
        revision_id=UUID(served["revision_id"]),
        payload_sha256=served["payload_sha256"],
        signed_by=UUID(served["signed_by"]),
        frozen_by=UUID(served["frozen_by"]),
        filed_by=UUID(served["filed_by"]),
        renderer_sha256=served["renderer_sha256"],
        filed_event_sha256=served["filed_event_sha256"],
    )
    filed = next(
        entry
        for entry in audit_trail(lite.conn, lite.case_id)
        if entry.action == "DELIVERABLE_FILED"
    )
    accepted = payload_digests(
        lite.conn,
        scope=lite.case_id,
        actor_id=receipt.filed_by,
        payload=filing_payload(receipt),
        commands=("FILE_DELIVERABLE",),
    )
    lite.conn.rollback()
    assert filed.payload_sha256 in accepted
    assert filed.payload_sha256 != digest_of(filing_payload(receipt)), (
        "a command's event carries its request digest; the store's does not"
    )


def test_a_signature_sent_over_http_is_provable_beside_one_the_store_made(
    filing_client: TestClient, lite: _Harness
) -> None:
    """Mixed provenance, because a deployment upgraded mid-case has it: the
    Committee read proves an act whoever wrote it."""
    reader = member(lite.conn, lite.case_id, Standing.READER)
    revision = _save(lite)
    digest = _digest(lite, revision)
    sign_opinion(
        lite.conn,
        case_id=lite.case_id,
        actor_id=_approver(lite),
        revision_id=revision,
    )
    lite.conn.commit()
    frozen = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/freeze",
        _approver(lite),
        {"payload_sha256": digest},
    )
    assert frozen.status_code == 200, frozen.text

    answer = _committee(filing_client, lite, revision, reader)

    assert answer.status_code == 200, answer.text
    assert answer.json()["body"]["state"] == "frozen"


def test_report_lists_the_runs_revisions_so_committee_has_a_front_door(
    filing_client: TestClient, lite: _Harness
) -> None:
    """A committee member reaches a frozen revision from Report: the read lists
    the run's revisions newest first with how far each has gone, and a run with
    none lists none."""
    reader = member(lite.conn, lite.case_id, Standing.READER)
    unsaved = filing_client.get(
        f"{_case(lite)}/report?run={lite.run_id}", headers=command_headers(reader)
    )
    assert unsaved.status_code == 200, unsaved.text
    assert unsaved.json()["body"]["revisions"] == []

    first = _save(lite)
    second = _save(lite)
    sign_opinion(
        lite.conn, case_id=lite.case_id, actor_id=_approver(lite), revision_id=second
    )
    lite.conn.commit()
    frozen = _post(
        filing_client,
        f"{_case(lite)}/revisions/{second}/freeze",
        _approver(lite),
        {"payload_sha256": _digest(lite, second)},
    )
    assert frozen.status_code == 200, frozen.text

    listed = filing_client.get(
        f"{_case(lite)}/report?run={lite.run_id}&revision={first}",
        headers=command_headers(reader),
    ).json()["body"]["revisions"]
    assert [(row["revision_id"], row["state"]) for row in listed] == [
        (str(second), "frozen"),
        (str(first), "saved"),
    ]
    assert listed[0]["payload_sha256"] == _digest(lite, second)
    committee = _committee(filing_client, lite, second, reader).json()["body"]
    assert committee["revisions"] == listed


# The commands that can write the three filing actions, which is what bounds
# `payload_digests`' receipt read. Not `_FILING` above: that is the four
# *actions* the controls are drawn from.
_FILING_COMMANDS = ("SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE")


def test_payload_digests_accepts_both_writers_and_nothing_else(
    lite: _Harness,
) -> None:
    """An audit payload is digested and never stored, so a reader that proves an
    event bound exactly some fields has to rebuild what the writer built -- and
    there are two writers. A store function called directly binds the payload as
    given; a command's envelope adds its request digest, which is not
    recomputable from the payload and is read back from the receipts that actor
    committed on that case.

    Both are exact. A payload carrying one more field, or one different value,
    matches neither, which is what keeps this a rebuild and not a relaxation.
    """
    conn, case_id = lite.conn, lite.case_id
    actor = _approver(lite)
    bound = {"revision_id": str(uuid4()), "payload_sha256": "a" * 64}

    before = payload_digests(
        conn, scope=case_id, actor_id=actor, payload=bound, commands=_FILING_COMMANDS
    )
    assert before == {digest_of(bound)}, "no receipt yet: only the store's own form"

    key, request = uuid4(), "b" * 64
    record_receipt(
        conn,
        actor_id=actor,
        scope=case_id,
        key=key,
        command="SIGN_OPINION",
        request_sha256=request,
        status=200,
        receipt={"revision_id": bound["revision_id"]},
    )
    conn.commit()

    after = payload_digests(
        conn, scope=case_id, actor_id=actor, payload=bound, commands=_FILING_COMMANDS
    )

    assert after == {digest_of(bound), digest_of({**bound, "request_sha256": request})}
    for wrong in (
        {**bound, "extra": "1"},
        {**bound, "payload_sha256": "c" * 64},
        {"revision_id": bound["revision_id"]},
    ):
        assert digest_of(wrong) not in after, wrong
    # Another actor's receipt is not this actor's request.
    assert payload_digests(
        conn, scope=case_id, actor_id=uuid4(), payload=bound, commands=_FILING_COMMANDS
    ) == {digest_of(bound)}
    conn.rollback()


def test_require_case_admin_is_the_floor_the_membership_commands_declare() -> None:
    """The floor is a dependency the route names, not a line inside it: an
    ADMIN floor written in the body would run after the store was opened."""
    routes = {
        inner.path: inner
        for route in app.routes
        for inner in getattr(getattr(route, "original_router", None), "routes", [route])
        if isinstance(inner, APIRoute)
    }
    for path in (
        "/api/v1/cases/{case_id}/members",
        "/api/v1/cases/{case_id}/members/{user_id}/revocation",
    ):
        calls = [d.call for d in routes[path].dependant.dependencies]
        assert require_case_admin in calls, path
        assert calls.index(actor_from_request) < calls.index(require_case_admin)


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/sources/not-a-uuid/withdrawal", "EVIDENCE_NOT_AVAILABLE"),
        ("/revisions/not-a-uuid/signature", "DELIVERABLE_NOT_FOUND"),
        ("/revisions/not-a-uuid/freeze", "DELIVERABLE_NOT_FOUND"),
        ("/revisions/not-a-uuid/filing", "DELIVERABLE_NOT_FOUND"),
        ("/members/not-a-uuid/revocation", "REQUEST_INVALID"),
    ],
)
def test_a_malformed_path_id_is_refused_in_the_declared_body(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    path: str,
    code: str,
) -> None:
    """`source_path`, `revision_path` and `member_path` each answer in the
    declared refusal body rather than FastAPI's 422, which would quote the
    input back."""
    conn, case_id = case
    actor = member(conn, case_id, Standing.ADMIN)

    answer = _post(command_client, f"/api/v1/cases/{case_id}{path}", actor)

    assert answer.json()["code"] == code, answer.text


def test_a_payload_naming_the_request_digest_itself_is_refused() -> None:
    """The envelope's view would shadow it, and disagree with itself doing so.

    `_WithRequest` answers `request_sha256` from the envelope while `__iter__`
    and `__len__` count the payload's own key once, so a payload carrying that
    key would be a mapping whose length did not match its items. Unreachable --
    no `GovernedAction` in the tree carries it -- and refused here because this
    is the one place that would hide it rather than raise.
    """
    with pytest.raises(Refusal, match=r"^INTERNAL_FAULT$"):
        _WithRequest({REQUEST_KEY: "a" * 64}, "b" * 64)

    view = _WithRequest({"revision_id": "r"}, "b" * 64)
    assert len(view) == len(list(view)) == 2
    assert view[REQUEST_KEY] == "b" * 64
