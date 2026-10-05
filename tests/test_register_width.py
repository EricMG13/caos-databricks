"""A register row a cell short or long is named to the guided retry (F509).

Live run LCR4: CP-3C was refused four times on "T3D.2 row 8: critical column
'Source Trace' holds a disqualifying placeholder ''". The row had 11 cells
under a 12-cell header; the vendor padded it, so its source text sat in
Credit Implication and the model, which saw that text in the row, kept it.

Live run LCR6 (F522): told "T3D.2 row 7 has 11 cells", the model rewrote that
row's text three times and kept it 11 wide. The line now names the row by its
first cell and quotes how its last columns read, so the shift is visible.
"""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

from canonical_fixtures import BUNDLE, CONTRACT, identity

from caos.methodology.bundle import assemble_authority
from caos.methodology.executor import SKILL
from caos.methodology.handoff import (
    MAX_FEEDBACK_CHARS,
    MAX_WIDTH_ROWS,
    feedback_lines,
)
from caos.methodology.vendor import catalog

HEADER = (
    "Instrument",
    "Amount",
    "Currency",
    "Maturity Date",
    "Years to Maturity",
    "Seniority / Lien",
    "Coupon / Margin",
    "Fixed / Floating",
    "Call Date",
    "Refinancing Pressure",
    "Credit Implication",
    "Source Trace",
)
SHORT_LINE = (
    "host table check: T3D.2 row 2 («Notes due 2032») has 11 cells under a"
    " 12-cell header; a cell is missing or extra, so its later columns shift"
    " (the last column, 'Source Trace', reads empty); as read, 'Refinancing"
    " Pressure' holds «value 10», 'Credit Implication' holds «value 11» and"
    " 'Source Trace' holds nothing"
)


def _row(cells: int, first: str = "Notes due 2032") -> str:
    values = [first, *(f"value {n}" for n in range(2, cells + 1))]
    return "| " + " | ".join(values) + " |"


def _lines(rows: list[str], tag: str = "") -> tuple[str, ...]:
    """The feedback CP-3C's retry would carry for a T3D.2 of these rows."""
    markdown = (
        "---\nmodule_id: CP-3C\n---\n\n### T3D.2 — Debt maturity\n\n"
        + tag
        + "| "
        + " | ".join(HEADER)
        + " |\n"
        + "|---" * len(HEADER)
        + "|\n"
        + "\n".join(rows)
        + "\n"
    )
    citation = {
        "source_id": str(UUID(int=1)),
        "page": 1,
        "matched_text": "value 2",
    }
    body = json.dumps({"canonical_markdown": markdown, "citations": [citation]})
    skill = assemble_authority(BUNDLE, "CP-3C").files[SKILL]
    ident = replace(identity("CP-0"), module_id="CP-3C")
    return feedback_lines(CONTRACT, catalog(BUNDLE), ident, body, skill=skill)


def _table_lines(lines: tuple[str, ...]) -> list[str]:
    return [line for line in lines if line.startswith("host table check")]


def test_a_short_register_row_is_named_before_the_vendors_empty_cell() -> None:
    lines = _lines([_row(12), _row(11)])
    vendor = (
        "completeness_check: T3D.2 row 2: critical column 'Source Trace'"
        " holds a disqualifying placeholder ''"
    )
    assert SHORT_LINE in lines and vendor in lines, lines
    assert lines.index(SHORT_LINE) < lines.index(vendor)
    assert _table_lines(lines) == [SHORT_LINE]


def test_a_register_row_with_an_extra_cell_is_named() -> None:
    assert _table_lines(_lines([_row(13), _row(14)])) == [
        "host table check: T3D.2 row 1 («Notes due 2032») has 13 cells under a"
        " 12-cell header; a cell is missing or extra, so its later columns shift"
        " (the cell past the last column, 'Source Trace', is dropped); as read,"
        " 'Refinancing Pressure' holds «value 10», 'Credit Implication' holds"
        " «value 11», 'Source Trace' holds «value 12» and past it «value 13» is"
        " dropped",
        "host table check: T3D.2 row 2 («Notes due 2032») has 14 cells under a"
        " 12-cell header; a cell is missing or extra, so its later columns shift"
        " (the 2 cells past the last column, 'Source Trace', are dropped); as"
        " read, 'Refinancing Pressure' holds «value 10», 'Credit Implication'"
        " holds «value 11», 'Source Trace' holds «value 12» and past it «value"
        " 13» is dropped",
    ]


