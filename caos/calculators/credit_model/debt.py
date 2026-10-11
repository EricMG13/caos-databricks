"""The debt stack over the historical columns: totals, payment ranks, the
roll-forward and the undrawn revolver.

A column's stack is CP-1's facility rows at its end date: the column's own
period first, then any period ending that day, in register order (the balance
rule `history` reads). Totals use carrying values. `total_debt` is every row
but an `OPERATING_LEASE` (finance leases included), plus a `DEBT ADJUSTMENT`
row however it is classified; `lease_liabilities` is the operating leases.
CP-1's `total_debt` account excludes every lease, so the host's total less its
finance leases is what is compared with it (`stated`). A row in a currency
other than the register's enters no total (spec B13: no FX); its `fac:` cell
keeps its figure, noted, and each total it would have entered, with the
roll-forward line it reads, is noted "excludes facility in another currency".
A `DEBT ADJUSTMENT` row is the one CP-1 writes with
`facility_type` `DEBT ADJUSTMENT` (REF_CP-1_STEPS, debt register; CP-MODEL's
validator reads the same column).

The roll-forward opens at the stack on the day before the column starts (its
end date less its days) and closes at the column's own; `debt_non_cash` is the
residual after the net debt raised in the cash flow statement, noted with
what its closing or opening leaves out. Where the
opening date has facility rows but none for a facility the closing stack
counts in total debt, the opening is `COMPONENT_MISSING`, noted "opening
stack incomplete" (a part-written stack is no opening balance). A facility
whose every row is in a period ending after the opening date is a new issue,
nil at the opening, only where CP-1's `total_debt` stated at the opening date
agrees, within its rounding, with the opening stack less its finance leases;
otherwise CP-1 left out the facility's history, and the opening is that stated
figure plus those finance leases, noted "facility history incomplete" (as is
the residual read from it). Without a stated figure, or with a facility in
another currency left out of the opening (CP-1's figure is then on another
footing), the opening is `COMPONENT_MISSING`, noted the same.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal, localcontext

from caos.calculators.credit_model._cells import (
    ABSENT,
    CONTEXT,
    DIFFERS,
    FOREIGN,
    RESIDUAL,
    beyond_rounding,
    calc,
    join_notes,
    no_negative_zero,
    opening_date,
    periods_at,
    refs,
    zeroed,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame, SourceRef
from caos.methodology.model_inputs import Cp1Registers, FacilityRow, iso_date

PAYMENT_RANKS: tuple[str, ...] = (
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
SECURED_RANKS = frozenset({"Super senior", "Senior secured"})
_DEBT_ADJUSTMENT = "DEBT ADJUSTMENT"
EXCLUDES_FOREIGN = "excludes facility in another currency"
EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"
OPENING_INCOMPLETE = "opening stack incomplete"
HISTORY_INCOMPLETE = "facility history incomplete"
# The notes a figure passes to every figure read from it: what it leaves out.
_CARRIED = (EXCLUDES_FOREIGN, EXCLUDES_UNALLOCATED)

# A senior row's rank by its security; super senior debt is only "Super
# senior" where it is secured, so `secured_debt` never counts unsecured or
# unstated security (REF_CP-1_STEPS: NOT_STATED is no evidence of security).
_SENIOR = {
    "SECURED": "Senior secured",
    "UNSECURED": "Senior unsecured",
}
_JUNIOR = {
    "SENIOR_SUBORDINATED": "Subordinated",
    "SUBORDINATED": "Subordinated",
    "JUNIOR": "Junior",
}
_STACK_KEYS = ("total_debt", "lease_liabilities", "secured_debt")


def notes_of(note: str | None) -> tuple[str, ...]:
    """A cell's note as its component notes: a compound note is joined with
    "; ", which no note contains."""
    return () if note is None else tuple(note.split("; "))


def carried(cells: Iterable[Cell]) -> str | None:
    """What the cells leave out ("excludes facility in another currency",
    "excludes unallocated CP-CF movements", then each part taken as nothing:
    `zeroed`), for a figure read from them."""
    kept = list(cells)
    found = {part for cell in kept for part in notes_of(cell.note)}
    leaves = (note for note in _CARRIED if note in found)
    return join_notes((*leaves, *zeroed(kept)))


def is_operating_lease(row: FacilityRow) -> bool:
    """Whether the row is an operating lease: classified so and not a `DEBT
    ADJUSTMENT` row (one is debt however it is classified)."""
    return (
        row.lease_classification == "OPERATING_LEASE"
        and row.facility_type != _DEBT_ADJUSTMENT
    )


def payment_rank(row: FacilityRow) -> str:
    """The row's place in `PAYMENT_RANKS`: a debt adjustment, a finance lease,
    then by seniority and security. A seniority outside CP-1's values ranks
    "Not stated", the bucket CP-1 keeps out of every secured or senior
    subtotal. An operating lease ranks like any row; it enters no rank's
    total (`facility_keys`)."""
    if row.facility_type == _DEBT_ADJUSTMENT:
        return "Debt adjustments"
    if row.lease_classification == "FINANCE_LEASE":
        return "Finance leases"
    if row.seniority in {"SUPER_SENIOR", "SENIOR"}:
        if row.seniority == "SUPER_SENIOR" and row.secured_status == "SECURED":
            return "Super senior"
        return _SENIOR.get(row.secured_status, "Senior, security not stated")
    return _JUNIOR.get(row.seniority, "Not stated")


def facility_keys(row: FacilityRow, currency: str) -> frozenset[str]:
    """The totals the row's carrying value enters: none in another currency,
    `lease_liabilities` for an operating lease, else `total_debt` and, ranked
    super senior or senior secured, `secured_debt`."""
    if row.currency != currency:
        return frozenset()
    if is_operating_lease(row):
        return frozenset({"lease_liabilities"})
    if payment_rank(row) in SECURED_RANKS:
        return frozenset({"total_debt", "secured_debt"})
    return frozenset({"total_debt"})


def _stack_at(
    regs: Cp1Registers, period_ids: list[str | None]
) -> dict[str, FacilityRow]:
    """Each facility's row at the first of `period_ids` with a carrying value,
    else at the first with a row; register order."""
    found: dict[str, FacilityRow] = {}
    for period_id in period_ids:
        for row in regs.facilities:
            held = found.get(row.facility_id)
            if row.period_id == period_id and (
                held is None or held.carrying_value is None
            ):
                found[row.facility_id] = row
    return found


def _stack_totals(
    rows: Iterable[tuple[FacilityRow, Decimal | None]], currency: str
) -> dict[str, Cell]:
    """`total_debt`, `lease_liabilities` and `secured_debt` of (row, carrying
    value) pairs; a total one of its rows has no value for is
    `COMPONENT_MISSING`, and with no rows at all each is `NOT_SOURCED`."""
    pairs = list(rows)
    if not pairs:
        return {key: Cell(None, "NOT_SOURCED") for key in _STACK_KEYS}
    sums = dict.fromkeys(_STACK_KEYS, Decimal(0))
    missing: set[str] = set()
    sources: dict[str, list[SourceRef | None]] = {key: [] for key in _STACK_KEYS}
    for row, value in pairs:
        for key in facility_keys(row, currency):
            if value is None:
                missing.add(key)
                continue
            sums[key] += value
            sources[key].append(row.source)
    return {
        key: Cell(None, "COMPONENT_MISSING")
        if key in missing
        else Cell(sums[key], basis="CALCULATED", sources=refs(sources[key]))
        for key in _STACK_KEYS
    }


def _fac_cell(row: FacilityRow, currency: str) -> Cell:
    note = FOREIGN if row.currency != currency else None
    if row.carrying_value is None:
        return Cell(None, "NOT_STATED", note=note)
    sources = refs([row.source])
    value = no_negative_zero(row.carrying_value)
    return Cell(value, basis="REPORTED", sources=sources, note=note)


def _stated_total(
    total: Cell, leases: list[FacilityRow], stated: Cell, currency: str
) -> Cell:
    """`total` with CP-1's `total_debt` as `stated`, noted where it differs
    beyond its rounding from the total less the finance `leases` in it."""
    figure = stated.value  # a balance: CP-1's figure or none, never `stated`
    if figure is None or total.value is None:
        return replace(total, stated=figure)
    in_total = (
        row.carrying_value
        for row in leases
        if "total_debt" in facility_keys(row, currency)
    )
    excluded = sum(value for value in in_total if value is not None)
    differs = beyond_rounding(figure, total.value - excluded)
    note = DIFFERS if differs else None
    return Cell(total.value, None, total.basis, figure, total.sources, note)


def _account(accounts: dict[str, Cell], metric_id: str) -> Cell:
    return accounts.get(f"acct:{metric_id}", ABSENT)


def left_out(rows: Iterable[FacilityRow], currency: str) -> frozenset[str]:
    """The totals (`facility_keys`) the rows in another currency would have
    entered in `currency`."""
    return frozenset(
        key
        for row in rows
        if row.currency != currency
        for key in facility_keys(replace(row, currency=currency), currency)
    )


def _excluding(cell: Cell, key: str, excluded: frozenset[str]) -> Cell:
    """`cell`, its figure noted where a row in another currency is left out
    of the `key` total."""
    if key not in excluded or cell.value is None:
        return cell
    return replace(cell, note=join_notes((cell.note, EXCLUDES_FOREIGN)))


def _issued_after(regs: Cp1Registers, facility_id: str, day: str | None) -> bool:
    """Whether every row of the facility is in a period ending after `day`
    (a facility first issued after it); not where a row's period has no end
    date or `day` is unknown."""
    after = iso_date(day)
    if after is None:
        return False
    ends = {p.period_id: iso_date(p.end_date) for p in regs.periods}
    rows = [
        ends.get(r.period_id) for r in regs.facilities if r.facility_id == facility_id
    ]
    return all(end is not None and end > after for end in rows)


def _opening_debt(
    regs: Cp1Registers,
    day: str | None,
    stack: dict[str, FacilityRow],
    opening: dict[str, FacilityRow],
) -> Cell:
    """Total debt at the opening `day`; `COMPONENT_MISSING`, noted, where the
    opening has rows but none for a facility in the closing's total debt that
    was issued by then; checked against CP-1's stated figure
    (`_without_history`) where a facility has no row by then."""
    currency = regs.currency
    closing = {
        facility_id
        for facility_id, row in stack.items()
        if "total_debt" in facility_keys(row, currency)
    }
    issued = {f for f in closing if _issued_after(regs, f, day)}
    if opening and not closing - issued <= opening.keys():
        return Cell(None, "COMPONENT_MISSING", note=OPENING_INCOMPLETE)
    total = _stack_totals(
        ((row, row.carrying_value) for row in opening.values()), currency
    )["total_debt"]
    total = _excluding(total, "total_debt", left_out(opening.values(), currency))
    if not opening or not issued or total.value is None:
        return total
    return _without_history(regs, day, total, opening)


def _stated_at(regs: Cp1Registers, metric_id: str, day: str | None) -> Cell:
    """CP-1's figure for the account at `day`: the first row with one, of a
    period ending that day, in register order; `NOT_SOURCED` without one."""
    for period_id in periods_at(regs, None, day):
        for row in regs.accounts:
            if (row.metric_id, row.period_id) == (metric_id, period_id) and (
                row.value is not None
            ):
                value = no_negative_zero(row.value)
                return Cell(value, basis="REPORTED", sources=refs([row.source]))
    return ABSENT


def _without_history(
    regs: Cp1Registers, day: str | None, total: Cell, opening: dict[str, FacilityRow]
) -> Cell:
    """The opening `total`, where facilities in the closing stack have no row
    by `day`: kept (they are new issues) where CP-1's `total_debt` at `day`
    agrees with it less its finance leases; else that figure plus the leases,
    noted `HISTORY_INCOMPLETE`; `COMPONENT_MISSING`, noted, without a stated
    figure or where `total` leaves out a facility in another currency."""
    stated = _stated_at(regs, "total_debt", day)
    missing = Cell(None, "COMPONENT_MISSING", note=HISTORY_INCOMPLETE)
    if stated.value is None or EXCLUDES_FOREIGN in notes_of(total.note):
        return missing
    leases = [
        row
        for row in opening.values()
        if row.lease_classification == "FINANCE_LEASE"
        and "total_debt" in facility_keys(row, regs.currency)
    ]
    lease_cells = [(_fac_cell(row, regs.currency), 1) for row in leases]
    in_leases = calc(lease_cells)
    if total.value is None or in_leases.value is None:
        return missing
    if not beyond_rounding(stated.value, total.value - in_leases.value):
        return total
    return calc([(stated, 1), *lease_cells], HISTORY_INCOMPLETE)


def _history(cell: Cell) -> tuple[str, ...]:
    """`HISTORY_INCOMPLETE` where the cell is noted so: a figure read from
    it keeps it."""
    return (HISTORY_INCOMPLETE,) if HISTORY_INCOMPLETE in notes_of(cell.note) else ()


def _column_debt(
    regs: Cp1Registers, column: Column, accounts: dict[str, Cell]
) -> dict[str, Cell]:
    currency = regs.currency
    stack = _stack_at(regs, periods_at(regs, column.period_id, column.end_date))
    day = opening_date(column)
    opening = _stack_at(regs, periods_at(regs, None, day))
    cells = {
        f"fac:{facility_id}": _fac_cell(row, currency)
        for facility_id, row in stack.items()
    }
    excluded = left_out(stack.values(), currency)
    raw = _stack_totals(((row, row.carrying_value) for row in stack.values()), currency)
    totals = {key: _excluding(cell, key, excluded) for key, cell in raw.items()}
    leases = [
        row
        for row in stack.values()
        if row.lease_classification == "FINANCE_LEASE"
        and row.facility_type != _DEBT_ADJUSTMENT
    ]
    stated = _account(accounts, "total_debt")
    total = _excluding(
        _stated_total(raw["total_debt"], leases, stated, currency),
        "total_debt",
        excluded,
    )
    opened = _opening_debt(regs, day, stack, opening)
    raised = _account(accounts, "net_debt_issue_repay")
    undrawn = (
        (_account(accounts, "rcf_commitment"), 1),
        (_account(accounts, "rcf_drawn"), -1),
    )
    cells.update(
        total_debt=total,
        lease_liabilities=totals["lease_liabilities"],
        secured_debt=totals["secured_debt"],
        undrawn_rcf=calc(undrawn),
        debt_opening=opened,
        debt_closing=totals["total_debt"],
        debt_non_cash=calc(
            ((total, 1), (opened, -1), (raised, -1)),
            join_notes((RESIDUAL, *_history(opened), carried((total, opened)))),
        ),
    )
    return cells


def debt_frame(
    regs: Cp1Registers, columns: tuple[Column, ...], accounts: Frame
) -> Frame:
    """Each column's `fac:` cells, `total_debt`, `lease_liabilities`,
    `secured_debt`, `undrawn_rcf` and the roll-forward: `debt_opening`,
    `debt_non_cash` (residual) and `debt_closing`; `accounts` is
    `account_frame` over `columns`."""
    with localcontext(CONTEXT):
        return {
            column.column_id: _column_debt(regs, column, accounts[column.column_id])
            for column in columns
        }
