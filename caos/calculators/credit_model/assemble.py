"""The assembled credit model and the bridges it must close.

`credit_model` runs the calculator end to end: the historical columns and
CP-1's figures over them, the statements (with "exclude unrealised" on every
frame, the LTM ending each quarter included), the PF-LTM where the register
has adjustments to the LTM, the projections where CP-CF ran, the credit
metrics, then the layout. Columns run quarters, PYTD, YTD, FY, LTM, PF-LTM,
then the Base years and the Downside years (spec M2).

`reconciliation_faults` checks these bridges on the assembled model, by line
and column, on exact Decimal equality (the calculator never rounds):

- `ebitda`: EBIT less D&A (negative) plus the EBITDA PF rows;
- `adjusted_ebitda`: EBITDA plus the add-backs in it and its PF rows;
- `ffo`: adjusted EBITDA, cash interest, cash taxes, other operating items
  and lease cash not in EBITDA;
- `cfo`: FFO plus the working-capital change, as the adjusted CFO;
- `fcf`: the adjusted CFO plus capex;
- `ncf`: FCF, acquisitions, debt and equity raised, dividends and other
  investing and financing;
- `cash`: opening cash plus the net cash flow and FX and other movements;
- `liquidity`: closing cash, its PF rows and the undrawn RCF;
- each rank subtotal: its facilities and their PF rows;
- `total_debt`: every facility in totals, their PF rows, the PF rows for
  debt the stack has no facility for, and the unallocated movements (a
  projection's total debt less its scheduled facilities);
- `debt_rollforward`: opening debt, debt raised, non-cash movements and the
  PF rows in total debt, as closing debt;
- `interest`, on a projection: cash interest as minus the weighted rate
  times the opening interest-bearing debt, to the 38 digits each is computed
  to (interest is computed from the facility weights, never through the
  rounded rate, so the two part only in their last digits).

Nothing else is checked: not the CFO as reported (a memo), the income
statement above EBIT, the debt totals net of cash and with leases, working
capital, the interest base, nor revenue against the business units (a noted
limitation, not a fault). A bridge with a line that has no figure on a
column is not checked there, except a line the calculator itself counts as
nothing when absent (an add-back, a pro forma row, lease cash not in
EBITDA, the residual other investing and financing and FX lines a projection
has not, and a facility not in the stack at that date): with reason
`NOT_SOURCED`, `NOT_APPLICABLE` or `NOT_PROJECTED` it adds zero. On the
PF-LTM an account shows the LTM's figure, its PF rows beneath. Each fault
reads `"<column_id>:<bridge>"`.

The limitations list each component of a compound cell note ("a; b") under
its own note, with the columns it is on, and say where the PF register
states both an `ebitda` and an `adjusted_ebitda` adjustment to the PF-LTM (a
PF `ebitda` adjustment already reaches adjusted EBITDA).

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from caos.calculators.credit_model.debt import notes_of
from caos.calculators.credit_model.frame import Column, Frame
from caos.calculators.credit_model.history import (
    account_frame,
    historical_columns,
    ltm_frames,
)
from caos.calculators.credit_model.layout import BANDS, Line, layout
from caos.calculators.credit_model.metrics import metric_frame
from caos.calculators.credit_model.projection import (
    ProjectionInputs,
    RateDeck,
    projection,
)
from caos.calculators.credit_model.statements import (
    pro_forma_column,
    statement_frame,
)
from caos.methodology.model_inputs import (
    Cp1Registers,
    DivisionGrowth,
    SlotAllocation,
)

NO_PROJECTIONS = "No projections: this route did not run CP-2G/CP-CF"
NOT_APPLIED = "PF adjustment to a metric the model has no line for, not applied"
DOUBLE_COUNT = (
    "PF register states both ebitda and adjusted_ebitda adjustments; "
    "check for double counting"
)
_EBITDA_METRICS = frozenset({"ebitda", "adjusted_ebitda"})
_ZERO_WHEN_ABSENT = frozenset({"NOT_SOURCED", "NOT_APPLICABLE", "NOT_PROJECTED"})
_OPEX_BAND, _ADJUSTED_BAND, _LIQUIDITY_BAND, _DEBT_BAND = (
    BANDS[3],
    BANDS[4],
    BANDS[6],
    BANDS[7],
)


@dataclass(frozen=True, slots=True)
class CreditModel:
    currency: str
    unit: str
    columns: tuple[Column, ...]
    lines: tuple[Line, ...]
    rate_deck_id: str | None
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelInputs:
    registers: Cp1Registers
    request: Mapping[str, Any] | None  # CP-CF's accepted request; None without
    growth: tuple[DivisionGrowth, ...]
    slots: tuple[SlotAllocation, ...]
    deck: RateDeck | None
    exclude_unrealised: bool = False


def _projected(inputs: ModelInputs, history: Frame) -> tuple[tuple[Column, ...], Frame]:
    """The projected columns, Base years then Downside years, and their
    frame; none without CP-CF's request."""
    if inputs.request is None:
        return (), {}
    columns, frame = projection(
        ProjectionInputs(
            regs=inputs.registers,
            request=inputs.request,
            growth=inputs.growth,
            slots=inputs.slots,
            deck=inputs.deck,
            history=history,
        )
    )
    ordered = sorted(columns, key=lambda column: column.case == "DOWNSIDE")
    return tuple(ordered), frame


