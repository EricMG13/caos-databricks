"""The assembled credit model: columns in the spec's order, the worked
layout's bands and lines, its limitations, and every bridge closing."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_request,
    example_slots,
    with_figures,
)

from caos.calculators.credit_model._cells import CONTEXT
from caos.calculators.credit_model.assemble import (
    CreditModel,
    ModelInputs,
    credit_model,
)
from caos.calculators.credit_model.frame import Cell, Column
from caos.calculators.credit_model.history import account_frame, historical_columns
from caos.calculators.credit_model.layout import (
    FacilityTerms,
    Line,
    facility_terms,
    layout,
)
from caos.calculators.credit_model.metrics import metric_frame
from caos.calculators.credit_model.statements import statement_frame
from caos.methodology.model_inputs import Cp1Registers

_PF = "PF:LTM_Q2_2026"
_LTM = "LTM:LTM_Q2_2026"
_BASE = "BASE:2026"


def _inputs(
    regs: Cp1Registers | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected: bool = True,
    exclude_unrealised: bool = False,
) -> ModelInputs:
    return ModelInputs(
        registers=regs or example_registers(),
        request=(request or example_request()) if projected else None,
        growth=example_growth(),
        slots=example_slots(),
        deck=example_deck(),
        exclude_unrealised=exclude_unrealised,
    )


def _model(
    regs: Cp1Registers | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected: bool = True,
    exclude_unrealised: bool = False,
) -> CreditModel:
    return credit_model(
        _inputs(
            regs, request, projected=projected, exclude_unrealised=exclude_unrealised
        )
    )


def _line(model: CreditModel, line_id: str) -> Line:
    return next(line for line in model.lines if line.line_id == line_id)


def _cell(model: CreditModel, line_id: str, column_id: str) -> Cell:
    index = [c.column_id for c in model.columns].index(column_id)
    return _line(model, line_id).cells[index]


def _value(model: CreditModel, line_id: str, column_id: str) -> Decimal:
    value = _cell(model, line_id, column_id).value
    assert value is not None, (line_id, column_id)
    return value


def _with_cell(
    model: CreditModel, line_id: str, column_id: str, cell: Cell
) -> CreditModel:
    """The model with one cell replaced."""
    index = [c.column_id for c in model.columns].index(column_id)
    lines = tuple(
        replace(
            line,
            cells=tuple(
                cell if i == index and line.line_id == line_id else old
                for i, old in enumerate(line.cells)
            ),
        )
        for line in model.lines
    )
    return replace(model, lines=lines)


def _nudged(model: CreditModel, line_id: str, column_id: str) -> CreditModel:
    """The model with one cell's figure one higher."""
    cell = _cell(model, line_id, column_id)
    assert cell.value is not None, (line_id, column_id)
    return _with_cell(model, line_id, column_id, replace(cell, value=cell.value + 1))


def test_columns_run_history_pf_then_base_years_then_downside_years() -> None:
    request = example_request()
    request["periods"] = sorted(request["periods"], key=lambda p: p["case"] == "BASE")
    model = _model(request=request)
    assert [c.column_id for c in model.columns] == [
        *(f"Q:Q{q}_{y}" for y in (2024, 2025) for q in (1, 2, 3, 4)),
        "Q:Q1_2026",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2023",
        "FY:FY2024",
        "FY:FY2025",
        _LTM,
        _PF,
        "BASE:2026",
        "BASE:2027",
        "BASE:2028",
        "DOWNSIDE:2026",
        "DOWNSIDE:2027",
        "DOWNSIDE:2028",
    ]


def test_a_rank_subtotal_sums_its_facilities_on_every_column() -> None:
    model = _model()
    for column in model.columns:
        if column.kind in ("PROJECTED", "PF_LTM"):
            continue
        secured = sum(
            _value(model, key, column.column_id)
            for key in ("fac:tlb", "fac:ssn29", "fac:ssn31")
        )
        assert _value(model, "rank:Senior secured", column.column_id) == secured
    assert _value(model, "rank:Senior secured", _PF) == 2316 + 2000 + 1600
    assert _value(model, "rank:Senior secured", _BASE) == (2328 - 24) + 2000 + 1000
    assert _cell(model, "rank:Senior secured", _LTM).basis == "CALCULATED"


