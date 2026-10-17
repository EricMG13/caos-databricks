"""The credit model's shared cell arithmetic and balance dates."""

from __future__ import annotations

import ast
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from credit_model_fixture import example_registers
from hypothesis import given
from hypothesis import strategies as st

from caos.calculators.credit_model import _cells
from caos.calculators.credit_model._cells import (
    SIGN_NORMALISED,
    UNSTATED_FOOTING,
    Footing,
    beyond_rounding,
    calc,
    combined_footing,
    flipped,
    footing_of,
    join_notes,
    no_negative_zero,
    opening_date,
    periods_at,
    refs,
    treated_as_zero,
    uncombined_periods,
    zeroed,
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


def test_calc_names_why_a_part_is_missing_on_its_missing_sum() -> None:
    why = Cell(None, "COMPONENT_MISSING", note="components do not span the period")
    other = Cell(None, "COMPONENT_MISSING", note="opening stack incomplete")
    one = Cell(Decimal(1), basis="REPORTED", note="residual")
    assert calc(((one, 1), (why, -1))) == Cell(None, "COMPONENT_MISSING", note=why.note)
    assert calc(((why, 1), (other, 1), (why, 1))).note == f"{why.note}; {other.note}"
    # The sum's own note says how a figure was found; there is none.
    assert calc(((one, 1), (why, 1)), "residual").note == why.note
    assert calc(((one, 1), (Cell(None, "NOT_STATED"), 1)), "residual") == Cell(
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


def test_zeroed_reads_each_part_taken_as_nothing_and_calc_carries_them() -> None:
    q2, q4 = treated_as_zero("Q2_2025"), treated_as_zero("Q4_2025")
    one = Cell(Decimal(3), note=f"residual; {q2}")
    two = Cell(Decimal(4), note=f"{q4}; {q2}")
    assert zeroed([one, two, Cell(Decimal(1))]) == (q2, q4, q2)
    assert zeroed([Cell(Decimal(1), note="not stated, treated as zeros")]) == ()
    assert zeroed([]) == ()
    flipped = Cell(Decimal(-5), note=SIGN_NORMALISED)
    assert calc(((one, 1), (two, -1), (flipped, 1)), "residual").note == (
        f"{SIGN_NORMALISED}; {q2}; {q4}; residual"
    )
    # A missing sum names why each part is missing, not what others took.
    assert calc(((one, 1), (Cell(None, "NOT_STATED"), 1))).note is None


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


def test_footing_of_reads_basis_and_perimeter_as_compared() -> None:
    period = replace(
        example_registers().periods[0],
        accounting_basis="US_GAAP",
        entity_perimeter=" Continuing-Operations ",
    )
    assert footing_of(period) == ("usgaap", "continuingoperations")
    unstated = replace(period, accounting_basis=None, entity_perimeter=None)
    assert footing_of(unstated) == UNSTATED_FOOTING == (None, None)


def test_combined_footing_takes_what_is_stated_and_refuses_two() -> None:
    assert combined_footing([]) == UNSTATED_FOOTING
    assert combined_footing([("a", None), (None, "p"), ("a", None)]) == ("a", "p")
    assert combined_footing([("a", None), (None, None), ("b", None)]) is None
    assert combined_footing([(None, "p"), ("a", "q")]) is None
    assert combined_footing([("a", "p"), None]) is None  # already refused
    assert combined_footing([("", None), (None, None)]) == ("", None)
    assert combined_footing([("", None), ("a", None)]) is None


_KEYS = st.sampled_from([None, "a", "b"])


@given(st.lists(st.tuples(_KEYS, _KEYS), max_size=6))
def test_combined_footing_is_pairwise(footings: list[Footing]) -> None:
    """None exactly where two footings state one basis, or one perimeter,
    differently; else each the one stated."""
    clash = any(
        x[i] is not None and y[i] is not None and x[i] != y[i]
        for x in footings
        for y in footings
        for i in (0, 1)
    )
    result = combined_footing(footings)
    if clash:
        assert result is None
    else:
        stated = [
            next((f[i] for f in footings if f[i] is not None), None) for i in (0, 1)
        ]
        assert result == (stated[0], stated[1])


def test_uncombined_periods_add_pairs_the_anchor_does_not_state() -> None:
    regs = example_registers()

    def footed(**bases: tuple[str | None, str | None]) -> frozenset[str]:
        periods = tuple(
            replace(
                p,
                accounting_basis=bases.get(p.period_id, (None, None))[0],
                entity_perimeter=bases.get(p.period_id, (None, None))[1],
            )
            for p in regs.periods
        )
        return uncombined_periods(replace(regs, periods=periods))

    assert footed() == frozenset()
    # The anchor (H1 2026) states the basis: only those off it.
    assert footed(H1_2026=("A", None), FY2025=("B", None), FY2024=("A", None)) == {
        "FY2025"
    }
    # It states none: every period stating one, where two differ.
    assert footed(FY2025=("A", None), H1_2025=("B", None), FY2024=("A", None)) == {
        "FY2025",
        "H1_2025",
        "FY2024",
    }
    assert footed(FY2025=("A", None), FY2024=("A", None)) == frozenset()
    # Perimeters the anchor does not state, beside a basis it does.
    assert footed(
        H1_2026=("A", None), FY2025=("A", "p"), H1_2025=("A", "q"), FY2024=("A", None)
    ) == {"FY2025", "H1_2025"}
    # No anchor: pairs alone.
    assert uncombined_periods(replace(regs, periods=())) == frozenset()
    undated = tuple(
        replace(p, end_date=None, accounting_basis=b)
        for p, b in zip(regs.periods[:2], ("A", "B"), strict=True)
    )
    assert uncombined_periods(replace(regs, periods=undated)) == {
        regs.periods[0].period_id,
        regs.periods[1].period_id,
    }


def _footed(basis: str | None, perimeter: str | None = None) -> Footing:
    period = replace(
        example_registers().periods[0],
        accounting_basis=basis,
        entity_perimeter=perimeter,
    )
    return footing_of(period)


def test_basis_spellings_differ_only_in_spacing_case_and_separators_are_one() -> None:
    """N208: "US GAAP" = "USGAAP" = "us-gaap" = "U.S._GAAP"; different
    standards stay different."""
    same = ["US GAAP", "USGAAP", "us-gaap", "US_GAAP", " us  gaap ", "U.S. GAAP"]
    assert len({_footed(text) for text in same}) == 1
    assert _footed("Continuing ops", "Group") == _footed("ContinuingOps", "group")
    for first, second in (
        ("US GAAP", "IFRS"),
        ("US GAAP", "GAAP"),
        ("UK GAAP", "US GAAP"),
    ):
        assert _footed(first) != _footed(second)
    assert _footed(None)[0] is None


@given(
    st.sampled_from(["US GAAP", "IFRS", "UK GAAP", "Continuing operations"]),
    st.lists(st.sampled_from([" ", "_", "-", ".", "  "]), min_size=3, max_size=3),
    st.booleans(),
)
def test_a_basis_is_unchanged_by_respacing_recasing_and_separators(
    text: str, separators: list[str], upper: bool
) -> None:
    words = text.split(" ")
    glued = separators[0].join(words)
    glued = glued.upper() if upper else glued.lower()
    assert _footed(glued) == _footed(text)


def test_footing_of_reads_not_stated_as_not_stated() -> None:
    period = replace(
        example_registers().periods[0],
        accounting_basis="Not stated",
        entity_perimeter=" NOT  stated ",
    )
    assert footing_of(period) == UNSTATED_FOOTING
