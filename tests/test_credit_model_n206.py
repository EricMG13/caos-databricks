"""N206 (R7) at the `credit_model` level: a balance read across stated
footings is refused, with a note naming both, in the debt frame, leverage and
the opening balances; the same footing and an unstated one read as before."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from credit_model_fixture import example_registers
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model._cells import (
    ABSENT,
    OTHER_FOOTING,
    balance_periods,
    footing_note,
    merged_footing_note,
    odd_quarter,
    periods_at,
    refused_balance,
)
from caos.calculators.credit_model.assemble import ModelInputs, credit_model
from caos.calculators.credit_model.debt import (
    _merged,
    _stated_at,
    debt_frame,
    facility_keys,
)
from caos.calculators.credit_model.frame import Cell
from caos.calculators.credit_model.history import (
    _term_length,
    account_frame,
    historical_columns,
)
from caos.methodology.model_inputs import Cp1Registers

Footing = tuple[str | None, str | None]
_KEYS = (
    "total_debt",
    "net_debt",
    "fac:tlb",
    "cash_opening",
    "debt_opening",
    "metric:total_leverage_reported",
    "metric:net_leverage_adjusted",
)


def _bases(regs: Cp1Registers, **bases: Footing) -> Cp1Registers:
    return replace(
        regs,
        periods=tuple(
            replace(
                p,
                accounting_basis=bases.get(p.period_id, (None, None))[0],
                entity_perimeter=bases.get(p.period_id, (None, None))[1],
            )
            for p in regs.periods
        ),
    )


def _cells(regs: Cp1Registers, column_id: str) -> dict[str, Cell]:
    model = credit_model(ModelInputs(regs, None, (), (), None))
    index = [c.column_id for c in model.columns].index(column_id)
    return {
        line.line_id: line.cells[index] for line in model.lines if line.line_id in _KEYS
    }


def _pytd_regs(own: Footing, other: Footing) -> Cp1Registers:
    """H1 2025 (own) has no total debt row; Q2 2025 (other), ending the same
    day, holds the facility rows."""
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if not (a.metric_id == "total_debt" and a.period_id == "H1_2025")
        ),
    )
    return _bases(regs, H1_2025=own, Q2_2025=other)


def _quarter_regs(own: Footing, other: Footing) -> Cp1Registers:
    """The facility rows of Q2 2025 move to H1 2025 (TLB 1000 higher), so
    Q2 2025 (own) reads them only from H1 2025 (other)."""
    regs = example_registers()
    moved = tuple(
        replace(
            f,
            period_id="H1_2025",
            carrying_value=f.carrying_value + 1000
            if f.facility_id == "tlb" and f.carrying_value is not None
            else f.carrying_value,
        )
        if f.period_id == "Q2_2025"
        else f
        for f in regs.facilities
    )
    return _bases(replace(regs, facilities=moved), Q2_2025=own, H1_2025=other)


_NOTE_PYTD = (
    f"{OTHER_FOOTING}: H1_2025 (RESTATED, not stated) and "
    "Q2_2025 (AS_REPORTED, not stated)"
)


def _refused(cell: Cell, needle: str) -> None:
    assert (cell.value, cell.reason) == (None, "COMPONENT_MISSING"), cell
    assert needle in (cell.note or ""), cell


def test_a_pytd_debt_frame_across_footings_is_refused() -> None:
    cells = _cells(
        _pytd_regs(("RESTATED", None), ("AS_REPORTED", None)), "PYTD:H1_2025"
    )
    for key in ("total_debt", "fac:tlb", "net_debt"):
        _refused(cells[key], _NOTE_PYTD)


def test_a_quarters_leverage_across_footings_is_refused() -> None:
    cells = _cells(
        _quarter_regs(("RESTATED", None), ("AS_REPORTED", None)), "Q:Q2_2025"
    )
    note = (
        f"{OTHER_FOOTING}: Q2_2025 (RESTATED, not stated) and "
        "H1_2025 (AS_REPORTED, not stated)"
    )
    _refused(cells["total_debt"], note)
    _refused(cells["metric:total_leverage_reported"], note)


@pytest.mark.parametrize(
    ("own", "other"),
    [
        (("RESTATED", None), ("restated", None)),
        (("RESTATED", None), (None, None)),
        ((None, None), ("AS_REPORTED", None)),
        ((None, None), (None, None)),
    ],
)
def test_same_and_absent_footing_debt_reads_are_unchanged(
    own: Footing, other: Footing
) -> None:
    base = _cells(_pytd_regs((None, None), (None, None)), "PYTD:H1_2025")
    assert _cells(_pytd_regs(own, other), "PYTD:H1_2025") == base
    assert base["total_debt"].value == Decimal(14130)
    base = _cells(_quarter_regs((None, None), (None, None)), "Q:Q2_2025")
    assert _cells(_quarter_regs(own, other), "Q:Q2_2025") == base


def test_an_opening_balance_from_another_footing_is_refused() -> None:
    """PYTD H1 2025 (RESTATED) opens on 2024-12-31, where only FY2024 and
    Q4 2024 (AS_REPORTED) have the balances."""
    regs = _bases(
        example_registers(),
        H1_2025=("RESTATED", None),
        FY2024=("AS_REPORTED", None),
        Q4_2024=("AS_REPORTED", None),
    )
    cells = _cells(regs, "PYTD:H1_2025")
    for key in ("cash_opening", "debt_opening"):
        _refused(cells[key], f"{OTHER_FOOTING}: H1_2025 (RESTATED, not stated) and ")
        assert "(AS_REPORTED, not stated)" in (cells[key].note or "")
    base = _cells(_bases(example_registers()), "PYTD:H1_2025")
    assert (base["cash_opening"].value, base["debt_opening"].value) == (
        Decimal(980),
        Decimal(14142),
    )
    same = _cells(
        _bases(
            example_registers(),
            H1_2025=("RESTATED", None),
            FY2024=("restated", None),
            Q4_2024=(None, None),
        ),
        "PYTD:H1_2025",
    )
    assert same == base


_FOOTINGS = st.tuples(
    st.sampled_from([None, "RESTATED", "AS_REPORTED", "IFRS"]),
    st.sampled_from([None, "Consolidated", "Continuing ops"]),
)


def _apart(own: Footing, other: Footing) -> bool:
    return any(
        a is not None and b is not None and a != b
        for a, b in zip(own, other, strict=False)
    )


@settings(max_examples=60, deadline=None)
@given(own=_FOOTINGS, other=_FOOTINGS)
def test_a_debt_read_never_crosses_stated_footings(
    own: Footing, other: Footing
) -> None:
    base = _cells(_pytd_regs((None, None), (None, None)), "PYTD:H1_2025")
    cells = _cells(_pytd_regs(own, other), "PYTD:H1_2025")
    if _apart(own, other):
        for key in ("total_debt", "fac:tlb", "net_debt"):
            assert cells[key].value is None and OTHER_FOOTING in (cells[key].note or "")
    else:
        assert cells == base
    regs = _bases(example_registers(), H1_2025=own, FY2024=other, Q4_2024=other)
    opening = _cells(regs, "PYTD:H1_2025")
    plain = _cells(_bases(example_registers()), "PYTD:H1_2025")
    for key in ("cash_opening", "debt_opening"):
        if _apart(own, other):
            assert opening[key].value is None
        else:
            assert opening[key] == plain[key]


def test_balance_periods_skips_apart_periods_and_names_them() -> None:
    regs = _pytd_regs(("RESTATED", None), ("AS_REPORTED", None))
    read, skipped = balance_periods(regs, "H1_2025", "2025-06-30")
    assert "Q2_2025" not in read and skipped == ("Q2_2025",)
    assert periods_at(regs, "H1_2025", "2025-06-30") == read
    assert footing_note(regs, "H1_2025", "Q2_2025") == _NOTE_PYTD
    assert refused_balance(regs, "H1_2025", skipped) == Cell(
        None, "COMPONENT_MISSING", note=_NOTE_PYTD
    )
    read, skipped = balance_periods(regs, "H1_2025", "2025-06-30", read_own=False)
    assert "H1_2025" not in read and skipped == ("Q2_2025",)
    # A basis a period does not state is named `not stated`, as written.
    unstated = _bases(regs, H1_2025=(None, "Group"), Q2_2025=("IFRS", "Parent"))
    assert footing_note(unstated, "H1_2025", "Q2_2025") == (
        f"{OTHER_FOOTING}: H1_2025 (not stated, Group) and Q2_2025 (IFRS, Parent)"
    )


def test_stated_at_skips_a_period_on_another_footing_and_says_so() -> None:
    """CP-1's stated figure at the opening day: read from a period on the
    column's footing; refused, noted, where only another has it."""
    day = "2025-06-30"
    row = next(
        a
        for a in example_registers().accounts
        if (a.metric_id, a.period_id) == ("total_debt", "Q2_2025")
    )
    same = _pytd_regs((None, None), (None, None))
    read = _stated_at(same, "total_debt", day, "H1_2025")
    assert (read.value, read.basis) == (row.value, "REPORTED")
    assert row.source is not None
    assert [s.cell_text for s in read.sources] == [row.source.cell_text]
    apart = _pytd_regs(("RESTATED", None), ("AS_REPORTED", None))
    assert _stated_at(apart, "total_debt", day, "H1_2025") == refused_balance(
        apart, "H1_2025", ("Q2_2025",)
    )
    # No row for the metric, or a row without a figure: nothing to refuse.
    assert _stated_at(apart, "no_such_metric", day, "H1_2025") == ABSENT
    blank = replace(
        apart,
        accounts=tuple(
            replace(a, value=None) if a.metric_id == "total_debt" else a
            for a in apart.accounts
        ),
    )
    assert _stated_at(blank, "total_debt", day, "H1_2025") == ABSENT


