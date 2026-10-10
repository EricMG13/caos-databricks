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
    HandoffRegister,
    HandoffRegisters,
    HandoffTable,
    HandoffTables,
    TableCell,
    figure_value,
    handoff_registers,
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
    for cell in ("1e64", "1e-63", "9" * 65):
        assert CONTRACT.cp_tables.parse_figure(cell) is not None
        assert figure_value(CONTRACT, cell) is None, cell
    # Fork r3 (N57): the bundle no longer underflows `1e-400` to 0.0; it refuses
    # an exponent outside float's range, `1e-999999` too, and so the host
    # serves no value either, before a million digits are written.
    for cell in ("1e-400", "1e-999999"):
        with pytest.raises(ValueError):
            CONTRACT.cp_tables.parse_figure(cell)
        assert figure_value(CONTRACT, cell) is None, cell
    [table] = handoff_tables(CONTRACT, _tagged("t.x", ["v"], [["1e64"]])).tables
    assert table.rows == ((TableCell("1e64", None),),)


@pytest.mark.parametrize(
    "cell",
    [
        "123456789012345678901234567890",
        "9" * 63,
        "9" * 64,
        "1e62",
        "1e1000000",
        "1e-62",
        "1,234,567.891234567890123456789",
        "0e1000000",
    ],
)
def test_an_accounting_parenthesis_is_the_positive_figure_negated(cell: str) -> None:
    """R24-10: unary minus applied the ambient 28-digit context, so the
    parenthesized form of a 30-digit figure was rounded where the figure was
    not, and `(1e1000000)` raised `decimal.Overflow` out of the table reader
    where the positive form is simply served no value. The sign is now exact
    and context-free: the parenthesized cell reads as the minus-signed one --
    the positive figure negated, or no value exactly where that has none (the
    sign counts toward `FIGURE_CHARS`, as the wire's bound does)."""
    positive = figure_value(CONTRACT, cell)
    negated = figure_value(CONTRACT, f"({cell})")
    assert negated == figure_value(CONTRACT, f"-{cell}")
    if positive is None:
        assert negated is None
    elif negated is not None:
        # `copy_negate`: unary minus here would round, as the reader did.
        assert Decimal(negated) == Decimal(positive).copy_negate()
        assert negated == ("-" + positive if Decimal(positive) else positive)
    [table] = handoff_tables(CONTRACT, _tagged("t.x", ["v"], [[f"({cell})"]])).tables
    assert table.rows == ((TableCell(f"({cell})", negated),),)


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


def _skill(module_id: str) -> str:
    return verified_bytes(BUNDLE, module_id, "SKILL.md").decode("utf-8")


