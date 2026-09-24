"""Forecast bytes must reconcile and bind every input to an accepted owner."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from forecast_fixtures import forecast_request

from caos.calculators.cash_flow import cash_flow_forecast
from caos.refusals import Refusal, RefusalCode


def forecast_markdown(request: dict[str, Any] | None = None) -> bytes:
    request = request or forecast_request()
    document = {
        "request": request,
        "bindings": {},
        "forecast": cash_flow_forecast(request),
    }
    return ("```caos-forecast-v1\n" + json.dumps(document) + "\n```\n").encode()


def test_forecast_projection_recomputes_the_exact_result() -> None:
    from caos.methodology.forecast import forecast_projection

    assert forecast_projection(forecast_markdown()) == cash_flow_forecast(
        forecast_request()
    )


def test_forecast_projection_refuses_changed_or_incomplete_result() -> None:
    from caos.methodology.forecast import forecast_projection

    valid = forecast_markdown()
    changed = valid.replace(b'"126.000000"', b'"999.000000"')
    request = forecast_request()
    request["drivers"][0]["status"] = "NOT_READY"
    for data in (changed, forecast_markdown(request), valid + valid):
        with pytest.raises(Refusal) as caught:
            forecast_projection(data)
        assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_forecast_projection_refuses_code_selection() -> None:
    from caos.methodology.forecast import forecast_projection

    raw = forecast_markdown().replace(
        b'"request":', b'"calculator": "os.system", "request":'
    )
    with pytest.raises(Refusal) as caught:
        forecast_projection(raw)
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_forecast_bindings_require_each_exact_accepted_owner_quote() -> None:
    from caos.methodology.forecast import validate_forecast_bindings

    with pytest.raises(Refusal) as caught:
        validate_forecast_bindings(forecast_markdown(), {}, {})
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_forecast_projection_refuses_duplicate_json_keys() -> None:
    from caos.methodology.forecast import forecast_projection

    raw = forecast_markdown().replace(
        b'"bindings": {}', b'"bindings": {}, "bindings": {}'
    )
    with pytest.raises(Refusal):
        forecast_projection(raw)


def test_forecast_projection_is_independent_of_ambient_decimal_context() -> None:
    from decimal import ROUND_DOWN, localcontext

    from caos.methodology.forecast import forecast_projection

    raw = forecast_markdown(deepcopy(forecast_request()))
    expected = forecast_projection(raw)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert forecast_projection(raw) == expected


def test_validate_driver_mapping_refuses_changed_vendor_movements() -> None:
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import validate_driver_mapping

    owner = canonical_markdown(route_identity("CP-2G"))
    markdown = forecast_markdown(request_data())
    validate_driver_mapping(CONTRACT, markdown, owner)
    changed = owner.replace(b"| 0 | CURRENCY_MM", b"| 1 | CURRENCY_MM", 1)
    assert changed != owner
    with pytest.raises(Refusal) as caught:
        validate_driver_mapping(CONTRACT, markdown, changed)
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE


def _driver_row(driver: str, case: str = "BASE", year: int = 2026) -> bytes:
    """The start of one fixture CP-2G driver row, up to its value cell."""
    return f"| {driver} |  | {case} | FY{year} | {year} | ".encode()


def _driver_cells(owner: bytes, driver: str, value: str, status: str) -> bytes:
    """`owner` with one BASE FY2026 CURRENCY_MM row's value and status replaced."""
    row = _driver_row(driver)
    start = owner.index(row)
    end = owner.index(b"\n", start)
    cells = owner[start:end].decode().split(" | ")
    assert cells[5] == "0" and cells[6] == "CURRENCY_MM" and cells[8] == "READY"
    cells[5], cells[8] = value, status
    return owner[:start] + " | ".join(cells).encode() + owner[end:]


@pytest.mark.parametrize(
    ("cell", "value"),
    [
        ("0", "0"),
        ("-45", "-45"),
        ("(45)", "-45"),
        ("( 45.5 )", "-45.5"),
        ("1,250.0", "1250.0"),
        ("(1,250,000.25)", "-1250000.25"),
        (" 12 ", "12"),
    ],
)
def test_a_driver_value_reads_comma_groups_and_parentheses_exactly(
    cell: str, value: str
) -> None:
    """G3-9: the bundle's own `parse_figure` reads `1,250.0` and `(45)`, and so
    does the host now, with `Decimal` and never a float (invariant 7)."""
    from decimal import Decimal

    from caos.methodology.forecast import driver_value

    read = driver_value(cell)
    assert isinstance(read, Decimal) and read == Decimal(value)
    assert str(read) == value


