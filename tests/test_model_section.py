"""The Model read: CP-1's credit model on the v1 wire, CP-2G and CP-CF's
projections where the route ran them, the run's pinned rate deck, and the
accepted CP-CF record kept for comparison -- with its live authority and no
fallback."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CATALOG, CONTRACT, fields_from_prompt, skill
from canonical_route_fixtures import driver_schema, forecast_driver_rows
from conftest import route_fault, tamper
from fastapi.testclient import TestClient
from lite_route_fixtures import _table
from pydantic import ValidationError
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
from test_forecast_route import ForecastCompletions, harness, request_data
from test_forecast_route import route as forecast_route

from caos.api import deps
from caos.api.app import app, store_connection
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import analysis as analysis_read
from caos.api.reads import model as model_read
from caos.api.wire import ModelBody
from caos.boundary_text import BoundaryText
from caos.calculators.credit_model.assemble import ModelInputs, credit_model
from caos.calculators.credit_model.layout import BANDS
from caos.calculators.credit_model.projection import RateDeckYear
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology import tables
from caos.methodology.forecast import forecast_inputs
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.methodology.model_inputs import cp1_registers
from caos.methodology.vendor import VendorContract
from caos.provider import Completion
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.rate_decks import save_deck
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
    if getattr(request, "param", None) == "no-model":
        # The same pack and owners, on the route without the model extension:
        # CP-1 and CP-2G run, CP-CF does not.
        return resolve_route(CATALOG, "FULL_CREDIT_32", "RELATIVE_VALUE")
    return resolved


def _columns(text: str) -> list[str]:
    return text.split("|")


def _period(period_id: str, year: str, days: str) -> list[str]:
    return [
        *(period_id, year, "", "FY", f"{year}-01-01", f"{year}-12-31", days),
        *("AUDITED", "USD", "MILLIONS", "IFRS", "consolidated", "issuer-pack"),
        *(f"{period_id} annual results", ""),
    ]


def _account(metric_id: str, period_id: str, value: str) -> list[str]:
    return [
        *(metric_id, period_id, value, "SIGNED_AS_REPORTED", "REPORTED"),
        *("Supported", "issuer-pack", f"{period_id} annual results", "", ""),
    ]


# The term loan's terms: floating over SOFR, so the pinned deck sets its rate.
TERM_COUPON = "SOFR + 300 bp"
PIK_COUPON = "SOFR + 300 bp cash, 2% PIK"


def _fiscal_year(year: int) -> list[str]:
    days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    return _period(f"FY{year}", str(year), str(days))


def _with(
    rows: list[list[str]], figures: Mapping[tuple[str, str], str]
) -> list[list[str]]:
    """Account rows with the `(metric_id, period_id)` figures written over."""
    return [[*row[:2], figures.get((row[0], row[1]), row[2]), *row[3:]] for row in rows]


def cp1_tables(
    coupon: str = TERM_COUPON,
    *,
    figures: Mapping[tuple[str, str], str] | None = None,
    years: Sequence[int] = (2024, 2025),
    segment: bool = False,
) -> str:
    """CP-1's tagged model registers as the model reads them: FY2024 and
    FY2025 income statements, the FY2025 balances, one unrealised add-back
    and one floating term loan. FY2025 revenue and the add-back carry CP-1's
    first citation marker; FY2024 revenue carries none. `figures` writes
    over account figures, `years` are the fiscal years registered, and
    `segment` adds one business unit bound to CP-2G's `DIVISION_1`."""
    written = {
        "cp1.model_period_register": (
            _columns(
                "period_id|fiscal_year|fiscal_quarter|period_type|start_date"
                "|end_date|day_count|audit_status|currency|unit|accounting_basis"
                "|entity_perimeter|source_id|source_locator|component_period_ids"
            ),
            [_fiscal_year(year) for year in years],
        ),
        "cp1.model_account_register": (
            _columns(
                "metric_id|period_id|value|sign_convention|value_class"
                "|calculation_status|source_id|source_locator|conflict_refs"
                "|limitation_refs"
            ),
            _with(
                [
                    _account(metric, period_id, value)
                    for period_id, stated in (
                        ("FY2024", ("950", "-570", "-240", "-50", "190")),
                        ("FY2025", ("1000 [C1]", "-600", "-250", "-50", "200")),
                    )
                    for metric, value in zip(
                        (
                            "revenue",
                            "cogs",
                            "opex_including_da",
                            "depreciation_amortization",
                            "ebitda",
                        ),
                        stated,
                        strict=True,
                    )
                ]
                + [
                    _account("cash_and_equivalents", "FY2025", "100"),
                    _account("total_debt", "FY2025", "600"),
                ],
                figures or {},
            ),
        ),
        "cp1.segment_revenue_schedule": (
            _columns(
                "segment_id|segment_name|segment_type|display_priority|period_id"
                "|revenue|status|source_id|source_locator"
            ),
            [
                [
                    *("SEG1", "Division one", "BUSINESS_UNIT", "1", period_id, revenue),
                    *("Supported", "issuer-pack", f"{period_id} segment note"),
                ]
                for period_id, revenue in (("FY2024", "950"), ("FY2025", "1000"))
            ]
            if segment
            else [],
        ),
        "cp1.adjusted_ebitda_bridge": (
            _columns(
                "addback_id|addback_label|addback_classification|realization_status"
                "|display_priority|period_id|value|status|source_definition"
                "|source_id|source_locator"
            ),
            [
                [
                    *("synergies", "Cost synergies", "SYNERGY", "UNREALIZED", "1"),
                    *("FY2025", "20 [C1]", "Supported", "run-rate", "issuer-pack"),
                    "FY2025 annual results",
                ]
            ],
        ),
        "cp1.debt_facility_register": (
            _columns(
                "facility_id|facility_name|period_id|facility_type|carrying_value"
                "|principal|drawn_amount|commitment|secured_status|seniority"
                "|currency|margin_or_coupon|maturity_date|lease_classification"
                "|rate_type|reference_rate|spread_bps|floor_bps|fixed_rate"
                "|annual_amortisation|source_id|source_locator"
            ),
            [
                [
                    *("TERM", "Term loan", "FY2025", "TERM_LOAN", "600", "600"),
                    *("600", "600", "SECURED", "SENIOR", "USD", coupon),
                    *("2030-12-31", "NOT_LEASE", "FLOATING", "SOFR", "300", "null"),
                    *("null", "0", "issuer-pack", "FY2025 annual results"),
                ]
            ],
        ),
    }
    if segment:
        written["cp1.cp_model_segment_allocation"] = (
            ["slot_id", "component_segment_ids"],
            [["DIVISION_1", "SEG1"]],
        )
    return "".join(
        f"<!-- table-id: {table_id} -->\n" + _table(columns, rows)
        for table_id, (columns, rows) in written.items()
    )


