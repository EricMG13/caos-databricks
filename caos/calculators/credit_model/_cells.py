"""What the credit model's modules share: the Decimal context, the notes,
cell arithmetic, where a balance at a date is read, and which periods are on
another footing.

The anchor is the period at the latest end date of a quarter, YTD or FY: an
FY ending then, else a YTD, else a quarter, first in register order. A period
whose accounting basis or entity perimeter differs from the anchor's (each
compared on case and separators; not stated, on either, matches anything) is
on another footing: it enters no other period's figure (CP-1 and CP-MODEL
never combine them), and a balance read for it is only its own. Whatever the
anchor states, no figure combines two periods that both state a basis, or a
perimeter, and differ (`combined_footing`, pairwise).

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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
from caos.methodology.model_inputs import Cp1Registers, PeriodRow, iso_date

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
# A positive cash tax: CP-1 writes inflows positive, so it is a refund; and a
# sum that took one.
TAX_REFUND = "positive: read as a tax refund"
# A derived period whose components are not distinct, contiguous and its
# exact span; or an LTM whose fiscal year does not meet its YTD and PYTD.
UNSPANNED = "components do not span the period"
# A latest fiscal year that is not twelve whole months is no LTM; `odd_year`
# names it with the period.
SHORT_YEAR = "short fiscal year"
LONG_YEAR = "long fiscal year"
ABSENT = Cell(None, "NOT_SOURCED")  # no row, or a key the frame has no cell for
# A sum that took a part with no row as nothing; `treated_as_zero` names it.
TREATED_AS_ZERO = "not stated, treated as zero"
# A sum refused because a part's row exists but states no figure.
NOT_STATED_PART = "part not stated"
# A figure that would combine a period on another accounting basis or entity
# perimeter than the anchor's (`off_footing`).
OTHER_FOOTING = "accounting basis or perimeter differs"
_RANK = {"FY": 0, "YTD": 1, "QUARTER": 2}  # which period at the anchor date
# A period's accounting basis and entity perimeter (`_footing_key`), each
# None where not stated.
Footing = tuple[str | None, str | None]
UNSTATED_FOOTING: Footing = (None, None)


@dataclass(frozen=True, slots=True)
class Footings:
    """What growth reads of footing (`combined_footing`): the anchor's; each
    column's, of the register periods its figures are read from (None where
    they differ), by column id; and, by quarter column id, the twelve months
    ending it's. A column without one is not stated."""

    anchor: Footing = UNSTATED_FOOTING
    columns: Mapping[str, Footing | None] = field(default_factory=dict)
    windows: Mapping[str, Footing | None] = field(default_factory=dict)


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


def join_notes(notes: tuple[str | None, ...]) -> str | None:
    """The notes as one, each once in order (a note may already join
    several); None without any. One tuple rather than `*notes`: a variadic
    is unbounded positional width, which the suppression budget charges
    (`tests/test_suppression_budget.py`), and a tuple, unlike any iterable,
    cannot be a bare string read a character at a time."""
    kept = dict.fromkeys(
        part for note in notes if note is not None for part in note.split("; ")
    )
    return "; ".join(kept) if kept else None


def treated_as_zero(part: str) -> str:
    """The note on a sum that took `part`, which has no row, as nothing."""
    return f"{TREATED_AS_ZERO} ({part})"


def not_stated(part: str) -> str:
    """The note on a sum refused for `part`, whose row has no figure."""
    return f"{NOT_STATED_PART} ({part})"


# The days a year of 52 or 53 weeks, or a calendar year, spans: twelve months
# beyond them are accepted (`history._twelve_months` allows a fortnight) but
# noted by `odd_length`.
YEAR_DAYS = (364, 371)


def odd_length(days: int | None) -> str | None:
    """The note on twelve months of `days` days outside `YEAR_DAYS` (a 51 or
    54-week year, a 378-day LTM); None inside them or where unknown."""
    if days is None or YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
        return None
    return f"twelve months of {days} days"


# The days a quarter spans (13 or 14 weeks, or a calendar quarter): a quarter
# of 11, 12 or 15 weeks still reads as three months (`history._whole_months`
# allows a fortnight) but is named by `odd_quarter`.
QUARTER_DAYS = (89, 98)