def test_a_parenthesised_driver_value_is_negated_exactly_in_any_context() -> None:
    """N14: `driver_value` negated with unary minus, an arithmetic operation
    rounded to the ambient context: at three digits `(1,250,000.25)` read as
    -1.25E+6. It flips the sign with `copy_negate`, as F271's reader does."""
    from decimal import Decimal, Inexact, localcontext

    from caos.methodology.forecast import driver_value

    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        read = driver_value("(1,250,000.25)")
    assert str(read) == "-1250000.25" and read == Decimal("-1250000.25")


@pytest.mark.parametrize(
    "cell",
    [
        "",
        "5,2",
        "1,25",
        "1.250,0",
        "12%",
        "$45",
        "1e3",
        "+45",
        "(-45)",
        "01",
        "0.1234567",
    ],
)
def test_a_driver_value_refuses_what_it_would_have_to_guess(cell: str) -> None:
    """An ambiguous separator, a decoration or a figure past the calculator's
    bound is refused, never guessed (`5,2` is 5.2 or 52 by notation)."""
    from caos.methodology.forecast import driver_value

    with pytest.raises(ValueError):
        driver_value(cell)


def test_a_not_applicable_driver_is_not_ready_but_a_bad_one_incomplete() -> None:
    """G3-9: CP-2G may mark a row NOT_APPLICABLE with a blank value; CP-CF then
    has nothing to project, which is `FORECAST_DRIVER_NOT_READY` ("Complete the
    driver first."), not the malformed handoff it was refused as. A row that
    breaks the vendor's own contract is still `HANDOFF_INCOMPLETE`, and a
    comma-grouped or parenthesised figure that equals the request is accepted."""
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import validate_driver_mapping

    owner = canonical_markdown(route_identity("CP-2G"))
    markdown = forecast_markdown(request_data())
    for driver in ("net_equity_issue_repay", "dividends_paid"):
        blank = _driver_cells(owner, driver, "", "NOT_APPLICABLE")
        with pytest.raises(Refusal) as caught:
            validate_driver_mapping(CONTRACT, markdown, blank)
        assert caught.value.code is RefusalCode.FORECAST_DRIVER_NOT_READY
    for value, status in (("0", "NOT_APPLICABLE"), ("0", "DRAFT"), ("5,2", "READY")):
        broken = _driver_cells(owner, "net_equity_issue_repay", value, status)
        with pytest.raises(Refusal) as caught:
            validate_driver_mapping(CONTRACT, markdown, broken)
        assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE
    # Malformed beats not ready: the answer is wrong whatever CP-2G states.
    both = _driver_cells(
        _driver_cells(owner, "dividends_paid", "", "NOT_APPLICABLE"),
        "net_equity_issue_repay",
        "7",
        "READY",
    )
    with pytest.raises(Refusal) as caught:
        validate_driver_mapping(CONTRACT, markdown, both)
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE
    # The same zero, written `(0)` or `0.0`, is the zero the request carries.
    zero = _driver_cells(owner, "other_investing_financing", "(0)", "READY")
    zero = _driver_cells(zero, "net_equity_issue_repay", "0.0", "READY")
    validate_driver_mapping(CONTRACT, markdown, zero)
    # CP-2G's outflows are negative and the calculator's positive (C2): a
    # `(45)` acquisition and a `(1,250.0)` dividend are 45 and 1250 here.
    request = request_data()
    request["drivers"][0].update(acquisitions_disposals="45", distributions="1250")
    moved = _driver_cells(owner, "acquisitions_disposals", "(45)", "READY")
    moved = _driver_cells(moved, "dividends_paid", "(1,250.0)", "READY")
    validate_driver_mapping(CONTRACT, forecast_markdown(request), moved)


# C2: CP-2G signs a driver as the vendor's CP-MODEL adds it into net cash flow
# (outflows negative), and the calculator subtracts both movements it maps. Per
# case: CP-2G's row, the request movement it is, and the close it projects
# from the route request's 145 (opening 100, no other movement).
SIGN_CASES = {
    "dividend": ("dividends_paid", "(45)", "distributions", "45", "100.000000"),
    "dividend-minus": ("dividends_paid", "-45", "distributions", "45", "100.000000"),
    "acquisition": (
        "acquisitions_disposals",
        "(45)",
        "acquisitions_disposals",
        "45",
        "100.000000",
    ),
    "disposal": (
        "acquisitions_disposals",
        "45",
        "acquisitions_disposals",
        "-45",
        "190.000000",
    ),
    "zero-dividend": ("dividends_paid", "(0)", "distributions", "0", "145.000000"),
    "zero-acquisition": (
        "acquisitions_disposals",
        "-0",
        "acquisitions_disposals",
        "0",
        "145.000000",
    ),
}


