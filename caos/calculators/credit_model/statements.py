"""The statements over the historical columns: the income statement to
adjusted EBITDAR, the cash flow waterfall, the net cash flow, liquidity, the
debt totals, working capital, and the pro forma LTM.

Outflows are negative in the frame. Each expense or outflow account in
`OUTFLOW_METRICS` is read as minus its absolute value (`account_frame` does
so row by row, before any sum), so a CP-1 run that wrote them positive reads
the same; a signed flow keeps CP-1's sign (cash taxes among them: a positive
one is a refund, CP-1's sign convention, served noted `TAX_REFUND`, where a
model that wrote its outflow positive shows). A line
the host recomputes where CP-1 states its own figure (gross profit, EBIT,
EBITDA, adjusted EBITDA) carries that figure as `stated`, noted where it
differs beyond its rounding. Three lines are residuals the host calculates and
never reads from CP-1: `other_operating` (so FFO plus the working-capital
change is the adjusted CFO), `other_investing_financing` (so the net cash
flow is CP-1's net cash change) and `fx_and_other_cash` (so opening cash plus
the net cash flow reaches closing cash); `debt.py` adds `debt_non_cash`.

The `acct:` keys are CP-1's cells from `account_frame`, outflows already
negative; the lines are the fixed keys (`cogs`, `da`, `capex` ...).

Adjusted CFO moves the lease payments and interest CP-1 classes in financing
into operating cash flow; where CP-1 has no row for either over the column's
periods it counts as zero there and in FFO. An add-back with no row for the
column's periods adds nothing to adjusted EBITDA (its `addback:` cell stays
`NOT_SOURCED`), and a PF adjustment to a facility the LTM has no balance for
adds to nothing. Each such sum, and every figure built from it, is noted
"not stated, treated as zero (<part>)" naming the part. One whose row has no
figure leaves
adjusted EBITDA `COMPONENT_MISSING`. With `exclude_unrealised`, an add-back
with any row `UNREALIZED` or `NOT_STATED` is left out of adjusted EBITDA on
every column (spec M7); CP-1's figure is kept as `stated` and compared only on
a column where nothing was left out (an excluded add-back of zero or none
leaves nothing out).

The PF-LTM shows no KPI, working-capital balance or days ratio
(`NOT_APPLICABLE`), as the worked example does; a PF `ebitda` adjustment
adds to both EBITDA and adjusted EBITDA. A PF adjustment is a change, not a
balance, so it keeps CP-1's sign (a refinancing that cuts interest is a
positive adjustment to cash interest); a negative zero reads as zero. A PF
facility adjustment for
a facility the LTM has no balance for adds to zero. The PF-LTM's debt
roll-forward opens at the LTM's opening, keeps its non-cash movements and
closes at the pro forma total debt; its debt raised is `NOT_APPLICABLE` in
this frame, and the layout's roll-forward reads the LTM's
(`rollforward:debt_raised_net`) with the PF rows that enter total debt
beneath, so the laid-out roll-forward foots.

A debt balance that leaves something out (a facility in another currency,
`debt.py`) passes its note to the balances read from it: net debt and the
lease-adjusted debts.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from decimal import Decimal, localcontext

from caos.calculators.credit_model._cells import (
    ABSENT,
    CONTEXT,
    DIFFERS,
    FOREIGN,
    RESIDUAL,
    SIGN_NORMALISED,
    beyond_rounding,
    calc,
    join_notes,
    no_negative_zero,
    opening_date,
    periods_at,
    refs,
    treated_as_zero,
)
from caos.calculators.credit_model.debt import (
    carried,
    debt_frame,
    facility_keys,
    notes_of,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.methodology.model_inputs import Cp1Registers, PfAdjustmentRow

_EXCLUDED = "excluded"
# A positive cash tax: CP-1 writes inflows positive, so it is a refund.
TAX_REFUND = "positive: read as a tax refund"
# The realisation statuses "exclude unrealised" leaves out (spec M7).
UNREALISED = frozenset({"UNREALIZED", "NOT_STATED"})

# Frame keys read straight from one CP-1 account (outflows normalised).
_LINES = {
    "revenue": "revenue",
    "cogs": "cogs",
    "da": "depreciation_amortization",
    "opex_total": "opex_including_da",
    "operating_lease_cost": "operating_lease_cost",
    "cash_interest": "cash_interest_paid",
    "lease_cash_not_in_ebitda": "lease_payments_in_financing",
    "cash_taxes": "cash_taxes_paid",
    "working_capital_change": "working_capital_change",
    "cfo_reported": "cfo_ncfo",
    "capex": "capex_and_intangible_investment",
    "acquisitions_net": "acquisitions_disposals",
    "debt_raised_net": "net_debt_issue_repay",
    "equity_raised_net": "net_equity_issue_repay",
    "dividends": "dividends_paid",
    "cash_closing": "cash_and_equivalents",
    "accounts_receivable": "net_accounts_receivable",
    "inventory": "inventory",
    "accounts_payable": "accounts_payable",
}
# The PF-LTM: what each pro forma metric adds to, and the keys with no
# pro forma meaning (the waterfall from FFO to the net cash flow, its
# residual, and both roll-forwards).
_PF_TARGETS = {
    "revenue": ("revenue",),
    "ebitda": ("ebitda", "adjusted_ebitda"),
    "adjusted_ebitda": ("adjusted_ebitda",),
    "cash_interest_paid": ("cash_interest",),
    "cash_and_equivalents": ("cash_closing",),
    "total_debt": ("total_debt", "debt_closing"),
}
# The PF net debt's note: a PF adjustment to debt or cash no line takes is not
# in it (the model's NOT_APPLIED limitation names it too).
PF_NET_DEBT_EXCLUDES = "PF adjustment to debt or cash not applied"
_NET_DEBT_WORDS = ("debt", "cash")
_PF_BLANK = (
    "other_operating",
    "ffo",
    "working_capital_change",
    "cfo_adjusted",
    "cfo_reported",
    "capex",
    "fcf",
    "acquisitions_net",
    "debt_raised_net",
    "equity_raised_net",
    "dividends",
    "other_investing_financing",
    "ncf",
    "cash_opening",
    "fx_and_other_cash",
    "accounts_receivable",
    "inventory",
    "accounts_payable",
    "days",
    "dso",
    "dio",
    "dpo",
    "ccc",
)
_FACILITY = "facility:"

_Get = Callable[[str], Cell]


def _line(accounts: dict[str, Cell], metric_id: str) -> Cell:
    """The account's cell (`account_frame` reads an outflow negative)."""
    return accounts.get(f"acct:{metric_id}", ABSENT)


