"""The actor matrix: what a client may assert about itself.

The first phase exposing an HTTP route shipped identity derivation and the
actor matrix together (`test_production_never_trusts_role_header`,
`test_unauthorised_case_is_private_404`). This is that phase; the second of
the pair lives with the route it is about, in `tests/test_api_routes.py`.

Both are the same instinct and the same refusal to indulge it. A role header is
convenient in development and is a client asserting its own authority; a 403 is
informative and tells a stranger the case exists. Each is the comfortable answer,
and each is refused.

The switch is off unless explicitly on. An environment variable that had to be
set to *disable* trust is one a misconfigured deployment forgets, and that
failure is silent and total.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import anyio
import pytest
from command_fixtures import command_client, command_headers, member
from fastapi.testclient import TestClient
from test_deliverable_canonical import harness, lite, route
from test_execution_commands import ROUTE, _ready, _Run
from test_execution_freshness import _Harness

from caos.api.app import app, methodology_bundle
from caos.api.identity import (
    TRUST_SWITCH,
    GlobalRole,
    actor_from_headers,
    role_from_groups,
)
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.filing import freeze, sign_opinion
from caos.deliverable.revisions import save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store import commands as store_commands
from caos.store.gates import Gate, gate_preview
from caos.store.members import Standing, revoke
from caos.store.routes import pin_route

__all__ = ["command_client", "harness", "lite", "route"]

USER = uuid4()


def _headers(**extra: str) -> dict[str, str]:
    return {"x-caos-user": str(USER), **extra}


def test_the_role_header_is_trusted_only_when_explicitly_switched_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development's convenience, and it has to be asked for by name."""
    monkeypatch.setenv(TRUST_SWITCH, "1")

    actor = anyio.run(actor_from_headers, _headers(**{"x-caos-role": "ADMIN"}))

    assert actor.role is GlobalRole.ADMIN


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", "on"])
def test_anything_but_one_leaves_the_switch_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Off unless exactly `1`. A switch that also accepted "true", "yes" and "on"
    would eventually accept something a deployment set for another purpose."""
    monkeypatch.setenv(TRUST_SWITCH, value)

    actor = anyio.run(
        actor_from_headers,
        _headers(**{"x-caos-role": "ADMIN", "x-forwarded-groups": "caos-readers"}),
    )

    assert actor.role is GlobalRole.READER


def test_an_unknown_role_name_under_trust_is_still_the_lowest_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even switched on, the header names a role from the closed set or names
    nothing. A parse that fell through to "whatever the client typed" is the
    header being trusted twice over."""
    monkeypatch.setenv(TRUST_SWITCH, "1")

    actor = anyio.run(actor_from_headers, _headers(**{"x-caos-role": "SUPERUSER"}))

    assert actor.role is GlobalRole.READER


def test_no_groups_and_no_trust_is_the_lowest_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed. An identity the proxy said nothing about is not an
    administrator by default."""
    monkeypatch.delenv(TRUST_SWITCH, raising=False)

    actor = anyio.run(actor_from_headers, _headers())

    assert actor.role is GlobalRole.READER


def test_a_request_with_no_user_at_all_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRUST_SWITCH, raising=False)

    with pytest.raises(Refusal) as caught:
        anyio.run(actor_from_headers, {"x-forwarded-groups": "caos-admins"})

    assert caught.value.code is RefusalCode.NOT_AUTHENTICATED


def test_a_user_that_is_not_an_identifier_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subject is a uuid the host issued. Anything else is a caller inventing
    an identity, which is the thing the role header would have done."""
    monkeypatch.delenv(TRUST_SWITCH, raising=False)

    with pytest.raises(Refusal) as caught:
        anyio.run(actor_from_headers, {"x-caos-user": "../../etc/passwd"})

    assert caught.value.code is RefusalCode.NOT_AUTHENTICATED


def test_something_that_is_not_even_a_headers_object_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller of this function, not a client -- but the same refusal either
    way. Something with no `.get` at all is not a lesser kind of unauthenticated,
    it is the same one."""
    monkeypatch.delenv(TRUST_SWITCH, raising=False)

    with pytest.raises(Refusal) as caught:
        anyio.run(actor_from_headers, None)

    assert caught.value.code is RefusalCode.NOT_AUTHENTICATED


def test_trust_switched_on_with_no_role_header_at_all_is_the_lowest_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even switched on, a request that asserted no role at all gets the same
    answer as one asserting a role outside the closed set: the floor."""
    monkeypatch.setenv(TRUST_SWITCH, "1")

    actor = anyio.run(actor_from_headers, _headers())

    assert actor.role is GlobalRole.READER


