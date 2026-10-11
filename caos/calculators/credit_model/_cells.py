"""What the credit model's modules share: the Decimal context, the notes,
cell arithmetic and where a balance at a date is read.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)

from caos.calculators.credit_model.frame import Cell, Column, SourceRef
from caos.methodology.model_inputs import Cp1Registers, iso_date

CONTEXT = Context(
    prec=38,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
DIFFERS = "differs from CP-1 stated"
FOREIGN = "different currency, not converted"
RESIDUAL = "residual"
# An outflow CP-1 wrote positive, read as minus its absolute value.
SIGN_NORMALISED = "sign normalised"
# A derived period whose components are not distinct, contiguous and its
# exact span; or an LTM whose fiscal year does not meet its YTD and PYTD.
UNSPANNED = "components do not span the period"
ABSENT = Cell(None, "NOT_SOURCED")  # no row, or a key the frame has no cell for


def beyond_rounding(stated: Decimal, host: Decimal) -> bool:
    """Whether `host` differs from `stated` by more than half a unit in the
    last place `stated` was written to."""
    decimals = -int(stated.as_tuple().exponent)
    return abs(stated - host) > Decimal("0.5").scaleb(-decimals)


def no_negative_zero(value: Decimal) -> Decimal:
    """`value`, a negative zero (how "(0)" reads) as zero; exact."""
    return value.copy_abs() if value.is_zero() else value


def refs(sources: Iterable[SourceRef | None]) -> tuple[SourceRef, ...]:
    """The sources in order, each once."""
    return tuple(dict.fromkeys(s for s in sources if s is not None))


def join_notes(*notes: str | None) -> str | None:
    """The notes as one, each once in order (a note may already join
    several); None without any."""
    kept = dict.fromkeys(
        part for note in notes if note is not None for part in note.split("; ")
    )
    return "; ".join(kept) if kept else None


def flipped(cell: Cell) -> bool:
    """Whether the cell's figure came from an outflow row CP-1 wrote
    positive."""
    return cell.note is not None and SIGN_NORMALISED in cell.note.split("; ")


def calc(parts: Iterable[tuple[Cell, int]], note: str | None = None) -> Cell:
    """The parts added (+1) or subtracted (-1); `COMPONENT_MISSING` when one
    has no value. Noted `SIGN_NORMALISED` where a part was, then `note`."""
    cells = list(parts)
    total = Decimal(0)
    sources: list[SourceRef] = []
    for cell, sign in cells:
        if cell.value is None:
            return Cell(None, "COMPONENT_MISSING")
        total += cell.value * sign
        sources.extend(cell.sources)
    normalised = any(flipped(cell) for cell, _ in cells)
    noted = join_notes(SIGN_NORMALISED if normalised else None, note)
    return Cell(total, basis="CALCULATED", sources=refs(sources), note=noted)


def opening_date(column: Column) -> str | None:
    """The day before the column starts: its end date less its days; None
    where either is unknown, the end is not a `YYYY-MM-DD` date, the days are
    not positive, or no calendar day is that far back."""
    end = iso_date(column.end_date)
    if end is None or column.days is None or column.days < 1:
        return None
    opening = end.toordinal() - column.days
    return date.fromordinal(opening).isoformat() if opening >= 1 else None


def periods_at(
    regs: Cp1Registers, own: str | None, day: str | None
) -> list[str | None]:
    """Where a balance at `day` is read: `own` first, then every period
    ending that day, in register order. None, no period, matches no row."""
    return [own, *(p.period_id for p in regs.periods if day and p.end_date == day)]
