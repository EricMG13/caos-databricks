"""The qualification label reads one exact persisted evidence identity."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from qualification_fixtures import (
    qualification_performed,
    record_performed_earlier,
    record_runs,
)

from caos.api import app as app_module
from caos.api.app import app, store_connection
from caos.api.wire import QualificationState
from caos.qualification.store import (
    Evidence,
    record_evidence,
    record_verdict,
)
from caos.qualification.verdict import read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect


def _evidence() -> Evidence:
    return qualification_performed().evidence


def _headers(user: UUID, role: str = "ANALYST") -> dict[str, str]:
    return {"x-caos-user": str(user), "x-caos-role": role}


@pytest.fixture
def client(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, StoreConnection]]:
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    monkeypatch.setenv("CAOS_TRUST_ROLE_HEADER", "1")
    with connect(empty_database) as conn:
        apply_schema(conn)
        app.dependency_overrides[store_connection] = lambda: conn
        try:
            with TestClient(app) as opened:
                yield opened, conn
        finally:
            app.dependency_overrides.clear()


def _record(conn: StoreConnection, *, expires_at: datetime) -> tuple[Evidence, UUID]:
    evidence = _evidence()
    performed = qualification_performed()
    record_performed_earlier(conn, performed)
    # The runs behind the snapshot: `record_verdict` refuses a verdict naming
    # a model no accepted artifact of them recorded.
    record_runs(conn, performed)
    decided_at = expires_at - timedelta(days=1)
    verdict = read_verdict(
        {
            "provider": evidence.provider + ":" + evidence.model,
            "qualification_set_sha256": evidence.qualification_set_sha256,
            "build_id": evidence.build_id,
            "decided_at": decided_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reviewer": "Reviewer",
        },
        now=decided_at,
    )
    reviewer_id = uuid4()
    record_verdict(conn, evidence=evidence, reviewer_id=reviewer_id, verdict=verdict)
    conn.commit()
    return evidence, reviewer_id


def _read(
    client: TestClient, evidence: Evidence, user: UUID, role: str = "ANALYST"
) -> Response:
    answer: Response = client.get(
        f"/api/v1/qualification/{evidence.sha256}", headers=_headers(user, role)
    )
    return answer


def test_read_qualification(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """read_qualification gives an analyst only an exact current verdict."""
    http, conn = client
    evidence, reviewer_id = _record(
        conn, expires_at=datetime.now(UTC) + timedelta(days=1)
    )

    response = _read(http, evidence, uuid4())

    assert response.status_code == 200
    body = response.json()
    assert {
        key: value
        for key, value in body.items()
        if key not in {"decided_at", "expires_at"}
    } == {
        "evidence_sha256": evidence.sha256,
        "state": QualificationState.QUALIFIED,
        "qualification_set_sha256": evidence.qualification_set_sha256,
        "performed_sha256": evidence.performed_sha256,
        "build_id": evidence.build_id,
        "adapter_version": evidence.adapter_version,
        "provider": evidence.provider,
        "model": evidence.model,
        "reviewer": "Reviewer",
        "reviewer_id": str(reviewer_id),
    }
    assert datetime.fromisoformat(body["decided_at"]) < datetime.fromisoformat(
        body["expires_at"]
    )


def test_missing_or_expired_evidence_is_unqualified_not_qualified(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, conn = client
    expired, _reviewer_id = _record(
        conn, expires_at=datetime.now(UTC) - timedelta(days=1)
    )

    missing = Evidence("c" * 64, "d" * 64, "build", "adapter", "p", "m")
    for evidence in (expired, missing):
        response = _read(http, evidence, uuid4())
        assert response.status_code == 200
        assert response.json() == {
            "evidence_sha256": evidence.sha256,
            "state": QualificationState.UNQUALIFIED,
            "qualification_set_sha256": None,
            "performed_sha256": None,
            "build_id": None,
            "adapter_version": None,
            "provider": None,
            "model": None,
            "reviewer": None,
            "reviewer_id": None,
            "decided_at": None,
            "expires_at": None,
        }


def test_reader_sees_restricted_without_global_verdict_metadata(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, conn = client
    evidence, _reviewer_id = _record(
        conn, expires_at=datetime.now(UTC) + timedelta(days=1)
    )

    response = _read(http, evidence, uuid4(), "READER")

    assert response.status_code == 200
    assert response.json() == {
        "evidence_sha256": evidence.sha256,
        "state": QualificationState.RESTRICTED,
        "qualification_set_sha256": None,
        "performed_sha256": None,
        "build_id": None,
        "adapter_version": None,
        "provider": None,
        "model": None,
        "reviewer": None,
        "reviewer_id": None,
        "decided_at": None,
        "expires_at": None,
    }


def test_invalid_persisted_verdict_is_unavailable_not_unqualified(
    client: tuple[TestClient, StoreConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, conn = client
    evidence = _evidence()
    record_performed_earlier(conn, qualification_performed())
    record_evidence(conn, evidence)
    conn.commit()

    def invalid(_conn: object, **_kwargs: object) -> object:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)

    from caos.api.reads import qualification as qualification_read

    monkeypatch.setattr(qualification_read, "current_verdict", invalid)
    response = _read(http, evidence, uuid4())

    assert response.status_code == 200
    assert response.json()["state"] == QualificationState.UNAVAILABLE


def test_malformed_evidence_digest_is_a_typed_refusal(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, _conn = client

    response = http.get("/api/v1/qualification/not-a-digest", headers=_headers(uuid4()))

    assert response.status_code == 400
    assert response.json() == {
        "code": "VERDICT_BINDING_INVALID",
        "clears": "Correct the verdict bindings.",
    }


def test_a_qualified_read_costs_what_it_declares(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """N9 for this route, and DQ-3's price: the store's clock, the evidence,
    the verdict, the runs' status and models `assert_store_agrees` reads, and
    the reviewer_id lookup beside it (CF-027)."""
    from test_qualification_sign import _Counting

    from caos.api.reads import qualification as qualification_read

    http, conn = client
    evidence, _reviewer_id = _record(
        conn, expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted

    response = _read(http, evidence, uuid4())

    assert response.json()["state"] == QualificationState.QUALIFIED
    assert counted.executed == qualification_read.IO_BUDGET == 6