def test_limitations_list_each_note_once() -> None:
    model = _model()
    notes = [text.split(": ")[0] for text in model.limitations]
    assert len(notes) == len(set(notes))
    for note in {cell.note for line in model.lines for cell in line.cells} - {None}:
        assert note in notes
    on = dict(text.split(": ", 1) for text in model.limitations)
    assert on["assumed refinanced"] == "BASE:2027, DOWNSIDE:2027"
    assert on["residual"].split(", ")[0] == "Q:Q1_2024"
    # On the PF-LTM only the roll-forward's residual, the LTM's, is shown.
    assert _PF in on["residual"].split(", ")
    residuals = [
        line.line_id for line in model.lines if _cell(model, line.line_id, _PF).note
    ]
    assert residuals == ["debt_non_cash"]
    assert len(model.limitations) == len(notes)


def test_a_note_on_revenue_keeps_cp1s_own() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=Decimal(5000))
            if a.metric_id == "revenue" and a.period_id == "H1_2026"
            else a
            for a in regs.accounts
        ),
        segments=tuple(
            replace(s, revenue=Decimal(1))
            if s.segment_id == "digital" and s.period_id == "Q1_2026"
            else s
            for s in regs.segments
        ),
    )
    cell = _cell(_model(regs=regs), "revenue", "YTD:H1_2026")
    assert cell.note == (
        "differs from CP-1 stated; business units do not sum to revenue"
    )


def test_cells_a_column_has_not_say_why() -> None:
    model = _model()
    assert _cell(model, "kpi:lv_occupancy", _BASE).reason == "NOT_PROJECTED"
    assert _cell(model, "cogs", _BASE).reason == "NOT_PROJECTED"
    assert _cell(model, "wa_rate", _LTM).reason == "NOT_APPLICABLE"
    assert _cell(model, "reference_rate", "Q:Q1_2024").reason == "NOT_APPLICABLE"
    assert _cell(model, "pf:silverlake_cash", _LTM).reason == "NOT_APPLICABLE"
    assert _cell(model, "pf:silverlake_cash", _BASE).reason == "NOT_APPLICABLE"
    assert _value(model, "pf:silverlake_cash", _PF) == -50
    regs = example_registers()
    regs = replace(regs, kpis=tuple(k for k in regs.kpis if k.period_id != "FY2023"))
    assert _cell(_model(regs=regs), "kpi:lv_occupancy", "FY:FY2023").reason == (
        "NOT_SOURCED"
    )
    assert _cell(model, "rank:Senior secured", _LTM).value is not None


def test_a_rank_subtotal_without_any_facility_at_a_date_says_why() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if not (f.facility_id in {"sun29", "sun32"} and f.period_id == "FY2023")
        ),
    )
    model = _model(regs=regs)
    assert _cell(model, "rank:Senior unsecured", "FY:FY2023").reason == "NOT_SOURCED"
    assert _value(model, "rank:Senior unsecured", "FY:FY2024") == 7100
    projected = Column(_BASE, "PROJECTED", "FY26E", "FY2026", "2026", None, 365, "BASE")
    lines = layout(regs, (projected,), {_BASE: {}}, False, None)
    subtotal = next(line for line in lines if line.line_id == "rank:Senior unsecured")
    assert subtotal.cells == (Cell(None, "NOT_PROJECTED"),)


def test_less_cash_is_closing_cash_negated() -> None:
    model = _model()
    for column in model.columns:
        if column.kind == "PF_LTM":
            continue  # closing cash shows the LTM's there, its PF row beneath
        cash = _cell(model, "cash_closing", column.column_id)
        less = _cell(model, "less_cash", column.column_id)
        assert cash.value is not None
        with localcontext(CONTEXT):
            assert less == replace(cash, value=-cash.value)
    assert _value(model, "less_cash", _PF) == -950
    regs = example_registers()
    stated = Decimal("1000")
    cash = replace(
        _cell(model, "cash_closing", _LTM), value=Decimal(1000), stated=stated
    )
    assert cash.stated == stated
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    frame[_LTM]["cash_closing"] = cash
    metrics = metric_frame(columns, frame, {k: frame[k] for k in frame})
    lines = layout(regs, columns, metrics, False, None)
    index = [c.column_id for c in columns].index(_LTM)
    less = next(line for line in lines if line.line_id == "less_cash").cells[index]
    assert (less.value, less.stated) == (Decimal(-1000), Decimal(-1000))


