"""Public owner-input access to the credit model's historical primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from caos.methodology.model_inputs import Cp1Registers, FacilityRow, PeriodRow


def facility_stack_at(
    regs: Cp1Registers, period_ids: list[str | None]
) -> dict[str, FacilityRow]:
    """Return the existing historical facility selection without changing it."""
    from caos.calculators.credit_model.debt import _stack_at

    return _stack_at(regs, period_ids)


def fiscal_year_note(period: PeriodRow) -> str | None:
    """Return the existing historical fiscal-year classification unchanged."""
    from caos.calculators.credit_model.history import _fiscal_year_note

    return _fiscal_year_note(period)
