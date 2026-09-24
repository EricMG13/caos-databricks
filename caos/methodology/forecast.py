"""Closed CP-CF request, host-recomputed projection and accepted owner bindings."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from caos.calculators.cash_flow import cash_flow_forecast
from caos.evidence.citations import AnchoredCitation
from caos.methodology.host import verified_host_bytes
from caos.methodology.vendor import VendorContract
from caos.refusals import Refusal, RefusalCode

# A block is an opener line, then its body, then the first line after the
# body that is exactly the closer. Found by two forward searches rather than
# one lazy DOTALL expression, whose every opener with no closer after it
# scanned to the end of the document: thousands of unclosed openers made one
# read of the model analysis quadratic, GIL held (EV-6).
_OPENER = re.compile(r"^```caos-forecast-v1\n", re.MULTILINE)
_CLOSER = re.compile(r"\n```$", re.MULTILINE)
_LIMIT = 1024 * 1024
_OWNERS = {
    "opening": "CP-1",
    "periods": "CP-1",
    "units": "CP-1",
    "perimeter": "CP-1",
    "drivers": "CP-2G",
    "tolerance": "CP-2G",
    "contractual": "CP-4",
}


def _blocks(text: str) -> list[str]:
    """Every block's body, in order, each searched for once.

    An opener with no closer after it ends the search: every later opener
    would have none either. The scan resumes after each closer, so a body is
    never searched again for an opener.
    """
    bodies: list[str] = []
    at = 0
    while (opener := _OPENER.search(text, at)) is not None:
        closer = _CLOSER.search(text, opener.end())
        if closer is None:
            break
        bodies.append(text[opener.end() : closer.start()])
        at = closer.end()
    return bodies


def _document(markdown: bytes) -> dict[str, Any]:
    from caos.methodology.handoff import strict_json

    try:
        found = _blocks(markdown.decode("utf-8"))
        document = (
            strict_json(found[0])
            if len(found) == 1 and len(found[0].encode()) <= _LIMIT
            else None
        )
    except (ValueError, RecursionError):
        document = None
    if (
        isinstance(document, dict)
        and set(document) == {"request", "bindings", "forecast"}
        and isinstance(document["request"], dict)
        and isinstance(document["bindings"], dict)
    ):
        return document
    raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)


def forecast_projection(markdown: bytes) -> dict[str, Any]:
    """Exact complete result, rederived before a Model reader may expose it.

    Callers must first obtain the Markdown with `accepted_handoff`, which
    additionally verifies current run identity, authority and owner bindings.
    This pure reader alone does not confer accepted provenance.
    """
    verified_host_bytes("scripts/cash_flow.py")
    document = _document(markdown)
    result = cash_flow_forecast(document["request"])
    if result["status"] != "complete" or json.dumps(
        result, sort_keys=True, ensure_ascii=False
    ) != json.dumps(document["forecast"], sort_keys=True, ensure_ascii=False):
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    return result


def forecast_inputs(markdown: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """The accepted request and its owner bindings, for a reader that must name
    the driver behind a projected figure and the quote it was bound to.

    Pure, like `forecast_projection` beside it: it confers no provenance. A
    caller states the figure's lineage only after that function has re-derived
    the projection from these same bytes.
    """
    document = _document(markdown)
    return document["request"], document["bindings"]


def _leaves(value: object, path: str = "") -> dict[str, object]:
    if isinstance(value, dict) and value:
        return {
            pointer: leaf
            for key, item in value.items()
            for pointer, leaf in _leaves(item, path + "/" + str(key)).items()
        }
    if isinstance(value, list) and value:
        return {
            pointer: leaf
            for index, item in enumerate(value)
            for pointer, leaf in _leaves(item, path + "/" + str(index)).items()
        }
    return {path: value}


def validate_forecast_bindings(
    markdown: bytes,
    upstream: Mapping[str, bytes],
    citations: Mapping[str, Sequence[AnchoredCitation]],
) -> None:
    """Every requested value must be an exact assignment anchored by its owner.

    Empty arrays are also bound: absence of contractual repayments is an
    explicit CP-4 statement, never a missing-input default.
    """
    forecast_projection(markdown)
    document = _document(markdown)
    leaves = _leaves(document["request"])
    bindings = document["bindings"]
    if set(bindings) != set(leaves) or not {"CP-1", "CP-2G", "CP-4"} <= set(upstream):
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    for pointer, value in leaves.items():
        owner = _OWNERS[pointer.split("/")[1]]
        binding = bindings[pointer]
        if not isinstance(binding, dict) or set(binding) != {"module_id", "quote"}:
            raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
        quote = binding["quote"]
        assignment = pointer + " = " + json.dumps(value, ensure_ascii=False)
        if (
            binding["module_id"] != owner
            or not isinstance(quote, str)
            or assignment not in quote.splitlines()
            or quote not in {c.matched_text for c in citations.get(owner, ())}
            or quote not in upstream[owner].decode("utf-8")
            or quote not in markdown.decode("utf-8")
        ):
            raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)


_DRIVER_TABLE = "cp2g.cp_model_forecast_drivers"
# The CP-2G driver rows CP-CF maps for each case and period (G3-9): each to the
# request movement named, or -- None -- to no movement this contract carries,
# so the row must be a READY 0 with its own source line.
_DRIVER_ROWS: tuple[tuple[str, str | None], ...] = (
    ("acquisitions_disposals", "acquisitions_disposals"),
    ("dividends_paid", "distributions"),
    ("net_equity_issue_repay", None),
    ("other_investing_financing", None),
)
# A driver value as the host reads it (G3-9): digits grouped by commas in
# threes or not at all, an optional fraction, and a sign written as a leading
# minus or as accounting parentheses -- `1,250.0` and `(45)`, as the bundle's
# own `cp_tables.parse_figure` reads them -- read with `Decimal`, never a float.
# Anything else is refused, never guessed: `5,2` is 5.2 in continental notation
# and a malformed 52 in Anglo, `1.250,0` is continental, and a percent is read
# two ways by the bundle itself (N57); none is a CURRENCY_MM figure.
_GROUPED = re.compile(r"(-?)([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(\.[0-9]+)?")
# The figure once its grouping and parentheses are read: the calculator's own
# bound on an amount, 18 integer digits and 6 decimals, no leading zero.
_PLAIN = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?")
# The one fault that is CP-2G's permitted word, not a malformed row.
_NOT_READY = "is NOT_APPLICABLE, not READY"
# How many refused rows one feedback line names; the rest are counted.
_LINE_ROWS = 8
_ROW_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def driver_value(cell: str) -> Decimal:
    """A CP-2G driver cell's exact figure: plain, comma-grouped in threes, or a
    negative in accounting parentheses. `ValueError` for anything else,
    ambiguous separators and decorations included (G3-9)."""
    text = cell.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    found = _GROUPED.fullmatch(text)
    if found is None or (negative and found.group(1)):
        raise ValueError
    sign, digits, fraction = found.groups()
    plain = sign + digits.replace(",", "") + (fraction or "")
    if _PLAIN.fullmatch(plain) is None:
        raise ValueError
    value = Decimal(plain)
    # `copy_negate`, not unary minus (F271): unary minus is an arithmetic
    # operation, rounded to the ambient context's precision and signalling
    # under its traps; the sign flip is exact whatever the context says.
    return value.copy_negate() if negative else value


def validate_driver_mapping(
    contract: VendorContract, markdown: bytes, owner: bytes
) -> None:
    """The four CP-2G driver rows CP-CF maps, read and compared exactly (G3-9).

    Unsupported cash flows refuse. `FORECAST_DRIVER_NOT_READY` where every row
    CP-CF needs is readable and one or more is NOT_APPLICABLE: CP-2G's
    permitted word, which leaves CP-CF nothing to project until CP-2G states
    the row READY (a zero with its own source line). `HANDOFF_INCOMPLETE` for
    anything else it cannot map: no table, a scale other than millions, a
    missing or doubled row, a status, unit or value that is malformed, or a
    value that is not the request's movement -- or, for the two movements this
    contract lacks, not 0.
    """
    request = _document(markdown)["request"]
    faults = _faults_or_none(contract, request, owner)
    if faults is None or any(fault != _NOT_READY for _row, fault in faults):
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    if faults:
        raise Refusal(RefusalCode.FORECAST_DRIVER_NOT_READY)


def driver_line(contract: VendorContract, markdown: bytes, owner: bytes) -> str | None:
    """Which CP-2G driver rows a refused CP-CF answer's request cannot map, for
    its one second attempt (D30): each by driver ID, case and period, never a
    value (G3-9). None when the answer carries no readable request or every
    row maps."""
    try:
        request = _document(markdown)["request"]
    except Refusal:
        return None
    faults = _faults_or_none(contract, request, owner)
    if not faults:
        return None
    shown = [f"CP-2G's {row} {fault}" for row, fault in faults[:_LINE_ROWS]]
    rest = len(faults) - len(shown)
    return (
        "host driver check: "
        + "; ".join(shown)
        + (f"; and {rest} more rows" if rest else "")
    )


def _faults_or_none(
    contract: VendorContract, request: Mapping[str, Any], owner: bytes
) -> list[tuple[str, str]] | None:
    """`_faults` over CP-2G's accepted driver table, or None when the table,
    the request or a value will not read at all."""
    try:
        table = contract.completeness_check.parse_tables(owner.decode())[_DRIVER_TABLE]
        return _faults(contract, request, table.rows)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return None


def _faults(
    contract: VendorContract, request: Mapping[str, Any], rows: list[dict[str, str]]
) -> list[tuple[str, str]]:
    """(row, fault) for each CP-2G driver row the request needs and CP-CF cannot
    map, in request order."""
    if request["units"]["scale"] != "millions":
        raise ValueError
    faults: list[tuple[str, str]] = []
    for driver in request["drivers"]:
        pair = (driver["case"], driver["period_id"])
        period = next((p for p in request["periods"] if _pair(p) == pair), None)
        if period is None:
            raise ValueError
        for vendor, field in _DRIVER_ROWS:
            key = (vendor, *pair, period["fiscal_year"])
            wanted = driver[field] if field else "0"
            fault = _row_fault(contract, rows, key, wanted, field)
            if fault is not None:
                faults.append((_row_name(key), fault))
    return faults


def _pair(period: Mapping[str, Any]) -> tuple[object, object]:
    return period["case"], period["period_id"]


def _row_fault(
    contract: VendorContract,
    rows: list[dict[str, str]],
    key: tuple[str, ...],
    wanted: str,
    field: str | None,
) -> str | None:
    """Why the one CP-2G row `key` names cannot be mapped to `wanted`, or None."""
    matches = [
        row
        for row in rows
        if (
            row.get("driver_id"),
            row.get("case"),
            row.get("period_id"),
            row.get("fiscal_year"),
        )
        == key
    ]
    if len(matches) != 1:
        return "is not exactly one row"
    row = matches[0]
    status, value = row.get("status"), row.get("value", "")
    if row.get("unit") != "CURRENCY_MM":
        return "is not CURRENCY_MM"
    if status == "NOT_APPLICABLE" and contract.cp_tables.is_null(value):
        return _NOT_READY
    if status != "READY":
        return "is neither READY nor NOT_APPLICABLE with a blank value"
    try:
        figure = driver_value(value)
    except ValueError:
        return "holds no plain, comma-grouped or parenthesised figure"
    if figure == Decimal(wanted):
        return None
    if field is None:
        return "is not 0, and this contract carries no such movement"
    return f"does not equal the request's {field}"


def _row_name(key: tuple[str, ...]) -> str:
    """`dividends_paid` row for BASE FY2026: the driver ID, and the case and
    period where each is a plain identifier; never other text."""
    vendor, case, period, _year = key
    if all(_ROW_KEY.fullmatch(str(part)) for part in (case, period)):
        return f"`{vendor}` row for {case} {period}"
    return f"`{vendor}` row"