def _pro_forma_limitations(
    inputs: ModelInputs, columns: tuple[Column, ...], lines: tuple[Line, ...]
) -> list[str]:
    """Each PF-LTM adjustment to a metric no line takes, and PF-LTM
    adjustments to both EBITDA and adjusted EBITDA."""
    ids = {line.line_id for line in lines}
    pro_forma = {c.period_id for c in columns if c.kind == "PF_LTM"}
    applied = [a for a in inputs.registers.pro_forma if a.period_id in pro_forma]
    found = [
        f"{NOT_APPLIED}: {a.label}"
        for a in applied
        if f"pf:{a.adjustment_id}" not in ids
    ]
    if _EBITDA_METRICS <= {a.metric_id for a in applied}:
        found.append(DOUBLE_COUNT)
    return found


def _limitations(
    inputs: ModelInputs, columns: tuple[Column, ...], lines: tuple[Line, ...]
) -> tuple[str, ...]:
    """The missing projections; the pro forma limitations; then each
    distinct cell note (each component of a compound one) with the columns
    it is on, in line order."""
    model = [] if inputs.request is not None else [NO_PROJECTIONS]
    notes: dict[str, dict[str, None]] = {}
    for line in lines:
        for column, cell in zip(columns, line.cells, strict=True):
            for note in notes_of(cell.note):
                notes.setdefault(note, {})[column.column_id] = None
    return (
        *model,
        *_pro_forma_limitations(inputs, columns, lines),
        *(f"{note}: {', '.join(on)}" for note, on in notes.items()),
    )


def credit_model(inputs: ModelInputs) -> CreditModel:
    """The credit model of CP-1's registers, with CP-2G and CP-CF's
    projections where `request` is CP-CF's accepted request: every column,
    every line and the limitations its cells note."""
    regs = inputs.registers
    exclude = inputs.exclude_unrealised
    historical = historical_columns(regs)
    history = statement_frame(
        account_frame(regs, historical), historical, regs, exclude
    )
    frame = dict(history)
    columns = list(historical)
    ltm = next((column for column in historical if column.kind == "LTM"), None)
    pro_forma = None if ltm is None else pro_forma_column(regs, ltm, history)
    if pro_forma is not None:
        columns.append(pro_forma[0])
        frame.update(pro_forma[1])
    projected, projected_frame = _projected(inputs, history)
    columns.extend(projected)
    frame.update(projected_frame)
    quarters = tuple(column for column in historical if column.kind == "QUARTER")
    ltm_ending = statement_frame(ltm_frames(regs, historical), quarters, regs, exclude)
    corporate = frozenset(
        row.segment_id
        for row in regs.segments
        if row.segment_type == "CORPORATE_ELIMINATION"
    )
    every = tuple(columns)
    metrics = metric_frame(every, frame, ltm_ending, corporate=corporate)
    deck = inputs.deck if inputs.request is not None else None
    lines = layout(regs, every, metrics, exclude, deck.as_of if deck else None)
    return CreditModel(
        currency=regs.currency,
        unit=regs.unit,
        columns=every,
        lines=lines,
        rate_deck_id=deck.deck_id if deck else None,
        limitations=_limitations(inputs, every, lines),
    )
