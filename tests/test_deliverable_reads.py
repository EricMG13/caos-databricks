"""The deliverable render and package reads (N4; `docs/rebuild/next.md`)."""

from __future__ import annotations

import html
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_analysis_section import _as, client
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_filed_receipts import _corrupt, _file
from test_filing_chain import _freeze, _sign
from test_revision_sections import _get
from test_revisions import _read, _save
from test_run_commands import _Counting

from caos.api.app import app, store_connection
from caos.api.edge import SECURITY_HEADERS
from caos.api.reads.deliverable import (
    BLOB_BUDGET,
    IO_BUDGET,
    Selection,
    Stores,
    _rendered,
    package_revision,
    render_revision,
)
from caos.api.reads.reports import ProvenRevision, proven_filing, proven_revision
from caos.blobs import BlobStore
from caos.deliverable.package import verify_package
from caos.deliverable.render import render
from caos.refusals import Refusal, RefusalCode
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke

__all__ = ["client", "harness", "lite", "route"]


def _stores(lite: _Harness) -> Stores:
    return Stores(lite.conn, lite.blobs, lite.bundle)


def _render_path(lite: _Harness, revision: object) -> str:
    return f"/api/v1/cases/{lite.case_id}/revisions/{revision}/render"


def _package_path(lite: _Harness, revision: object) -> str:
    return f"/api/v1/cases/{lite.case_id}/revisions/{revision}/package"


def _downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every blob a request's store downloads: a `get` its memo cannot answer."""
    downloaded: list[str] = []
    real_get = BlobStore.get

    def counted(store: BlobStore, digest: str) -> bytes:
        if store.verified is None or digest not in store.verified:
            downloaded.append(digest)
        return real_get(store, digest)

    monkeypatch.setattr(BlobStore, "get", counted)
    return downloaded