def _refund(taxes: Cell) -> Cell:
    """The cash taxes, noted `TAX_REFUND` where positive (a refund, as CP-1
    signs it)."""
    if taxes.value is None or taxes.value <= 0:
        return taxes
    return replace(taxes, note=join_notes((taxes.note, TAX_REFUND)))


def _stated(host: Cell, account: Cell, compare: bool = True) -> Cell:
    """`host` with CP-1's figure as `stated`: the account's own on a reported
    column, else the figure CP-1 stated for the derived one (the account's
    value there is the host's sum); its own notes kept, and noted where it
    differs beyond its rounding."""
    figure = account.value if account.basis == "REPORTED" else account.stated
    differs = (
        compare
        and figure is not None
        and host.value is not None
        and beyond_rounding(figure, host.value)
    )
    note = join_notes((host.note, DIFFERS if differs else None))
    return replace(host, stated=figure, note=note)


def excluded_addbacks(regs: Cp1Registers, exclude_unrealised: bool) -> frozenset[str]:
    """The add-backs left out of adjusted EBITDA, those with any row
    unrealised or not stated (`UNREALISED`); none unless
    `exclude_unrealised`."""
    if not exclude_unrealised:
        return frozenset()
    return frozenset(
        b.addback_id for b in regs.addbacks if b.realization_status in UNREALISED
    )


def _left_out(accounts: dict[str, Cell], excluded: frozenset[str]) -> bool:
    """Whether an excluded add-back leaves anything out on this column: a
    figure other than zero, or a row without one (an unknown amount)."""
    # Every add-back has a cell on every column (`account_frame`).
    cells = (accounts[f"addback:{addback}"] for addback in excluded)
    return any(cell.reason != "NOT_SOURCED" and cell.value != 0 for cell in cells)