@pytest.mark.parametrize("case", sorted(SIGN_CASES))
def test_a_cp2g_driver_maps_to_the_calculator_with_its_sign_reversed(
    case: str,
) -> None:
    """C2: the host compared CP-2G's signed figure with the request's as
    written, so a `(45)` dividend matched only distributions -45, which the
    calculator refuses -- no dividend-paying forecast could pass -- and a
    `(45)` acquisition matched only -45, which the calculator books as an
    inflow: closing cash 190 instead of 100. Each mapped row now declares its
    conversion, and the opposite sign is refused."""
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import validate_driver_mapping

    driver, cell, field, movement, closing = SIGN_CASES[case]
    owner = _driver_cells(
        canonical_markdown(route_identity("CP-2G")), driver, cell, "READY"
    )
    request = request_data()
    request["drivers"][0].update({field: movement, "stated_closing_cash": closing})
    forecast = cash_flow_forecast(request)
    assert forecast["status"] == "complete"
    assert forecast["rows"][0]["cash"]["closing"] == closing
    validate_driver_mapping(CONTRACT, forecast_markdown(request), owner)
    if movement == "0":
        return
    # The request as CP-2G writes it -- the pairing the host used to accept --
    # is refused, or refused by the calculator itself for a distribution.
    request["drivers"][0][field] = (
        movement[1:] if movement[0] == "-" else "-" + movement
    )
    try:
        opposite = forecast_markdown(request)
    except Refusal as refused:
        assert field == "distributions"
        assert refused.code is RefusalCode.METHODOLOGY_INPUT_INVALID
        return
    with pytest.raises(Refusal) as caught:
        validate_driver_mapping(CONTRACT, opposite, owner)
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_a_dividend_cp2g_writes_as_an_inflow_maps_to_no_request() -> None:
    """C2: a `dividends_paid` row written positive is an inflow in CP-2G's
    convention; negated it is a distribution of -45, which the calculator's
    unsigned field refuses, so the request's 45 is not it and the answer is
    refused rather than booked as a payment."""
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import driver_line, validate_driver_mapping

    owner = _driver_cells(
        canonical_markdown(route_identity("CP-2G")), "dividends_paid", "45", "READY"
    )
    request = request_data()
    request["drivers"][0].update(distributions="45", stated_closing_cash="100")
    markdown = forecast_markdown(request)
    with pytest.raises(Refusal) as caught:
        validate_driver_mapping(CONTRACT, markdown, owner)
    assert caught.value.code is RefusalCode.HANDOFF_INCOMPLETE
    assert "distributions once negated" in (
        driver_line(CONTRACT, markdown, owner) or ""
    )


def test_a_request_movement_the_calculator_would_not_read_maps_to_nothing() -> None:
    """The request's movement is read as the calculator reads it -- a string
    in its own number form, with `Decimal` -- never a float or another type."""
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import _faults_or_none

    owner = canonical_markdown(route_identity("CP-2G"))
    assert _faults_or_none(CONTRACT, request_data(), owner) == []
    for wrong in (0, 0.0, "0.0000001", "00", "-", None):
        request = request_data()
        request["drivers"][0]["distributions"] = wrong
        assert _faults_or_none(CONTRACT, request, owner) is None


def test_the_driver_line_names_each_row_by_its_id_never_a_value() -> None:
    """What CP-CF's second attempt is told about the driver rows its request
    could not map: the driver ID, case and period of each, never a cell."""
    from canonical_fixtures import CONTRACT
    from canonical_route_fixtures import canonical_markdown, route_identity
    from test_forecast_route import request_data

    from caos.methodology.forecast import driver_line

    owner = canonical_markdown(route_identity("CP-2G"))
    request = request_data()
    request["drivers"][0]["distributions"] = "4"
    markdown = forecast_markdown(request)
    blank = _driver_cells(owner, "net_equity_issue_repay", "", "NOT_APPLICABLE")
    assert driver_line(CONTRACT, markdown, blank) == (
        "host driver check: CP-2G's `dividends_paid` row for BASE FY2026 does not"
        " equal the request's distributions once negated: CP-2G signs an outflow"
        " negative, the calculator positive; CP-2G's `net_equity_issue_repay` row"
        " for BASE FY2026 is NOT_APPLICABLE, not READY"
    )
    assert driver_line(CONTRACT, forecast_markdown(request_data()), owner) is None
    assert driver_line(CONTRACT, b"no forecast block", owner) is None
    assert driver_line(CONTRACT, markdown, b"no driver table") is None