# CP-1's tagged tables the fixture writes, from the first model register to
# the table after the debt register; `ModelCompletions` writes them over.
_FIRST = "<!-- table-id: cp1.model_period_register -->"
_AFTER = "<!-- table-id: cp1.model_reconciliation_register -->"


# One of CP-2G's division growth drivers, as the fixture writes it, and the
# same row in a unit no growth driver is read in (`model_inputs._fraction`).
_GROWTH_ROW = "| division_growth | DIVISION_1 | BASE | FY2026 | 2026 | 0.05 | "
_PERCENT, _MONEY = "PERCENT_DECIMAL |", "CURRENCY_MM |"


class ModelCompletions(ForecastCompletions):
    """The forecast route's answers, CP-1's model registers written as
    `cp1_tables()` in place of the fixture's bounded findings; with
    `money_growth`, CP-2G's first growth driver stated as money, which the
    model cannot read; with `tables`, those CP-1 tables; with `growth`, that
    figure as CP-2G's first growth driver."""

    def __init__(
        self,
        source_id: UUID,
        *,
        defect: str = "",
        money_growth: bool = False,
        tables: str | None = None,
        growth: str | None = None,
    ) -> None:
        super().__init__(source_id, defect=defect)
        self.tables = tables if tables is not None else cp1_tables()
        self.money_growth = money_growth
        # CP-2G's BASE FY2026 growth for `DIVISION_1`, in place of 0.05.
        self.growth = growth

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        done = super().complete(prompt, json_object=json_object)
        module = fields_from_prompt(prompt)["module_id"]
        if module not in {"CP-1", "CP-2G"}:
            return done
        assert done.content is not None
        answer = json.loads(done.content)
        markdown = answer["canonical_markdown"]
        if module == "CP-1":
            start, end = markdown.index(_FIRST), markdown.index(_AFTER)
            markdown = markdown[:start] + self.tables + markdown[end:]
        elif self.money_growth:
            row = _GROWTH_ROW + _PERCENT
            assert row in markdown
            markdown = markdown.replace(row, _GROWTH_ROW + _MONEY)
        elif self.growth is not None:
            row = _GROWTH_ROW + _PERCENT
            assert row in markdown
            grown = _GROWTH_ROW.replace("| 0.05 | ", f"| {self.growth} | ")
            markdown = markdown.replace(row, grown + _PERCENT)
        answer["canonical_markdown"] = markdown
        return replace(done, content=json.dumps(answer))