def odd_quarter(days: int | None) -> str | None:
    """The note on a quarter of `days` days outside `QUARTER_DAYS`; None
    inside them or where unknown."""
    if days is None or QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
        return None
    return f"quarter of {days} days"


def odd_year(period_id: str, short: bool) -> str:
    """The note on an LTM that is a fiscal year, `period_id`, of fewer
    (`short`) or more than twelve months."""
    return f"{SHORT_YEAR if short else LONG_YEAR} ({period_id})"


def zeroed(cells: Iterable[Cell]) -> tuple[str, ...]:
    """The cells' `treated_as_zero` notes, in order: a figure built from
    one took the same part as nothing."""
    prefix = f"{TREATED_AS_ZERO} ("
    return tuple(
        part
        for cell in cells
        if cell.note is not None
        for part in cell.note.split("; ")
        if part.startswith(prefix)
    )


def flipped(cell: Cell) -> bool:
    """Whether the cell's figure came from an outflow row CP-1 wrote
    positive."""
    return cell.note is not None and SIGN_NORMALISED in cell.note.split("; ")


def calc(parts: Iterable[tuple[Cell, int]], note: str | None = None) -> Cell:
    """The parts added (+1) or subtracted (-1); `COMPONENT_MISSING` when one
    has no value, noted with why each missing part is missing (its note).
    Noted `SIGN_NORMALISED` where a part was, then with each part a part
    took as nothing (`zeroed`), then `note`."""
    cells = list(parts)
    total = Decimal(0)
    sources: list[SourceRef] = []
    for cell, sign in cells:
        if cell.value is None:
            why = join_notes(
                tuple(part.note for part, _ in cells if part.value is None)
            )
            return Cell(None, "COMPONENT_MISSING", note=why)
        total += cell.value * sign
        sources.extend(cell.sources)
    normalised = any(flipped(cell) for cell, _ in cells)
    noted = join_notes(
        (SIGN_NORMALISED if normalised else None, *zeroed(c for c, _ in cells), note)
    )
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
    ending that day, in register order; none on another footing than the
    anchor's (`off_footing`), and only `own` where it is; none on a footing
    apart from `own`'s (`balance_periods`). None, no period, matches no
    row."""
    return balance_periods(regs, own, day)[0]


def balance_periods(
    regs: Cp1Registers, own: str | None, day: str | None, *, read_own: bool = True
) -> tuple[list[str | None], tuple[str, ...]]:
    """The periods a balance at `day` is read from, and those skipped.
    Read: `own` (unless `read_own` is false, for an opening balance), then
    every period ending that day, in register order, none on another footing
    than the anchor's (`off_footing`), and only `own` where it is. Skipped:
    a period ending that day whose stated basis or perimeter is apart from
    `own`'s (R7, N206); not stated matches anything."""
    off = off_footing(regs)
    if read_own and own in off:
        return [own], ()
    read: list[str | None] = [own] if read_own else []
    skipped: list[str] = []
    for period in regs.periods:
        if not day or period.end_date != day or period.period_id in off:
            continue
        if period.period_id == own:
            continue  # read first above, or an opening's own: no balance there
        if own is not None and _apart_periods(regs, own, period.period_id):
            skipped.append(period.period_id)
        else:
            read.append(period.period_id)
    return read, tuple(skipped)


def _footing_at(regs: Cp1Registers, period_id: str | None) -> Footing:
    for period in regs.periods:
        if period.period_id == period_id:
            return footing_of(period)
    return UNSTATED_FOOTING


def _apart_periods(regs: Cp1Registers, own: str, other: str) -> bool:
    """Whether the two register periods state a different basis or perimeter
    (a period not in the register states none)."""
    pair = (_footing_at(regs, own), _footing_at(regs, other))
    return combined_footing(pair) is None


def _written(regs: Cp1Registers, period_id: str) -> str:
    """The period's id with its basis and perimeter as written, `not stated`
    for one it does not state."""
    for period in regs.periods:
        if period.period_id == period_id:
            basis = period.accounting_basis or "not stated"
            perimeter = period.entity_perimeter or "not stated"
            return f"{period_id} ({basis}, {perimeter})"
    return f"{period_id} (not stated, not stated)"


def footing_note(regs: Cp1Registers, own: str, other: str) -> str:
    """`OTHER_FOOTING`, naming both periods with the footing each states."""
    return f"{OTHER_FOOTING}: {_written(regs, own)} and {_written(regs, other)}"


