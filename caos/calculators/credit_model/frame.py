"""The credit model's shared types: a column, a cell and the frame of both.

A frame maps a column id to its keys and each key to one cell. A cell holds a
`Decimal` or the reason it has none, never both; its sources keep the CP-1
cell text verbatim, `[C<n>]` markers kept (D107).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ColumnKind = Literal["QUARTER", "PYTD", "YTD", "FY", "LTM", "PF_LTM", "PROJECTED"]
Case = Literal["BASE", "DOWNSIDE"]
Basis = Literal["REPORTED", "CALCULATED", "PRO_FORMA", "PROJECTED", "DRIVER"]
Reason = Literal[
    "NOT_PROJECTED",
    "NOT_APPLICABLE",
    "NOT_SOURCED",
    "COMPONENT_MISSING",
    "ZERO_OR_NEGATIVE_DENOMINATOR",
    "NOT_STATED",
]


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    source_locator: str
    cell_text: str  # the CP-1 cell text verbatim, [C<n>] markers kept (D107)


@dataclass(frozen=True, slots=True)
class Cell:
    value: Decimal | None
    reason: Reason | None = None  # set iff value is None
    basis: Basis | None = None
    stated: Decimal | None = None  # CP-1's own figure where the host recomputed one
    sources: tuple[SourceRef, ...] = ()
    # "implied rate", "assumed refinanced", "held flat", "differs from CP-1 stated"
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Column:
    # "Q:<period_id>", "PYTD:<period_id>", "YTD:<period_id>", "FY:<period_id>",
    # "LTM:<period_id>", "PF:<period_id>", "BASE:<fiscal_year>",
    # "DOWNSIDE:<fiscal_year>"
    column_id: str
    kind: ColumnKind
    # "Q2 26", "PYTD H1 25", "YTD H1 26", "FY25", "LTM Q2 26", "PF-LTM", "FY26E"
    label: str
    period_id: str | None
    fiscal_year: str
    end_date: str | None  # ISO date
    days: int | None
    case: Case | None


Frame = dict[str, dict[str, Cell]]  # column_id -> key -> Cell