def _complete(harness: _Harness, answers: ForecastCompletions | None = None) -> None:
    completions = answers or ModelCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, completions)) is None
    harness.conn.rollback()


def _path(harness: _Harness, run: object = None, query: str = "") -> str:
    return f"/api/v1/cases/{harness.case_id}/model?run={run or harness.run_id}{query}"


def _get(client: TestClient, harness: _Harness, query: str = "") -> dict[str, Any]:
    response = client.get(_path(harness, query=query), headers=_as(harness.approver))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    return dict(response.json())


def _text(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:f}"


def _line(body: dict[str, Any], line_id: str) -> dict[str, Any]:
    [line] = [line for line in body["lines"] if line["line_id"] == line_id]
    return dict(line)


def _cell(body: dict[str, Any], line_id: str, column_id: str) -> dict[str, Any]:
    index = [c["column_id"] for c in body["columns"]].index(column_id)
    return dict(_line(body, line_id)["cells"][index])


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
    assert values["metrics.interest_coverage"]["unit"] == "MULTIPLE"
    assert values["operating.margin"]["unit"] == "RATIO"
    # N3: FCF over debt is a fraction of the debt, which credit practice
    # states as a percentage -- never a multiple of it.
    assert values["metrics.fcf_to_debt"]["unit"] == "RATIO"
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


def test_a_run_with_cp1_serves_columns_and_lines_in_layout_order(
    client: TestClient, harness: _Harness
) -> None:
    """CP-1's model, CP-CF's projection beside it: the calculator's columns
    and lines, in its order, each figure an exact decimal string."""
    _complete(harness)
    document = _get(client, harness)
    body = document["body"]
    assert (document["observed_empty"], document["status"], document["notes"]) == (
        False,
        "complete",
        [],
    )
    assert (body["currency"], body["unit"], body["exclude_unrealised"]) == (
        "USD",
        "MILLIONS",
        False,
    )
    assert [
        (c["column_id"], c["kind"], c["label"], c["case"]) for c in body["columns"]
    ] == [
        ("FY:FY2024", "FY", "FY24", None),
        ("FY:FY2025", "FY", "FY25", None),
        ("LTM:FY2025", "LTM", "LTM Q4 25", None),
        ("BASE:2026", "PROJECTED", "FY26E", "BASE"),
    ]
    fy25 = body["columns"][1]
    assert (fy25["period_id"], fy25["fiscal_year"], fy25["end_date"]) == (
        "FY2025",
        "2025",
        "2025-12-31",
    )
    assert fy25["days"] == 365
    # The calculator's own model of the same inputs, line for line: the read
    # maps, it does not reorder or drop.
    expected = credit_model(
        ModelInputs(
            registers=cp1_registers(
                tables.handoff_tables(CONTRACT, cp1_tables()).tables
            ),
            request=request_data(),
            growth=(),
            slots=(),
            deck=None,
        )
    )
    assert [line["line_id"] for line in body["lines"]] == [
        line.line_id for line in expected.lines
    ]
    # Every served cell is the calculator's, field for field.
    assert [
        [
            (cell["value"], cell["reason"], cell["basis"], cell["stated"], cell["note"])
            for cell in line["cells"]
        ]
        for line in body["lines"]
    ] == [
        [
            (_text(c.value), c.reason, c.basis, _text(c.stated), c.note)
            for c in line.cells
        ]
        for line in expected.lines
    ]
    bands = [BANDS.index(line["band"]) for line in body["lines"]]
    assert bands == sorted(bands)
    revenue = _cell(body, "revenue", "FY:FY2025")
    assert (revenue["value"], revenue["basis"], revenue["reason"]) == (
        "1000",
        "REPORTED",
        None,
    )
    [source] = revenue["sources"]
    assert (source["source_id"], source["source_locator"]) == (
        "issuer-pack",
        "FY2025 annual results",
    )
    # A cell without a figure says why, and never a zero.
    interest = _cell(body, "cash_interest", "FY:FY2025")
    assert (interest["value"], interest["reason"]) == (None, "NOT_SOURCED")
    term = _line(body, "fac:TERM")
    assert term["terms"] == {
        "reference_rate": "SOFR",
        "spread_or_coupon": "+300 bp",
        "floor": "none",
        "maturity": "2030-12-31",
        "amortisation": "bullet",
    }
    assert all(
        cell["value"] is None or "E" not in cell["value"]
        for line in body["lines"]
        for cell in line["cells"]
    )
    assert body["rate_deck"] is None
    assert body["forecast"]["route_node_id"].endswith("CP-CF")


