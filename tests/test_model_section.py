"""Real accepted CP-CF reads: projection identity, live authority and no fallback."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CONTRACT, skill
from canonical_route_fixtures import driver_schema, forecast_driver_rows
from conftest import route_fault, tamper
from fastapi.testclient import TestClient
from test_analysis_section import (
    _as,
    _CountingConnection,
    _downloads,
    _reader,
    _serving,
    client,
)
from test_canonical_runtime import _module_provider, _run_route
from test_execution_freshness import _Harness
from test_forecast_route import ForecastCompletions, harness
from test_forecast_route import route as forecast_route

from caos.api.app import app, store_connection
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import analysis as analysis_read
from caos.boundary_text import BoundaryText
from caos.graph.route import ResolvedRoute
from caos.methodology import tables
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.methodology.vendor import VendorContract
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run

__all__ = ["client", "forecast_route", "harness", "route"]


@pytest.fixture
def route(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> ResolvedRoute:
    if getattr(request, "param", None) == "zero-interest":
        import test_forecast_route as fixture

        data = fixture.request_data()
        data["drivers"][0].update(cash_interest="0", stated_closing_cash="155")
        rows = fixture.assignment_rows(data)
        monkeypatch.setattr(fixture, "request_data", lambda: data)
        monkeypatch.setattr(fixture, "ROWS", rows)
        monkeypatch.setattr(
            fixture,
            "OWNER_QUOTES",
            {
                module: "\n".join(
                    v for p, v in rows.items() if fixture.OWNER[p] == module
                )
                for module in ("CP-1", "CP-2G", "CP-4")
            },
        )
    resolved = request.getfixturevalue("forecast_route")
    assert isinstance(resolved, ResolvedRoute)
    return resolved


def _complete(harness: _Harness) -> None:
    assert (
        _run_route(
            harness, _module_provider(harness, ForecastCompletions(harness.source_id))
        )
        is None
    )
    harness.conn.rollback()


def _path(harness: _Harness, run: object = None) -> str:
    return f"/api/v1/cases/{harness.case_id}/model?run={run or harness.run_id}"


def _get(client: TestClient, harness: _Harness) -> dict[str, Any]:
    response = client.get(_path(harness), headers=_as(harness.approver))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    return dict(response.json())


def test_model_reads_only_the_accepted_cp_cf_projection(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    latest = start_run(harness.conn, harness.case_id)
    harness.conn.commit()
    document = _get(client, harness)
    body = document["body"]
    assert body["case_id"] == str(harness.case_id)
    assert body["latest_run_id"] == str(latest)
    assert body["displayed_run_id"] == str(harness.run_id)
    assert body["unavailable_reason"] is None
    forecast = body["forecast"]
    assert (forecast["currency"], forecast["scale"], forecast["perimeter"]) == (
        "USD",
        "millions",
        "Consolidated",
    )
    [period] = forecast["periods"]
    assert (period["case"], period["period_id"], period["fiscal_year"]) == (
        "BASE",
        "FY2026",
        "2026",
    )
    values = {v["name"]: v for v in period["values"]}
    assert values["cash.closing"]["value"] == "145.000000"
    assert values["debt.closing"]["value"] == "600.000000"
    assert values["metrics.gross_leverage"]["value"] == "6.0000"
    # R24-12: a chart labelling every line by the forecast's currency and
    # scale would call a leverage multiple and a margin ratio a monetary
    # amount. Each value's own `unit` -- MONEY for an `_amount`, MULTIPLE for
    # the leverage/coverage family, RATIO for the one margin -- is what a
    # reader now derives its label from instead.
    assert values["cash.closing"]["unit"] == "MONEY"
    assert values["debt.closing"]["unit"] == "MONEY"
    assert values["metrics.gross_leverage"]["unit"] == "MULTIPLE"
    assert values["metrics.net_leverage"]["unit"] == "MULTIPLE"
    assert values["operating.margin"]["unit"] == "RATIO"
    assert period["unavailable_reason"] is None
    assert all(v["unavailable_reason"] is None for v in values.values())
    row = harness.conn.execute(
        "SELECT route_node_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id LIKE '%%CP-CF%%'",
        (harness.run_id,),
    ).fetchone()
    assert row is not None
    assert (
        tuple(
            forecast[k] for k in ("route_node_id", "artifact_sha256", "record_sha256")
        )
        == row
    )
    assert document["status"] == "complete" and document["chrome"]["actions"] == []


def test_analysis_labels_the_accepted_cp_cf_projection_as_host_calculation(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    response = client.get(
        f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
    )
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    handoff = next(
        h for h in response.json()["body"]["handoffs"] if h["module_id"] == "CP-CF"
    )
    assert handoff["host_calculation"] == "CP_CF_FORECAST"


def test_analysis_serves_the_tagged_tables_each_owner_wrote(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read from the accepted Markdown by the bundle's reader, at request time:
    CP-1's seven interface tables in its contract's order, CP-2G's forecast
    drivers with each figure's exact `Decimal` and every other cell a string,
    and none on CP-CF, whose Markdown tags none."""
    _complete(harness)

    def handoffs() -> dict[str, dict[str, Any]]:
        response = client.get(
            f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
        )
        harness.conn.rollback()
        assert response.status_code == 200, response.json()
        return {h["module_id"]: h for h in response.json()["body"]["handoffs"]}

    served = handoffs()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1").decode(), "CP-1")
    cp1 = served["CP-1"]
    assert [t["table_id"] for t in cp1["tables"]] == rules[
        "unconditional_stable_tables"
    ]
    [drivers] = served["CP-2G"]["tables"]
    assert drivers["table_id"] == "cp2g.cp_model_forecast_drivers"
    assert drivers["columns"] == driver_schema()["required"]
    written = forecast_driver_rows()
    assert [[c["text"] for c in row] for row in drivers["rows"]] == written
    value, driver = (drivers["columns"].index(c) for c in ("value", "driver_id"))
    assert {row[value]["value"] for row in drivers["rows"]} == {"0.05", "-0.10", "0"}
    assert {row[driver]["value"] for row in drivers["rows"]} == {None}
    assert (
        served["CP-CF"]["tables"],
        served["CP-CF"]["tables_unavailable_reason"],
    ) == (
        [],
        None,
    )

    # Past a bound, one handoff's tables are withheld with the reason, and
    # every other handoff's are served as before.
    monkeypatch.setattr(tables, "TABLE_ROWS_MAX", len(written) - 1)
    bounded = handoffs()
    assert bounded["CP-2G"]["tables"] == []
    assert bounded["CP-2G"]["tables_unavailable_reason"] == "TABLES_TOO_LARGE"
    assert bounded["CP-1"]["tables"] == cp1["tables"]