def _income(
    get: _Get, accounts: dict[str, Cell], excluded: frozenset[str]
) -> dict[str, Cell]:
    """Gross profit to adjusted EBITDAR; adjusted EBITDA compared with CP-1's
    unless an excluded add-back left something out."""
    rev, cogs, opex, da = get("revenue"), get("cogs"), get("opex_total"), get("da")
    gross = _stated(calc(((rev, 1), (cogs, 1))), get("acct:gross_profit"))
    ebit = _stated(calc(((gross, 1), (opex, 1))), get("acct:ebit"))
    ebitda = _stated(calc(((ebit, 1), (da, -1))), get("acct:ebitda"))
    addbacks = [
        (_zero_if_absent(cell, key), 1)
        for key, cell in accounts.items()
        if key.startswith("addback:") and key.removeprefix("addback:") not in excluded
    ]
    adjusted = _stated(
        calc(((ebitda, 1), *addbacks)),
        get("acct:adjusted_ebitda"),
        compare=not _left_out(accounts, excluded),
    )
    return {
        "gross_profit": gross,
        "opex_ex_da": calc(((opex, 1), (da, -1))),
        "ebit": ebit,
        "ebitda": ebitda,
        "adjusted_ebitda": adjusted,
        "adjusted_ebitdar": calc(((adjusted, 1), (get("operating_lease_cost"), -1))),
    }


def _zero_if_absent(cell: Cell, part: str) -> Cell:
    """An add-back or financing line CP-1 has no row for counts as zero,
    noted (`treated_as_zero`) so every figure built from it says so."""
    if cell.reason != "NOT_SOURCED":
        return cell
    return Cell(Decimal(0), note=treated_as_zero(part))


def _waterfall(get: _Get, adjusted: Cell) -> dict[str, Cell]:
    """Adjusted CFO, FFO and its residual, and free cash flow."""
    lease = _zero_if_absent(
        get("lease_cash_not_in_ebitda"), "lease_payments_in_financing"
    )
    interest = _zero_if_absent(
        get("acct:interest_paid_in_financing"), "interest_paid_in_financing"
    )
    cfo = calc(((get("cfo_reported"), 1), (lease, 1), (interest, 1)))
    funds = [
        (adjusted, 1),
        (get("cash_interest"), 1),
        (lease, 1),
        (get("cash_taxes"), 1),
    ]
    other = calc(
        (
            (cfo, 1),
            (get("working_capital_change"), -1),
            *((cell, -sign) for cell, sign in funds),
        ),
        RESIDUAL,
    )
    return {
        "cfo_adjusted": cfo,
        "other_operating": other,
        "ffo": calc((*funds, (other, 1))),
        "fcf": calc(((cfo, 1), (get("capex"), 1))),
    }


def _net_cash(get: _Get, fcf: Cell, opening: Cell) -> dict[str, Cell]:
    """The net cash flow to CP-1's net cash change, and the cash bridge."""
    uses = [
        (fcf, 1),
        (get("acquisitions_net"), 1),
        (get("debt_raised_net"), 1),
        (get("equity_raised_net"), 1),
        (get("dividends"), 1),
    ]
    other = calc(
        (
            (get("acct:net_cash_change"), 1),
            *((cell, -sign) for cell, sign in uses),
        ),
        RESIDUAL,
    )
    ncf = calc((*uses, (other, 1)))
    closing = get("cash_closing")
    return {
        "other_investing_financing": other,
        "ncf": ncf,
        "cash_opening": opening,
        "fx_and_other_cash": calc(((closing, 1), (opening, -1), (ncf, -1)), RESIDUAL),
    }


def _opening_cash(regs: Cp1Registers, column: Column) -> Cell:
    """CP-1's cash at the day before the column starts: the first period
    ending then with a figure, in register order; a negative zero as zero."""
    for period_id in periods_at(regs, None, opening_date(column)):
        for row in regs.accounts:
            if (
                row.metric_id == "cash_and_equivalents"
                and row.period_id == period_id
                and row.value is not None
            ):
                value = no_negative_zero(row.value)
                return Cell(value, basis="REPORTED", sources=refs([row.source]))
    return Cell(None, "NOT_SOURCED")


