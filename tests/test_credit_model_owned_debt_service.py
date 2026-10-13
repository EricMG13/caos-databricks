"""Independent aggregate debt-service answer keys and tamper checks."""

import json
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from typing import Any, cast
from unicodedata import normalize

import pytest
from credit_model_fixture import example_growth, example_slots
from test_credit_model_assemble import _cell, _with_cell
from test_credit_model_assemble import _model as _legacy_model
from test_forecast_debt_service import debt_inputs

from caos.calculators.cash_flow import cash_flow_forecast
from caos.calculators.credit_model.assemble import (
    CreditModel,
    ModelInputs,
    credit_model,
    reconciliation_faults,
)
from caos.calculators.credit_model.frame import Cell
from caos.calculators.credit_model.projection import ProjectionInputs, projection
from caos.methodology.model_inputs import Cp1Registers
from caos.refusals import Refusal, RefusalCode


def owned_inputs() -> tuple[dict[str, Any], Cp1Registers]:
    request, regs = debt_inputs()
    loan = next(r for r in regs.facilities if r.facility_id == "tlb")
    cost = next(r for r in regs.facilities if r.facility_type == "DEBT ADJUSTMENT")
    facilities = (
        replace(loan, carrying_value=Decimal(11792)),
        replace(cost, carrying_value=Decimal(-8)),
    )
    regs = replace(
        regs,
        facilities=facilities,
        accounts=tuple(a for a in regs.accounts if a.metric_id != "cash_interest"),
    )
    request["opening"]["debt_by_facility"] = [
        {"facility_id": r.facility_id, "amount": str(r.carrying_value)}
        for r in facilities
    ]
    request["periods"] = []
    request["drivers"] = []
    request["contractual"]["aggregate_amortisation"] = []
    for case in ("BASE", "DOWNSIDE"):
        for year, principal, cash, debt in (
            (2026, 55, 1225, 11657),
            (2027, 114, 1617, 11569),
            (2028, 767, 1356, 10828),
        ):
            period_id = f"FY{year % 100}"
            request["periods"].append(
                dict(
                    case=case,
                    period_id=period_id,
                    fiscal_year=str(year),
                    days="366" if year == 2028 else "365",
                    start_date=f"{year}-01-01",
                    end_date=f"{year}-12-31",
                )
            )
            request["contractual"]["aggregate_amortisation"].append(
                dict(
                    case=case,
                    period_id=period_id,
                    start_date=f"{year}-07-01" if year == 2026 else f"{year}-01-01",
                    end_date=f"{year}-12-31",
                    amount=str(principal),
                )
            )
            request["drivers"].append(
                dict(
                    case=case,
                    period_id=period_id,
                    status="READY",
                    revenue="5000",
                    ebitda="2000",
                    cfo="1800",
                    capex="400",
                    cash_interest="738",
                    cash_taxes="50",
                    distributions="82",
                    issuance="0",
                    optional_repayment="0",
                    acquisitions_disposals="0",
                    pik="0",
                    capitalised_interest="0",
                    fx_perimeter="0",
                    net_equity_issue_repay="0",
                    other_investing_financing="-24",
                    restricted_cash_change="15" if year == 2026 else "0",
                    carrying_value_change="26",
                    stated_closing_cash=str(cash),
                    stated_closing_debt=str(debt),
                )
            )
    return request, regs


def _model() -> CreditModel:
    request, regs = owned_inputs()
    return credit_model(
        ModelInputs(regs, request, example_growth(), example_slots(), None)
    )


def _rename_forecast_periods(
    request: dict[str, Any], suffix: str, all_periods: bool
) -> None:
    for rows in (
        request["periods"],
        request["drivers"],
        request["contractual"]["aggregate_amortisation"],
        request["actuals"]["debt_cash_movements"],
    ):
        for row in rows:
            if all_periods or row["period_id"] == "FY26":
                row["period_id"] += suffix


