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