def _register(heading: str, columns: list[str], rows: list[list[str]]) -> str:
    lines = [heading, "", "| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n\n"


HEADROOM = [
    *("Test", "Test Type", "Threshold", "Current Basis", "Formula", "Headroom (x)"),
    *("Status", "Limitation", "Risk Mechanic", "Credit Implication", "Evidence ID"),
]


def test_a_register_is_served_under_its_id_with_the_columns_the_bundle_binds() -> None:
    rows = [
        [
            *("Net leverage", "Maintenance", "5.00x", "3.50x", "Net debt / EBITDA"),
            *("1.50x", "Pass", "None", "Margin squeeze", "Low PD", "E1"),
        ],
        [
            *("Interest cover", "Incurrence", "2.00x"),
            "[Insufficient Information] \u2014 current tested ratio",
            *("EBITDA / interest", "n/a", "Untested", "No Q4 accounts"),
            *("Rate rise", "Watch", "E2"),
        ],
    ]
    markdown = "## Analysis\n\n" + _register(
        "### T4C.4 \u2014 Covenant headroom", HEADROOM, rows
    )

    found = handoff_registers(CONTRACT, _skill("CP-4"), "CP-4", markdown)

    assert found.unavailable_reason is None
    [register] = found.registers
    assert register.register_id == "T4C.4"
    assert register.columns == tuple(HEADROOM)
    assert register.declared == tuple(
        "Headroom" if c == "Headroom (x)" else c for c in HEADROOM
    )
    assert register.rows == tuple(
        tuple(TableCell(cell, figure_value(CONTRACT, cell)) for cell in row)
        for row in rows
    )
    assert register.rows[0][2] == TableCell("5.00x", "5.00")
    assert register.rows[1][3] == TableCell(
        "[Insufficient Information] \u2014 current tested ratio", None
    )


def test_a_template_column_binds_no_declared_column() -> None:
    markdown = _register(
        "### T4.6 \u2014 Cash flow statement",
        ["Line Item", "FY2024", "FY2025"],
        [["Operating cash flow", "120", "(45)"]],
    )

    found = handoff_registers(CONTRACT, _skill("CP-1"), "CP-1", markdown)

    assert found == HandoffRegisters(
        (
            HandoffRegister(
                "T4.6",
                ("Line Item", "FY2024", "FY2025"),
                ("Line Item", None, None),
                (
                    (
                        TableCell("Operating cash flow", None),
                        TableCell("120", "120"),
                        TableCell("(45)", "-45"),
                    ),
                ),
            ),
        ),
        None,
    )


def test_registers_come_back_in_the_profiles_order_and_only_those_written() -> None:
    # Written T4.6 first; the profile declares T4.4 first; T4.5 is not written.
    markdown = _register(
        "### T4.6 \u2014 Cash flow statement", ["Line Item", "FY2025"], [["Capex", "9"]]
    ) + _register(
        "### T4.4 \u2014 Income statement", ["Line Item", "FY2025"], [["Revenue", "7"]]
    )

    found = handoff_registers(CONTRACT, _skill("CP-1"), "CP-1", markdown)

    assert [r.register_id for r in found.registers] == ["T4.4", "T4.6"]
    assert found.unavailable_reason is None


def test_a_skill_with_no_output_profile_declares_no_registers() -> None:
    markdown = _register("### T4.6", ["Line Item", "FY2025"], [["Capex", "9"]])
    assert handoff_registers(
        CONTRACT, "# A skill\n\nNo profile here.\n", "CP-1", markdown
    ) == HandoffRegisters((), None)


def test_a_register_past_a_bound_serves_none_as_tables_too_large() -> None:
    def written(rows: int) -> str:
        return _register("### T4.6", ["Line Item", "FY2025"], [["Capex", "9"]] * rows)

    skill = _skill("CP-1")
    at_bound = handoff_registers(
        CONTRACT, skill, "CP-1", written(tables.TABLE_ROWS_MAX)
    )
    assert at_bound.unavailable_reason is None
    assert len(at_bound.registers[0].rows) == tables.TABLE_ROWS_MAX
    past = handoff_registers(
        CONTRACT, skill, "CP-1", written(tables.TABLE_ROWS_MAX + 1)
    )
    assert past == HandoffRegisters((), "TABLES_TOO_LARGE")


def test_every_declared_register_id_fits_the_wires_table_id() -> None:
    checker = CONTRACT.completeness_check
    ids: list[str] = []
    for module_id in BUNDLE.physical_modules():
        text = _skill(module_id)
        for profile in checker.profile_bodies(text):
            ids += checker.load_contract(text, profile)["registers"]
    assert ids
    for register_id in ids:
        assert re.fullmatch(r"[A-Za-z0-9_.]+", register_id), register_id
        assert len(register_id) <= tables.TABLE_ID_CHARS, register_id


def test_a_register_row_of_another_width_than_its_header_is_malformed() -> None:
    # Threshold left out: the vendor pads the row, so `3.50x` would sit under
    # Threshold and `E1` under Notes.
    row = [
        *("Net leverage", "Maintenance", "3.50x", "Net debt / EBITDA", "1.50x"),
        *("Pass", "None", "Margin squeeze", "Low PD", "E1"),
    ]
    markdown = _register(
        "### T4C.4 \u2014 Covenant headroom", [*HEADROOM, "Notes"], [row]
    )
    found = handoff_registers(CONTRACT, _skill("CP-4"), "CP-4", markdown)
    assert found == HandoffRegisters((), "TABLES_MALFORMED")


@pytest.mark.parametrize(
    "header",
    [["Line Item", "FY2025", "FY2025"], ["Line Item", "", "FY2025"]],
    ids=["repeated", "empty"],
)
def test_a_register_header_with_a_repeated_or_empty_cell_is_malformed(
    header: list[str],
) -> None:
    markdown = _register("### T4.6", header, [["Capex", "9", "11"]])
    found = handoff_registers(CONTRACT, _skill("CP-1"), "CP-1", markdown)
    assert found == HandoffRegisters((), "TABLES_MALFORMED")


def test_a_cell_two_columns_claim_is_declared_to_the_one_it_spells() -> None:
    # Without `Test`, the bundle binds `Test` to the `Test Type` cell too.
    header = HEADROOM[1:]
    row = [
        *("Maintenance", "5.00x", "3.50x", "Net debt / EBITDA", "1.50x"),
        *("Pass", "None", "Margin squeeze", "Low PD", "E1"),
    ]
    markdown = _register("### T4C.4 \u2014 Covenant headroom", header, [row])
    [register] = handoff_registers(CONTRACT, _skill("CP-4"), "CP-4", markdown).registers
    assert register.declared[0] == "Test Type"
    assert "Test" not in register.declared


@pytest.mark.parametrize("letter", ["\u0130", "\u0131"])
def test_a_vendor_exception_on_the_answer_is_malformed(letter: str) -> None:
    # The locator's title match is case-insensitive where its lookup casefolds.
    markdown = _register(f"#### Company descr{letter}ption", ["a", "b"], [["1", "2"]])
    found = handoff_registers(CONTRACT, _skill("CP-1A"), "CP-1A", markdown)
    assert found == HandoffRegisters((), "TABLES_MALFORMED")