@pytest.mark.parametrize("suffix", ["-cafe\u0301", "-caf\u00e9"], ids=["NFD", "NFC"])
@pytest.mark.parametrize("all_periods", [False, True], ids=["first", "all"])
def test_owned_normalized_period_lookup_preserves_request_identity(
    suffix: str, all_periods: bool
) -> None:
    request, regs = owned_inputs()
    baseline = credit_model(ModelInputs(regs, request, (), (), None))
    _rename_forecast_periods(request, suffix, all_periods)
    original = json.dumps(request, ensure_ascii=False).encode("utf-8")
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    assert result["rows"][0]["period_id"] == "FY26-caf\u00e9"
    model = credit_model(ModelInputs(regs, request, (), (), None))
    assert reconciliation_faults(model) == ()
    # Every cell, expectation and note remains equal; only raw column IDs differ.
    assert replace(model, columns=baseline.columns) == baseline
    projected = [column for column in model.columns if column.kind == "PROJECTED"]
    assert [column.period_id for column in projected] == [
        row["period_id"] for row in request["periods"]
    ]
    for case in ("BASE", "DOWNSIDE"):
        for year, debt_cash, ncf, cash, debt in (
            (2026, -153, 353, 1225, 11657),
            (2027, -114, 392, 1617, 11569),
            (2028, -767, -261, 1356, 10828),
        ):
            for key, value in zip(
                (
                    "cash_interest",
                    "fcf",
                    "debt_raised_net",
                    "ncf",
                    "cash_closing",
                    "debt_closing",
                ),
                (-738, 612, debt_cash, ncf, cash, debt),
                strict=True,
            ):
                assert _cell(model, key, f"{case}:{year}").value == value
    # Original scalar spellings remain available for exact owner assignment quotes.
    assert request["periods"][0]["period_id"] == "FY26" + suffix
    assert request["drivers"][0]["period_id"] == "FY26" + suffix
    assert (
        request["contractual"]["aggregate_amortisation"][0]["period_id"]
        == "FY26" + suffix
    )
    assert request["actuals"]["debt_cash_movements"][0]["period_id"] == "FY26" + suffix
    assert json.dumps(request, ensure_ascii=False).encode("utf-8") == original


@pytest.mark.parametrize("collection", ["periods", "drivers", "aggregate_amortisation"])
def test_owned_normalized_duplicate_period_pairs_remain_refused(
    collection: str,
) -> None:
    request, regs = owned_inputs()
    _rename_forecast_periods(request, "-cafe\u0301", True)
    rows = (
        request["contractual"][collection]
        if collection == "aggregate_amortisation"
        else request[collection]
    )
    rows.append({**rows[0], "period_id": normalize("NFC", rows[0]["period_id"])})
    with pytest.raises(Refusal) as cash_error:
        cash_flow_forecast(request)
    assert cash_error.value.code == RefusalCode.METHODOLOGY_INPUT_INVALID
    with pytest.raises(Refusal) as model_error:
        credit_model(ModelInputs(regs, request, (), (), None))
    assert model_error.value.code == RefusalCode.HANDOFF_MALFORMED


def test_owned_primary_totals_match_independent_cash_request_without_native_rate() -> (
    None
):
    request, regs = owned_inputs()
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    model = credit_model(ModelInputs(regs, request, (), (), None))
    assert reconciliation_faults(model) == ()
    expected = {
        "cash_interest": -738,
        "fcf": 612,
        "debt_raised_net": -153,
        "ncf": 353,
        "cash_opening": 887,
        "cash_closing": 1225,
        "debt_opening": 11784,
        "debt_closing": 11657,
        "debt_non_cash": 26,
        "debt:unallocated": 11657,
        "contractual_repayment": -55,
        "actual_debt_cash_movement": -98,
    }
    for key, value in expected.items():
        assert _cell(model, key, "BASE:2026").value == value, key
    for case in ("BASE", "DOWNSIDE"):
        for year, debt in ((2026, 11657), (2027, 11569), (2028, 10828)):
            col = f"{case}:{year}"
            assert _cell(model, "debt_closing", col).value == debt
            assert _cell(model, "actual_debt_cash_movement", col).value == (
                -98 if year == 2026 else 0
            )
            row = next(
                r
                for r in result["rows"]
                if r["case"] == case and r["fiscal_year"] == str(year)
            )
            assert _cell(model, "cash_closing", col).value == Decimal(
                row["cash"]["closing"]
            )
            assert not any(
                "assumed refinanced"
                in (
                    line.cells[[c.column_id for c in model.columns].index(col)].note
                    or ""
                )
                for line in model.lines
            )
    assert (
        _cell(model, "metric:interest_coverage_adjusted", "BASE:2026").value is not None
    )
    assert "Cash debt-service basis" in (
        _cell(model, "metric:interest_coverage_adjusted", "BASE:2026").note or ""
    )


