"""Exercise read_report, read_committee and revision_query through real HTTP reads."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_analysis_section import _as, client
from test_deliverable_canonical import QUOTE, harness, lite, route
from test_execution_freshness import _Harness
from test_filed_receipts import _corrupt, _file
from test_filing_chain import _actor, _default_signer, _freeze, _sign
from test_revisions import _read, _save
from test_run_commands import _Counting

from caos.api.app import app, store_connection
from caos.api.reads.reports import IO_BUDGET
from caos.boundary_text import BoundaryText
from caos.deliverable.filing import file_deliverable, receipt_bytes
from caos.refusals import Refusal, RefusalCode
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run
from caos.store.source_sets import cited_source_ids

__all__ = ["client", "harness", "lite", "route"]


def _path(lite: _Harness, revision: object, section: str = "report") -> str:
    return (
        f"/api/v1/cases/{lite.case_id}/{section}?run={lite.run_id}&revision={revision}"
    )


def _get(
    client: TestClient, lite: _Harness, revision: UUID, section: str
) -> dict[str, Any]:
    response = client.get(_path(lite, revision, section), headers=_as(lite.approver))
    lite.conn.rollback()
    assert response.status_code == 200, response.json()
    return dict(response.json()["body"])


def test_report_reads_the_exact_saved_revision(
    client: TestClient, lite: _Harness
) -> None:
    node = lite.route.nodes[0].route_node_id
    revision = _save(
        lite,
        [
            [
                {"text": "Debt: "},
                {"figure": {"route_node_id": node, "citation_index": 0}},
            ]
        ],
    )
    saved = _read(lite, revision)
    _save(lite, [[{"text": "New draft"}]])
    start_run(lite.conn, lite.case_id)
    lite.conn.commit()
    body = _get(client, lite, revision, "report")
    assert body["revision_id"] == str(revision)
    assert body["displayed_run_id"] == str(lite.run_id)
    assert body["narrative"][0][0] == {"text": "Debt: ", "figure": None}
    # N59: the served figure is the saved one plus the two fields the
    # evidence drawer needs to open its source without cross-referencing
    # `artifacts` or the run's pinned members itself.
    figure = body["narrative"][0][1]["figure"]
    saved_figure = saved["narrative"][0][1]["figure"]
    assert {k: figure[k] for k in saved_figure} == saved_figure
    assert figure["matched_text"] == QUOTE
    assert figure["source_id"] == str(lite.source_id)
    assert figure["record_sha256"] == next(
        a["record_sha256"] for a in saved["artifacts"] if a["route_node_id"] == node
    )
    assert [a["route_node_id"] for a in body["artifacts"]] == [
        n.route_node_id for n in lite.route.nodes
    ]
    for actual, expected in zip(body["artifacts"], saved["artifacts"], strict=True):
        assert {k: actual[k] for k in expected} == expected
        projections = json.loads(expected["record"])["projections"]
        assert actual["limitation_flags"] == projections["limitation_flags"]
        assert actual["decision_scope"] == projections["decision_scope"]


def test_cited_source_ids_resolves_the_run_pin_and_refuses_an_uncited_document(
    client: TestClient, lite: _Harness
) -> None:
    """`cited_source_ids` is what `read_report`/`read_committee` resolve a
    figure's `source_id` from (N59): the same document this run's own
    narrative cites resolves to the source that pinned it, an empty request
    costs no query, and a document no member of the run names is the typed
    `ARTIFACT_RECORD_MISMATCH` -- never a `KeyError` a reader would leak."""
    node = lite.route.nodes[0].route_node_id
    revision = _save(
        lite,
        [[{"figure": {"route_node_id": node, "citation_index": 0}}]],
    )
    body = _get(client, lite, revision, "report")
    document = body["narrative"][0][0]["figure"]["document_sha256"]
    assert cited_source_ids(lite.conn, lite.run_id, [document]) == {
        document: lite.source_id
    }
    assert cited_source_ids(lite.conn, lite.run_id, []) == {}
    with pytest.raises(Refusal) as excinfo:
        cited_source_ids(lite.conn, lite.run_id, [document, "0" * 64])
    assert excinfo.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


@pytest.mark.parametrize(
    "damage", ["secondary", "injected", "filed", "filed_missing", "orphan"]
)
def test_committee_reads_the_exact_frozen_payload_and_receipt(
    client: TestClient, lite: _Harness, damage: str
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _sign(lite, revision, _actor(lite))
    _freeze(lite, revision)
    receipt = file_deliverable(
        lite.conn,
        lite.blobs,
        case_id=lite.case_id,
        actor_id=_actor(lite),
        revision_id=revision,
    )
    saved = _read(lite, receipt.revision_id)
    _save(lite, [[{"text": "Later draft"}]])
    body = _get(client, lite, receipt.revision_id, "committee")
    assert body["state"] == "filed"
    assert body["receipt"] == json.loads(receipt_bytes(receipt))
    assert body["payload_sha256"] == receipt.payload_sha256
    assert body["frozen_by"] == str(receipt.frozen_by)
    assert body["filed_by"] == str(receipt.filed_by)
    assert body["signed_by"] == [str(receipt.signed_by), str(_default_signer(lite))]
    assert body["artifacts"][0]["markdown"] == saved["artifacts"][0]["markdown"]
    if damage == "secondary":
        _corrupt(
            lite,
            "UPDATE deliverable_opinions SET signed_by=gen_random_uuid()"
            " WHERE signed_by=%s",
            _default_signer(lite),
        )
    elif damage == "injected":
        _corrupt(
            lite,
            "INSERT INTO deliverable_opinions"
            " SELECT revision_id,case_id,payload_sha256,gen_random_uuid(),"
            " signed_at-interval '1 day' FROM deliverable_opinions"
            " WHERE signed_by=%s",
            _default_signer(lite),
        )
    else:
        _corrupt(
            lite, "UPDATE deliverable_publications SET filed_by=%s,filed_at=NULL", None
        )
        if damage == "filed_missing":
            lite.blobs.path_of(sha256(receipt_bytes(receipt)).hexdigest()).unlink()
        elif damage == "orphan":
            _corrupt(
                lite,
                "DELETE FROM deliverable_receipts WHERE revision_id=%s",
                str(revision),
            )
            _corrupt(
                lite,
                "UPDATE audit_events SET at='2000-01-01' WHERE entry_sha256=%s",
                receipt.filed_event_sha256,
            )
    lite.conn.commit()
    response = client.get(
        _path(lite, revision, "committee"), headers=_as(lite.approver)
    )
    assert response.status_code != 200
    assert response.json()["code"] == "DELIVERABLE_PAYLOAD_INVALID"
    assert set(response.json()) == {"code", "clears"}


def test_committee_distinguishes_frozen_from_filed(
    client: TestClient, lite: _Harness
) -> None:
    _file(lite)
    revision = _save(lite)
    response = client.get(
        _path(lite, revision, "committee"), headers=_as(lite.approver)
    )
    assert response.status_code != 200
    lite.conn.rollback()
    _sign(lite, revision)
    _freeze(lite, revision)
    counter = _Counting(lite.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    body = _get(client, lite, revision, "committee")
    assert (body["state"], body["filed_by"], body["receipt"]) == ("frozen", None, None)
    assert counter.executed == IO_BUDGET["frozen"]


def test_historical_receiptless_filing_does_not_block_a_newer_frozen_revision(
    client: TestClient, lite: _Harness
) -> None:
    historical = _file(lite)
    _corrupt(
        lite,
        "DELETE FROM deliverable_receipts WHERE revision_id=%s",
        str(historical.revision_id),
    )
    lite.conn.execute("SET LOCAL session_replication_role = replica")
    lite.conn.execute(
        "INSERT INTO legacy_filing_events (case_id,filed_event_sha256) VALUES (%s,%s)",
        (lite.case_id, historical.filed_event_sha256),
    )
    lite.conn.execute("SET LOCAL session_replication_role = origin")
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    body = _get(client, lite, revision, "committee")
    assert (body["state"], body["filed_by"], body["receipt"]) == ("frozen", None, None)


@pytest.mark.parametrize("section", ["report", "committee"])
@pytest.mark.parametrize(
    "damage", ["payload", "record", "source", "receipt", "actor", "corrupt"]
)
def test_financial_section_reads_fail_closed_before_returning_text(
    client: TestClient, lite: _Harness, section: str, damage: str
) -> None:
    receipt = _file(lite)
    if damage == "source":
        withdraw_source(
            lite.conn,
            case_id=lite.case_id,
            source_id=lite.source_id,
            actor_id=lite.approver,
        )
    elif damage == "actor":
        _corrupt(
            lite, "UPDATE deliverable_publications SET frozen_by=%s", lite.approver
        )
    else:
        digest = receipt.payload_sha256
        if damage == "record":
            row = lite.conn.execute(
                "SELECT record_sha256 FROM artifacts LIMIT 1"
            ).fetchone()
            assert row is not None
            digest = row[0]
        elif damage == "receipt":
            row = lite.conn.execute(
                "SELECT receipt_sha256 FROM deliverable_receipts"
            ).fetchone()
            assert row is not None
            digest = row[0]
        if damage == "corrupt":
            lite.blobs.path_of(digest).write_bytes(b"corrupt saved payload")
        else:
            lite.blobs.path_of(digest).unlink()
    lite.conn.commit()
    response = client.get(
        _path(lite, receipt.revision_id, section), headers=_as(lite.approver)
    )
    lite.conn.rollback()
    if section == "report" and damage in {"receipt", "actor"}:
        assert response.status_code == 200  # A saved report is not a filing claim.
    elif section == "committee" and damage in {"record", "source"}:
        # A filed deliverable reads from the snapshot proven at filing (FP-05):
        # live state moving afterwards does not unfile it. Its own payload,
        # receipt and signers still fail closed.
        assert response.status_code == 200
    else:
        assert response.status_code != 200
        assert set(response.json()) == {"code", "clears"}


@pytest.mark.parametrize("section", ["report", "committee"])
def test_revision_selection_is_private_and_exact(
    client: TestClient, lite: _Harness, section: str
) -> None:
    receipt = _file(lite)
    for revision in (uuid4(), "malformed", ""):
        response = client.get(
            _path(lite, revision, section), headers=_as(lite.approver)
        )
        lite.conn.rollback()
        assert response.status_code == 404
        assert response.json()["code"] == "DELIVERABLE_NOT_FOUND"
    other = start_run(lite.conn, lite.case_id)
    lite.conn.commit()
    path = _path(lite, receipt.revision_id, section).replace(
        str(lite.run_id), str(other)
    )
    assert client.get(path, headers=_as(lite.approver)).status_code == 404
    lite.conn.rollback()
    foreign = create_case(lite.conn, BoundaryText.of("Other case"))
    grant(lite.conn, case_id=foreign, user_id=lite.approver, standing=Standing.READER)
    foreign_run = start_run(lite.conn, foreign)
    lite.conn.commit()
    for moved in (
        path.replace(str(lite.case_id), str(foreign)),
        path.replace(str(other), str(foreign_run)),
    ):
        response = client.get(moved, headers=_as(lite.approver))
        lite.conn.rollback()
        assert response.status_code == 404
        assert response.json()["code"] == "DELIVERABLE_NOT_FOUND"


@pytest.mark.parametrize("field", ["frozen_by", "signed_by"])
def test_frozen_actors_must_match_the_saved_events(
    client: TestClient, lite: _Harness, field: str
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    table = (
        "deliverable_publications" if field == "frozen_by" else "deliverable_opinions"
    )
    _corrupt(lite, f"UPDATE {table} SET {field}=%s", uuid4())
    lite.conn.commit()
    response = client.get(
        _path(lite, revision, "committee"), headers=_as(lite.approver)
    )
    assert response.status_code != 200
    assert response.json()["code"] == "DELIVERABLE_PAYLOAD_INVALID"


ACTIONS = (
    "SAVE_REVISION",
    "SIGN_OPINION",
    "FREEZE_DELIVERABLE",
    "FILE_DELIVERABLE",
)


@pytest.mark.parametrize("section", ["report", "committee"])
def test_revision_http_actor_matrix_and_declared_io(
    client: TestClient, lite: _Harness, section: str
) -> None:
    receipt = _file(lite)
    readers = [uuid4() for _ in range(4)]
    for actor, standing in zip(readers, Standing, strict=True):
        grant(lite.conn, case_id=lite.case_id, user_id=actor, standing=standing)
    revoked = uuid4()
    grant(lite.conn, case_id=lite.case_id, user_id=revoked, standing=Standing.READER)
    revoke(lite.conn, case_id=lite.case_id, user_id=revoked)
    lite.conn.commit()
    # Task 12.1: the section offers its four filing controls, and every one of
    # them is refused here whatever the standing -- these callers assert no
    # global role, and a global READER may not write however the case sees it.
    for actor in [*readers, uuid4(), revoked]:
        counter = _Counting(lite.conn)
        app.dependency_overrides[store_connection] = lambda: counter  # noqa: B023
        response = client.get(
            _path(lite, receipt.revision_id, section),
            headers=_as(actor, "ADMIN" if actor not in readers else None),
        )
        lite.conn.rollback()
        if actor in readers:
            assert response.status_code == 200, response.json()
            assert counter.executed == IO_BUDGET[section]
            offered = {
                view["action"]: view["refusal"] and view["refusal"]["code"]
                for view in response.json()["chrome"]["actions"]
            }
            assert offered == dict.fromkeys(ACTIONS, "NOT_AUTHORISED")
        else:
            assert response.json()["code"] == "CASE_NOT_FOUND"
            assert counter.executed == 2  # isolation and live standing only


@pytest.mark.parametrize("section", ["report", "committee"])
def test_revision_authentication_and_syntax_precede_connection(
    client: TestClient, lite: _Harness, section: str
) -> None:
    def unexpected() -> None:
        pytest.fail("opened store before authentication and syntax checks")

    app.dependency_overrides[store_connection] = unexpected
    assert client.get(_path(lite, uuid4(), section)).status_code == 401
    for path in (
        _path(lite, "bad", section),
        _path(lite, uuid4(), section).replace(str(lite.run_id), "bad"),
        _path(lite, uuid4(), section).replace(str(lite.case_id), "bad"),
        # Report without a revision reads the run's head or offers its first
        # save (`tests/test_governed_write_routes.py`); Committee serves only a
        # named frozen revision, so it still refuses before the store.
        *(
            [f"/api/v1/cases/{lite.case_id}/{section}?run={lite.run_id}"]
            if section == "committee"
            else []
        ),
    ):
        assert client.get(path, headers=_as(lite.approver)).status_code == 404