def test_the_refusal_carries_no_part_of_what_was_sent() -> None:
    """§ refusals: the code travels, the offending text never does. An identity
    header is exactly the string that must not reach a log line."""
    with pytest.raises(Refusal) as caught:
        anyio.run(actor_from_headers, {"x-caos-user": "mallory@example.test"})

    assert "mallory" not in str(caught.value)
    assert "mallory" not in repr(caught.value)


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ({"caos-admins"}, GlobalRole.ADMIN),
        ({"caos-analysts"}, GlobalRole.ANALYST),
        ({"caos-readers"}, GlobalRole.READER),
        ({"something-else"}, GlobalRole.READER),
        ({"caos-readers", "caos-admins"}, GlobalRole.ADMIN),
        ({"caos-analysts", "caos-readers"}, GlobalRole.ANALYST),
    ],
)
def test_the_highest_group_wins(groups: set[str], expected: GlobalRole) -> None:
    """Someone in two groups holds the greater of them, and a group this system
    does not know grants nothing.

    `role_from_groups` is the pure mapping platform mode feeds the workspace's
    SCIM group list through (D10): it is the only mode a group list ever
    decides a role in, now that the HMAC edge assertion is gone.
    """
    assert role_from_groups(groups) is expected


def test_an_actor_is_a_subject_and_a_role_and_nothing_else() -> None:
    """Persona is not authority (spec §7). Which section a user is
    looking at composes a view and grants nothing, so it is not on the actor --
    and per-case standing lives in `case_members`, not in a header."""
    from caos.api.identity import Actor

    assert set(Actor.__annotations__) == {"user_id", "role"}


def test_the_switch_is_read_at_the_request_not_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process started in one mode must not keep behaving that way after the
    environment is corrected."""
    monkeypatch.delenv(TRUST_SWITCH, raising=False)
    before = anyio.run(actor_from_headers, _headers(**{"x-caos-role": "ADMIN"}))

    monkeypatch.setenv(TRUST_SWITCH, "1")
    after = anyio.run(actor_from_headers, _headers(**{"x-caos-role": "ADMIN"}))

    assert (before.role, after.role) == (GlobalRole.READER, GlobalRole.ADMIN)


# Task 4.2's actor matrix, every command endpoint in one table. `None` is the
# brief's "n/a": create case has no case to hold standing on.
ACTORS = (
    "anonymous nonmember reader writer approver revoked admin reader_writer case_admin"
)
# `case_admin` arrived with Task 12.1: membership is the first command whose
# floor is ADMIN, so without it the matrix would have had no actor that could
# succeed at one, and a table where every cell refuses proves only the refusal.
MATRIX: dict[str, tuple[int | None, ...]] = {
    "create-case": (401, 201, None, None, None, None, 201, 403, None),
    "admit": (401, 404, 403, 201, 201, 404, 404, 403, 201),
    "runs": (401, 404, 403, 201, 201, 404, 404, 403, 201),
    "input": (401, 404, 403, 200, 200, 404, 404, 403, 200),
    "preview": (401, 404, 200, 200, 200, 404, 404, 200, 200),
    "approval": (401, 404, 403, 403, 200, 404, 404, 403, 200),
    "start": (401, 404, 403, 202, 202, 404, 404, 403, 202),
    "retry": (401, 404, 403, 202, 202, 404, 404, 403, 202),
    "cancel": (401, 404, 403, 202, 202, 404, 404, 403, 202),
    # Task 12.1. Membership takes the ADMIN floor; withdrawal takes WRITER's.
    "members": (401, 404, 403, 403, 403, 404, 404, 403, 201),
    "revocation": (401, 404, 403, 403, 403, 404, 404, 403, 200),
    "withdrawal": (401, 404, 403, 200, 200, 404, 404, 403, 200),
}
SUBJECT = {
    "issuer_id": "EXAMPLE",
    "issuer_name": "Example Holdings plc",
    "reporting_period": "FY2025",
    "analysis_date": "2026-09-08",
}


def _actors(conn: StoreConnection, case_id: UUID) -> list[tuple[UUID | None, str]]:
    """Each actor's user and global role, in `ACTORS` order."""
    revoked = member(conn, case_id, Standing.ADMIN)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()
    return [
        (None, "ANALYST"),
        (uuid4(), "ANALYST"),
        (member(conn, case_id, Standing.READER), "ANALYST"),
        (member(conn, case_id, Standing.WRITER), "ANALYST"),
        (member(conn, case_id, Standing.APPROVER), "ANALYST"),
        (revoked, "ANALYST"),
        (uuid4(), "ADMIN"),
        (member(conn, case_id, Standing.WRITER), "READER"),
        (member(conn, case_id, Standing.ADMIN), "ANALYST"),
    ]


