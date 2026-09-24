"""The deliverable render and package reads (N4; `docs/rebuild/next.md`)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_analysis_section import _as, client
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_filed_receipts import _file
from test_filing_chain import _freeze, _sign
from test_revision_sections import _get
from test_revisions import _read, _save
from test_run_commands import _Counting

from caos.api.app import app, store_connection
from caos.api.edge import SECURITY_HEADERS
from caos.api.reads.deliverable import (
    BLOB_BUDGET,
    IO_BUDGET,
    _rendered,
    package_revision,
    render_revision,
)
from caos.blobs import BlobStore
from caos.deliverable.package import verify_package
from caos.deliverable.render import render
from caos.refusals import Refusal, RefusalCode
from caos.store.members import Standing, grant, revoke

__all__ = ["client", "harness", "lite", "route"]


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
    html = render_revision(
        lite.conn, lite.blobs, case_id=lite.case_id, revision_id=revision
    )
    lite.conn.rollback()
    assert html == render(payload)


def test_package_revision_builds_an_archive_that_verifies(lite: _Harness) -> None:
    receipt = _file(lite)
    archive = package_revision(
        lite.conn, lite.blobs, case_id=lite.case_id, revision_id=receipt.revision_id
    )
    lite.conn.rollback()
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