def test_every_facility_only_another_footing_holds_is_refused() -> None:
    regs = _pytd_regs(("RESTATED", None), ("AS_REPORTED", None))
    held = {f.facility_id for f in regs.facilities if f.period_id == "Q2_2025"}
    assert len(held) > 1
    model = credit_model(ModelInputs(regs, None, (), (), None))
    index = [c.column_id for c in model.columns].index("PYTD:H1_2025")
    cells = {line.line_id: line.cells[index] for line in model.lines}
    for facility_id in held:
        _refused(cells[f"fac:{facility_id}"], _NOTE_PYTD)
    columns = tuple(
        c for c in historical_columns(regs) if c.column_id == "PYTD:H1_2025"
    )
    frame = debt_frame(regs, columns, account_frame(regs, columns))["PYTD:H1_2025"]
    assert {k for k in frame if k.startswith("fac:")} == {f"fac:{f}" for f in held}


def test_the_stated_opening_total_on_another_footing_is_refused() -> None:
    """A facility with no row at the opening (a history gap) is checked
    against CP-1's stated total debt there; where only a period on another
    footing states it, the opening is refused with that note, not read."""
    regs = _drop_tlb_history(example_registers())
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if (a.metric_id, a.period_id) != ("total_debt", "Q2_2025")
        ),
    )
    regs = _bases(
        regs,
        LTM_Q2_2026=("RESTATED", None),
        Q2_2025=("restated", None),
        H1_2025=("AS_REPORTED", None),
    )
    opening = _cells(regs, "LTM:LTM_Q2_2026")["debt_opening"]
    _refused(opening, footing_note(regs, "LTM_Q2_2026", "H1_2025"))