def test_facility_terms_are_shown_as_stated_never_rounded() -> None:
    model = _model()
    assert _line(model, "fac:rcf").terms == FacilityTerms(
        "SOFR", "+225 bp", "none", "2030-01-31", "bullet"
    )
    assert _line(model, "fac:tlb").terms == FacilityTerms(
        "SOFR", "+275 bp", "0.50%", "2030-02-28", "24 p.a."
    )
    assert _line(model, "fac:ssn29").terms == FacilityTerms(
        "none", "6.500%", "n.a.", "2029-02-15", "bullet"
    )
    assert _line(model, "fac:finl").terms == FacilityTerms(
        "not stated", "not stated", "n.a.", "not stated", "not stated"
    )
    assert _line(model, "revenue").terms is None
    row = next(f for f in example_registers().facilities if f.facility_id == "tlb")
    odd = replace(
        row,
        reference_rate="TERM_SOFR",
        spread_bps=Decimal("262.5"),
        floor_bps=Decimal("12.5"),
        annual_amortisation=Decimal("0.0001"),
    )
    assert facility_terms(odd) == FacilityTerms(
        "Term SOFR", "+262.5 bp", "0.125%", "2030-02-28", "0.0001 p.a."
    )
    assert (
        facility_terms(replace(odd, reference_rate="LIBOR")).reference_rate == "LIBOR"
    )
    assert (
        facility_terms(replace(odd, spread_bps=None)).spread_or_coupon == "not stated"
    )
    assert facility_terms(replace(odd, rate_type="FIXED")).spread_or_coupon == (
        "not stated"
    )
    fixed = replace(odd, rate_type="FIXED", fixed_rate=Decimal("7.125"), floor_bps=None)
    assert (facility_terms(fixed).spread_or_coupon, facility_terms(fixed).floor) == (
        "7.125%",
        "n.a.",
    )
    assert (
        facility_terms(replace(odd, rate_type="NOT_STATED", floor_bps=None)).floor
        == "n.a."
    )
    assert (
        facility_terms(
            replace(odd, rate_type="FIXED", fixed_rate=Decimal("1E+1"))
        ).spread_or_coupon
        == "10%"
    )


def test_every_metric_in_the_frame_has_one_line() -> None:
    model = _model()
    ids = [line.line_id for line in model.lines]
    assert len(ids) == len(set(ids))
    regs = example_registers()
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    ltm_ending = {c.column_id: frame[c.column_id] for c in columns}
    keys = metric_frame(columns, frame, ltm_ending)[_LTM]
    metrics = {
        k
        for k in keys
        if k.startswith(("metric:", "bu_growth:")) or k.endswith("_growth")
    }
    assert metrics - set(ids) == {"bu_growth:corporate_eliminations"}


def test_growth_lines_read_their_growth() -> None:
    model = _model()
    with localcontext(CONTEXT):
        revenue = Decimal(11519) / Decimal(11165) - 1
        adjusted = Decimal(4019) / Decimal(3872) - 1
    assert _value(model, "revenue_growth", "FY:FY2025") == revenue
    assert _value(model, "adjusted_ebitda_growth", "FY:FY2025") == adjusted


def test_an_add_back_with_another_realisation_status_shows_it() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(a, realization_status="PARTIAL")
            if a.addback_id == "restructuring"
            else a
            for a in regs.addbacks
        ),
    )
    line = _line(_model(regs=regs, exclude_unrealised=True), "addback:restructuring")
    assert (line.label, line.kind) == ("Add-back: Restructuring (PARTIAL)", "ACCOUNT")


def test_projected_interest_reads_the_rate_deck() -> None:
    model = _model()
    assert _cell(model, "reference_rate", _BASE).value == Decimal("0.0380")
    assert _cell(model, "reference_rate", "DOWNSIDE:2026").value == Decimal("0.0480")


def test_a_period_without_revenue_notes_nothing() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=None)
            if a.metric_id == "revenue" and a.period_id == "Q1_2024"
            else a
            for a in regs.accounts
        ),
    )
    cell = _cell(_model(regs=regs), "revenue", "Q:Q1_2024")
    assert (cell.value, cell.note) == (None, None)


_EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"


def _on(model: CreditModel) -> dict[str, str]:
    """Each limitation's note and the columns it is on."""
    return dict(text.split(": ", 1) for text in model.limitations if ": " in text)