def test_a_register_of_the_header_width_gets_no_table_line() -> None:
    assert _table_lines(_lines([_row(12), _row(12)])) == []


def test_an_escaped_pipe_is_one_cell_as_the_vendor_reads_it() -> None:
    """`_row_cells` splits at the unescaped pipes when every pipe gives
    another width: `A \\| B` is one cell, so the row is 12 wide. Where
    every pipe gives the header's width the vendor splits there, and binds a
    row of 12 cells, so the host counts 12 too."""
    assert _table_lines(_lines([_row(12, first="Notes A \\| B")])) == []
    assert _table_lines(_lines([_row(11, first="Notes A \\| B")])) == []
    two = _lines([_row(11, first="Notes A \\| B \\| C")])
    assert _table_lines(two) == [
        "host table check: T3D.2 row 1 («Notes A \\») has 13 cells under a"
        " 12-cell header; a cell is missing or extra, so its later columns shift (the"
        " cell past the last column, 'Source Trace', is dropped); as read,"
        " 'Refinancing Pressure' holds «value 8», 'Credit Implication' holds"
        " «value 9», 'Source Trace' holds «value 10» and past it «value 11» is"
        " dropped"
    ]


def test_a_tagged_table_keeps_the_vendors_width_line_alone() -> None:
    """The R4/C1 interface-table message already names the row; the host
    adds no second line for the same table."""
    lines = _lines([_row(12), _row(11)], tag="<!-- table-id: cp3c.debt -->\n")
    assert any(
        line.startswith("completeness_check: cp3c.debt: row 2")
        and "differs from its header" in line
        for line in lines
    ), lines
    assert _table_lines(lines) == []


def test_at_most_max_width_rows_are_named_and_the_rest_counted() -> None:
    lines = _table_lines(_lines([_row(11)] * (MAX_WIDTH_ROWS + 2)))
    assert len(lines) == MAX_WIDTH_ROWS + 1
    assert lines[0] == SHORT_LINE.replace("row 2", "row 1")
    assert lines[-1] == (
        "host table check: 2 more register rows differ in width from the header"
    )


def test_lcr6_the_short_row_is_named_by_its_first_cell_and_its_shift_shown() -> None:
    """LCR6 CP-3C row 7 left out Credit Implication: its source trace read
    under Credit Implication. The line quotes each of the last three columns'
    text, cut at a word to at most `_QUOTE_CHARS` characters."""
    cells = [
        "CEI Senior Secured Notes due 2032",
        *(f"value {n}" for n in range(2, 10)),
        "Long-dated maturity, but collateral release, debt-incurrence and"
        " amendment paths could affect recovery if used [C7, C30]",
        "10-Q p. 9; Indenture p. 42.",
    ]
    (line,) = _table_lines(_lines(["| " + " | ".join(cells) + " |"]))
    assert line == (
        "host table check: T3D.2 row 1 («CEI Senior Secured Notes due 2032»)"
        " has 11 cells under a 12-cell header; a cell is missing or extra, so"
        " its later columns shift (the last column, 'Source Trace', reads"
        " empty); as read, 'Refinancing Pressure' holds «Long-dated maturity,"
        " but collateral…», 'Credit Implication' holds «10-Q p. 9; Indenture"
        " p. 42.» and 'Source Trace' holds nothing"
    )
    assert len(line) <= MAX_FEEDBACK_CHARS + len("host table check: ")


def test_a_cell_that_hides_text_is_never_quoted() -> None:
    """A bidirectional control in a quoted cell drops the quotes, never the
    line: the row is still named by number."""
    (line,) = _table_lines(_lines([_row(11, first="Notes \u202e due")]))
    assert line == (
        "host table check: T3D.2 row 1 has 11 cells under a 12-cell header; a"
        " cell is missing or extra, so its later columns shift (the last"
        " column, 'Source Trace', reads empty)"
    )