def _drop_tlb_history(regs: Cp1Registers) -> Cp1Registers:
    """The term loan written only from Q3 2025 on."""
    early = {"FY2023", "Q1_2024", "Q2_2024", "Q3_2024", "Q4_2024", "FY2024"}
    early |= {"Q1_2025", "Q2_2025"}
    kept = tuple(
        f
        for f in regs.facilities
        if not (f.facility_id == "tlb" and f.period_id in early)
    )
    return replace(regs, facilities=kept)


def test_term_length_is_unknown_for_a_term_that_is_not_a_column() -> None:
    assert _term_length(((None, 1),), {}) is None
    assert _term_length((("FY2025", 1),), {}) is None


# N220 (2)-(4): notes and refusals scoped to the facilities concerned.
_PYTD = "PYTD:H1_2025"


def _debt(regs: Cp1Registers) -> dict[str, Cell]:
    columns = tuple(c for c in historical_columns(regs) if c.column_id == _PYTD)
    return debt_frame(regs, columns, account_frame(regs, columns))[_PYTD]


def _own_holds(regs: Cp1Registers, held: set[str], blank: set[str]) -> Cp1Registers:
    """H1 2025 (RESTATED, the column's own) also holds Q2 2025's (AS_REPORTED)
    rows of the `held` facilities, those in `blank` without a carrying value."""
    copies = tuple(
        replace(
            f,
            period_id="H1_2025",
            carrying_value=None if f.facility_id in blank else f.carrying_value,
        )
        for f in regs.facilities
        if f.period_id == "Q2_2025" and f.facility_id in held
    )
    regs = replace(regs, facilities=(*regs.facilities, *copies))
    return _bases(regs, H1_2025=("RESTATED", None), Q2_2025=("AS_REPORTED", None))