def test_read_analysis_without_tables_matches_read_analysis_but_the_tables(
    harness: _Harness,
) -> None:
    """`read_analysis_without_tables` is `read_analysis` (N58): every field
    matches except each handoff's tagged tables, which it never derives."""
    _complete(harness)
    actor = Actor(harness.approver, GlobalRole.ANALYST)
    args = (
        actor,
        harness.case_id,
        None,
        Standing.APPROVER,
        harness.conn,
        harness.blobs,
        harness.bundle,
    )
    served = analysis_read.read_analysis(*args)
    harness.conn.rollback()
    lean = analysis_read.read_analysis_without_tables(
        analysis_read.AnalysisQuery(*args)
    )
    harness.conn.rollback()

    assert lean.body.model_dump(exclude={"handoffs"}) == served.body.model_dump(
        exclude={"handoffs"}
    )
    assert len(lean.body.handoffs) == len(served.body.handoffs)
    for bare, full in zip(lean.body.handoffs, served.body.handoffs, strict=True):
        stripped = {"tables", "tables_unavailable_reason"}
        assert bare.model_dump(exclude=stripped) == full.model_dump(exclude=stripped)
        assert (bare.tables, bare.tables_unavailable_reason) == ([], None)
    assert any(h.tables for h in served.body.handoffs)