def _days_ratio(balance: Cell, flow: Cell, days: Cell) -> Cell:
    """`balance / flow x days`; `COMPONENT_MISSING` with the missing inputs'
    notes; `ZERO_OR_NEGATIVE_DENOMINATOR` for a flow at or below zero."""
    if balance.value is None or flow.value is None or days.value is None:
        missing = (part for part in (balance, flow, days) if part.value is None)
        return Cell(
            None, "COMPONENT_MISSING", note=join_notes(tuple(p.note for p in missing))
        )
    if flow.value <= 0:
        return Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    sources = refs([*balance.sources, *flow.sources])
    value = balance.value / flow.value * days.value
    return Cell(value, basis="CALCULATED", sources=sources)


def _working_capital(get: _Get, column: Column) -> dict[str, Cell]:
    days = (
        Cell(None, "NOT_SOURCED")
        if column.days is None
        else Cell(Decimal(column.days), basis="CALCULATED")
    )
    cost = calc(((get("cogs"), -1),))
    dso = _days_ratio(get("accounts_receivable"), get("revenue"), days)
    dio = _days_ratio(get("inventory"), cost, days)
    dpo = _days_ratio(get("accounts_payable"), cost, days)
    return {
        "days": days,
        "dso": dso,
        "dio": dio,
        "dpo": dpo,
        "ccc": calc(((dso, 1), (dio, 1), (dpo, -1))),
    }


def _balances(get: _Get) -> dict[str, Cell]:
    """Liquidity and the debt totals net of cash and with leases, each noted
    with what the debt it reads leaves out."""
    cash, debt, leases = (
        get("cash_closing"),
        get("total_debt"),
        get("lease_liabilities"),
    )
    leased = calc(((debt, 1), (leases, 1)), carried((debt, leases)))
    return {
        "liquidity": calc(((cash, 1), (get("undrawn_rcf"), 1))),
        "lease_adjusted_debt": leased,
        "net_debt": calc(((debt, 1), (cash, -1)), carried((debt,))),
        "lease_adjusted_net_debt": calc(((leased, 1), (cash, -1)), carried((leased,))),
    }


def _column(
    regs: Cp1Registers,
    column: Column,
    accounts: dict[str, Cell],
    debt: dict[str, Cell],
    excluded: frozenset[str],
) -> dict[str, Cell]:
    """One column's cells; `excluded` the add-backs left out."""
    cells = dict(accounts)
    for addback in excluded:
        key = f"addback:{addback}"
        if key in cells:
            cells[key] = replace(
                cells[key], note=join_notes((cells[key].note, _EXCLUDED))
            )
    cells.update(debt)
    cells.update({key: _line(accounts, metric) for key, metric in _LINES.items()})
    cells["cash_taxes"] = _refund(cells["cash_taxes"])

    def get(key: str) -> Cell:
        if key.startswith("acct:"):
            return _line(accounts, key.removeprefix("acct:"))
        return cells[key]

    cells.update(_income(get, accounts, excluded))
    cells.update(_waterfall(get, cells["adjusted_ebitda"]))
    cells.update(_net_cash(get, cells["fcf"], _opening_cash(regs, column)))
    cells.update(_working_capital(get, column))
    cells.update(_balances(get))
    return cells


def statement_frame(
    accounts: Frame,
    columns: tuple[Column, ...],
    regs: Cp1Registers,
    exclude_unrealised: bool = False,
) -> Frame:
    """Each column's `accounts` cells (from `account_frame`), its `debt_frame`
    cells, and the statement keys: the income statement to adjusted EBITDAR,
    the waterfall to free cash flow, the net cash flow and cash bridge,
    liquidity, the debt totals and working capital."""
    with localcontext(CONTEXT):
        debt = debt_frame(regs, columns, accounts)
        excluded = excluded_addbacks(regs, exclude_unrealised)
        return {
            column.column_id: _column(
                regs,
                column,
                accounts[column.column_id],
                debt[column.column_id],
                excluded,
            )
            for column in columns
        }


def _pf_keys(adjustment: PfAdjustmentRow, regs: Cp1Registers) -> Iterable[str]:
    """The frame keys a pro forma adjustment adds to: a facility's `fac:` key
    and the totals its last register row enters (`total_debt` for a facility
    the register has no row for), else its metric's line; none for a metric
    outside CP-1's list."""
    if not adjustment.metric_id.startswith(_FACILITY):
        return _PF_TARGETS.get(adjustment.metric_id, ())
    facility_id = adjustment.metric_id.removeprefix(_FACILITY)
    row = next(
        (f for f in reversed(regs.facilities) if f.facility_id == facility_id), None
    )
    totals = {"total_debt"} if row is None else facility_keys(row, regs.currency)
    if "total_debt" in totals:
        totals = {*totals, "debt_closing"}
    return (f"fac:{facility_id}", *sorted(totals))