def test_render_of_a_filed_revision_equals_render_of_its_own_payload(
    client: TestClient, lite: _Harness
) -> None:
    receipt = _file(lite)
    payload = _read(lite, receipt.revision_id)
    response = client.get(
        _render_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    assert response.status_code == 200
    assert response.content == render(payload)
    assert response.headers["content-type"] == "text/html; charset=utf-8"


def test_render_of_a_frozen_unfiled_revision_also_serves(
    client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    payload = _read(lite, revision)
    response = client.get(_render_path(lite, revision), headers=_as(lite.approver))
    assert response.status_code == 200
    assert response.content == render(payload)


def test_render_of_an_unfrozen_revision_is_refused_not_frozen(
    client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    response = client.get(_render_path(lite, revision), headers=_as(lite.approver))
    assert response.status_code != 200
    assert response.json()["code"] == "DELIVERABLE_NOT_FROZEN"


def test_render_of_an_unknown_revision_is_refused_not_found(
    client: TestClient, lite: _Harness
) -> None:
    response = client.get(_render_path(lite, uuid4()), headers=_as(lite.approver))
    assert response.status_code == 404
    assert response.json()["code"] == "DELIVERABLE_NOT_FOUND"


def test_package_of_a_filed_revision_verifies(
    client: TestClient, lite: _Harness
) -> None:
    receipt = _file(lite)
    response = client.get(
        _package_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="deliverable-{receipt.revision_id}.zip"'
    )
    verified = verify_package(response.content)
    assert verified.verified, verified.reason


def test_package_of_a_frozen_unfiled_revision_is_refused_not_found(
    client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    response = client.get(_package_path(lite, revision), headers=_as(lite.approver))
    assert response.status_code != 200
    assert response.json()["code"] == "DELIVERABLE_NOT_FOUND"


def test_package_of_an_unsaved_revision_is_refused_not_found(
    client: TestClient, lite: _Harness
) -> None:
    response = client.get(_package_path(lite, uuid4()), headers=_as(lite.approver))
    assert response.status_code == 404
    assert response.json()["code"] == "DELIVERABLE_NOT_FOUND"


@pytest.mark.parametrize("kind", ["render", "package"])
def test_a_non_member_is_refused_the_private_case_not_found(
    client: TestClient, lite: _Harness, kind: str
) -> None:
    receipt = _file(lite)
    stranger = uuid4()
    path = (_render_path if kind == "render" else _package_path)(
        lite, receipt.revision_id
    )
    response = client.get(path, headers=_as(stranger))
    assert response.status_code == 404
    assert response.json()["code"] == "CASE_NOT_FOUND"


@pytest.mark.parametrize("kind", ["render", "package"])
def test_a_revoked_member_is_refused_the_private_case_not_found(
    client: TestClient, lite: _Harness, kind: str
) -> None:
    receipt = _file(lite)
    revoked = uuid4()
    grant(lite.conn, case_id=lite.case_id, user_id=revoked, standing=Standing.READER)
    revoke(lite.conn, case_id=lite.case_id, user_id=revoked)
    lite.conn.commit()
    path = (_render_path if kind == "render" else _package_path)(
        lite, receipt.revision_id
    )
    response = client.get(path, headers=_as(revoked))
    assert response.status_code == 404
    assert response.json()["code"] == "CASE_NOT_FOUND"


def test_render_headers_carry_the_narrow_policy_and_the_usual_headers(
    client: TestClient, lite: _Harness
) -> None:
    receipt = _file(lite)
    response = client.get(
        _render_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert csp == (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )
    assert csp != SECURITY_HEADERS["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == SECURITY_HEADERS["referrer-policy"]
    assert (
        response.headers["cross-origin-opener-policy"]
        == SECURITY_HEADERS["cross-origin-opener-policy"]
    )
    assert (
        response.headers["cross-origin-resource-policy"]
        == SECURITY_HEADERS["cross-origin-resource-policy"]
    )
    assert response.headers["cache-control"] == "no-store"


def test_package_headers_carry_the_workspace_policy_unchanged(
    client: TestClient, lite: _Harness
) -> None:
    receipt = _file(lite)
    response = client.get(
        _package_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_a_render_refusal_maps_to_its_typed_code() -> None:
    """`render` refuses `DELIVERABLE_PAYLOAD_INVALID` for a payload with no
    artifacts; `_rendered` answers the same typed code, not a bare exception
    for the edge guard to turn into `INTERNAL_FAULT`."""
    with pytest.raises(Refusal) as excinfo:
        _rendered({"case_title": "Acme", "revision_id": "r-1", "artifacts": []})
    assert excinfo.value.code == RefusalCode.DELIVERABLE_PAYLOAD_INVALID


def test_a_frozen_row_disagreeing_with_the_saved_revision_is_refused_invalid(
    client: TestClient, lite: _Harness
) -> None:
    """`deliverable_revisions` is immutable, so only the frozen row can move:
    a `payload_sha256` written outside `freeze_in` is the app disagreeing
    with itself, not the caller's fault, and `_frozen`'s own tamper check
    catches it before `render` ever sees a byte."""
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    lite.conn.execute(
        "UPDATE deliverable_publications SET payload_sha256=%s"
        " WHERE case_id=%s AND revision_id=%s",
        ("0" * 64, lite.case_id, str(revision)),
    )
    lite.conn.commit()
    response = client.get(_render_path(lite, revision), headers=_as(lite.approver))
    assert response.status_code != 200
    assert response.json()["code"] == "DELIVERABLE_PAYLOAD_INVALID"


def test_render_revision_reads_the_frozen_bytes_directly(lite: _Harness) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    payload = _read(lite, revision)
    selection = Selection(_stores(lite), lite.approver, lite.case_id, revision)
    html = render_revision(selection)
    assert html == render(payload)


def test_package_revision_builds_an_archive_that_verifies(lite: _Harness) -> None:
    receipt = _file(lite)
    archive = package_revision(
        Selection(_stores(lite), lite.approver, lite.case_id, receipt.revision_id)
    )
    verified = verify_package(archive)
    assert verified.verified, verified.reason


def test_render_meets_its_declared_budgets(
    client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _file(lite)
    counter = _Counting(lite.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    downloads = _downloads(monkeypatch)
    response = client.get(
        _render_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    lite.conn.rollback()
    assert response.status_code == 200
    assert counter.executed == IO_BUDGET["render"]
    assert len(downloads) == len(set(downloads)) == BLOB_BUDGET["render"]


def test_a_frozen_render_meets_its_declared_budgets(
    client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2: a frozen, unfiled revision is re-derived before it is rendered, as
    Committee re-derives it, so it pays what Committee's "frozen" proof pays."""
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    counter = _Counting(lite.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    downloads = _downloads(monkeypatch)
    response = client.get(_render_path(lite, revision), headers=_as(lite.approver))
    lite.conn.rollback()
    assert response.status_code == 200
    assert counter.executed == IO_BUDGET["render_frozen"]
    assert len(downloads) == len(set(downloads)) == BLOB_BUDGET["render_frozen"]


def test_package_meets_its_declared_budgets(
    client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _file(lite)
    counter = _Counting(lite.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    downloads = _downloads(monkeypatch)
    response = client.get(
        _package_path(lite, receipt.revision_id), headers=_as(lite.approver)
    )
    lite.conn.rollback()
    assert response.status_code == 200
    assert counter.executed == IO_BUDGET["package"]
    assert len(downloads) == len(set(downloads)) == BLOB_BUDGET["package"]


def test_the_committee_read_links_to_both_downloads(
    client: TestClient, lite: _Harness
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    frozen_body = _get(client, lite, revision, "committee")
    assert frozen_body["render_url"] == _render_path(lite, revision)
    assert frozen_body["package_url"] is None

    receipt = _file(lite)
    filed_body = _get(client, lite, receipt.revision_id, "committee")
    assert filed_body["render_url"] == _render_path(lite, receipt.revision_id)
    assert filed_body["package_url"] == _package_path(lite, receipt.revision_id)
    render_response = client.get(filed_body["render_url"], headers=_as(lite.approver))
    package_response = client.get(filed_body["package_url"], headers=_as(lite.approver))
    assert render_response.status_code == 200
    assert package_response.status_code == 200


def _section(lite: _Harness, revision: object, section: str) -> str:
    query = f"run={lite.run_id}&revision={revision}"
    return f"/api/v1/cases/{lite.case_id}/{section}?{query}"


def _answer(client: TestClient, lite: _Harness, path: str) -> tuple[int, str | None]:
    response = client.get(path, headers=_as(lite.approver))
    lite.conn.rollback()
    code = None if response.status_code == 200 else response.json()["code"]
    return response.status_code, code


def test_render_refuses_a_frozen_revision_committee_refuses(
    client: TestClient, lite: _Harness
) -> None:
    """W2. Frozen, unfiled, then a cited source withdrawn: Report and Committee
    re-prove the frozen revision and refuse; the render only looked for the
    publication row and kept serving the withdrawn source's quoted text."""
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    payload = _read(lite, revision)
    quotes = [
        citation["matched_text"]
        for artifact in payload["artifacts"]
        for citation in json.loads(artifact["record"])["citations"]
    ]
    assert quotes
    withdraw_source(
        lite.conn,
        case_id=lite.case_id,
        source_id=lite.source_id,
        actor_id=lite.approver,
    )
    lite.conn.commit()

    committee = _answer(client, lite, _section(lite, revision, "committee"))
    report = _answer(client, lite, _section(lite, revision, "report"))
    response = client.get(_render_path(lite, revision), headers=_as(lite.approver))
    lite.conn.rollback()

    assert committee[0] != 200
    assert report == committee
    assert (response.status_code, response.json()["code"]) == committee
    assert not any(html.escape(quote) in response.text for quote in quotes)


@pytest.mark.parametrize("kind", ["render", "package"])
def test_both_downloads_refuse_a_filing_committee_refuses(
    client: TestClient, lite: _Harness, kind: str
) -> None:
    """W2. A filed revision whose signer's `OPINION_SIGNED` event no longer
    matches its opinion row: Committee's provenance proof refuses it, and each
    download runs that same proof rather than its own narrower one."""
    receipt = _file(lite)
    _corrupt(lite, "UPDATE deliverable_opinions SET signed_by=%s", uuid4())
    lite.conn.commit()
    path = (_render_path if kind == "render" else _package_path)(
        lite, receipt.revision_id
    )

    committee = _answer(client, lite, _section(lite, receipt.revision_id, "committee"))

    assert committee[0] != 200
    assert _answer(client, lite, path) == committee


def _proof(lite: _Harness, revision: UUID) -> ProvenRevision:
    row = lite.conn.execute(
        "SELECT payload_sha256 FROM deliverable_revisions WHERE revision_id=%s",
        (revision,),
    ).fetchone()
    assert row is not None
    return ProvenRevision(
        lite.conn,
        lite.blobs,
        lite.bundle,
        lite.case_id,
        lite.run_id,
        revision,
        str(row[0]),
    )


def test_proven_revision_is_committees_proof_of_either_state(lite: _Harness) -> None:
    """The one proof Committee and both downloads share: a frozen revision is
    re-derived, a filed one is read back with its proven receipt."""
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    frozen, payload = proven_revision(_proof(lite, revision))
    lite.conn.rollback()
    assert (frozen["state"], frozen["receipt"]) == ("frozen", None)
    assert payload == _read(lite, revision)

    receipt = _file(lite)
    filed, filed_payload = proven_revision(_proof(lite, receipt.revision_id))
    lite.conn.rollback()
    assert filed["state"] == "filed"
    assert filed["receipt"]["filed_event_sha256"] == receipt.filed_event_sha256
    assert filed_payload == _read(lite, receipt.revision_id)


def test_proven_filing_names_no_filing_for_an_unfiled_revision(
    lite: _Harness,
) -> None:
    """Saved or frozen, a revision nobody filed has no package: the same
    `DELIVERABLE_NOT_FOUND` for both, before any re-derivation."""
    revision = _save(lite)
    with pytest.raises(Refusal) as saved:
        proven_filing(_proof(lite, revision))
    lite.conn.rollback()
    _sign(lite, revision)
    _freeze(lite, revision)
    with pytest.raises(Refusal) as frozen:
        proven_filing(_proof(lite, revision))
    lite.conn.rollback()
    assert saved.value.code is frozen.value.code is RefusalCode.DELIVERABLE_NOT_FOUND
