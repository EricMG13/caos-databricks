"""Credit metrics on every column: leverage and coverage on a 12-month basis,
cash flow and liquidity ratios, margins and like-period growth."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest
from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_request,
    example_slots,
)

from caos.calculators.credit_model._cells import CONTEXT, refs
from caos.calculators.credit_model.frame import Cell, Column, Frame, SourceRef
from caos.calculators.credit_model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from caos.calculators.credit_model.metrics import metric_frame, unit_of
from caos.calculators.credit_model.projection import ProjectionInputs, projection
from caos.calculators.credit_model.statements import (
    pro_forma_column,
    statement_frame,
)
from caos.methodology.model_inputs import Cp1Registers

_CORPORATE = frozenset({"corporate_eliminations"})
_LEVERAGE = (
    "total_leverage_reported",
    "total_leverage_adjusted",
    "net_leverage_reported",
    "net_leverage_adjusted",
    "senior_secured_leverage",
    "senior_secured_net_leverage",
    "lease_adjusted_leverage",
    "lease_adjusted_net_leverage",
)
_COVERAGE = (
    "interest_coverage_reported",
    "interest_coverage_adjusted",
    "capex_adjusted_coverage",
    "ebitdar_coverage",
)
_PERCENT = (
    "ffo_to_debt",
    "ffo_to_lease_adjusted_debt",
    "fcf_to_debt",
    "fcf_to_adjusted_ebitda",
    "capex_to_revenue",
    "liquidity_to_debt",
    "gross_margin",
    "ebitda_margin",
    "adjusted_ebitda_margin",
)


def _model(
    regs: Cp1Registers | None = None,
) -> tuple[tuple[Column, ...], Frame, Frame]:
    """Every column of the example: history, the PF-LTM and the projections;
    their frame; and the statements of the LTM ending each quarter."""
    regs = regs or example_registers()
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    quarters = tuple(c for c in columns if c.kind == "QUARTER")
    ltm_ending = statement_frame(ltm_frames(regs, columns), quarters, regs)
    ltm = next(c for c in columns if c.kind == "LTM")
    pro_forma = pro_forma_column(regs, ltm, frame)
    assert pro_forma is not None
    pf_column, pf_frame = pro_forma
    projected, projected_frame = projection(
        ProjectionInputs(
            regs=regs,
            request=example_request(),
            growth=example_growth(),
            slots=example_slots(),
            deck=example_deck(),
            history=frame,
        )
    )
    every = (*columns, pf_column, *projected)
    return every, {**frame, **pf_frame, **projected_frame}, ltm_ending


def _metrics() -> tuple[Frame, Frame, Frame]:
    columns, frame, ltm_ending = _model()
    result = metric_frame(columns, frame, ltm_ending, corporate=_CORPORATE)
    return result, frame, ltm_ending


def _div(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return numerator / denominator


def _rise(current: Decimal, prior: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return current / prior - 1


def _v(cells: dict[str, Cell], key: str) -> Decimal:
    value = cells[key].value
    assert value is not None, key
    return value


def _fy(column_id: str, end: str, fiscal_year: str = "FY2025") -> Column:
    return Column(column_id, "FY", column_id, column_id, fiscal_year, end, 365, None)


_SOURCE_A = SourceRef("S1", "10-K", "100")
_SOURCE_B = SourceRef("S2", "10-Q", "200")


def _cells(**values: str) -> dict[str, Cell]:
    return {
        key: Cell(Decimal(value), basis="REPORTED", sources=(_SOURCE_A,))
        for key, value in values.items()
    }


def test_quarter_leverage_uses_the_ltm_ending_that_quarter() -> None:
    result, frame, ltm_ending = _metrics()
    quarter = result["Q:Q2_2026"]
    ltm = ltm_ending["Q:Q2_2026"]
    # LTM to Q2 2026: adjusted EBITDA 4,089 (the quarter alone is 1,053) and
    # the host's total debt at 30 June 2026, 14,106.
    assert _v(ltm, "adjusted_ebitda") == 4089
    assert _v(frame["Q:Q2_2026"], "adjusted_ebitda") == 1053
    expected = _div(Decimal(14106), Decimal(4089))
    assert quarter["metric:total_leverage_adjusted"] == Cell(
        expected,
        basis="CALCULATED",
        sources=quarter["metric:total_leverage_adjusted"].sources,
    )
    assert result["LTM:LTM_Q2_2026"]["metric:total_leverage_adjusted"].value == (
        expected
    )
    coverage = quarter["metric:interest_coverage_adjusted"].value
    assert coverage == _div(Decimal(4089), -_v(ltm, "cash_interest"))
    # Margins stay on the quarter's own period.
    own = frame["Q:Q2_2026"]
    assert quarter["metric:adjusted_ebitda_margin"].value == _div(
        Decimal(1053), _v(own, "revenue")
    )
    # Same-period flow ratios are on the quarter's own period too; a ratio
    # against a balance is on its twelve months.
    assert quarter["metric:capex_to_revenue"].value == _div(
        -_v(own, "capex"), _v(own, "revenue")
    )
    assert quarter["metric:fcf_to_adjusted_ebitda"].value == _div(
        _v(own, "fcf"), Decimal(1053)
    )
    assert quarter["metric:fcf_to_debt"].value == _div(
        _v(ltm, "fcf"), _v(ltm, "total_debt")
    )
    assert quarter["metric:liquidity_to_debt"].value == _div(
        _v(ltm, "liquidity"), _v(ltm, "total_debt")
    )
    # The first quarters have no four to sum: the LTM's reason carries.
    first = result["Q:Q1_2024"]["metric:total_leverage_adjusted"]
    assert first == Cell(None, "COMPONENT_MISSING")


def test_ytd_leverage_is_not_applicable() -> None:
    result, frame, _ = _metrics()
    for column_id in ("YTD:H1_2026", "PYTD:H1_2025"):
        cells = result[column_id]
        for name in (*_LEVERAGE, *_COVERAGE, "ffo_to_debt", "fcf_to_debt"):
            assert cells[f"metric:{name}"] == Cell(None, "NOT_APPLICABLE"), name
        assert cells["metric:ffo_to_lease_adjusted_debt"].reason == "NOT_APPLICABLE"
        own = frame[column_id]
        assert cells["metric:gross_margin"].value == _div(
            _v(own, "gross_profit"), _v(own, "revenue")
        )
        assert cells["metric:fcf_to_adjusted_ebitda"].value == _div(
            _v(own, "fcf"), _v(own, "adjusted_ebitda")
        )
        assert cells["metric:liquidity_to_debt"].value == _div(
            _v(own, "liquidity"), _v(own, "total_debt")
        )


def test_each_metric_has_reported_and_adjusted_variants_where_named() -> None:
    result, frame, _ = _metrics()
    ltm = frame["LTM:LTM_Q2_2026"]
    cells = result["LTM:LTM_Q2_2026"]
    debt, cash = _v(ltm, "total_debt"), _v(ltm, "cash_closing")
    ebitda, adjusted = _v(ltm, "ebitda"), _v(ltm, "adjusted_ebitda")
    ebitdar, secured = _v(ltm, "adjusted_ebitdar"), _v(ltm, "secured_debt")
    interest, capex = -_v(ltm, "cash_interest"), _v(ltm, "capex")
    lease_cost, revenue = _v(ltm, "operating_lease_cost"), _v(ltm, "revenue")
    leased = _v(ltm, "lease_adjusted_debt")
    expected = {
        "total_leverage_reported": _div(debt, ebitda),
        "total_leverage_adjusted": _div(debt, adjusted),
        "net_leverage_reported": _div(debt - cash, ebitda),
        "net_leverage_adjusted": _div(debt - cash, adjusted),
        "senior_secured_leverage": _div(secured, adjusted),
        "senior_secured_net_leverage": _div(secured - cash, adjusted),
        "lease_adjusted_leverage": _div(leased, ebitdar),
        "lease_adjusted_net_leverage": _div(
            _v(ltm, "lease_adjusted_net_debt"), ebitdar
        ),
        "interest_coverage_reported": _div(ebitda, interest),
        "interest_coverage_adjusted": _div(adjusted, interest),
        "capex_adjusted_coverage": _div(adjusted + capex, interest),
        "ebitdar_coverage": _div(ebitdar + capex, interest - lease_cost),
        "ffo_to_debt": _div(_v(ltm, "ffo"), debt),
        "ffo_to_lease_adjusted_debt": _div(_v(ltm, "ffo"), leased),
        "fcf_to_debt": _div(_v(ltm, "fcf"), debt),
        "fcf_to_adjusted_ebitda": _div(_v(ltm, "fcf"), adjusted),
        "capex_to_revenue": _div(-capex, revenue),
        "liquidity_to_debt": _div(_v(ltm, "liquidity"), debt),
        "gross_margin": _div(_v(ltm, "gross_profit"), revenue),
        "ebitda_margin": _div(ebitda, revenue),
        "adjusted_ebitda_margin": _div(adjusted, revenue),
    }
    assert {key: cells[f"metric:{key}"].value for key in expected} == expected
    assert all(cells[f"metric:{key}"].basis == "CALCULATED" for key in expected)
    assert cells["metric:total_leverage_reported"].value != (
        cells["metric:total_leverage_adjusted"].value
    )
    # Reported EBITDA and lease balances are not projected; adjusted is.
    base = result["BASE:2026"]
    for name in (
        "total_leverage_reported",
        "net_leverage_reported",
        "interest_coverage_reported",
        "lease_adjusted_leverage",
        "lease_adjusted_net_leverage",
        "ebitdar_coverage",
        "ffo_to_debt",
        "ffo_to_lease_adjusted_debt",
        "gross_margin",
        "ebitda_margin",
    ):
        assert base[f"metric:{name}"] == Cell(None, "NOT_PROJECTED"), name
    projected = frame["BASE:2026"]
    assert base["metric:total_leverage_adjusted"].value == _div(
        _v(projected, "total_debt"), _v(projected, "adjusted_ebitda")
    )
    assert base["metric:senior_secured_net_leverage"].value == _div(
        _v(projected, "secured_debt") - _v(projected, "cash_closing"),
        _v(projected, "adjusted_ebitda"),
    )
    assert base["metric:capex_adjusted_coverage"].value == _div(
        _v(projected, "adjusted_ebitda") + _v(projected, "capex"),
        -_v(projected, "cash_interest"),
    )


def test_units_are_multiples_for_leverage_and_coverage() -> None:
    for name in (*_LEVERAGE, *_COVERAGE):
        assert unit_of(f"metric:{name}") == "MULTIPLE"
    for name in _PERCENT:
        assert unit_of(f"metric:{name}") == "PERCENT"
    for key in ("revenue_growth", "adjusted_ebitda_growth", "bu_growth:digital"):
        assert unit_of(key) == "PERCENT"
    with pytest.raises(KeyError):
        unit_of("metric:unknown")
    with pytest.raises(KeyError, match="revenue"):
        unit_of("revenue")


def test_every_column_carries_every_metric_and_keeps_its_cells() -> None:
    columns, frame, ltm_ending = _model()
    result = metric_frame(columns, frame, ltm_ending)
    assert set(result) == {c.column_id for c in columns}
    names = {f"metric:{n}" for n in (*_LEVERAGE, *_COVERAGE, *_PERCENT)}
    for column in columns:
        cells = result[column.column_id]
        assert names <= set(cells)
        assert {k: cells[k] for k in frame[column.column_id]} == (
            frame[column.column_id]
        )
    # Without `corporate`, every segment is compared: eliminations are
    # negative, so the denominator refuses.
    eliminations = result["FY:FY2025"]["bu_growth:corporate_eliminations"]
    assert eliminations == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")


def test_a_non_positive_denominator_is_zero_or_negative() -> None:
    column = _fy("FY:A", "2025-12-31")
    base = _cells(
        total_debt="500",
        cash_closing="100",
        secured_debt="300",
        ebitda="0",
        adjusted_ebitda="-10",
        cash_interest="0",
        operating_lease_cost="0",
        revenue="0",
        capex="-5",
    )
    cells = metric_frame((column,), {"FY:A": base}, {})["FY:A"]
    for name in (
        "total_leverage_reported",
        "total_leverage_adjusted",
        "senior_secured_leverage",
        "interest_coverage_reported",
        "capex_adjusted_coverage",
        "capex_to_revenue",
        "adjusted_ebitda_margin",
    ):
        assert cells[f"metric:{name}"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    # A missing input carries its own reason, the first in formula order.
    assert cells["metric:lease_adjusted_leverage"] == Cell(None, "NOT_SOURCED")
    assert cells["metric:ebitdar_coverage"] == Cell(None, "NOT_SOURCED")
    # A positive denominator is a ratio, sourced once per source.
    positive = {
        **base,
        "ebitda": Cell(Decimal("0.5"), sources=(_SOURCE_B, _SOURCE_A)),
        "cash_interest": Cell(Decimal("-0.25")),
    }
    cells = metric_frame((column,), {"FY:A": positive}, {})["FY:A"]
    assert cells["metric:total_leverage_reported"] == Cell(
        Decimal(1000), basis="CALCULATED", sources=(_SOURCE_A, _SOURCE_B)
    )
    assert cells["metric:interest_coverage_reported"].value == 2
    assert cells["metric:net_leverage_reported"].value == 800


def test_a_missing_input_gives_its_reason_first_in_formula_order() -> None:
    column = _fy("FY:A", "2025-12-31")
    cells = {
        **_cells(total_debt="500", cash_closing="100", revenue="10"),
        "ebitda": Cell(None, "NOT_STATED"),
        "secured_debt": Cell(None, "COMPONENT_MISSING"),
        "adjusted_ebitda": Cell(None, "NOT_APPLICABLE"),
        "cash_interest": Cell(Decimal(-5)),
    }
    out = metric_frame((column,), {"FY:A": cells}, {})["FY:A"]
    assert out["metric:total_leverage_reported"] == Cell(None, "NOT_STATED")
    assert out["metric:senior_secured_leverage"] == Cell(None, "COMPONENT_MISSING")
    assert out["metric:senior_secured_net_leverage"] == Cell(None, "COMPONENT_MISSING")
    assert out["metric:total_leverage_adjusted"] == Cell(None, "NOT_APPLICABLE")
    # The numerator's reason before the denominator's.
    assert out["metric:interest_coverage_reported"] == Cell(None, "NOT_STATED")
    assert out["metric:fcf_to_debt"] == Cell(None, "NOT_SOURCED")


def test_growth_compares_like_periods() -> None:
    result, frame, _ = _metrics()

    def growth(column_id: str, prior_id: str, key: str) -> Decimal:
        return _rise(_v(frame[column_id], key), _v(frame[prior_id], key))

    assert result["Q:Q2_2026"]["revenue_growth"] == Cell(
        _rise(Decimal(3008), Decimal(2940)),
        basis="CALCULATED",
        sources=refs(
            [
                *frame["Q:Q2_2026"]["revenue"].sources,
                *frame["Q:Q2_2025"]["revenue"].sources,
            ]
        ),
    )
    assert result["YTD:H1_2026"]["revenue_growth"].value == growth(
        "YTD:H1_2026", "PYTD:H1_2025", "revenue"
    )
    assert result["FY:FY2025"]["adjusted_ebitda_growth"].value == growth(
        "FY:FY2025", "FY:FY2024", "adjusted_ebitda"
    )
    assert result["FY:FY2025"]["bu_growth:regional"].value == growth(
        "FY:FY2025", "FY:FY2024", "bu:regional"
    )
    # A projection against the last FY, then its own case's prior year.
    assert result["BASE:2026"]["bu_growth:las_vegas"].value == Decimal("0.025")
    assert result["DOWNSIDE:2026"]["bu_growth:las_vegas"].value == Decimal("-0.06")
    assert result["BASE:2027"]["bu_growth:regional"].value == Decimal("0.015")
    assert result["BASE:2026"]["bu_growth:managed_other"].value == 0
    assert result["BASE:2027"]["revenue_growth"].value == growth(
        "BASE:2027", "BASE:2026", "revenue"
    )
    assert result["DOWNSIDE:2027"]["adjusted_ebitda_growth"].value == growth(
        "DOWNSIDE:2027", "DOWNSIDE:2026", "adjusted_ebitda"
    )
    # No prior, or no like period: not applicable.
    na = Cell(None, "NOT_APPLICABLE")
    for column_id in (
        "Q:Q1_2024",
        "FY:FY2023",
        "PYTD:H1_2025",
        "PF:LTM_Q2_2026",
    ):
        assert result[column_id]["revenue_growth"] == na, column_id
        assert result[column_id]["adjusted_ebitda_growth"] == na, column_id
    assert result["FY:FY2025"]["bu_growth:corporate_eliminations"] == na
    assert result["BASE:2026"]["bu_growth:corporate_eliminations"] == na
    # The LTM against the LTM ending a year earlier, at Q2 2025: revenue
    # 2,807 + 2,783 + 2,810 + 2,940, adjusted EBITDA 973 + 965 + 975 + 1,017
    # and Las Vegas 1,000 + 1,020 + 1,040 + 1,092.
    ltm = result["LTM:LTM_Q2_2026"]
    assert ltm["revenue_growth"].value == _rise(Decimal(11654), Decimal(11340))
    assert ltm["adjusted_ebitda_growth"].value == _rise(Decimal(4089), Decimal(3930))
    assert ltm["bu_growth:las_vegas"].value == _rise(Decimal(4256), Decimal(4152))
    assert ltm["bu_growth:corporate_eliminations"] == na


def test_growth_takes_a_like_period_within_a_week_of_a_year_earlier() -> None:
    now = _fy("FY:B", "2025-12-31", "FY2025")
    cells = {"FY:B": _cells(revenue="110", adjusted_ebitda="0")}
    for end, found in (
        ("2024-12-24", True),  # 372 days
        ("2024-12-23", False),  # 373
        ("2025-01-07", True),  # 358
        ("2025-01-08", False),  # 357
    ):
        prior = _fy("FY:A", end, "FY2024")
        frame = {**cells, "FY:A": _cells(revenue="100", adjusted_ebitda="-1")}
        out = metric_frame((now, prior), frame, {})["FY:B"]
        if found:
            assert out["revenue_growth"].value == Decimal("0.1"), end
            assert out["adjusted_ebitda_growth"] == Cell(
                None, "ZERO_OR_NEGATIVE_DENOMINATOR"
            )
        else:
            assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE"), end
    # Another kind is never the like period; a missing figure carries.
    quarter = replace(_fy("Q:A", "2024-12-31", "FY2024"), kind="QUARTER")
    frame = {**cells, "Q:A": _cells(revenue="100")}
    out = metric_frame((now, quarter), frame, {"Q:A": {}})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    prior = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {**cells, "FY:A": {"revenue": Cell(None, "NOT_STATED")}}
    out = metric_frame((now, prior), frame, {})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_STATED")
    assert out["adjusted_ebitda_growth"] == Cell(None, "NOT_SOURCED")
    # Without an end date there is no like period.
    undated = replace(now, end_date=None)
    out = metric_frame((undated, prior), frame, {})["FY:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")


def test_projected_growth_needs_a_four_digit_year() -> None:
    projected = Column("BASE:X", "PROJECTED", "X", "X", "FYX", None, 365, "BASE")
    fiscal = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {"BASE:X": _cells(revenue="110"), "FY:A": _cells(revenue="100")}
    out = metric_frame((projected, fiscal), frame, {})["BASE:X"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    # The other case's prior year is never the prior.
    later = replace(projected, column_id="BASE:2026", fiscal_year="2026")
    other = replace(projected, column_id="DOWNSIDE:2025", fiscal_year="2025")
    other = replace(other, case="DOWNSIDE")
    frame = {"BASE:2026": _cells(revenue="110"), "DOWNSIDE:2025": _cells(revenue="1")}
    out = metric_frame((later, other), frame, {})["BASE:2026"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")


def test_pf_leverage_uses_pf_debt_and_pf_ebitda() -> None:
    result, frame, _ = _metrics()
    pf = frame["PF:LTM_Q2_2026"]
    # The $600m add-on notes and Silverlake's 45 of adjusted EBITDA.
    assert _v(pf, "total_debt") == 14106 + 600
    assert _v(pf, "adjusted_ebitda") == 4089 + 45
    cells = result["PF:LTM_Q2_2026"]
    assert cells["metric:total_leverage_adjusted"].value == _div(
        Decimal(14706), Decimal(4134)
    )
    assert cells["metric:senior_secured_leverage"].value == _div(
        _v(pf, "secured_debt"), Decimal(4134)
    )
    assert cells["metric:interest_coverage_adjusted"].value == _div(
        Decimal(4134), -_v(pf, "cash_interest")
    )
    assert cells["metric:total_leverage_adjusted"].value != (
        result["LTM:LTM_Q2_2026"]["metric:total_leverage_adjusted"].value
    )
    # The waterfall below cash interest has no pro forma meaning.
    assert cells["metric:ffo_to_debt"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:capex_adjusted_coverage"] == Cell(None, "NOT_APPLICABLE")


def test_pf_reported_ebitda_variants_are_not_applicable() -> None:
    result, frame, _ = _metrics()
    cells = result["PF:LTM_Q2_2026"]
    assert frame["PF:LTM_Q2_2026"]["ebitda"].value is not None
    for name in (
        "total_leverage_reported",
        "net_leverage_reported",
        "interest_coverage_reported",
    ):
        assert cells[f"metric:{name}"] == Cell(None, "NOT_APPLICABLE"), name
        assert result["LTM:LTM_Q2_2026"][f"metric:{name}"].value is not None
    # Acquired EBITDA over unadjusted revenue is no margin; gross margin is.
    pf = frame["PF:LTM_Q2_2026"]
    assert cells["metric:ebitda_margin"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:adjusted_ebitda_margin"] == Cell(None, "NOT_APPLICABLE")
    assert cells["metric:gross_margin"].value == _div(
        _v(pf, "gross_profit"), _v(pf, "revenue")
    )


def test_pf_margins_with_a_revenue_adjustment() -> None:
    regs = example_registers()
    revenue = replace(
        regs.pro_forma[0],
        adjustment_id="silverlake_revenue",
        metric_id="revenue",
        value=Decimal(300),
    )
    regs = replace(regs, pro_forma=(*regs.pro_forma, revenue))
    columns, frame, ltm_ending = _model(regs)
    cells = metric_frame(columns, frame, ltm_ending)["PF:LTM_Q2_2026"]
    pf = frame["PF:LTM_Q2_2026"]
    assert _v(pf, "revenue") == 11654 + 300
    assert cells["metric:adjusted_ebitda_margin"].value == _div(
        Decimal(4134), Decimal(11954)
    )
    assert cells["metric:ebitda_margin"].value == _div(_v(pf, "ebitda"), Decimal(11954))
    # The reported-EBITDA variants stay not applicable.
    assert cells["metric:total_leverage_reported"] == Cell(None, "NOT_APPLICABLE")


def test_lease_adjusted_metrics_read_the_lease_balances() -> None:
    column = _fy("FY:A", "2025-12-31")
    cells = _cells(
        total_debt="500",
        lease_adjusted_debt="600",
        lease_adjusted_net_debt="500",
        cash_closing="100",
        ffo="60",
        adjusted_ebitda="100",
        adjusted_ebitdar="150",
    )
    out = metric_frame((column,), {"FY:A": cells}, {})["FY:A"]
    assert out["metric:ffo_to_debt"].value == Decimal("0.12")
    assert out["metric:ffo_to_lease_adjusted_debt"].value == Decimal("0.1")
    assert out["metric:total_leverage_adjusted"].value == 5
    assert out["metric:lease_adjusted_leverage"].value == 4
    assert out["metric:lease_adjusted_net_leverage"].value == _div(
        Decimal(500), Decimal(150)
    )


def test_corporate_names_only_segments() -> None:
    column = _fy("FY:B", "2025-12-31", "FY2025")
    prior = _fy("FY:A", "2024-12-31", "FY2024")
    frame = {
        "FY:B": _cells(revenue="110", adjusted_ebitda="22", **{"bu:revenue": "55"}),
        "FY:A": _cells(revenue="100", adjusted_ebitda="20", **{"bu:revenue": "50"}),
    }
    corporate = frozenset({"revenue", "adjusted_ebitda"})
    out = metric_frame((column, prior), frame, {}, corporate=corporate)["FY:B"]
    assert out["revenue_growth"].value == Decimal("0.1")
    assert out["adjusted_ebitda_growth"].value == Decimal("0.1")
    assert out["bu_growth:revenue"] == Cell(None, "NOT_APPLICABLE")


def test_ltm_growth_reads_the_ltm_ending_a_year_earlier() -> None:
    ltm = replace(_fy("LTM:B", "2025-12-31", "FY2025"), kind="LTM")
    frame = {"LTM:B": _cells(revenue="120", adjusted_ebitda="30")}
    # No quarter ending a year earlier: not applicable.
    out = metric_frame((ltm,), frame, {})["LTM:B"]
    assert out["revenue_growth"] == Cell(None, "NOT_APPLICABLE")
    # The quarter's own cells are not the twelve months; its LTM frame is.
    quarter = replace(_fy("Q:A", "2024-12-31", "FY2024"), kind="QUARTER")
    frame = {**frame, "Q:A": _cells(revenue="30", adjusted_ebitda="8")}
    ending = {"Q:A": _cells(revenue="100", adjusted_ebitda="25")}
    out = metric_frame((ltm, quarter), frame, ending)["LTM:B"]
    assert out["revenue_growth"].value == Decimal("0.2")
    assert out["adjusted_ebitda_growth"].value == Decimal("0.2")


# Fix wave B (the adversary audit of b64facb7): H6 and M4, a debt figure that
# leaves something out says so on every metric that reads it.

_EXCLUDES_FOREIGN = "excludes facility in another currency"
_EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"


def _noted(cell: Cell, note: str) -> Cell:
    return replace(cell, note=note)


def test_a_metric_carries_what_its_debt_or_interest_leaves_out() -> None:
    column = _fy("FY:A", "2025-12-31")
    base = _cells(
        total_debt="500",
        cash_closing="100",
        secured_debt="300",
        ebitda="50",
        adjusted_ebitda="60",
        adjusted_ebitdar="70",
        cash_interest="-10",
        operating_lease_cost="-5",
        revenue="400",
        capex="-5",
        ffo="40",
        fcf="20",
        liquidity="150",
        lease_adjusted_debt="550",
        lease_adjusted_net_debt="450",
    )
    noted = {
        **base,
        "total_debt": _noted(
            base["total_debt"], f"differs from CP-1 stated; {_EXCLUDES_FOREIGN}"
        ),
        "secured_debt": _noted(base["secured_debt"], _EXCLUDES_UNALLOCATED),
        "lease_adjusted_debt": _noted(base["lease_adjusted_debt"], _EXCLUDES_FOREIGN),
        "lease_adjusted_net_debt": _noted(
            base["lease_adjusted_net_debt"], _EXCLUDES_FOREIGN
        ),
        "cash_interest": _noted(base["cash_interest"], _EXCLUDES_FOREIGN),
    }
    cells = metric_frame((column,), {"FY:A": noted}, {})["FY:A"]

    for name in (
        "total_leverage_reported",
        "net_leverage_adjusted",
        "lease_adjusted_leverage",
        "lease_adjusted_net_leverage",
        "interest_coverage_adjusted",
        "ebitdar_coverage",
        "ffo_to_debt",
        "ffo_to_lease_adjusted_debt",
        "fcf_to_debt",
        "liquidity_to_debt",
    ):
        assert cells[f"metric:{name}"].note == _EXCLUDES_FOREIGN, name
    for name in ("senior_secured_leverage", "senior_secured_net_leverage"):
        assert cells[f"metric:{name}"].note == _EXCLUDES_UNALLOCATED, name
    for name in ("fcf_to_adjusted_ebitda", "capex_to_revenue", "ebitda_margin"):
        assert cells[f"metric:{name}"].note is None, name
    both = {
        **noted,
        "secured_debt": _noted(
            base["secured_debt"], f"{_EXCLUDES_UNALLOCATED}; {_EXCLUDES_FOREIGN}"
        ),
    }
    cells = metric_frame((column,), {"FY:A": both}, {})["FY:A"]
    assert cells["metric:senior_secured_net_leverage"].note == (
        f"{_EXCLUDES_FOREIGN}; {_EXCLUDES_UNALLOCATED}"
    )
    # A metric without a figure says why, not what it would leave out.
    missing = {**noted, "ebitda": Cell(None, "NOT_STATED")}
    cells = metric_frame((column,), {"FY:A": missing}, {})["FY:A"]
    assert cells["metric:total_leverage_reported"] == Cell(None, "NOT_STATED")
    clean = metric_frame((column,), {"FY:A": base}, {})["FY:A"]
    assert all(
        cell.note is None for key, cell in clean.items() if key.startswith("metric:")
    )