def _unapplied_debt_or_cash(
    adjustments: list[PfAdjustmentRow], regs: Cp1Registers
) -> list[PfAdjustmentRow]:
    """The adjustments no line takes (`_pf_keys`) to a metric that names
    debt or cash: what net debt (debt less cash) would have taken."""
    return [
        a
        for a in adjustments
        if not tuple(_pf_keys(a, regs))
        and any(w in a.metric_id for w in _NET_DEBT_WORDS)
    ]


def _pf_value(adjustment: PfAdjustmentRow) -> Decimal:
    """The adjustment's figure in CP-1's own sign, a negative zero as zero."""
    return no_negative_zero(adjustment.value)


def _pf_cell(adjustment: PfAdjustmentRow) -> Cell:
    sources = refs([adjustment.source])
    return Cell(_pf_value(adjustment), basis="PRO_FORMA", sources=sources)


def _pf_add(key: str, base: Cell | None, adjustments: list[PfAdjustmentRow]) -> Cell:
    """`base` plus the adjustments; a key the LTM has not, or a facility it
    has no balance for, is their sum. Kept from the notes: a facility in
    another currency, the base's sign normalised and what a total leaves
    out."""
    unsourced = base is not None and base.reason == "NOT_SOURCED"
    start = base
    if start is None or (unsourced and key.startswith("fac:")):
        start = Cell(Decimal(0), note=treated_as_zero(key))
    if start.value is None:
        return Cell(None, "COMPONENT_MISSING", note=start.note)
    total = start.value + sum(_pf_value(a) for a in adjustments)
    sources = refs([*start.sources, *(a.source for a in adjustments)])
    kept = [n for n in notes_of(start.note) if n in {FOREIGN, SIGN_NORMALISED}]
    note = join_notes((*kept, carried((start,))))
    return Cell(total, basis="PRO_FORMA", sources=sources, note=note)


def pro_forma_column(
    regs: Cp1Registers, ltm: Column, frame: Frame
) -> tuple[Column, Frame] | None:
    """The PF-LTM column and its frame (that column only): the LTM's cells,
    a `pf:<adjustment_id>` cell for each of CP-1's adjustments to the LTM's
    period, each added once to its line and the totals that line enters, and
    the waterfall below the cash interest blank. None when the register has
    no adjustment to the LTM's period."""
    adjustments = [a for a in regs.pro_forma if a.period_id == ltm.period_id]
    if not adjustments:
        return None
    column = replace(
        ltm, column_id=f"PF:{ltm.period_id}", kind="PF_LTM", label="PF-LTM"
    )
    with localcontext(CONTEXT):
        cells = dict(frame[ltm.column_id])
        added: dict[str, list[PfAdjustmentRow]] = {}
        for adjustment in adjustments:
            cells[f"pf:{adjustment.adjustment_id}"] = _pf_cell(adjustment)
            for key in _pf_keys(adjustment, regs):
                added.setdefault(key, []).append(adjustment)
        for key, rows in added.items():
            cells[key] = _pf_add(key, cells.get(key), rows)
        adjusted = cells["adjusted_ebitda"]
        lease_cost = cells["operating_lease_cost"]
        ebitdar = calc(((adjusted, 1), (lease_cost, -1)))
        cells["adjusted_ebitdar"] = replace(ebitdar, basis="PRO_FORMA")
        cells.update(
            {
                key: replace(cell, basis="PRO_FORMA")
                if cell.value is not None
                else cell
                for key, cell in _balances(cells.__getitem__).items()
            }
        )
        left_out = _unapplied_debt_or_cash(adjustments, regs)
        net_debt = cells["net_debt"]
        if left_out and net_debt.value is not None:
            names = ", ".join(a.label for a in left_out)
            cells["net_debt"] = replace(
                net_debt,
                note=join_notes((net_debt.note, f"{PF_NET_DEBT_EXCLUDES}: {names}")),
            )
        blank = (*_PF_BLANK, *(key for key in cells if key.startswith("kpi:")))
        cells.update({key: Cell(None, "NOT_APPLICABLE") for key in blank})
        return column, {column.column_id: cells}