def test_model_reads_the_analysis_route_without_deriving_its_tables(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N58: the Model section reads every accepted handoff through
    `read_analysis_without_tables`, not `read_analysis` -- `ModelBody`
    excludes `handoffs` outright, so deriving each handoff's tagged tables for
    this route only ever produced a value the wire then dropped."""
    _complete(harness)
    calls: list[None] = []

    def counting(contract: VendorContract, markdown: str) -> tables.HandoffTables:
        calls.append(None)
        return tables.handoff_tables(contract, markdown)

    monkeypatch.setattr(analysis_read, "handoff_tables", counting)
    served = _get(client, harness)
    assert served["body"]["forecast"] is not None
    assert calls == []

    analysis_response = client.get(
        f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
    )
    harness.conn.rollback()
    assert analysis_response.status_code == 200, analysis_response.json()
    assert calls  # the direct Analysis read still derives them


@pytest.mark.parametrize("change", ["owner", "record", "pin", "source", "blob"])
def test_model_refuses_missing_or_changed_projection_authority(
    client: TestClient, harness: _Harness, change: str
) -> None:
    _complete(harness)
    if change == "owner":
        tamper(
            harness.conn,
            "DELETE FROM artifacts WHERE run_id=%s AND route_node_id LIKE '%%CP-1%%'",
            (harness.run_id,),
        )
    elif change == "record":
        node, digest = harness.conn.execute(
            "SELECT route_node_id,record_sha256 FROM artifacts"
            " WHERE run_id=%s AND route_node_id LIKE '%%CP-CF%%'",
            (harness.run_id,),
        ).fetchone()  # type: ignore[misc]
        record = _decoded_record(harness.blobs.get(digest))
        altered = replace(
            record, projections=replace(record.projections, confidence_score=1)
        )
        tamper(
            harness.conn,
            "UPDATE artifacts SET record_sha256=%s"
            " WHERE run_id=%s AND route_node_id=%s",
            (harness.blobs.put(record_bytes(altered)), harness.run_id, node),
        )
    elif change == "pin":
        with route_fault(harness.conn):
            harness.conn.execute(
                "UPDATE run_routes SET resolved='{}' WHERE run_id=%s",
                (harness.run_id,),
            )
    elif change == "blob":
        row = harness.conn.execute(
            "SELECT artifact_sha256 FROM artifacts WHERE run_id=%s"
            " AND route_node_id LIKE '%%CP-CF%%'",
            (harness.run_id,),
        ).fetchone()
        assert row is not None
        harness.blobs.path_of(row[0]).unlink()
    else:
        withdraw_source(
            harness.conn,
            case_id=harness.case_id,
            source_id=harness.source_id,
            actor_id=harness.approver,
        )
    harness.conn.commit()
    response = client.get(_path(harness), headers=_as(harness.approver))
    harness.conn.rollback()
    assert response.status_code != 200
    assert set(response.json()) == {"code", "clears"}
    assert response.json()["code"] in {
        "ARTIFACT_RECORD_MISMATCH",
        "ROUTE_IDENTITY_INVALID",
        "RUN_INPUT_INVALID",
        "EVIDENCE_NOT_AVAILABLE",
    }


def test_model_without_an_accepted_forecast_has_no_computed_values(
    client: TestClient, harness: _Harness
) -> None:
    body = _get(client, harness)["body"]
    assert body["forecast"] is None
    assert body["unavailable_reason"] == "NO_ACCEPTED_FORECAST"
    # "No accepted forecast" is a fact about now, so it travels with the run
    # state that says whether one is still coming: this run has not ended, and
    # no verdict has blocked it.
    assert body["displayed_run_status"] == "RUNNING"
    assert body["blocked_by"] is None
    assert _get(client, harness)["status"] == "partial"
    foreign_case = create_case(harness.conn, BoundaryText.of("Other case"))
    foreign_run = start_run(harness.conn, foreign_case)
    harness.conn.commit()
    for invalid in (uuid4(), "malformed", foreign_run):
        response = client.get(_path(harness, invalid), headers=_as(harness.approver))
        assert response.status_code == 404
        assert response.json()["code"] == "RUN_NOT_FOUND"
        harness.conn.rollback()


def test_model_does_not_substitute_a_refused_provider_forecast(
    client: TestClient, harness: _Harness
) -> None:
    assert (
        _run_route(
            harness,
            _module_provider(
                harness, ForecastCompletions(harness.source_id, defect="result")
            ),
        )
        is not None
    )
    harness.conn.rollback()
    assert _get(client, harness)["body"]["forecast"] is None


@pytest.mark.parametrize("route", ["zero-interest"], indirect=True)
def test_model_preserves_an_accepted_unavailable_ratio_reason(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    [period] = _get(client, harness)["body"]["forecast"]["periods"]
    ratio = next(
        v for v in period["values"] if v["name"] == "metrics.interest_coverage"
    )
    assert ratio == {
        "name": "metrics.interest_coverage",
        "unit": "MULTIPLE",
        "value": None,
        "unavailable_reason": "ZERO_OR_NEGATIVE_DENOMINATOR",
    }


def test_model_http_actor_matrix_and_declared_io(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _complete(harness)
    reader = _reader(harness)
    writer, admin, revoked = uuid4(), uuid4(), uuid4()
    for who, standing in (
        (writer, Standing.WRITER),
        (admin, Standing.ADMIN),
        (revoked, Standing.READER),
    ):
        grant(harness.conn, case_id=harness.case_id, user_id=who, standing=standing)
    revoke(harness.conn, case_id=harness.case_id, user_id=revoked)
    harness.conn.commit()
    assert client.get(_path(harness)).status_code == 401
    for who, role in ((uuid4(), None), (revoked, None), (uuid4(), "ADMIN")):
        counter = _CountingConnection(harness.conn)
        app.dependency_overrides[store_connection] = _serving(counter)
        response = client.get(_path(harness), headers=_as(who, role))
        harness.conn.rollback()
        assert response.status_code == 404
        assert response.json()["code"] == "CASE_NOT_FOUND"
        assert counter.executed == 1  # only live standing, no case data
    from caos.api.reads import analysis, model

    # The forecast route's ten handoffs, CP-CF's owner proofs among them, and
    # the pin: under the budget declared for the longest route (ED-7), and
    # every blob downloaded once however often its readers ask.
    nodes = len(harness.route.nodes)
    ten_nodes = (
        analysis.FIXED_IO + nodes * analysis.PER_HANDOFF_IO + analysis.MODEL_PROOFS_IO
    )
    assert nodes == 10
    downloads = _downloads(monkeypatch)
    for who in (reader, writer, harness.approver, admin):
        counter = _CountingConnection(harness.conn)
        app.dependency_overrides[store_connection] = _serving(counter)
        downloads.clear()
        response = client.get(_path(harness), headers=_as(who))
        harness.conn.rollback()
        assert response.status_code == 200
        assert counter.executed == ten_nodes + model.PIN_IO <= model.IO_BUDGET
        assert len(downloads) == nodes * analysis.PER_HANDOFF_BLOBS
        assert len(downloads) <= model.BLOB_BUDGET
        assert response.json()["chrome"]["actions"] == []
    assert model.IO_BUDGET == analysis.IO_BUDGET + model.PIN_IO


def test_model_malformed_or_anonymous_opens_no_connection(
    client: TestClient, harness: _Harness
) -> None:
    def unexpected() -> None:
        pytest.fail("opened store before authenticating and parsing identifiers")

    app.dependency_overrides[store_connection] = unexpected
    assert client.get(_path(harness)).status_code == 401
    for path in (_path(harness, "bad"), "/api/v1/cases/bad/model"):
        assert client.get(path, headers=_as(UUID(int=1))).status_code == 404
