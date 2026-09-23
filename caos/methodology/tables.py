"""The tagged tables an accepted handoff carries, read by the bundle's own reader.

A handoff's machine interface is its `<!-- table-id: x.y -->`-tagged pipe
tables; an untagged table is presentation (the vendor's `cp_tables`). The
Markdown stays the authority and nothing here is stored: a reader derives the
tables from bytes it has already verified, as the bundle's `parse_tables`
reads them, in document order, each cell its exact text as that reader splits
it.

What a figure is, is the bundle's: a cell has a value only where its own
`parse_figure` reads one, so its null vocabulary is null and a separator it will
not guess (`5,2`) is no value. What the figure is worth, is the host's: the same
spelling read again with `Decimal`, never through the vendor's float
(invariant 7), and served in plain notation at the cell's own scale. A figure
whose exact value would not fit the wire's bound has no value; its text stands.

Pure: no I/O. A vendor exception never leaves here, and its message, which can
quote the document, is never read (invariant 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

from caos.methodology.vendor import VendorContract

# Bounds, restated on the wire (`caos.api.wire.TableView`). The bundle's widest
# table has sixteen columns; the longest, `cp1.model_account_register`, is one
# row per metric id (32) per period, so two thousand rows is 62 periods.
TABLES_MAX = 64
TABLE_COLUMNS_MAX = 32
TABLE_ROWS_MAX = 2000
TABLE_ID_CHARS = 256
CELL_CHARS = 4096
# `ModelValue.value`'s bound: a figure is served in the shape the model is.
FIGURE_CHARS = 64

# Why a handoff serves no tables: the bundle's reader refused its tagged
# tables, or they are past a bound above. Either way the Markdown still reads.
TablesUnavailable = Literal["TABLES_MALFORMED", "TABLES_TOO_LARGE"]

# `parse_figure`'s decorations and separator grammar, restated so a spelling
# the bundle read as a figure is read again, exactly, in the order it reads it.
_SPACES = str.maketrans("", "", "\u00a0\u202f ")
_CURRENCY = re.compile("^[\u20ac$\u00a3\u00a5\u20b9]|[\u20ac$\u00a3\u00a5\u20b9]$")
_MULTIPLE = re.compile(r"[xX]$")
_PERCENT = re.compile(r"%$")
_FIGURE = re.compile(r"[-+]?[0-9][0-9.,]*(?:[eE][-+]?[0-9]+)?")
_ANGLO_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_CONTINENTAL = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_AMBIGUOUS_COMMA = re.compile(r"^\d+,\d{1,2}$")


@dataclass(frozen=True, slots=True)
class TableCell:
    """One cell: its exact text, and its exact figure where the bundle reads one."""

    text: str
    value: str | None


@dataclass(frozen=True, slots=True)
class HandoffTable:
    """One tagged table: its id, its header, and every row in header order."""

    table_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple[TableCell, ...], ...]


@dataclass(frozen=True, slots=True)
class HandoffTables:
    """Every tagged table a handoff carries, or none and the reason why."""

    tables: tuple[HandoffTable, ...]
    unavailable_reason: TablesUnavailable | None


class _VendorTable(Protocol):
    """`cp_tables.Table`, as far as this module reads it."""

    table_id: str
    columns: list[str]
    rows: list[dict[str, str]]  # column -> the cell's text


def handoff_tables(contract: VendorContract, markdown: str) -> HandoffTables:
    """Every tagged table in `markdown`, as the bundle's `parse_tables` reads it.

    `TABLES_MALFORMED` when that reader refuses them -- a tag with no table, a
    duplicate id, a missing separator, a row wider or narrower than its header
    -- and `TABLES_TOO_LARGE` past a bound; both serve no table at all, since a
    partial set would read as the whole one.
    """
    try:
        parsed = contract.cp_tables.parse_tables(markdown)
    except ValueError:
        return HandoffTables((), "TABLES_MALFORMED")
    tables: list[_VendorTable] = list(parsed.values())
    if len(tables) > TABLES_MAX or not all(_bounded(table) for table in tables):
        return HandoffTables((), "TABLES_TOO_LARGE")
    return HandoffTables(tuple(_table(contract, table) for table in tables), None)


def figure_value(contract: VendorContract, cell: str) -> str | None:
    """`cell`'s exact figure as a plain decimal string, or None.

    A value only where the bundle's `parse_figure` reads a figure too: None for
    its null vocabulary, for prose and for a separator it will not guess. What
    the figure is worth is `Decimal`'s reading; the vendor's number is a float
    and is discarded unread. None too for a figure whose plain notation is
    longer than `FIGURE_CHARS`. The cheap reading goes first, so the bundle is
    asked only about a cell that reads as a figure at all.
    """
    value = _exact(cell)
    if value is None:
        return None
    try:
        read = contract.cp_tables.parse_figure(cell)
    except ValueError:  # `AmbiguousFigure` among them: a separator it will not guess
        return None
    # `None` is the bundle's null vocabulary: null, never zero.
    return None if read is None else _plain(value)


def _bounded(table: _VendorTable) -> bool:
    return (
        len(table.table_id) <= TABLE_ID_CHARS
        and len(table.columns) <= TABLE_COLUMNS_MAX
        and len(table.rows) <= TABLE_ROWS_MAX
        and all(len(column) <= CELL_CHARS for column in table.columns)
        and all(len(cell) <= CELL_CHARS for row in table.rows for cell in row.values())
    )


def _table(contract: VendorContract, table: _VendorTable) -> HandoffTable:
    """The reader's rows are keyed by column; they are served in header order."""
    columns = tuple(table.columns)
    return HandoffTable(
        table_id=table.table_id,
        columns=columns,
        rows=tuple(
            tuple(TableCell(row[c], figure_value(contract, row[c])) for c in columns)
            for row in table.rows
        ),
    )


def _exact(cell: str) -> Decimal | None:
    """`parse_figure`'s reading of `cell`, step for step, in `Decimal`."""
    text = cell.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    core = _CURRENCY.sub("", text.translate(_SPACES))
    core = _PERCENT.sub("", _MULTIPLE.sub("", core))
    plain = _separated(core) if _FIGURE.fullmatch(core) else None
    if plain is None:
        return None
    try:
        value = Decimal(plain)
    except InvalidOperation:  # `1.2.3`: the bundle refuses it before this
        return None
    return -value if negative else value


def _separated(core: str) -> str | None:
    """`core` with the bundle's separator rules applied: the separator that
    comes last is the decimal one, and `5,2` is refused rather than guessed."""
    body = core.lstrip("-+")
    if "," in core and "." in core:
        if core.rfind(",") > core.rfind("."):
            if not _CONTINENTAL.match(body):
                return None
            return core.replace(".", "").replace(",", ".")
        if not _ANGLO_THOUSANDS.fullmatch(body):
            return None
        return core.replace(",", "")
    if "," in core:
        if _AMBIGUOUS_COMMA.match(body) or not _ANGLO_THOUSANDS.match(body):
            return None
        return core.replace(",", "")
    return core


def _plain(value: Decimal) -> str | None:
    """`value` in plain notation at its own scale, no sign on zero, or None past
    `FIGURE_CHARS` -- judged before formatting, so `1e999999` never is."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -FIGURE_CHARS:
        return None
    if value and value.adjusted() >= FIGURE_CHARS:
        return None
    text = format(value if value else abs(value), "f")
    return text if len(text) <= FIGURE_CHARS else None