def test_an_own_row_without_a_value_beside_an_apart_twin_is_refused_with_note() -> None:
    """N220 (3): the own period holds the term loan with no carrying value,
    Q2 2025 (another footing) holds 2340: the total is refused, naming both."""
    regs = _own_holds(_pytd_regs((None, None), (None, None)), {"tlb"}, {"tlb"})
    cells = _debt(regs)
    for key in ("total_debt", "secured_debt", "fac:tlb"):
        _refused(cells[key], footing_note(regs, "H1_2025", "Q2_2025"))


def test_only_the_totals_a_refused_facility_feeds_are_refused() -> None:
    """N220 (4): an unsecured note held only on another footing refuses
    `total_debt`, not `secured_debt` or `lease_liabilities`."""
    base = _pytd_regs((None, None), (None, None))
    everyone = {f.facility_id for f in base.facilities if f.period_id == "Q2_2025"}
    regs = _own_holds(base, everyone - {"sun29"}, set())
    cells = _debt(regs)
    _refused(cells["total_debt"], footing_note(regs, "H1_2025", "Q2_2025"))
    _refused(cells["debt_closing"], footing_note(regs, "H1_2025", "Q2_2025"))
    plain = _debt(_pytd_regs((None, None), (None, None)))
    assert cells["secured_debt"].value == plain["secured_debt"].value
    assert cells["lease_liabilities"].reason != "COMPONENT_MISSING"


def _with_lease_and_foreign(regs: Cp1Registers) -> Cp1Registers:
    """Q2 2025 also holds an operating lease (50) and a note in EUR (70)."""
    finl = next(
        f
        for f in regs.facilities
        if (f.facility_id, f.period_id) == ("finl", "Q2_2025")
    )
    sun = next(
        f
        for f in regs.facilities
        if (f.facility_id, f.period_id) == ("sun29", "Q2_2025")
    )
    extra = (
        replace(
            finl,
            facility_id="opl",
            carrying_value=Decimal(50),
            period_id="Q2_2025",
            **_OP,
        ),
        replace(sun, facility_id="eur", carrying_value=Decimal(70), currency="EUR"),
    )
    return replace(regs, facilities=(*regs.facilities, *extra))


@settings(max_examples=60, deadline=None)
@given(kept=st.sets(st.sampled_from(range(11)), min_size=1, max_size=10))
def test_a_total_is_refused_exactly_when_a_facility_feeding_it_is_apart(
    kept: set[int],
) -> None:
    base = _with_lease_and_foreign(_pytd_regs((None, None), (None, None)))
    rows = [f for f in base.facilities if f.period_id == "Q2_2025"]
    held = {rows[i].facility_id for i in kept}
    cells = _debt(_own_holds(base, held, set()))
    for key in ("total_debt", "secured_debt", "lease_liabilities"):
        # An apart row feeds what it would in the register's currency; a held
        # row in another currency feeds nothing.
        apart = [
            r
            for r in rows
            if r.facility_id not in held
            and key in facility_keys(replace(r, currency="USD"), "USD")
        ]
        mine = [
            r for r in rows if r.facility_id in held and key in facility_keys(r, "USD")
        ]
        if apart:
            assert cells[key].reason == "COMPONENT_MISSING", key
            assert OTHER_FOOTING in (cells[key].note or ""), key
        else:
            total = sum((r.carrying_value or Decimal(0) for r in mine), Decimal(0))
            assert cells[key].value == total, key