def _target(
    conn: StoreConnection, case_id: UUID, tmp_path: Path, endpoint: str
) -> tuple[str, dict[str, object] | None]:
    """A fresh path and JSON body on which `endpoint` succeeds for its floor."""
    runs = f"/api/v1/cases/{case_id}/runs"
    if endpoint == "members":
        return f"/api/v1/cases/{case_id}/members", {
            "user_id": str(uuid4()),
            "standing": "READER",
        }
    if endpoint == "revocation":
        target = member(conn, case_id, Standing.READER)
        return f"/api/v1/cases/{case_id}/members/{target}/revocation", {}
    if endpoint == "withdrawal":
        [source] = admit_pack(
            conn,
            BlobStore(tmp_path / "blobs"),
            case_id=case_id,
            documents=[Document(BoundaryText.of("a.txt"), b"Supplied report text.\n")],
        )
        conn.commit()
        return f"/api/v1/cases/{case_id}/sources/{source}/withdrawal", {}
    if endpoint in ("start", "retry", "cancel"):
        run_id, fingerprint = _ready(conn, case_id, tmp_path, endpoint)
        body: dict[str, object] = (
            {} if fingerprint is None else {"input_fingerprint": fingerprint}
        )
        return f"{runs}/{run_id}/{endpoint}", body
    if endpoint == "input":
        run = _Run(conn, case_id, tmp_path, pinned=False)
        pin_route(conn, run.run_id, ROUTE)
        return f"{runs}/{run.run_id}/input", {"subject": SUBJECT, "research": None}
    if endpoint in ("preview", "approval"):
        run = _Run(conn, case_id, tmp_path, pinned=True)
        preview = gate_preview(conn, run.run_id, Gate.SOURCE_SET)
        conn.rollback()
        gate = f"{runs}/{run.run_id}/gates/source-set"
        if endpoint == "preview":
            return f"{gate}/preview", None
        digests = (preview.preview_sha256, preview.input_fingerprint)
        return f"{gate}/approval", dict(
            zip(("preview_sha256", "input_fingerprint"), digests, strict=True)
        )
    if endpoint == "runs":
        return runs, {
            "profile_id": ROUTE.profile_id,
            "selection_id": ROUTE.selection_id,
            "supersedes": None,
            "model_extension": False,
        }
    if endpoint == "admit":
        return f"/api/v1/cases/{case_id}/sources", None
    return "/api/v1/cases", {"title": "Acme 2027"}


def _ask(
    client: TestClient,
    target: tuple[str, dict[str, object] | None],
    headers: dict[str, str],
) -> int:
    path, body = target
    if path.endswith("/sources"):
        files = [("document", ("a.txt", b"Supplied report text.\n", "text/plain"))]
        return int(client.post(path, headers=headers, files=files).status_code)
    if body is None:
        return int(client.get(path, headers=headers).status_code)
    return int(client.post(path, headers=headers, json=body).status_code)


@pytest.mark.parametrize("endpoint", sorted(MATRIX))
def test_every_command_across_the_seven_actors_and_a_global_reader_writer(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    endpoint: str,
) -> None:
    conn, case_id = case
    actors = _actors(conn, case_id)
    # Every target is prepared before any request: a retry target's claim would
    # otherwise take a run an earlier success requeued.
    targets = [_target(conn, case_id, tmp_path, endpoint) for _ in actors]

    observed = {
        name: _ask(
            command_client,
            target,
            {} if user is None else command_headers(user, role=role),
        )
        for name, (user, role), target, expected in zip(
            ACTORS.split(), actors, targets, MATRIX[endpoint], strict=True
        )
        if expected is not None
    }

    expected = dict(zip(ACTORS.split(), MATRIX[endpoint], strict=True))
    assert observed == {k: v for k, v in expected.items() if v is not None}