def test_every_line_has_one_cell_per_column(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    body = _get(client, harness)["body"]
    width = len(body["columns"])
    assert width and body["lines"]
    assert all(len(line["cells"]) == width for line in body["lines"])
    # The wire refuses a body whose line has a cell too few.
    ragged = json.loads(json.dumps(body))
    ragged["lines"][0]["cells"] = ragged["lines"][0]["cells"][:-1]
    with pytest.raises(ValidationError):
        ModelBody.model_validate(ragged)
    assert ModelBody.model_validate(body).columns


def test_a_run_without_cp1_is_observed_empty_with_handoffs_pending(
    client: TestClient, harness: _Harness
) -> None:
    """Spec M1: a Model exists once CP-1 is accepted; before that the body is
    empty and says the handoffs are pending."""
    document = _get(client, harness)
    body = document["body"]
    assert document["observed_empty"] is True
    assert document["status"] == "partial"
    assert "HANDOFFS_PENDING" in document["notes"]
    assert (body["columns"], body["lines"], body["forecast"]) == ([], [], None)
    assert (body["currency"], body["unit"], body["rate_deck"]) == (None, None, None)
    # Whether the model is still coming: this run has not ended.
    assert body["displayed_run_status"] == "RUNNING"
    foreign_case = create_case(harness.conn, BoundaryText.of("Other case"))
    foreign_run = start_run(harness.conn, foreign_case)
    harness.conn.commit()
    for invalid in (uuid4(), "malformed", foreign_run):
        response = client.get(_path(harness, invalid), headers=_as(harness.approver))
        assert response.status_code == 404
        assert response.json()["code"] == "RUN_NOT_FOUND"
        harness.conn.rollback()


@pytest.mark.parametrize("route", ["no-model"], indirect=True)
def test_a_route_without_cp_cf_serves_history_only_with_a_limitation(
    client: TestClient, harness: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "CP-CF" not in {node.module_id for node in harness.route.nodes}
    _complete(harness)
    capsys.readouterr()
    document = _get(client, harness)
    body = document["body"]
    assert document["observed_empty"] is False
    assert {c["kind"] for c in body["columns"]} == {"FY", "LTM"}
    assert "No projections: this route did not run CP-2G/CP-CF" in body["limitations"]
    # CP-2G ran and its drivers read: nothing was held flat for want of them.
    assert model_read.GROWTH_UNAVAILABLE not in body["limitations"]
    assert "model_tables_unreadable" not in capsys.readouterr().err
    assert body["forecast"] is None
    assert body["rate_deck"] is None


@pytest.fixture
def pinned_deck(case: tuple[StoreConnection, UUID]) -> UUID:
    """A deck saved before the harness creates its run, which pins it: SOFR
    at 4.00% Base and 5.00% Downside for FY+1. Requested before `client` and
    `harness`, so it is saved first."""
    conn, _case_id = case
    deck_id = save_deck(
        conn,
        uuid4(),
        date(2026, 1, 2),
        (RateDeckYear("SOFR", 1, Decimal("0.0400"), Decimal("0.0500")),),
    )
    conn.commit()
    return deck_id


def test_projection_interest_uses_the_runs_pinned_deck_not_a_newer_one(
    pinned_deck: UUID, client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    newer = save_deck(
        harness.conn,
        uuid4(),
        date(2026, 6, 30),
        (RateDeckYear("SOFR", 1, Decimal("0.0900"), Decimal("0.0950")),),
    )
    harness.conn.commit()
    body = _get(client, harness)["body"]
    assert body["rate_deck"] == {"deck_id": str(pinned_deck), "as_of": "2026-01-02"}
    assert newer != pinned_deck
    assert _cell(body, "reference_rate", "BASE:2026")["value"] == "0.0400"
    # SOFR 4.00% plus the 300 bp spread, on the 600 opening debt.
    assert _cell(body, "wa_rate", "BASE:2026")["value"] == "0.0700"
    assert _cell(body, "cash_interest", "BASE:2026")["value"] == "-42.0000"


def test_exclude_unrealised_changes_adjusted_ebitda(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    included = _get(client, harness)["body"]
    excluded = _get(client, harness, "&exclude_unrealised=1")["body"]
    assert (included["exclude_unrealised"], excluded["exclude_unrealised"]) == (
        False,
        True,
    )
    assert _cell(included, "adjusted_ebitda", "FY:FY2025")["value"] == "220"
    assert _cell(excluded, "adjusted_ebitda", "FY:FY2025")["value"] == "200"
    assert _line(excluded, "addback:synergies")["kind"] == "MEMO"
    for spelled in ("0", "false"):
        off = _get(client, harness, f"&exclude_unrealised={spelled}")["body"]
        assert off["exclude_unrealised"] is False
    for spelled in ("true",):
        on = _get(client, harness, f"&exclude_unrealised={spelled}")["body"]
        assert on["exclude_unrealised"] is True


def test_a_malformed_exclude_unrealised_is_refused_before_the_store(
    client: TestClient, harness: _Harness
) -> None:
    def unexpected() -> None:
        pytest.fail("opened the store before parsing the query")

    app.dependency_overrides[store_connection] = unexpected
    response = client.get(
        _path(harness, query="&exclude_unrealised=maybe"),
        headers=_as(harness.approver),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_INVALID"
    assert model_read.exclude_unrealised_query(None) is False
    assert model_read.exclude_unrealised_query("1") is True
    with pytest.raises(Refusal) as refused:
        model_read.exclude_unrealised_query("yes")
    assert refused.value.code == RefusalCode.REQUEST_INVALID


def test_a_marker_resolves_to_the_cp1_citation(
    client: TestClient, harness: _Harness
) -> None:
    """D107: a CP-1 cell's `[C1]` is CP-1's own first citation, as Analysis
    serves it; a cell without a marker cites nothing."""
    _complete(harness)
    body = _get(client, harness)["body"]
    analysis = client.get(
        f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
    )
    harness.conn.rollback()
    [cp1] = [h for h in analysis.json()["body"]["handoffs"] if h["module_id"] == "CP-1"]
    [first] = [fact for fact in cp1["source_facts"] if fact["marker"] == 1]
    [marked] = _cell(body, "revenue", "FY:FY2025")["sources"]
    assert marked["citation"] == first
    [unmarked] = _cell(body, "revenue", "FY:FY2024")["sources"]
    assert unmarked["citation"] is None
    [addback] = _cell(body, "addback:synergies", "FY:FY2025")["sources"]
    assert addback["citation"] == first


def test_a_pik_coupon_is_a_stated_limitation(
    client: TestClient, harness: _Harness
) -> None:
    _complete(
        harness, ModelCompletions(harness.source_id, tables=cp1_tables(PIK_COUPON))
    )
    limitations = _get(client, harness)["body"]["limitations"]
    assert model_read.PIK_LIMITATION in limitations
    assert model_read.PIK_LIMITATION == (
        "PIK notes carry only their cash coupon in the rate terms;"
        " PIK interest is not modelled"
    )


def test_a_cash_coupon_states_no_pik_limitation(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    assert model_read.PIK_LIMITATION not in _get(client, harness)["body"]["limitations"]


def _unreadable(harness: _Harness, module: str) -> str:
    return (
        f"model_tables_unreadable case={harness.case_id} run={harness.run_id}"
        f" module={module} code=HANDOFF_MALFORMED"
    )


def test_an_older_cp1_without_model_tables_serves_the_forecast_partially(
    client: TestClient, harness: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    """A CP-1 whose model registers do not parse -- an older run's, written
    before the CP-1 fork, here the fixture's bounded findings -- does not
    refuse the Model: the accepted CP-CF forecast is still served, the model
    is empty, and why is said and logged, never with document text."""
    _complete(harness, ForecastCompletions(harness.source_id))
    capsys.readouterr()
    document = _get(client, harness)
    body = document["body"]
    assert document["status"] == "partial"
    # A forecast is served, so the document is not empty.
    assert document["observed_empty"] is False
    assert (body["columns"], body["lines"]) == ([], [])
    assert body["limitations"] == ["CP-1 model tables unreadable"]
    assert body["forecast"] is not None
    assert body["forecast"]["route_node_id"].endswith("CP-CF")
    assert (body["currency"], body["unit"], body["rate_deck"]) == (None, None, None)
    logged = capsys.readouterr().err
    assert _unreadable(harness, "CP-1") in logged
    assert "issuer-pack" not in logged


def test_malformed_cp2g_drivers_hold_business_units_flat_with_a_limitation(
    client: TestClient, harness: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    _complete(harness, ModelCompletions(harness.source_id, money_growth=True))
    capsys.readouterr()
    body = _get(client, harness)["body"]
    assert "BASE:2026" in [c["column_id"] for c in body["columns"]]
    assert (
        "CP-2G growth drivers unavailable: business units held flat"
        in (body["limitations"])
    )
    # The model the calculator makes without growth, figure for figure.
    flat = credit_model(
        ModelInputs(
            registers=cp1_registers(
                tables.handoff_tables(CONTRACT, cp1_tables()).tables
            ),
            request=request_data(),
            growth=(),
            slots=(),
            deck=None,
        )
    )
    assert [[c["value"] for c in line["cells"]] for line in body["lines"]] == [
        [None if c.value is None else f"{c.value:f}" for c in line.cells]
        for line in flat.lines
    ]
    assert _unreadable(harness, "CP-2G") in capsys.readouterr().err


def test_withheld_cp2g_tables_hold_business_units_flat_with_a_limitation(
    client: TestClient,
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Past a bound, Analysis withholds CP-2G's tables with the reason; the
    model is served without CP-2G's growth, and says so."""
    _complete(harness)
    monkeypatch.setattr(tables, "TABLE_ROWS_MAX", len(forecast_driver_rows()) - 1)
    capsys.readouterr()
    body = _get(client, harness)["body"]
    assert body["lines"] and body["forecast"] is not None
    assert (
        "CP-2G growth drivers unavailable: business units held flat"
        in (body["limitations"])
    )
    assert _unreadable(harness, "CP-2G") in capsys.readouterr().err


NINES = "9" * 64
WITHHELD = "figures too large to serve were withheld"


def _withheld(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        cell
        for line in body["lines"]
        for cell in line["cells"]
        if cell["note"] == "figure too large to serve"
    ]


def _unservable(harness: _Harness, count: int) -> str:
    return (
        f"model_figure_unservable case={harness.case_id} run={harness.run_id}"
        f" count={count}"
    )


def test_a_ratio_too_long_to_serve_is_withheld_with_a_limitation(
    client: TestClient, harness: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    """Figures in every bound CP-1 allows -- 10^-10 of EBITDA over 3 x 10^17
    of revenue -- still make a margin whose plain decimal runs past the
    wire's 64 characters. That cell is withheld with its reason and note,
    never a 500; the rest of the model is served."""
    tiny = {
        ("revenue", "FY2025"): "300000000000000000",
        ("cogs", "FY2025"): "-300000000000000000",
        ("opex_including_da", "FY2025"): "-0.0000000001",
        ("depreciation_amortization", "FY2025"): "-0.0000000002",
        ("ebitda", "FY2025"): "0.0000000001",
    }
    tables = cp1_tables(figures=tiny)
    expected = credit_model(
        ModelInputs(
            registers=cp1_registers(tables_of(tables)),
            request=request_data(),
            growth=(),
            slots=(),
            deck=None,
        )
    )
    long = [
        (line.line_id, index)
        for line in expected.lines
        for index, cell in enumerate(line.cells)
        if cell.value is not None and len(f"{cell.value:f}") > 64
    ]
    assert long, "the figures make no value past the wire's bound"
    _complete(harness, ModelCompletions(harness.source_id, tables=tables))
    capsys.readouterr()
    body = _get(client, harness)["body"]
    for line_id, index in long:
        cell = _line(body, line_id)["cells"][index]
        assert (cell["value"], cell["reason"], cell["note"]) == (
            None,
            "NOT_APPLICABLE",
            "figure too large to serve",
        )
    assert WITHHELD in body["limitations"]
    assert _cell(body, "revenue", "FY:FY2025")["value"] == "300000000000000000"
    logged = capsys.readouterr().err
    assert _unservable(harness, len(_withheld(body))) in logged
    assert "300000000000000000" not in logged


def tables_of(markdown: str) -> tuple[tables.HandoffTable, ...]:
    return tables.handoff_tables(CONTRACT, markdown).tables


@pytest.mark.parametrize(
    "repro",
    ["revenue", "cash", "growth"],
)
def test_the_audits_oversized_figures_never_fault_the_read(
    client: TestClient,
    harness: _Harness,
    capsys: pytest.CaptureFixture[str],
    repro: str,
) -> None:
    """The audit's three repros: 64 nines of revenue in both years (a margin
    past 64 characters), 64 nines of cash with no debt (net debt 65), and a
    63-digit CP-2G growth driver (a business unit past 64). Each is served,
    every figure within the wire's bound. Where the CP-1 reader admits the
    figure the serving guard withholds what overflows; where it refuses it
    (its own figure bound, wave C) the tables are unreadable instead."""
    answers = {
        "revenue": ModelCompletions(
            harness.source_id,
            tables=cp1_tables(
                figures={("revenue", "FY2024"): NINES, ("revenue", "FY2025"): NINES}
            ),
        ),
        "cash": ModelCompletions(
            harness.source_id,
            tables=cp1_tables(
                figures={
                    ("cash_and_equivalents", "FY2025"): NINES,
                    ("total_debt", "FY2025"): "0",
                }
            ),
        ),
        "growth": ModelCompletions(
            harness.source_id, tables=cp1_tables(segment=True), growth="9" * 63
        ),
    }[repro]
    _complete(harness, answers)
    capsys.readouterr()
    body = _get(client, harness)["body"]
    assert all(
        cell["value"] is None or len(cell["value"]) <= 64
        for line in body["lines"]
        for cell in line["cells"]
    )
    logged = capsys.readouterr().err
    assert NINES not in logged
    if WITHHELD in body["limitations"]:
        assert _withheld(body)
        assert _unservable(harness, len(_withheld(body))) in logged
    else:
        assert {"CP-1 model tables unreadable", model_read.GROWTH_UNAVAILABLE} & set(
            body["limitations"]
        )


def test_a_model_past_the_grid_bounds_is_partial_with_the_forecast(
    client: TestClient, harness: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    """Seventy fiscal years are seventy FY columns, past the wire's 64: the
    model is checked before it is mapped, and served as an empty grid with
    the forecast kept, the reason stated and logged."""
    years = range(1956, 2026)
    assert len(years) == 70
    _complete(
        harness, ModelCompletions(harness.source_id, tables=cp1_tables(years=years))
    )
    capsys.readouterr()
    document = _get(client, harness)
    body = document["body"]
    assert document["status"] == "partial"
    assert document["observed_empty"] is False
    assert (body["columns"], body["lines"]) == ([], [])
    assert body["limitations"] == ["model exceeds the grid bounds"]
    assert body["forecast"] is not None
    logged = capsys.readouterr().err
    assert (
        f"model_grid_oversize case={harness.case_id} run={harness.run_id} columns="
    ) in logged
    [line] = [line for line in logged.splitlines() if "model_grid_oversize" in line]
    columns = int(line.split("columns=")[1].split()[0])
    assert columns > 64 and " lines=" in line


def test_a_reconciliation_fault_is_visible_and_logged_not_refused(
    client: TestClient,
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The bridges close by construction; one that did not would be a host
    defect. An assist model shows it rather than withholding the model, and
    the log names the case, the run and the count, never a figure."""
    _complete(harness)
    assert not any(
        limitation.startswith("reconciliation: ")
        for limitation in _get(client, harness)["body"]["limitations"]
    )
    faults = ("FY:FY2025:ebitda", "BASE:2026:cash")
    monkeypatch.setattr(model_read, "reconciliation_faults", lambda _model: faults)
    capsys.readouterr()
    limitations = _get(client, harness)["body"]["limitations"]
    assert [f"reconciliation: {fault}" for fault in faults] == [
        limitation
        for limitation in limitations
        if limitation.startswith("reconciliation: ")
    ]
    logged = capsys.readouterr().err
    assert (
        f"model_reconciliation_fault case={harness.case_id}"
        f" run={harness.run_id} count=2"
    ) in logged
    assert "ebitda" not in logged


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


def test_analysis_serves_the_registers_each_modules_profile_declares(
    client: TestClient, harness: _Harness
) -> None:
    """N94: CP-4's `T4C.4` is read from its accepted Markdown by the bundle's
    locator, with the profile column the bundle binds to each header cell; CP-CF
    (the host's own `SKILL.md`) serves no register and no refusal."""
    _complete(harness)
    response = client.get(
        f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
    )
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    served = {h["module_id"]: h for h in response.json()["body"]["handoffs"]}

    cp4 = served["CP-4"]
    assert cp4["registers_unavailable_reason"] is None
    [register] = [r for r in cp4["registers"] if r["register_id"] == "T4C.4"]
    profile = CONTRACT.completeness_check.load_contract(skill("CP-4").decode(), "CP-4")
    expected = profile["registers"]["T4C.4"]["columns"]
    assert register["columns"] == expected
    assert register["declared"] == expected
    [row] = register["rows"]
    assert [cell["text"] for cell in row][:3] == ["Net leverage", "maintenance", "4.0x"]
    assert set(register) == {"register_id", "columns", "declared", "rows"}
    assert (
        served["CP-CF"]["registers"],
        served["CP-CF"]["registers_unavailable_reason"],
    ) == ([], None)


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
        stripped = {
            "tables",
            "tables_unavailable_reason",
            "registers",
            "registers_unavailable_reason",
        }
        assert bare.model_dump(exclude=stripped) == full.model_dump(exclude=stripped)
        assert (bare.tables, bare.tables_unavailable_reason) == ([], None)
        assert (bare.registers, bare.registers_unavailable_reason) == ([], None)
    assert any(h.tables for h in served.body.handoffs)
    assert any(h.registers for h in served.body.handoffs)


def test_model_derives_only_the_tables_of_cp1_and_cp2g(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N58: the Model section reads every accepted handoff through
    `read_analysis_without_tables`, not `read_analysis`, and derives the
    tagged tables of the two handoffs its model reads, CP-1 and CP-2G, once
    each -- never every handoff's."""
    _complete(harness)
    calls: list[str] = []
    derived: list[str] = []

    def counting(contract: VendorContract, markdown: str) -> tables.HandoffTables:
        calls.append(markdown)
        return tables.handoff_tables(contract, markdown)

    def deriving(contract: VendorContract, markdown: str) -> tables.HandoffTables:
        derived.append(markdown)
        return tables.handoff_tables(contract, markdown)

    monkeypatch.setattr(analysis_read, "handoff_tables", counting)
    monkeypatch.setattr(model_read, "handoff_tables", deriving)
    served = _get(client, harness)
    assert served["body"]["forecast"] is not None and served["body"]["lines"]
    assert calls == []
    analysis = client.get(
        f"/api/v1/cases/{harness.case_id}/analysis", headers=_as(harness.approver)
    )
    harness.conn.rollback()
    assert analysis.status_code == 200, analysis.json()
    accepted = {h["module_id"]: h for h in analysis.json()["body"]["handoffs"]}
    assert derived == [
        accepted["CP-1"]["model_analysis"],
        accepted["CP-2G"]["model_analysis"],
    ]
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


def test_model_does_not_substitute_a_refused_provider_forecast(
    client: TestClient, harness: _Harness
) -> None:
    assert (
        _run_route(
            harness,
            _module_provider(
                harness, ModelCompletions(harness.source_id, defect="result")
            ),
        )
        is not None
    )
    harness.conn.rollback()
    body = _get(client, harness)["body"]
    assert body["forecast"] is None
    # CP-1 was accepted, so its model is served, with no projection.
    assert {c["kind"] for c in body["columns"]} == {"FY", "LTM"}
    assert "No projections: this route did not run CP-2G/CP-CF" in body["limitations"]


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


def test_the_model_reads_within_its_declared_io_budget(
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
        # Live standing, then -- the request names a run -- whether it has a
        # live book entry (spec B9's grant, `deps.visible_run`); no case data.
        assert counter.executed == 1 + deps.GRANT_IO
    from caos.api.reads import analysis, model

    # The forecast route's ten handoffs, CP-CF's owner proofs among them, the
    # live-source pin and the run's pinned deck: under the budget declared for
    # the longest route (ED-7), and every blob downloaded once however often
    # its readers ask.
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
        assert (
            counter.executed
            == ten_nodes + model.PIN_IO + model.DECK_IO
            <= model.READ_IO
            <= model.IO_BUDGET
        )
        assert len(downloads) == nodes * analysis.PER_HANDOFF_BLOBS
        assert len(downloads) <= model.BLOB_BUDGET
        assert response.json()["chrome"]["actions"] == []
    assert model.READ_IO == analysis.IO_BUDGET + model.PIN_IO + model.DECK_IO
    assert model.IO_BUDGET == model.READ_IO + model.ENTRY_IO


def test_model_malformed_or_anonymous_opens_no_connection(
    client: TestClient, harness: _Harness
) -> None:
    def unexpected() -> None:
        pytest.fail("opened store before authenticating and parsing identifiers")

    app.dependency_overrides[store_connection] = unexpected
    assert client.get(_path(harness)).status_code == 401
    for path in (_path(harness, "bad"), "/api/v1/cases/bad/model"):
        assert client.get(path, headers=_as(UUID(int=1))).status_code == 404


def test_the_accepted_forecast_is_re_derived_with_its_request_and_bindings(
    harness: _Harness,
) -> None:
    """`accepted_forecast` re-derives the accepted CP-CF record the Model
    keeps for comparison, and `forecast_inputs` reads the accepted request
    and the owner bindings behind it from the same bytes."""
    _complete(harness)
    analysis = analysis_read.read_analysis(
        Actor(harness.approver, GlobalRole.ANALYST),
        harness.case_id,
        None,
        Standing.APPROVER,
        harness.conn,
        harness.blobs,
        harness.bundle,
    ).body
    forecast = model_read.accepted_forecast(harness.conn, analysis)
    harness.conn.rollback()
    accepted = next(h for h in analysis.handoffs if h.module_id == "CP-CF")
    assert forecast is not None
    assert forecast.record_sha256 == accepted.record_sha256
    request, bindings = forecast_inputs(accepted.model_analysis.encode("utf-8"))
    assert request["drivers"][0]["ebitda"] == "100"
    assert bindings["/drivers/0/ebitda"]["module_id"] == "CP-2G"