def test_two_same_day_periods_on_different_footings_merged_are_noted() -> None:
    """N220 (2): the column's own period states none; the stack reads Q2 2025
    (AS_REPORTED) and ALT_2025 (IFRS, holds one senior note)."""
    base = _pytd_regs((None, None), ("AS_REPORTED", None))
    quarter = next(p for p in base.periods if p.period_id == "Q2_2025")
    alt = replace(quarter, period_id="ALT_2025", accounting_basis="IFRS")
    moved = tuple(
        replace(f, period_id="ALT_2025")
        if (f.facility_id, f.period_id) == ("ssn29", "Q2_2025")
        else f
        for f in base.facilities
    )
    regs = replace(base, periods=(*base.periods, alt), facilities=moved)
    cells = _debt(regs)
    note = footing_note(regs, "Q2_2025", "ALT_2025")
    assert cells["total_debt"].value is not None
    assert note in (cells["total_debt"].note or "")
    assert note in (cells["secured_debt"].note or "")  # the moved note is secured
    assert cells["secured_debt"].value is not None
    assert OTHER_FOOTING not in (cells["lease_liabilities"].note or "")


def test_merged_footing_note_names_the_first_apart_pair_in_order() -> None:
    regs = _bases(
        _pytd_regs((None, None), (None, None)),
        H1_2025=("IFRS", None),
        Q2_2025=("US GAAP", None),
        FY2024=("IFRS", None),
    )
    assert merged_footing_note(regs, ["FY2024", "H1_2025"]) is None
    assert merged_footing_note(regs, iter(["FY2024", "H1_2025", "H1_2025"])) is None
    assert merged_footing_note(regs, ["FY2024", "Q2_2025", "H1_2025"]) == footing_note(
        regs, "FY2024", "Q2_2025"
    )
    assert merged_footing_note(regs, []) is None


def test_odd_quarter_names_only_days_outside_89_to_98() -> None:
    assert odd_quarter("Q1_2025", None) is None
    assert [odd_quarter("Q1_2025", n) for n in (89, 98)] == [None, None]
    assert odd_quarter("Q1_2025", 88) == "quarter Q1_2025 of 88 days"
    assert odd_quarter("Q2_2025", 99) == "quarter Q2_2025 of 99 days"


def test_a_total_without_a_figure_is_not_given_the_merge_note() -> None:
    base = _pytd_regs((None, None), ("AS_REPORTED", None))
    quarter = next(p for p in base.periods if p.period_id == "Q2_2025")
    alt = replace(quarter, period_id="ALT_2025", accounting_basis="IFRS")
    regs = replace(base, periods=(*base.periods, alt))
    rows = [f for f in regs.facilities if f.period_id == "Q2_2025"][:2]
    stack = {
        f.facility_id: replace(f, period_id=pid)
        for f, pid in zip(rows, ["Q2_2025", "ALT_2025"], strict=True)
    }
    refused = Cell(None, "COMPONENT_MISSING")
    assert _merged(regs, stack, "total_debt", refused) == refused
    figure = _merged(regs, stack, "total_debt", Cell(Decimal(1), basis="CALCULATED"))
    assert figure.note == footing_note(regs, "Q2_2025", "ALT_2025")


def test_an_opening_stack_merged_across_footings_is_noted() -> None:
    """N220 (2) at the opening (2024-12-31): the column's own period states
    none; Q4 2024 (AS_REPORTED) lacks the 2029 senior note, FY2024 (IFRS)
    has it."""
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if (f.facility_id, f.period_id) != ("sun29", "Q4_2024")
        ),
    )
    regs = _bases(regs, Q4_2024=("AS_REPORTED", None), FY2024=("IFRS", None))
    opened = _debt(regs)["debt_opening"]
    assert opened.value is not None
    assert footing_note(regs, "Q4_2024", "FY2024") in (opened.note or "")


# Fix round 1: the refusal scope covers every skipped row, in the register's
# currency, and the merge note reaches net debt.
_OP: dict[str, Any] = {
    "lease_classification": "OPERATING_LEASE",
    "facility_type": "LEASE",
}


def _edit(
    regs: Cp1Registers, facility: str, period: str, change: dict[str, Any]
) -> Cp1Registers:
    return replace(
        regs,
        facilities=tuple(
            replace(f, **change)
            if (f.facility_id, f.period_id) == (facility, period)
            else f
            for f in regs.facilities
        ),
    )


def _everyone(regs: Cp1Registers) -> set[str]:
    return {f.facility_id for f in regs.facilities if f.period_id == "Q2_2025"}