@pytest.mark.parametrize(
    "key",
    [
        "fac:tlb",
        "secured_debt",
        "metric:senior_secured_leverage",
        "metric:senior_secured_net_leverage",
        "undrawn_rcf",
        "liquidity",
        "wa_rate",
        "reference_rate",
        "interest_bearing_debt_opening",
    ],
)
def test_owned_diagnostics_are_explicitly_unprojected(key: str) -> None:
    cell = _cell(_model(), key, "BASE:2026")
    assert cell.value is None
    assert cell.reason == "NOT_PROJECTED"
    assert (
        cell.note
        == "Aggregate cash debt-service forecast. Instrument allocation not supplied"
    )


@pytest.mark.parametrize(
    "key",
    [
        "cash_interest",
        "cash_closing",
        "debt_opening",
        "debt_non_cash",
        "fcf",
        "ncf",
        "debt:unallocated",
        "contractual_repayment",
        "actual_debt_cash_movement",
    ],
)
def test_owned_reconciliation_rejects_primary_perturbation(key: str) -> None:
    model = _model()
    before = _cell(model, key, "BASE:2026")
    assert before.value is not None
    changed = _with_cell(
        model, key, "BASE:2026", replace(before, value=before.value + 1)
    )
    assert "BASE:2026:owned_inputs" in reconciliation_faults(changed)


def test_owned_rejects_coordinated_interest_cash_and_missing_expectations() -> None:
    model = _model()
    changed = _with_cell(model, "cash_interest", "BASE:2026", Cell(Decimal(-737)))
    changed = _with_cell(changed, "cash_closing", "BASE:2026", Cell(Decimal(1226)))
    assert "BASE:2026:owned_inputs" in reconciliation_faults(changed)
    assert "BASE:2026:owned_inputs" in reconciliation_faults(
        replace(model, owned_checks=())
    )


@pytest.mark.parametrize("basis", [None, "OTHER"])
@pytest.mark.parametrize("remove_memos", [False, True])
def test_owned_expected_records_require_selected_basis(
    basis: str | None, remove_memos: bool
) -> None:
    model = _model()
    changed = replace(
        model,
        projection_basis=cast(Any, basis),
        lines=tuple(
            line
            for line in model.lines
            if not remove_memos
            or line.line_id
            not in {"contractual_repayment", "actual_debt_cash_movement"}
        ),
    )
    assert reconciliation_faults(changed) == tuple(
        f"{column.column_id}:owned_inputs"
        for column in model.columns
        if column.kind == "PROJECTED"
    )


@pytest.mark.parametrize("basis", [None, "OTHER"])
@pytest.mark.parametrize(
    "removed_memo", [None, "contractual_repayment", "actual_debt_cash_movement"]
)
def test_owned_memos_require_selected_basis_without_expected_records(
    basis: str | None, removed_memo: str | None
) -> None:
    model = _model()
    changed = replace(
        model,
        projection_basis=cast(Any, basis),
        owned_checks=(),
        lines=tuple(line for line in model.lines if line.line_id != removed_memo),
    )
    assert reconciliation_faults(changed) == tuple(
        f"{column.column_id}:owned_inputs"
        for column in model.columns
        if column.kind == "PROJECTED"
    )


def test_owned_guard_preserves_legacy_constructor_and_ignores_notes() -> None:
    model = _legacy_model()
    legacy = CreditModel(
        model.currency,
        model.unit,
        model.columns,
        model.lines,
        model.rate_deck_id,
        model.limitations,
    )
    assert legacy == model
    assert legacy.projection_basis is None
    assert legacy.owned_checks == ()
    assert not {"contractual_repayment", "actual_debt_cash_movement"}.intersection(
        line.line_id for line in legacy.lines
    )
    assert reconciliation_faults(legacy) == ()
    changed = _with_cell(
        legacy,
        "cash_interest",
        "BASE:2026",
        replace(
            _cell(legacy, "cash_interest", "BASE:2026"),
            note="Cash debt-service basis: accepted CP-CF aggregate forecast",
        ),
    )
    assert reconciliation_faults(changed) == ()


@pytest.mark.parametrize(
    "key",
    [
        "secured_debt",
        "wa_rate",
        "fac:tlb",
        "liquidity",
        "metric:senior_secured_leverage",
    ],
)
def test_owned_reconciliation_rejects_numeric_diagnostics(key: str) -> None:
    changed = _with_cell(_model(), key, "BASE:2026", Cell(Decimal(1)))
    assert "BASE:2026:owned_diagnostics" in reconciliation_faults(changed)


