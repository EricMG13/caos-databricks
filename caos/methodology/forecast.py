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


def validate_driver_mapping(
    contract: VendorContract, markdown: bytes, owner: bytes
) -> None:
    """Only two vendor driver rows map to movements; unsupported cash flows refuse."""
    request = _document(markdown)["request"]
    try:
        table = contract.completeness_check.parse_tables(owner.decode())[
            "cp2g.cp_model_forecast_drivers"
        ]
        rows = table.rows
        _mapped_rows(request, rows)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        pass
    else:
        return
    raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)


def _mapped_rows(request: Mapping[str, Any], rows: list[dict[str, str]]) -> None:
    if request["units"]["scale"] != "millions":
        raise ValueError
    for driver in request["drivers"]:
        period = next(
            p
            for p in request["periods"]
            if (p["case"], p["period_id"]) == (driver["case"], driver["period_id"])
        )
        for vendor, field in (
            ("acquisitions_disposals", "acquisitions_disposals"),
            ("dividends_paid", "distributions"),
            ("net_equity_issue_repay", None),
            ("other_investing_financing", None),
        ):
            matches = [
                r
                for r in rows
                if (
                    r.get("driver_id"),
                    r.get("case"),
                    r.get("period_id"),
                    r.get("fiscal_year"),
                )
                == (vendor, driver["case"], driver["period_id"], period["fiscal_year"])
            ]
            if len(matches) != 1:
                raise ValueError
            row = matches[0]
            if row["status"] != "READY" or row["unit"] != "CURRENCY_MM":
                raise ValueError
            value = row["value"]
            if re.fullmatch(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?", value) is None:
                raise ValueError
            if Decimal(value) != Decimal(driver[field] if field else "0"):
                raise ValueError