def test_a_foreign_facility_only_another_footing_holds_refuses_its_totals() -> None:
    """Important 1: a EUR note would have fed `total_debt` (`left_out`); held
    only on another footing, it refuses that total with the note, no other."""
    base = _edit(
        _pytd_regs((None, None), (None, None)), "sun29", "Q2_2025", {"currency": "EUR"}
    )
    regs = _own_holds(base, _everyone(base) - {"sun29"}, set())
    cells = _debt(regs)
    note = footing_note(regs, "H1_2025", "Q2_2025")
    _refused(cells["total_debt"], note)
    _refused(cells["debt_closing"], note)
    assert cells["secured_debt"].value is not None
    assert cells["lease_liabilities"].reason != "COMPONENT_MISSING"


@pytest.mark.parametrize("operating_first", [True, False])
def test_a_facility_on_two_other_footings_refuses_the_union_of_its_totals(
    operating_first: bool,
) -> None:
    """Important 2: finl is an operating lease on Q2 (US GAAP) and a finance
    lease on ALT_Q2 (IFRS), neither the own footing's: both totals refused,
    whichever row comes first."""
    base = _pytd_regs((None, None), (None, None))
    quarter = next(p for p in base.periods if p.period_id == "Q2_2025")
    alt = replace(
        quarter, period_id="ALT_Q2", fiscal_quarter=None, period_type="PERIOD_END"
    )
    finl = next(
        f
        for f in base.facilities
        if (f.facility_id, f.period_id) == ("finl", "Q2_2025")
    )
    operating = replace(finl, **_OP)
    finance = replace(finl, period_id="ALT_Q2")
    rows = [f for f in base.facilities if f is not finl]
    rows += [operating, finance] if operating_first else [finance, operating]
    regs = _own_holds(
        replace(base, periods=(*base.periods, alt), facilities=tuple(rows)),
        _everyone(base) - {"finl"},
        set(),
    )
    regs = _bases(
        regs,
        H1_2025=("RESTATED", None),
        Q2_2025=("US GAAP", None),
        ALT_Q2=("IFRS", None),
    )
    cells = _debt(regs)
    for key in ("total_debt", "lease_liabilities"):
        _refused(cells[key], OTHER_FOOTING)
    assert cells["secured_debt"].value is not None


@pytest.mark.parametrize("twin", [_OP, {"currency": "EUR"}])
def test_an_unvalued_own_row_beside_a_twin_refuses_the_union_of_both_keys(
    twin: dict[str, Any],
) -> None:
    """Minor 3: the own term loan has no carrying value; the apart twin is an
    operating lease (or in EUR): every total either row feeds is refused, with
    every other facility held, so the refusal is the facility's alone."""
    base = _edit(_pytd_regs((None, None), (None, None)), "tlb", "Q2_2025", twin)
    regs = _own_holds(base, _everyone(base), {"tlb"})
    regs = replace(
        regs,
        facilities=tuple(
            replace(
                f,
                lease_classification="NOT_LEASE",
                facility_type="TERM_LOAN",
                currency="USD",
            )
            if (f.facility_id, f.period_id) == ("tlb", "H1_2025")
            else f
            for f in regs.facilities
        ),
    )
    cells = _debt(regs)
    note = footing_note(regs, "H1_2025", "Q2_2025")
    keys = ["total_debt", "secured_debt"] + (
        ["lease_liabilities"] if twin is _OP else []
    )
    for key in keys:
        _refused(cells[key], note)


def test_the_merge_note_reaches_net_debt() -> None:
    """Minor 4: net debt, read from a total noted for a merge, carries it."""
    base = _pytd_regs((None, None), ("AS_REPORTED", None))
    quarter = next(p for p in base.periods if p.period_id == "Q2_2025")
    alt = replace(quarter, period_id="ALT_2025", accounting_basis="IFRS")
    regs = replace(base, periods=(*base.periods, alt))
    regs = _edit(regs, "ssn29", "Q2_2025", {"period_id": "ALT_2025"})
    note = footing_note(regs, "Q2_2025", "ALT_2025")
    cell = _cells(regs, _PYTD)["net_debt"]
    assert cell.value is not None
    assert note in (cell.note or "")