@pytest.mark.parametrize("endpoint", ["admit", "runs", "input", "approval", "start"])
def test_a_commit_time_revocation_answers_the_private_404(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    """Standing held at the precheck and lost before the governed unit commits:
    the unit refuses, nothing lands, and the answer is the stranger's 404."""
    conn, case_id = case
    target = _target(conn, case_id, tmp_path, endpoint)
    user = member(conn, case_id, Standing.APPROVER)
    real_lookup = store_commands._lookup

    revocations: list[UUID] = []

    def revoked_meanwhile(unit: StoreConnection, row: object) -> object:
        revocations.append(user)
        revoke(conn, case_id=case_id, user_id=user)
        conn.commit()
        return real_lookup(unit, row)  # type: ignore[arg-type]

    monkeypatch.setattr(store_commands, "_lookup", revoked_meanwhile)
    audited = conn.execute("SELECT count(*) FROM audit_events").fetchone()
    conn.rollback()

    headers = command_headers(user)
    path, body = target
    if body is None:
        answer = command_client.post(
            path, headers=headers, files=[("document", ("a.txt", b"Text.\n", "x"))]
        )
    else:
        answer = command_client.post(path, headers=headers, json=body)

    assert (answer.status_code, answer.json()["code"]) == (404, "CASE_NOT_FOUND")
    receipts = conn.execute("SELECT count(*) FROM command_requests").fetchone()
    after = conn.execute("SELECT count(*) FROM audit_events").fetchone()
    conn.rollback()
    assert receipts == (0,)
    assert after == audited, "the revocation writes no event; the command wrote none"
    assert revocations == [user], "standing was lost after the precheck, not before"


def test_without_a_token_or_the_switch_groups_grant_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C3: a loopback peer cannot pick ADMIN by sending groups to a tokenless API.

    Dev mode never reads a groups header at all -- it is not even a header
    `actor_from_headers` looks at outside platform mode (D10) -- so a client
    sending one grants nothing whatever its value.
    """
    monkeypatch.delenv(TRUST_SWITCH, raising=False)
    actor = anyio.run(
        actor_from_headers, _headers(**{"x-forwarded-groups": "caos-admins"})
    )
    assert actor.role is GlobalRole.READER


# Task 12.1's other four commands, in the same table but not the same fixture:
# a revision can only be derived from a run whose artifacts are accepted, which
# the `case` fixture above has none of. The identities and their expectations
# are `ACTORS` and `MATRIX`'s, so a floor that moved would show in both.
DELIVERABLE: dict[str, tuple[int | None, ...]] = {
    "save": (401, 404, 403, 201, 201, 404, 404, 403, 201),
    "signature": (401, 404, 403, 403, 200, 404, 404, 403, 200),
    "freeze": (401, 404, 403, 403, 200, 404, 404, 403, 200),
    "filing": (401, 404, 403, 403, 200, 404, 404, 403, 200),
}


def _prepared(lite: _Harness, endpoint: str) -> tuple[str, dict[str, object]]:
    """A path and body on which `endpoint` succeeds for an independent approver.

    Each actor gets its own revision: signing a frozen one, freezing a frozen
    one and filing a filed one are all refused, so a shared target would make
    the second actor's answer depend on the first's.
    """
    case = f"/api/v1/cases/{lite.case_id}"
    if endpoint == "save":
        latest = _latest_revision(lite)
        return f"{case}/runs/{lite.run_id}/revisions", {
            "expected_revision_id": latest,
            "narrative": [],
        }
    revision = save_revision(
        lite.conn,
        lite.blobs,
        lite.bundle,
        case_id=lite.case_id,
        run_id=lite.run_id,
        actor_id=lite.approver,
        narrative=[],
    )
    lite.conn.commit()
    digest = _revision_digest(lite, revision)
    if endpoint != "signature":
        signer = member(lite.conn, lite.case_id, Standing.APPROVER)
        sign_opinion(
            lite.conn,
            case_id=lite.case_id,
            actor_id=signer,
            revision_id=revision,
        )
        lite.conn.commit()
    if endpoint == "filing":
        freezer = member(lite.conn, lite.case_id, Standing.APPROVER)
        freeze(
            lite.conn,
            lite.blobs,
            lite.bundle,
            case_id=lite.case_id,
            actor_id=freezer,
            revision_id=revision,
        )
        lite.conn.commit()
    return f"{case}/revisions/{revision}/{endpoint}", {"payload_sha256": digest}


def _latest_revision(lite: _Harness) -> str | None:
    row = lite.conn.execute(
        "SELECT revision_id FROM deliverable_revisions WHERE case_id=%s AND run_id=%s"
        " ORDER BY saved_at DESC, revision_id DESC LIMIT 1",
        (lite.case_id, lite.run_id),
    ).fetchone()
    lite.conn.rollback()
    return None if row is None else str(row[0])


def _revision_digest(lite: _Harness, revision: UUID) -> str:
    row = lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_revisions WHERE revision_id=%s",
        (revision,),
    ).fetchone()
    lite.conn.rollback()
    assert row is not None
    return str(row[0])


@pytest.mark.parametrize("endpoint", sorted(DELIVERABLE))
def test_the_filing_chain_across_the_same_actors(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    lite: _Harness,
    endpoint: str,
) -> None:
    conn, case_id = case
    app.dependency_overrides[methodology_bundle] = lambda: lite.bundle
    actors = _actors(conn, case_id)

    observed = {}
    for name, (user, role), expected in zip(
        ACTORS.split(), actors, DELIVERABLE[endpoint], strict=True
    ):
        if expected is None:
            continue
        # Prepared one actor at a time: a save that succeeds moves the head the
        # next body has to name, and each chain target is one revision's only use.
        path, body = _prepared(lite, endpoint)
        headers = {} if user is None else command_headers(user, role=role)
        observed[name] = command_client.post(
            path, headers=headers, json=body
        ).status_code

    assert observed == dict(zip(ACTORS.split(), DELIVERABLE[endpoint], strict=True))