def test_owned_decimal_isolation_and_owner_refusal() -> None:
    expected = _model()
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert _model() == expected
        assert reconciliation_faults(expected) == ()
    request, regs = owned_inputs()
    request["actuals"]["debt_cash_movements"][0]["amount"] = "98"
    with pytest.raises(Refusal):
        projection(ProjectionInputs(regs, request, (), (), None, {}))


def test_owned_reconciliation_rejects_truncated_expected_record() -> None:
    model = _model()
    first = model.owned_checks[0]
    truncated = replace(first, values=first.values[:1])
    changed = replace(model, owned_checks=(truncated, *model.owned_checks[1:]))
    assert "BASE:2026:owned_inputs" in reconciliation_faults(changed)


def test_owned_direct_projection_numeric_cells_have_no_missing_reason() -> None:
    request, regs = owned_inputs()
    _, frame = projection(ProjectionInputs(regs, request, (), (), None, {}))
    for cells in frame.values():
        for key, cell in cells.items():
            if cell.value is not None:
                assert cell.reason is None, key


def test_owned_negative_cash_is_not_fabricated_liquidity() -> None:
    request, regs = owned_inputs()
    for driver in request["drivers"]:
        index = int(driver["period_id"][-2:]) - 25
        driver["cfo"] = "0"
        driver["stated_closing_cash"] = str(
            Decimal(driver["stated_closing_cash"]) - 1800 * index
        )
    model = credit_model(ModelInputs(regs, request, (), (), None))
    assert _cell(model, "cash_closing", "BASE:2026").value == -575
    assert _cell(model, "liquidity", "BASE:2026").value is None
    assert reconciliation_faults(model) == ()


def test_owned_history_and_terms_remain_legacy() -> None:
    request, regs = owned_inputs()
    selected = credit_model(ModelInputs(regs, request, (), (), None))
    legacy = credit_model(ModelInputs(regs, None, (), (), None))
    for line in legacy.lines:
        matched = next(row for row in selected.lines if row.line_id == line.line_id)
        assert matched.terms == line.terms
        assert matched.cells[: len(legacy.columns)] == line.cells


def test_owned_incomplete_cash_result_refuses() -> None:
    request, regs = owned_inputs()
    request["drivers"][0]["stated_closing_cash"] = "0"
    with pytest.raises(Refusal):
        credit_model(ModelInputs(regs, request, (), (), None))


def test_owned_layout_retains_band_order() -> None:
    from caos.calculators.credit_model.layout import BANDS

    positions = [BANDS.index(line.band) for line in _model().lines]
    assert positions == sorted(positions)


def test_owned_never_calls_native_schedule_or_interest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caos.calculators.credit_model import projection as module

    def unexpected(*args: object) -> None:
        raise AssertionError

    monkeypatch.setattr(module, "_schedule", unexpected)
    monkeypatch.setattr(module, "_interest", unexpected)
    assert reconciliation_faults(_model()) == ()


def test_owned_rank_subtotals_are_not_allocated() -> None:
    request, regs = owned_inputs()
    loan, cost = regs.facilities
    facilities = (
        replace(loan, carrying_value=Decimal(5900)),
        replace(loan, facility_id="second", carrying_value=Decimal(5892)),
        cost,
    )
    regs = replace(regs, facilities=facilities)
    request["opening"]["debt_by_facility"] = [
        {"facility_id": r.facility_id, "amount": str(r.carrying_value)}
        for r in facilities
    ]
    model = credit_model(ModelInputs(regs, request, (), (), None))
    cell = _cell(model, "rank:Senior secured", "BASE:2026")
    assert cell.value is None
    assert cell.reason == "NOT_PROJECTED"
    assert (
        cell.note
        == "Aggregate cash debt-service forecast. Instrument allocation not supplied"
    )
    assert reconciliation_faults(model) == ()


def test_owned_expected_records_are_frozen_independent_of_input_mutation() -> None:
    from dataclasses import FrozenInstanceError

    request, regs = owned_inputs()
    model = credit_model(ModelInputs(regs, request, (), (), None))
    first = model.owned_checks[0]
    with pytest.raises(FrozenInstanceError):
        first.__setattr__("column_id", "bad")
    request["drivers"][0]["cash_interest"] = "1"
    assert dict(first.values)["cash_interest"] == -738
    assert reconciliation_faults(model) == ()
    wrong = replace(
        first,
        values=tuple(
            (key, value + 1 if key == "cash_interest" else value)
            for key, value in first.values
        ),
    )
    assert "BASE:2026:owned_inputs" in reconciliation_faults(
        replace(model, owned_checks=(wrong, *model.owned_checks[1:]))
    )
