"""The credit model's shared cell arithmetic and balance dates."""

from __future__ import annotations

import ast
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from credit_model_fixture import example_registers

from caos.calculators.credit_model import _cells
from caos.calculators.credit_model._cells import (
    SIGN_NORMALISED,
    beyond_rounding,
    calc,
    flipped,
    join_notes,
    no_negative_zero,
    opening_date,
    periods_at,
    refs,
)
from caos.calculators.credit_model.frame import Cell, Column, SourceRef

_A = SourceRef("S1", "here", "1")
_B = SourceRef("S2", "there", "2")


def test_beyond_rounding_is_half_a_unit_in_the_stated_last_place() -> None:
    assert not beyond_rounding(Decimal("1.0"), Decimal("1.05"))
    assert beyond_rounding(Decimal("1.0"), Decimal("1.06"))
    assert not beyond_rounding(Decimal(10), Decimal("10.5"))
    assert beyond_rounding(Decimal(10), Decimal("9.4"))


def test_refs_keep_each_source_once_in_order() -> None:
    assert refs([_B, None, _A, _B]) == (_B, _A)


def test_calc_adds_and_subtracts_or_is_component_missing() -> None:
    one = Cell(Decimal(5), basis="REPORTED", sources=(_A,))
    two = Cell(Decimal(2), basis="REPORTED", sources=(_B, _A))
    assert calc(((one, 1), (two, -1)), "residual") == Cell(
        Decimal(3), basis="CALCULATED", sources=(_A, _B), note="residual"
    )
    assert calc(((one, 1), (Cell(None, "NOT_SOURCED"), 1))) == Cell(
        None, "COMPONENT_MISSING"
    )


def test_opening_date_and_the_periods_a_balance_is_read_at() -> None:
    column = Column("Q:X", "QUARTER", "Q2 26", "X", "2026", "2026-06-30", 91, None)
    assert opening_date(column) == "2026-03-31"
    assert opening_date(replace(column, days=None)) is None
    assert opening_date(replace(column, end_date=None)) is None
    regs = example_registers()
    assert periods_at(regs, "H1_2026", "2026-06-30") == [
        "H1_2026",
        "Q2_2026",
        "H1_2026",
        "LTM_Q2_2026",
    ]
    assert periods_at(regs, None, None) == [None]


@pytest.mark.parametrize(
    ("end_date", "days"),
    [
        ("31/12/2025", 365),
        ("2025-12-31T00:00:00", 365),
        ("20251231", 365),
        ("2025-02-30", 1),
        ("2026-06-30", 800000),
        ("2026-06-30", -90),
        ("2026-06-30", 0),
        ("0001-01-01", 1),
        ("9999-12-31", -1),
    ],
)
def test_opening_date_is_none_where_there_is_no_such_day(
    end_date: str, days: int
) -> None:
    column = Column("Q:X", "QUARTER", "Q2 26", "X", "2026", end_date, days, None)
    assert opening_date(column) is None


def test_opening_date_reaches_the_first_representable_day() -> None:
    column = Column("Q:X", "QUARTER", "Q", "X", "0001", "0001-01-02", 1, None)
    assert opening_date(column) == "0001-01-01"


def test_join_notes_keeps_each_note_once_in_order() -> None:
    assert join_notes(()) is None
    assert join_notes((None, None)) is None
    assert join_notes(("a", None, "b", "a")) == "a; b"
    assert join_notes(("a; b", "b", "c")) == "a; b; c"


def test_calc_carries_a_sign_normalised_part_and_no_other_note() -> None:
    flipped = Cell(Decimal(-5), basis="REPORTED", note=SIGN_NORMALISED)
    other = Cell(Decimal(2), basis="REPORTED", note="differs from CP-1 stated")
    both = Cell(Decimal(1), note=f"{SIGN_NORMALISED}; residual")
    assert calc(((flipped, 1), (other, 1))).note == SIGN_NORMALISED
    assert calc(((other, 1),)).note is None
    assert calc(((both, -1),)).note == SIGN_NORMALISED
    assert calc(((flipped, 1),), "residual").note == f"{SIGN_NORMALISED}; residual"
    assert calc(((flipped, 1), (Cell(None, "NOT_SOURCED"), 1))) == Cell(
        None, "COMPONENT_MISSING"
    )


def test_flipped_reads_the_sign_note_among_others() -> None:
    assert flipped(Cell(Decimal(-1), note=SIGN_NORMALISED))
    assert flipped(Cell(Decimal(-1), note=f"residual; {SIGN_NORMALISED}"))
    assert not flipped(Cell(Decimal(-1)))
    assert not flipped(Cell(Decimal(-1), note="residual"))
    assert not flipped(Cell(Decimal(-1), note=f"{SIGN_NORMALISED} twice"))


# Limitations the model lists whole, never joined into a cell's note.
_LIMITATIONS = frozenset({"NO_PROJECTIONS", "NOT_APPLIED", "DOUBLE_COUNT"})


def _note_constants() -> dict[str, str]:
    """Every module-level string constant in the credit model's modules, by
    module and name: the notes, among others."""
    package = Path(_cells.__file__).parent
    found: dict[str, str] = {}
    for module in sorted(package.glob("*.py")):
        for node in ast.parse(module.read_text()).body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and target.id not in _LIMITATIONS
                ):
                    found[f"{module.stem}.{target.id}"] = value.value
    return found


def test_no_note_contains_the_note_separator() -> None:
    notes = _note_constants()

    assert notes["_cells.FOREIGN"] == "different currency, not converted"
    assert {name for name, text in notes.items() if "; " in text} == set()
    assert join_notes((_cells.FOREIGN, "held flat")) == (
        "different currency, not converted; held flat"
    )


def test_no_negative_zero_reads_a_parenthesised_zero_as_zero() -> None:
    for written, read in (("-0", "0"), ("-0.00", "0.00"), ("0", "0"), ("-1", "-1")):
        value = no_negative_zero(Decimal(written))
        assert (str(value), value.is_signed()) == (read, read.startswith("-"))
