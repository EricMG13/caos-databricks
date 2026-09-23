"""A handoff's tagged tables, read by the bundle's own reader (`tables`).

Every `<!-- table-id: -->`-tagged table in document order, each cell its exact
text and, where the bundle's `parse_figure` reads a figure, that figure's exact
value in `Decimal` (invariant 7). What the bundle's reader refuses, and what is
past a bound, serves no table and a typed reason. And the demo fixtures carry
exactly the tables their own Markdown derives, under the bundle's column names.
"""

from __future__ import annotations

import ast
import json
import random
import re
from decimal import Decimal
from pathlib import Path

import pytest
from canonical_fixtures import BUNDLE, CONTRACT

from caos.api.wire import AnalysisDocument, CellView, TableView
from caos.methodology import tables
from caos.methodology.bundle import verified_bytes
from caos.methodology.tables import (
    HandoffTable,
    HandoffTables,
    TableCell,
    figure_value,
    handoff_tables,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "frontend" / "fixtures"
PLAIN = re.compile(r"-?[0-9]+(\.[0-9]+)?")


def _tagged(table_id: str, columns: list[str], rows: list[list[str]]) -> str:
    lines = [f"<!-- table-id: {table_id} -->", "| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n\n"


def test_every_tagged_table_is_served_in_order_and_an_untagged_one_is_not() -> None:
    markdown = (
        "## Analysis\n\n| presentation | only |\n| --- | --- |\n| 1 | 2 |\n\n"
        "<!-- table-id: cp1.debt_facility_register -->\n"
        "| facility_id | carrying_value | commitment |\n| --- | ---: | --- |\n"
        "| TERM | 1,245.50 | n/a |\n| NOTES | (996) | Not stated |\n\n"
        "```\n<!-- table-id: fenced.example -->\n| a |\n| --- |\n| 1 |\n```\n\n"
        "<!-- table-id: cp2g.cp_model_forecast_drivers -->\n"
        "| driver_id | value |\n| --- | --- |\n"
    )

    assert handoff_tables(CONTRACT, markdown) == HandoffTables(
        (
            HandoffTable(
                "cp1.debt_facility_register",
                ("facility_id", "carrying_value", "commitment"),
                (
                    (
                        TableCell("TERM", None),
                        TableCell("1,245.50", "1245.50"),
                        TableCell("n/a", None),
                    ),
                    (
                        TableCell("NOTES", None),
                        TableCell("(996)", "-996"),
                        TableCell("Not stated", None),
                    ),
                ),
            ),
            # Present and empty is a table; the bundle permits an empty register.
            HandoffTable("cp2g.cp_model_forecast_drivers", ("driver_id", "value"), ()),
        ),
        None,
    )
    assert handoff_tables(CONTRACT, "No table here.\n") == HandoffTables((), None)


@pytest.mark.parametrize(
    "markdown",
    [
        "<!-- table-id: a.b -->\n",
        _tagged("a.b", ["x"], [["1"]]) + _tagged("a.b", ["x"], [["2"]]),
        "<!-- table-id: a.b -->\n| x | y |\n| 1 | 2 |\n",
        "<!-- table-id: a.b -->\n| x | y |\n| --- | --- |\n| 1 |\n",
        "<!-- table-id: a.b -->\n| x | x |\n| --- | --- |\n",
        _tagged("a.b", ["x"], [["1"]]) + "<!-- table-id: c.d -->\n",
    ],
    ids=[
        "no-table",
        "duplicate",
        "no-separator",
        "narrow-row",
        "same-column",
        "one-of",
    ],
)
def test_tables_the_bundle_reader_refuses_serve_none_as_tables_malformed(
    markdown: str,
) -> None:
    # One refused table refuses them all: a partial set would read as the whole.
    assert handoff_tables(CONTRACT, markdown) == HandoffTables((), "TABLES_MALFORMED")


def _tables(count: int) -> str:
    return "".join(_tagged(f"t.n{i}", ["x"], [["1"]]) for i in range(count))


def _table_of(columns: int = 1, rows: int = 1, cell: int = 1, table_id: int = 3) -> str:
    return _tagged(
        "t." + "x" * (table_id - 2),
        [f"c{i}" for i in range(columns - 1)] + ["x" * cell],
        [["1"] * columns] * rows,
    )


@pytest.mark.parametrize(
    ("at_bound", "past_bound"),
    [
        (_tables(tables.TABLES_MAX), _tables(tables.TABLES_MAX + 1)),
        (
            _table_of(columns=tables.TABLE_COLUMNS_MAX),
            _table_of(columns=tables.TABLE_COLUMNS_MAX + 1),
        ),
        (
            _table_of(rows=tables.TABLE_ROWS_MAX),
            _table_of(rows=tables.TABLE_ROWS_MAX + 1),
        ),
        (_table_of(cell=tables.CELL_CHARS), _table_of(cell=tables.CELL_CHARS + 1)),
        (
            _table_of(table_id=tables.TABLE_ID_CHARS),
            _table_of(table_id=tables.TABLE_ID_CHARS + 1),
        ),
        (
            _tagged("t.x", ["x"], [["1" * tables.CELL_CHARS]]),
            _tagged("t.x", ["x"], [["1" * (tables.CELL_CHARS + 1)]]),
        ),
    ],
    ids=["tables", "columns", "rows", "column-name", "table-id", "cell"],
)
def test_tables_past_a_bound_serve_none_as_tables_too_large(
    at_bound: str, past_bound: str
) -> None:
    assert handoff_tables(CONTRACT, at_bound).unavailable_reason is None
    assert handoff_tables(CONTRACT, past_bound) == HandoffTables((), "TABLES_TOO_LARGE")


def test_the_wire_restates_the_bounds_the_reader_holds() -> None:
    schema = TableView.model_json_schema()
    props = schema["properties"]
    assert props["table_id"]["maxLength"] == tables.TABLE_ID_CHARS
    assert props["columns"]["maxItems"] == tables.TABLE_COLUMNS_MAX
    assert props["columns"]["items"]["maxLength"] == tables.CELL_CHARS
    assert props["rows"]["maxItems"] == tables.TABLE_ROWS_MAX
    assert props["rows"]["items"]["maxItems"] == tables.TABLE_COLUMNS_MAX
    [value, _null] = CellView.model_json_schema()["properties"]["value"]["anyOf"]
    assert value["maxLength"] == tables.FIGURE_CHARS


# Spellings a register cell is written in, each read by the bundle and the host.
SPELLINGS = (
    *("1,234", "(1,234)", "$1,234.56", "\u20ac1.234,56", "1.234.567,89", "12,345.6"),
    *("1,234,567.891", "\u00a312", "\u00a51,000", "\u20b95", "5\u20ac", "$5$", "$$5"),
    *("-5", "+5", "(-5)", "( 5 )", "(5", "5)", " 5 ", "5x", "5.2X", "10.4%", "(5%)"),
    *("5%x", "5x%", "1 234", "1\u00a0234", "1\u202f234", "1\u2009234", ".5", "5."),
    *("0.1", "007", "0.05", "-0.10", "(14)", "$7,125", "197,325", "5.50%", "2026"),
    *("1e3", "1E+3", "1.5e-3", "2.5E2", "1,234e5", "1e400", "0e70", "-0", "(0)"),
    *("5,2", "5,25", "12,34", "1,2345", "1,23,456", "5,250", "1.234", "1..2"),
    *("1.2.3", "--5", "+-5", "\u0663", "x", "X5", "2026-09-08", "FY2026", "Q2-2026"),
    *("SOFR + 3.20%", "9.00% cash / 12.00% PIK", "roughly 5", "5 to 6"),
    *("", "-", "\u2014", "\u2013", "n/a", "N/A", "na", "None", "null", "TBD"),
    *("Not applicable", "not disclosed", "Unknown", "unavailable", "not stated"),
    *("[Insufficient Information]", "Not calculable from provided materials"),
)


def _random_spellings(count: int) -> list[str]:
    """Seeded, so a failure names the same spelling on every run. No exponent,
    so every figure is within `FIGURE_CHARS` and the comparison is total."""
    alphabet = [*"0123456789" * 3, *",.-+()$%xX ", *"\u20ac\u00a3\u00a0\u202f"]
    chosen = random.Random(20260923)
    return [
        "".join(chosen.choice(alphabet) for _ in range(chosen.randint(1, 12)))
        for _ in range(count)
    ]


def _vendor(cell: str) -> float | None:
    """The bundle's number for `cell`, or None where it reads none."""
    reader = CONTRACT.cp_tables
    try:
        number = reader.to_number(cell)
    except reader.AmbiguousFigure:
        number = None
    try:
        figure = reader.parse_figure(cell)
    except ValueError:
        figure = None
    assert figure == number  # the two readings of one cell never disagree
    return None if number is None else float(number)


@pytest.mark.parametrize(
    "spellings", [SPELLINGS, _random_spellings(20_000)], ids=["written", "seeded"]
)
def test_figure_values_agree_with_the_bundles_parse_figure_on_every_spelling(
    spellings: tuple[str, ...] | list[str],
) -> None:
    read = 0
    for cell in spellings:
        number, value = _vendor(cell), figure_value(CONTRACT, cell)
        if number is None:
            assert value is None, cell
            continue
        read += 1
        assert value is not None, cell
        assert PLAIN.fullmatch(value), cell
        # The exact decimal rounds to the very float the bundle computed.
        assert float(Decimal(value)) == number, cell
    assert read > len(spellings) // 10, "a comparison that compared nothing"


def test_a_figure_is_exact_where_a_float_is_not() -> None:
    for cell, exact in (
        ("0.1", "0.1"),
        ("1,234,567.891234567890123", "1234567.891234567890123"),
        ("123456789012345678901", "123456789012345678901"),
    ):
        assert figure_value(CONTRACT, cell) == exact
        assert Decimal(float(exact)) != Decimal(exact), "a float would have held it"
    # And at the scale it was written, which a float does not keep either.
    assert figure_value(CONTRACT, "(7,125.00)") == "-7125.00"


def test_a_figure_past_the_wire_bound_has_no_value_and_keeps_its_text() -> None:
    at_bound = {"1e63": "1" + "0" * 63, "1e-62": "0." + "0" * 61 + "1"}
    for cell, plain in at_bound.items():
        assert figure_value(CONTRACT, cell) == plain
        assert len(plain) == tables.FIGURE_CHARS
    # The bundle reads `1e-400` as 0.0 -- its float underflowed -- and
    # `1e-999999` too, which is refused before a million digits are written.
    for cell in ("1e64", "1e-63", "9" * 65, "1e-400", "1e-999999"):
        assert CONTRACT.cp_tables.parse_figure(cell) is not None
        assert figure_value(CONTRACT, cell) is None, cell
    [table] = handoff_tables(CONTRACT, _tagged("t.x", ["v"], [["1e64"]])).tables
    assert table.rows == ((TableCell("1e64", None),),)


def test_zero_is_served_without_a_sign() -> None:
    for cell, plain in (("(0)", "0"), ("-0", "0"), ("-0.00", "0.00"), ("0e5", "0")):
        assert figure_value(CONTRACT, cell) == plain


def _fixture(name: str) -> dict[str, object]:
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    AnalysisDocument.model_validate(document)
    assert isinstance(document, dict)
    return document


def _served(derived: HandoffTables) -> list[dict[str, object]]:
    return [
        TableView(
            table_id=table.table_id,
            columns=list(table.columns),
            rows=[
                [CellView(text=c.text, value=c.value) for c in r] for r in table.rows
            ],
        ).model_dump(mode="json")
        for table in derived.tables
    ]


@pytest.mark.parametrize("name", ["analysis.json", "states/analysis.partial.json"])
def test_the_demo_fixtures_carry_exactly_the_tables_their_markdown_derives(
    name: str,
) -> None:
    body = _fixture(name)["body"]
    assert isinstance(body, dict)
    for handoff in body["handoffs"]:
        derived = handoff_tables(CONTRACT, handoff["model_analysis"])
        assert handoff["tables"] == _served(derived), handoff["module_id"]
        assert handoff["tables_unavailable_reason"] == derived.unavailable_reason


def _stable_columns() -> dict[str, set[str]]:
    """The CP-MODEL validator's own column sets, read from its verified bytes."""
    source = verified_bytes(BUNDLE, "CP-MODEL", "scripts/validate_cp_model_inputs.py")
    [columns] = [
        ast.literal_eval(node.value)
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "STABLE_TABLE_REQUIRED_COLUMNS"
            for t in node.targets
        )
    ]
    assert isinstance(columns, dict)
    return columns


def test_the_demo_cp1_tables_carry_the_bundles_column_names_literally() -> None:
    body = _fixture("analysis.json")["body"]
    assert isinstance(body, dict)
    [cp1] = [h for h in body["handoffs"] if h["module_id"] == "CP-1"]
    reference = verified_bytes(BUNDLE, "CP-1", "references/REF_CP-1_STEPS.md").decode()
    stable = _stable_columns()
    served = {t["table_id"]: t["columns"] for t in cp1["tables"]}
    assert list(served) == [
        "cp1.model_period_register",
        "cp1.segment_revenue_schedule",
        "cp1.operating_kpi_schedule",
        "cp1.adjusted_ebitda_bridge",
        "cp1.debt_facility_register",
    ]
    for table_id, columns in served.items():
        # In the order and spelling REF_CP-1_13 declares them.
        assert "`" + " | ".join(columns) + "`" in reference, table_id
        assert set(columns) == stable.get(table_id, set(columns)), table_id
