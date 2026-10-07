"""GitHub Copilot as the model behind the one factory (D77, addendum 2): the
names, the shared reply mapping against the SDK's own event schema (R1), the
AI-unit charge (R2.3, R2.4, R2.9) and spend on a failed call (R2.10).

Every fake event is built through `copilot.SessionEvent.from_dict(...).to_dict()`
(R5), so a field the pinned SDK does not know, or a value it cannot parse,
fails the fake and not the adapter.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from langchain_core.messages import AIMessage

from caos.copilot import (
    CopilotModel,
    parsed,
    settled_charge,
)
from caos.provider import (
    reserved_amount,
    reserving,
)
from caos.refusals import Refusal, RefusalCode

PIN = "claude-opus-5.5"
MODEL = f"copilot:{PIN}@high"
TARGET = CopilotModel("copilot", PIN, "high")
# GitHub's published rate, one AI credit in US dollars (D77).
CREDIT = Decimal("0.01")


# -- The fakes (R5): every one through the SDK's own types. ----------------


# -- Names (Design 1). -------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (MODEL, TARGET),
        ("copilot:gpt-6-luna", CopilotModel("copilot", "gpt-6-luna", None)),
        (
            "copilot-cli:gpt-6-luna@low",
            CopilotModel("copilot-cli", "gpt-6-luna", "low"),
        ),
        ("claude-opus-5-5", None),
        ("databricks-claude-opus-5", None),
        ("other:thing", None),
        ("openai/gpt-6-luna", None),
    ],
)
def test_a_copilot_name_is_its_platform_model_and_effort_and_any_other_is_an_endpoint(
    name: str, expected: CopilotModel | None
) -> None:
    assert parsed(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "copilot:",
        "copilot-cli:",
        "copilot:Claude-Opus",
        "copilot:gpt-6@turbo",
        "copilot:gpt-6@none",
        "copilot:gpt-6@high@low",
        "copilot:gpt 6",
        "copilot:-gpt",
        "copilot:gpt:6",
        "copilot:gpt-6\n",
        "Copilot:gpt-6",
        "COPILOT-CLI:gpt-6",
        "copilot:" + "a" * 129,
    ],
)
def test_a_name_that_claims_copilot_and_does_not_parse_is_refused(name: str) -> None:
    with pytest.raises(Refusal) as refused:
        parsed(name)
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_the_longest_model_id_parses() -> None:
    longest = "a" * 128
    assert parsed("copilot:" + longest) == CopilotModel("copilot", longest, None)


# -- The witnesses (R1). -----------------------------------------------------


# -- The charge (R2.3, R2.4, R2.9). ------------------------------------------


def test_the_largest_whole_ai_unit_count_is_charged_exactly() -> None:
    largest = 2**53 - 1
    message = AIMessage(content="answer", response_metadata={"nano_aiu": largest})
    expected = Decimal(largest) * Decimal("0.03") / Decimal(10**9)
    assert settled_charge(message, Decimal("0.03")) == expected


@pytest.mark.parametrize(
    ("nano_aiu", "credit"),
    [
        (None, CREDIT),
        ("251164000", CREDIT),
        (251_164_000.0, CREDIT),
        (True, CREDIT),
        (-1, CREDIT),
        (2**53, CREDIT),
        (251_164_000, None),
        (251_164_000, 0.01),
        (251_164_000, Decimal("0")),
        (251_164_000, Decimal("-0.01")),
        (251_164_000, Decimal("NaN")),
    ],
)
def test_a_charge_with_no_whole_ai_units_or_no_credit_price_is_unknown(
    nano_aiu: object, credit: object
) -> None:
    message = AIMessage(content="answer", response_metadata={"nano_aiu": nano_aiu})
    assert settled_charge(message, cast(Decimal, credit)) is None


def test_a_stated_zero_settles_at_zero() -> None:
    message = AIMessage(content="", response_metadata={"nano_aiu": 0})
    assert settled_charge(message, CREDIT) == Decimal(0)


# -- Spend on a failed call (R2.10) and the errors (R1). ---------------------


# -- ChatCopilot (the seam `ChatCompletions` calls). --------------------------


# -- The reservation in scope (R2.7's input; `caos.provider`). ---------------


def test_reserving_names_the_reservation_only_inside_its_block() -> None:
    assert reserved_amount.get() is None
    with reserving(Decimal("1.5")):
        assert reserved_amount.get() == Decimal("1.5")
        with reserving(Decimal("0.25")):
            assert reserved_amount.get() == Decimal("0.25")
        assert reserved_amount.get() == Decimal("1.5")
    assert reserved_amount.get() is None
    with pytest.raises(RuntimeError), reserving(Decimal(2)):
        raise RuntimeError
    assert reserved_amount.get() is None


@pytest.mark.parametrize(
    ("amount", "code"),
    [
        (1.5, RefusalCode.MONEY_NOT_DECIMAL),
        (Decimal(-1), RefusalCode.MONEY_INVALID),
        (Decimal("NaN"), RefusalCode.MONEY_INVALID),
    ],
)
def test_reserving_refuses_an_amount_that_is_no_spend(
    amount: object, code: RefusalCode
) -> None:
    with pytest.raises(Refusal) as refused, reserving(cast(Decimal, amount)):
        pytest.fail("entered")
    assert refused.value.code is code
    assert reserved_amount.get() is None


# -- What mutation testing found the suite did not pin. ----------------------
