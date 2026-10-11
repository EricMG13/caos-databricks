"""The debt stack: totals, leases, payment ranks and the roll-forward."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from credit_model_fixture import example_registers, with_figures

from caos.calculators.credit_model.debt import (
    HISTORY_INCOMPLETE,
    PAYMENT_RANKS,
    carried,
    debt_frame,
    facility_keys,
    is_operating_lease,
    left_out,
    notes_of,
    payment_rank,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.calculators.credit_model.history import account_frame, historical_columns
from caos.calculators.credit_model.statements import statement_frame
from caos.methodology.model_inputs import AccountRow, Cp1Registers, FacilityRow

# CP-MODEL's SENIORITY_STATUSES and CP-1's secured_status values.
_SENIORITIES = (
    "SUPER_SENIOR",
    "SENIOR",
    "SENIOR_SUBORDINATED",
    "SUBORDINATED",
    "JUNIOR",
    "NOT_STATED",
)
_SECURITY = ("SECURED", "UNSECURED", "NOT_STATED")
_RANKS = {
    ("SUPER_SENIOR", "SECURED"): "Super senior",
    ("SUPER_SENIOR", "UNSECURED"): "Senior unsecured",
    ("SUPER_SENIOR", "NOT_STATED"): "Senior, security not stated",
    ("SENIOR", "SECURED"): "Senior secured",
    ("SENIOR", "UNSECURED"): "Senior unsecured",
    ("SENIOR", "NOT_STATED"): "Senior, security not stated",
    **{
        (s, security): "Subordinated"
        for s in _SENIORITIES[2:4]
        for security in _SECURITY
    },
    **{("JUNIOR", security): "Junior" for security in _SECURITY},
    **{("NOT_STATED", security): "Not stated" for security in _SECURITY},
}


def _row(regs: Cp1Registers, facility_id: str) -> FacilityRow:
    return next(f for f in regs.facilities if f.facility_id == facility_id)


def _columns(regs: Cp1Registers) -> dict[str, Column]:
    return {column.label: column for column in historical_columns(regs)}


def _debt(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame:
    return debt_frame(regs, columns, account_frame(regs, columns))


def _with_facilities(regs: Cp1Registers, *rows: FacilityRow) -> Cp1Registers:
    return replace(regs, facilities=(*regs.facilities, *rows))


def test_payment_rank_maps_seniority_and_security() -> None:
    assert PAYMENT_RANKS == (
        "Super senior",
        "Senior secured",
        "Senior, security not stated",
        "Senior unsecured",
        "Subordinated",
        "Junior",
        "Not stated",
        "Finance leases",
        "Debt adjustments",
    )
    tlb = _row(example_registers(), "tlb")
    for seniority in _SENIORITIES:
        for security in _SECURITY:
            row = replace(tlb, seniority=seniority, secured_status=security)
            assert payment_rank(row) == _RANKS[seniority, security], row
            leased = replace(row, lease_classification="FINANCE_LEASE")
            assert payment_rank(leased) == "Finance leases"
            adjustment = replace(row, facility_type="DEBT ADJUSTMENT")
            assert payment_rank(adjustment) == "Debt adjustments"
    assert payment_rank(replace(tlb, seniority="MEZZANINE")) == "Not stated"
    operating = replace(tlb, lease_classification="OPERATING_LEASE")
    assert payment_rank(operating) == "Senior secured"
    assert set(_RANKS.values()) | {"Finance leases", "Debt adjustments"} == set(
        PAYMENT_RANKS
    )


def test_facility_keys_name_the_totals_a_row_enters() -> None:
    regs = example_registers()
    assert facility_keys(_row(regs, "tlb"), "USD") == {"total_debt", "secured_debt"}
    assert facility_keys(_row(regs, "sun29"), "USD") == {"total_debt"}
    assert facility_keys(_row(regs, "finl"), "USD") == {"total_debt"}
    assert facility_keys(_row(regs, "disc"), "USD") == {"total_debt"}
    rcf = _row(regs, "rcf")
    assert facility_keys(rcf, "USD") == {"total_debt", "secured_debt"}
    assert facility_keys(rcf, "EUR") == frozenset()
    operating = replace(rcf, lease_classification="OPERATING_LEASE")
    assert facility_keys(operating, "USD") == {"lease_liabilities"}
    adjustment = replace(operating, facility_type="DEBT ADJUSTMENT")
    assert facility_keys(adjustment, "USD") == {"total_debt"}


def test_total_debt_excludes_operating_leases_and_includes_finance_leases() -> None:
    regs = example_registers()
    finl = _row(regs, "finl")
    leases = replace(
        finl,
        facility_id="opl",
        facility_name="Operating lease liabilities",
        facility_type="OPERATING_LEASE",
        lease_classification="OPERATING_LEASE",
        period_id="Q2_2026",
        carrying_value=Decimal(500),
        source=None,
    )
    euro = replace(
        _row(regs, "sun29"),
        facility_id="eur",
        facility_name="EUR notes",
        currency="EUR",
        period_id="Q2_2026",
        carrying_value=Decimal(300),
        source=None,
    )
    regs = _with_facilities(regs, leases, euro)
    columns = historical_columns(regs)
    q2_id = _columns(regs)["Q2 26"].column_id
    q2 = _debt(regs, columns)[q2_id]
    assert q2["total_debt"].value == 14106
    assert q2["total_debt"].stated == 13846
    # The EUR notes are left out of it, said so (H6).
    assert q2["total_debt"].note == "excludes facility in another currency"
    assert q2["total_debt"].basis == "CALCULATED"
    assert q2["lease_liabilities"].value == 500
    assert q2["secured_debt"].value == 5316
    assert q2["fac:eur"] == Cell(
        Decimal(300), basis="REPORTED", note="different currency, not converted"
    )
    assert q2["fac:opl"].value == 500
    assert q2["fac:tlb"].note is None
    assert q2["undrawn_rcf"].value == 2200
    accounts = account_frame(regs, columns)
    statement = statement_frame(accounts, columns, regs)[q2_id]
    assert statement["lease_adjusted_debt"].value == 14606
    assert statement["net_debt"].value == 14106 - 1000
    assert statement["lease_adjusted_net_debt"].value == 14606 - 1000
    assert statement["fac:eur"].note == "different currency, not converted"
    stated = with_figures(regs, "Q2_2026", {"total_debt": Decimal(13800)})
    differs = _debt(stated, columns)[q2_id]["total_debt"]
    assert differs.note == (
        "differs from CP-1 stated; excludes facility in another currency"
    )
    assert differs.stated == 13800


def test_debt_totals_need_every_carrying_value() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=None)
            if (f.facility_id, f.period_id) == ("ssn29", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    assert q2["total_debt"].reason == "COMPONENT_MISSING"
    assert q2["secured_debt"].reason == "COMPONENT_MISSING"
    assert q2["lease_liabilities"].value == 0
    assert q2["fac:ssn29"] == Cell(None, "NOT_STATED")
    assert q2["debt_non_cash"].reason == "COMPONENT_MISSING"


def test_debt_roll_forward_closes_to_the_stack() -> None:
    regs = example_registers()
    columns = historical_columns(regs)
    frame = _debt(regs, columns)
    by_label = _columns(regs)
    q2 = frame[by_label["Q2 26"].column_id]
    assert q2["debt_opening"].value == 14112
    assert q2["debt_non_cash"].value == 0
    assert q2["debt_closing"].value == 14106
    assert q2["debt_non_cash"].note == "residual"
    ltm = frame[by_label["LTM Q2 26"].column_id]
    assert ltm["debt_opening"].value == 14130
    assert ltm["debt_closing"].value == 14106
    assert ltm["debt_non_cash"].value == 0
    fy23 = frame[by_label["FY23"].column_id]
    assert fy23["debt_opening"] == Cell(None, "NOT_SOURCED")
    assert fy23["debt_non_cash"].reason == "COMPONENT_MISSING"
    accounts = account_frame(regs, columns)
    statement = statement_frame(accounts, columns, regs)
    closed = 0
    for cells in statement.values():
        opening, raised, other, closing = (
            cells[key].value
            for key in (
                "debt_opening",
                "debt_raised_net",
                "debt_non_cash",
                "debt_closing",
            )
        )
        if opening is None or raised is None or other is None:
            continue
        assert opening + raised + other == closing == cells["total_debt"].value
        closed += 1
    assert closed >= 10
    grown = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=Decimal(280))
            if (f.facility_id, f.period_id) == ("finl", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    moved = _debt(grown, historical_columns(grown))
    assert moved[by_label["Q2 26"].column_id]["debt_non_cash"].value == 20


def test_a_column_without_facility_rows_has_no_debt() -> None:
    regs = example_registers()
    columns = historical_columns(regs)
    ytd = _debt(regs, columns)[_columns(regs)["YTD H1 26"].column_id]
    assert ytd["total_debt"].value == 14106
    bare = replace(regs, facilities=())
    empty = _debt(bare, columns)[_columns(regs)["Q2 26"].column_id]
    for key in ("total_debt", "lease_liabilities", "secured_debt", "debt_closing"):
        assert empty[key].value is None, key
        assert empty[key].reason == "NOT_SOURCED", key
    assert empty["total_debt"].stated == 13846
    assert empty["debt_non_cash"].reason == "COMPONENT_MISSING"


@pytest.mark.parametrize("missing", ["rcf_commitment", "rcf_drawn"])
def test_undrawn_rcf_needs_commitment_and_drawn(missing: str) -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != missing
            or a.period_id not in {"Q2_2026", "H1_2026", "LTM_Q2_2026"}
        ),
    )
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    assert q2["undrawn_rcf"].reason == "COMPONENT_MISSING"


def test_a_column_reads_its_own_period_first_then_any_ending_that_day() -> None:
    regs = example_registers()
    tlb = next(
        f for f in regs.facilities if (f.facility_id, f.period_id) == ("tlb", "Q2_2026")
    )
    restated = replace(tlb, period_id="H1_2026", carrying_value=Decimal(2310))
    regs = _with_facilities(regs, restated)
    columns = historical_columns(regs)
    frame = _debt(regs, columns)
    by_label = _columns(regs)
    assert frame[by_label["Q2 26"].column_id]["fac:tlb"].value == 2316
    assert frame[by_label["YTD H1 26"].column_id]["fac:tlb"].value == 2310
    assert frame[by_label["YTD H1 26"].column_id]["total_debt"].value == 14100
    assert frame[by_label["LTM Q2 26"].column_id]["fac:tlb"].value == 2316
    blank = replace(tlb, carrying_value=None)
    gap = replace(
        regs,
        facilities=tuple(blank if f is tlb else f for f in regs.facilities),
    )
    ytd = _debt(gap, columns)[by_label["Q2 26"].column_id]
    assert ytd["fac:tlb"].value == 2310


def test_stack_cells_carry_sources_and_need_no_cp1_total() -> None:
    regs = example_registers()
    q2_rows = [f for f in regs.facilities if f.period_id == "Q2_2026"]
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != "total_debt"
            or a.period_id not in {"Q2_2026", "H1_2026", "LTM_Q2_2026"}
        ),
    )
    regs = with_figures(regs, "Q2_2026", {"rcf_drawn": Decimal(300)})
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    sources = tuple(dict.fromkeys(f.source for f in q2_rows if f.source))
    assert q2["total_debt"] == Cell(Decimal(14106), basis="CALCULATED", sources=sources)
    assert q2["fac:tlb"].sources == (q2_rows[1].source,)
    assert q2["undrawn_rcf"].value == 1900
    assert q2["undrawn_rcf"].sources


def test_a_foreign_facility_without_a_value_keeps_its_note() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR", carrying_value=None)
            if (f.facility_id, f.period_id) == ("sun29", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    assert q2["fac:sun29"] == Cell(
        None, "NOT_STATED", note="different currency, not converted"
    )
    assert q2["total_debt"].value == 14106 - 3600


def test_debt_totals_are_exact_beyond_the_default_precision() -> None:
    regs = example_registers()
    fine = Decimal("2316.12345678901234567890123456789")
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=fine)
            if (f.facility_id, f.period_id) == ("tlb", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    assert q2["total_debt"].value == Decimal("14106.12345678901234567890123456789")


def test_an_account_the_register_never_states_is_not_sourced() -> None:
    regs = example_registers()
    regs = replace(
        regs, accounts=tuple(a for a in regs.accounts if a.metric_id != "rcf_drawn")
    )
    columns = historical_columns(regs)
    q2 = _debt(regs, columns)[_columns(regs)["Q2 26"].column_id]
    assert q2["undrawn_rcf"] == Cell(None, "COMPONENT_MISSING")


# Fix wave B (the adversary audit of b64facb7): M1, H6, Task 7 (5).

_INCOMPLETE = "opening stack incomplete"
_EXCLUDES_FOREIGN = "excludes facility in another currency"


def _drop(regs: Cp1Registers, facility_id: str, *period_ids: str) -> Cp1Registers:
    return replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if not (f.facility_id == facility_id and f.period_id in period_ids)
        ),
    )


def test_a_facility_without_an_opening_row_leaves_no_opening_debt() -> None:
    regs = _drop(example_registers(), "ssn29", "Q2_2025")
    ltm = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]

    assert ltm["debt_opening"] == Cell(None, "COMPONENT_MISSING", note=_INCOMPLETE)
    assert ltm["debt_non_cash"].reason == "COMPONENT_MISSING"
    assert ltm["debt_closing"].value == 14106


def test_a_facility_repaid_or_outside_total_debt_leaves_the_opening_whole() -> None:
    # Repaid in the period: at the opening, not at the closing.
    regs = _drop(example_registers(), "ssn29", "Q2_2026", "LTM_Q2_2026")
    ltm = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]
    assert ltm["debt_opening"].value == 14130
    # An operating lease, or a facility in another currency, enters no total
    # debt: without an opening row it leaves the opening whole.
    dropped = _drop(example_registers(), "ssn29", "Q2_2025")
    ssn29 = _row(dropped, "ssn29")
    for outside in (
        replace(ssn29, lease_classification="OPERATING_LEASE"),
        replace(ssn29, currency="EUR"),
    ):
        regs = replace(
            dropped,
            facilities=tuple(
                replace(outside, period_id=f.period_id)
                if f.facility_id == "ssn29"
                else f
                for f in dropped.facilities
            ),
        )
        ltm = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]
        assert ltm["debt_opening"].value == 14130 - 2000


def test_a_foreign_facility_is_noted_on_the_totals_it_leaves() -> None:
    regs = example_registers()
    eur = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "sun29" else f
            for f in regs.facilities
        ),
    )
    ltm = _debt(eur, historical_columns(eur))["LTM:LTM_Q2_2026"]

    assert ltm["total_debt"].note == f"differs from CP-1 stated; {_EXCLUDES_FOREIGN}"
    for key in ("debt_closing", "debt_opening"):
        assert ltm[key].note == _EXCLUDES_FOREIGN, key
    assert ltm["secured_debt"].note is None
    assert ltm["lease_liabilities"].note is None
    secured = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "ssn29" else f
            for f in regs.facilities
        ),
    )
    ltm = _debt(secured, historical_columns(secured))["LTM:LTM_Q2_2026"]
    assert ltm["secured_debt"].note == _EXCLUDES_FOREIGN
    lease = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR", lease_classification="OPERATING_LEASE")
            if f.facility_id == "finl"
            else f
            for f in regs.facilities
        ),
    )
    ltm = _debt(lease, historical_columns(lease))["LTM:LTM_Q2_2026"]
    assert ltm["lease_liabilities"].note == _EXCLUDES_FOREIGN
    assert ltm["debt_closing"].note is None
    clean = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]
    for key in ("total_debt", "debt_closing", "secured_debt", "lease_liabilities"):
        assert clean[key].note is None, key


def test_a_debt_adjustment_classified_as_an_operating_lease_is_debt() -> None:
    row = replace(
        _row(example_registers(), "disc"), lease_classification="OPERATING_LEASE"
    )

    assert facility_keys(row, "USD") == frozenset({"total_debt"})
    assert payment_rank(row) == "Debt adjustments"
    assert not is_operating_lease(row)
    assert is_operating_lease(
        replace(
            _row(example_registers(), "finl"), lease_classification="OPERATING_LEASE"
        )
    )


def test_notes_of_splits_a_compound_note_at_each_separator() -> None:
    assert notes_of(None) == ()
    assert notes_of("residual") == ("residual",)
    assert notes_of("implied rate; amortisation not stated") == (
        "implied rate",
        "amortisation not stated",
    )
    assert notes_of("held flat; different currency, not converted; residual") == (
        "held flat",
        "different currency, not converted",
        "residual",
    )
    assert notes_of("not converted; different currency") == (
        "not converted",
        "different currency",
    )


def test_carried_names_only_what_a_figure_leaves_out_in_order() -> None:
    cells = [
        Cell(Decimal(1), note=f"{_EXCLUDES_UNALLOCATED}; residual"),
        Cell(Decimal(2), note=f"differs from CP-1 stated; {_EXCLUDES_FOREIGN}"),
        Cell(None, "NOT_STATED"),
    ]
    assert carried(cells) == f"{_EXCLUDES_FOREIGN}; {_EXCLUDES_UNALLOCATED}"
    assert carried([Cell(Decimal(1), note="residual")]) is None
    assert carried([]) is None


_EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"


def test_left_out_names_the_totals_a_row_in_another_currency_would_enter() -> None:
    regs = example_registers()
    eur = {f.facility_id: replace(f, currency="EUR") for f in regs.facilities}

    assert left_out([eur["ssn29"]], "USD") == {"total_debt", "secured_debt"}
    assert left_out([eur["sun29"], _row(regs, "ssn29")], "USD") == {"total_debt"}
    lease = replace(eur["finl"], lease_classification="OPERATING_LEASE")
    assert left_out([lease], "USD") == {"lease_liabilities"}
    assert left_out(regs.facilities, "USD") == frozenset()


def _stated_debt(regs: Cp1Registers, figure: str | None) -> Cp1Registers:
    """`regs` with CP-1's total debt at 30 June 2025 (Q2 and H1 2025) set to
    `figure`, or without those rows."""
    at = {"Q2_2025", "H1_2025"}

    def opening(a: AccountRow) -> bool:
        return a.metric_id == "total_debt" and a.period_id in at

    if figure is None:
        return replace(regs, accounts=tuple(a for a in regs.accounts if not opening(a)))
    return replace(
        regs,
        accounts=tuple(
            replace(a, value=Decimal(figure)) if opening(a) else a
            for a in regs.accounts
        ),
    )


_HISTORY = "facility history incomplete"
_EARLY = ("FY2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024", "FY2024")


def test_a_facility_without_history_opens_at_cp1s_stated_total() -> None:
    """The adversary's MAJOR-3 probe: the term loan written only from Q3 2025
    on. CP-1 states 13870 at 30 June 2025 (no lease) and the facilities less
    the 260 finance lease sum to 11530: the loan is no new issue."""
    regs = _drop(example_registers(), "tlb", *_EARLY, "Q1_2025", "Q2_2025")
    ltm = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]
    assert HISTORY_INCOMPLETE == _HISTORY

    opening = ltm["debt_opening"]
    assert (opening.value, opening.basis, opening.note) == (
        Decimal(13870 + 260),
        "CALCULATED",
        _HISTORY,
    )
    assert {s.cell_text for s in opening.sources} == {"13870", "260"}
    assert ltm["debt_closing"].value == 14106
    assert ltm["debt_non_cash"].value == 0
    assert ltm["debt_non_cash"].note == f"residual; {_HISTORY}"

    # No stated total at the opening either: missing, noted.
    unstated = _debt(_stated_debt(regs, None), historical_columns(regs))
    assert unstated["LTM:LTM_Q2_2026"]["debt_opening"] == Cell(
        None, "COMPONENT_MISSING", note=_HISTORY
    )
    # A facility in another currency at the opening: the stated total is on
    # another footing, so missing, noted.
    eur = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "sun29" else f
            for f in regs.facilities
        ),
    )
    assert _debt(eur, historical_columns(eur))["LTM:LTM_Q2_2026"][
        "debt_opening"
    ] == Cell(None, "COMPONENT_MISSING", note=_HISTORY)
    # An opening row without a value: the total is missing however CP-1
    # states it.
    blank = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=None)
            if (f.facility_id, f.period_id) == ("ssn29", "Q2_2025")
            else f
            for f in regs.facilities
        ),
    )
    assert _debt(blank, historical_columns(blank))["LTM:LTM_Q2_2026"][
        "debt_opening"
    ] == Cell(None, "COMPONENT_MISSING")
    # Where CP-1's stated total agrees, the loan is a new issue, nil then.
    agreed = _debt(_stated_debt(regs, "11530"), historical_columns(regs))
    assert agreed["LTM:LTM_Q2_2026"]["debt_opening"].value == 14130 - 2340
    assert agreed["LTM:LTM_Q2_2026"]["debt_opening"].note is None
    # Within the stated figure's rounding (to the nearest hundred) agrees.
    rounded = _debt(_stated_debt(regs, "1.15E+4"), historical_columns(regs))
    assert rounded["LTM:LTM_Q2_2026"]["debt_opening"].value == 14130 - 2340


def test_a_facility_first_issued_inside_the_column_opens_at_nil() -> None:
    early = _EARLY
    regs = _drop(example_registers(), "ssn29", *early, "Q1_2025", "Q2_2025")
    # CP-1's total at the opening agrees: the notes were issued after it.
    regs = _stated_debt(regs, "11870")
    ltm = _debt(regs, historical_columns(regs))["LTM:LTM_Q2_2026"]

    assert ltm["debt_opening"].value == 14130 - 2000
    assert ltm["debt_opening"].note is None
    # The notes issued in the period, not raised in its cash flow statement.
    assert ltm["debt_non_cash"].value == 2000
    # With an earlier row, a facility missing at the opening is still a gap.
    gap = _drop(example_registers(), "ssn29", *early[1:], "Q1_2025", "Q2_2025")
    ltm = _debt(gap, historical_columns(gap))["LTM:LTM_Q2_2026"]
    assert ltm["debt_opening"] == Cell(None, "COMPONENT_MISSING", note=_INCOMPLETE)


def test_a_facility_written_as_a_negative_zero_is_zero() -> None:
    regs = example_registers()
    zero = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=Decimal("-0")) if f.facility_id == "ssn29" else f
            for f in regs.facilities
        ),
    )
    q2 = _debt(zero, historical_columns(zero))[_columns(zero)["Q2 26"].column_id]

    value = q2["fac:ssn29"].value
    assert value is not None and (str(value), value.is_signed()) == ("0", False)


def test_debt_non_cash_keeps_what_its_closing_leaves_out() -> None:
    """The adversary's MINOR-2: ssn31 in USD at the opening and in EUR at
    the close; the residual names the facility it leaves out."""
    regs = example_registers()
    eur = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR")
            if (f.facility_id, f.period_id) == ("ssn31", "Q2_2026")
            else f
            for f in regs.facilities
        ),
    )
    q2 = _debt(eur, historical_columns(eur))["Q:Q2_2026"]
    assert q2["debt_closing"].note == _EXCLUDES_FOREIGN
    assert q2["debt_opening"].note is None
    assert q2["debt_non_cash"].value == -1000
    assert q2["debt_non_cash"].note == f"residual; {_EXCLUDES_FOREIGN}"