def refused_balance(
    regs: Cp1Registers, own: str | None, skipped: tuple[str, ...]
) -> Cell:
    """`COMPONENT_MISSING` for a balance only the `skipped` periods (see
    `balance_periods`) hold, noted with the first one's footing and `own`'s."""
    return Cell(
        None, "COMPONENT_MISSING", note=footing_note(regs, str(own), skipped[0])
    )


def merged_footing_note(regs: Cp1Registers, period_ids: Iterable[str]) -> str | None:
    """`footing_note` of the first two of the periods, in order, that state a
    different basis or perimeter (`_apart_periods`); None where none do."""
    seen: list[str] = []
    for period_id in dict.fromkeys(period_ids):
        for earlier in seen:
            if _apart_periods(regs, earlier, period_id):
                return footing_note(regs, earlier, period_id)
        seen.append(period_id)
    return None


def anchor_period(regs: Cp1Registers) -> PeriodRow | None:
    """The period at the latest end date of a quarter, YTD or FY: an FY
    ending then, else a YTD, else a quarter, first in register order. An end
    that is not a `YYYY-MM-DD` date is none (its text would sort anywhere)."""
    candidates = [p for p in regs.periods if p.period_type in _RANK]
    ends = [day.isoformat() for p in candidates if (day := iso_date(p.end_date))]
    if not ends:
        return None
    return min(
        (p for p in candidates if p.end_date == max(ends)),
        key=lambda p: _RANK[p.period_type],
    )


_SEPARATORS = frozenset("_-.")
_NOT_STATED = "notstated"


def _footing_key(text: str | None) -> str | None:
    """`text` casefolded with its whitespace, `_`, `-` and `.` removed, so
    "US GAAP", "USGAAP", "us-gaap" and "U.S. GAAP" are one basis; different
    standards stay different. None for none."""
    if text is None:
        return None
    key = "".join(
        c for c in text.casefold() if not c.isspace() and c not in _SEPARATORS
    )
    return None if key == _NOT_STATED else key


def _differs(text: str | None, anchor: str | None) -> bool:
    """Whether both are stated and differ (`_footing_key`)."""
    first, second = _footing_key(text), _footing_key(anchor)
    return first is not None and second is not None and first != second


def footing_of(period: PeriodRow) -> Footing:
    """The period's accounting basis and entity perimeter, each compared on
    case, spacing and separators (`_footing_key`); None where not stated."""
    return _footing_key(period.accounting_basis), _footing_key(period.entity_perimeter)


def combined_footing(footings: Iterable[Footing | None]) -> Footing | None:
    """The footings as one: its basis, and its perimeter, the one any states
    (None where none does); None where two state different ones, or one is
    None already: no figure combines them. Not stated matches anything, so
    this is pairwise, never only against one of them."""
    merged: list[str | None] = [None, None]
    for footing in footings:
        if footing is None:
            return None
        for index, key in enumerate(footing):
            if key is None:
                continue
            if merged[index] not in (None, key):
                return None
            merged[index] = key
    return merged[0], merged[1]


def uncombined_periods(regs: Cp1Registers) -> frozenset[str]:
    """The periods some figure may not combine with another: those on
    another footing than the anchor's (`off_footing`); and, on a basis or a
    perimeter the anchor does not state (or with no anchor), where two
    periods state different ones, every period that states one."""
    anchor = anchor_period(regs)
    reference = UNSTATED_FOOTING if anchor is None else footing_of(anchor)
    footings = {p.period_id: footing_of(p) for p in regs.periods}
    found = set(off_footing(regs))
    for index, key in enumerate(reference):
        stated = {footing[index] for footing in footings.values()} - {None}
        if key is None and len(stated) > 1:
            found.update(
                i for i, footing in footings.items() if footing[index] is not None
            )
    return frozenset(found)


def off_footing(regs: Cp1Registers) -> frozenset[str]:
    """The periods whose accounting basis or entity perimeter differs from
    the anchor period's (`anchor_period`); not stated matches anything."""
    anchor = anchor_period(regs)
    if anchor is None:
        return frozenset()
    return frozenset(
        p.period_id
        for p in regs.periods
        if _differs(p.accounting_basis, anchor.accounting_basis)
        or _differs(p.entity_perimeter, anchor.entity_perimeter)
    )
