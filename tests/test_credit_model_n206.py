"""N206 (R7) at the `credit_model` level: a balance read across stated
footings is refused, with a note naming both, in the debt frame, leverage and
the opening balances; the same footing and an unstated one read as before."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from credit_model_fixture import example_registers
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model._cells import (
    OTHER_FOOTING,
    balance_periods,
    footing_note,
    periods_at,
)
from caos.calculators.credit_model.assemble import ModelInputs, credit_model
from caos.calculators.credit_model.frame import Cell
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


def _refused(cell: Cell, fragment: str) -> None:
    assert (cell.value, cell.reason) == (None, "COMPONENT_MISSING"), cell
    assert fragment in (cell.note or ""), cell


def test_a_pytd_debt_frame_across_footings_is_refused() -> None:
    cells = _cells(_pytd_regs(("RESTATED", None), ("AS_REPORTED", None)), "PYTD:H1_2025")
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
    assert (base["cash_opening"].value, base["debt_opening"].value) == (980, 14142)
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
    return any(a is not None and b is not None and a != b for a, b in zip(own, other))


@settings(max_examples=60, deadline=None)
@given(own=_FOOTINGS, other=_FOOTINGS)
def test_a_debt_read_never_crosses_stated_footings(own: Footing, other: Footing) -> None:
    base = _cells(_pytd_regs((None, None), (None, None)), "PYTD:H1_2025")
    cells = _cells(_pytd_regs(own, other), "PYTD:H1_2025")
    if _apart(own, other):
        for key in ("total_debt", "fac:tlb", "net_debt"):
            assert cells[key].value is None and OTHER_FOOTING in (cells[key].note or "")
    else:
        assert cells == base
    regs = _bases(
        example_registers(), H1_2025=own, FY2024=other, Q4_2024=other
    )
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
    read, skipped = balance_periods(regs, "H1_2025", "2025-06-30", read_own=False)
    assert "H1_2025" not in read and skipped == ("Q2_2025",)