def test_unclosed_block_openers_cost_no_more_than_their_length() -> None:
    """EV-6: the block was found by a lazy DOTALL expression, and each opener
    with no closer after it scanned to the end of the document: one real block
    and 8,000 unclosed openers inside a `~~~` fence took about 6 s, GIL held,
    on every read of the model analysis. Found by a forward scan now."""
    import time

    from caos.methodology.forecast import forecast_projection

    tail = b"~~~\n" + b"```caos-forecast-v1\n" * 8_000 + b"~~~\n"
    carried = b"## Analysis\n\n" + forecast_markdown() + b"\n## Next\n\n" + tail
    started = time.perf_counter()
    result = forecast_projection(carried)
    spent = time.perf_counter() - started
    assert result == cash_flow_forecast(forecast_request())
    assert spent < 1.0, spent


@pytest.mark.parametrize(
    "text",
    [
        "```caos-forecast-v1\n{}\n```",
        "```caos-forecast-v1\n{}\n```\n",
        "```caos-forecast-v1\n\n```\n",
        "```caos-forecast-v1\n```\n```\n",
        "```caos-forecast-v1\n{}\n```x\n```\n",
        "x```caos-forecast-v1\n{}\n```\n",
        "```caos-forecast-v1 \n{}\n```\n",
        "```caos-forecast-v1\na\n```caos-forecast-v1\nb\n```\n```\n",
        "```caos-forecast-v1\na\n```\n```caos-forecast-v1\nb\n```\n",
        "```caos-forecast-v1\na\n```\n\n```caos-forecast-v1\nb\n```",
        "```caos-forecast-v1\r\na\r\n```\r\n",
        "```caos-forecast-v1\na\n```\r\n```\n",
        "```caos-forecast-v1\n" * 3,
        "",
    ],
)
def test_the_block_scan_finds_what_the_expression_found(text: str) -> None:
    """The scan is the old expression's answer, block for block, on every edge
    it had: a closer that is not alone on its line, an opener inside a body,
    an empty body, a closer on the opener's next line, no final newline."""
    import re

    from caos.methodology.forecast import _blocks

    expression = re.compile(
        r"^```caos-forecast-v1\n(.*?)\n```$", re.MULTILINE | re.DOTALL
    )
    assert _blocks(text) == expression.findall(text)


def test_answer_markdown_is_the_transports_markdown_or_none() -> None:
    """What CP-CF's second attempt reads the refused request from: the stored
    answer's Markdown bytes, or nothing when the body is not the transport."""
    from uuid import UUID

    from canonical_fixtures import wire

    from caos.methodology.handoff import answer_markdown

    cited = {"source_id": str(UUID(int=1)), "page": 1, "matched_text": "Revenue"}
    body = wire(forecast_markdown(), [cited])
    assert answer_markdown(body) == forecast_markdown()
    assert answer_markdown("not json") is None
    assert answer_markdown(json.dumps({"canonical_markdown": "x"})) is None


def test_the_brief_and_the_extension_state_the_driver_sign_convention() -> None:
    """C2: CP-CF's brief and the forecast owners' extension say that CP-2G's
    driver table keeps the vendor's signs, outflows negative, and that the
    request's `distributions` and `acquisitions_disposals` are the vendor
    figure with its sign reversed -- the rule `_DRIVER_ROWS` enforces."""
    from caos.icm import prompt_block
    from caos.methodology.host import verified_host_bytes

    brief = " ".join(verified_host_bytes("SKILL.md").decode().split())
    extension = " ".join(prompt_block("forecast_extension").split())
    for text in (brief, extension):
        assert "outflows negative" in text
        assert "distributions 45" in text
    assert "each with its sign reversed" in brief
    assert "a `(45)` acquisition is acquisitions_disposals 45" in brief
    assert "a `45` disposal is -45" in brief
    assert "a 45 dividend is `dividends_paid` (45) and distributions 45" in extension
    assert "a 45 disposal `acquisitions_disposals` 45 and -45" in extension