def test_projected_secured_metrics_note_unallocated_movements() -> None:
    model = _model()

    for line_id in (
        "metric:senior_secured_leverage",
        "metric:senior_secured_net_leverage",
    ):
        assert _cell(model, line_id, _BASE).note == _EXCLUDES_UNALLOCATED
        assert _cell(model, line_id, "DOWNSIDE:2026").note is None
        assert _cell(model, line_id, _LTM).note is None
    assert _on(model)[_EXCLUDES_UNALLOCATED] == "BASE:2026, BASE:2027, BASE:2028"


def _signed_zeros(model: CreditModel) -> list[tuple[str, str]]:
    return [
        (line.line_id, column.column_id)
        for line in model.lines
        for column, cell in zip(model.columns, line.cells, strict=True)
        for figure in (cell.value, cell.stated)
        if figure is not None and figure.is_zero() and figure.is_signed()
    ]


def test_no_cell_is_a_negative_zero() -> None:
    request = example_request()
    for driver in request["drivers"]:
        driver.update({"capex": "0", "cash_taxes": "-0", "acquisitions_disposals": "0"})
    regs = with_figures(
        example_registers(),
        "FY2025",
        {"dividends_paid": Decimal(0), "capex_and_intangible_investment": Decimal(0)},
    )
    model = _model(regs=regs, request=request)

    assert _signed_zeros(model) == []
    assert _value(model, "dividends", "DOWNSIDE:2026") == 0


def test_a_compound_note_is_listed_under_each_of_its_notes() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, rate_type="NOT_STATED", annual_amortisation=None)
            if f.facility_id == "tlb"
            else f
            for f in regs.facilities
        ),
    )
    model = _model(regs=regs)
    assert (
        _cell(model, "fac:tlb", _BASE).note == "implied rate; amortisation not stated"
    )

    on = _on(model)
    assert not any("; " in note for note in on)
    assert _BASE in on["implied rate"].split(", ")
    assert _BASE in on["amortisation not stated"].split(", ")


def test_the_unallocated_line_has_no_payment_rank() -> None:
    assert _line(_model(), "debt:unallocated").rank is None


def test_an_add_back_label_shows_the_status_that_excludes_it() -> None:
    regs = example_registers()
    rows = [a for a in regs.addbacks if a.addback_id == "restructuring"]
    regs = replace(
        regs,
        addbacks=tuple(
            replace(a, realization_status="UNREALIZED") if a is rows[0] else a
            for a in regs.addbacks
        ),
    )
    assert rows[-1].realization_status == "REALIZED"

    line = _line(_model(regs=regs, exclude_unrealised=True), "addback:restructuring")
    assert (line.label, line.kind) == (
        "Add-back: Restructuring (unrealised), excluded",
        "MEMO",
    )
    line = _line(_model(regs=regs), "addback:restructuring")
    assert (line.label, line.kind) == (
        "Add-back: Restructuring (unrealised)",
        "ACCOUNT",
    )


def test_business_unit_growth_reads_the_like_period() -> None:
    model = _model()
    with localcontext(CONTEXT):
        las_vegas = (
            _value(model, "bu:las_vegas", "FY:FY2025")
            / _value(model, "bu:las_vegas", "FY:FY2024")
            - 1
        )
    assert _value(model, "bu_growth:las_vegas", "FY:FY2025") == las_vegas
    assert _value(model, "bu_growth:las_vegas", _BASE) == Decimal("0.025")


def test_a_pf_refinancing_that_cuts_interest_raises_pf_coverage() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        pro_forma=tuple(
            replace(a, value=Decimal(30)) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )
    model = _model(regs=regs)

    coverage = "metric:interest_coverage_adjusted"
    assert _value(model, coverage, _PF) > _value(model, coverage, _LTM)
    assert _value(model, "pf:silverlake_interest", _PF) == 30


def test_a_parenthesised_zero_is_never_a_negative_zero() -> None:
    zero = Decimal("-0")  # how the host reads "(0)"
    regs = with_figures(
        example_registers(),
        "FY2025",
        {"revenue": zero, "dividends_paid": zero},
    )
    regs = with_figures(regs, "Q2_2026", {"dividends_paid": zero})
    regs = replace(
        regs,
        pro_forma=tuple(
            replace(a, value=zero) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )
    model = _model(regs=regs)

    assert _signed_zeros(model) == []
    assert str(_value(model, "pf:silverlake_interest", _PF)) == "0"
