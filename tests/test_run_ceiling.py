"""The deployment's run ceiling (F28): named by the environment, priced policy."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import preflight
import pytest
from canonical_fixtures import BUNDLE, CATALOG

from caos.methodology.bundle import delivered_authority
from caos.methodology.invocation import (
    _FINAL_CHECK,
    _HOST_STEPS,
    _INSTRUCTION,
    MAX_UPSTREAM_HANDOFF_BYTES,
)
from caos.pricing import ModelPrice, price_from_environment, priced_request, worst_case
from caos.provider import encode_request
from caos.refusals import Refusal
from caos.store.budget import CEILING, CEILING_ENV, configured_ceiling

REPO = Path(__file__).resolve().parents[1]


def test_the_environment_names_the_ceiling_or_the_store_default_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CEILING_ENV, raising=False)
    assert configured_ceiling() is None
    monkeypatch.setenv(CEILING_ENV, " 25.00 ")
    assert configured_ceiling() == Decimal("25.00")
    assert configured_ceiling("") is None
    for bad in ("abc", "-1", "NaN", "Infinity"):
        with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
            configured_ceiling(bad)


def test_preflight_refuses_a_ceiling_below_one_worst_case_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    price = "databricks-claude-opus-5,0.000005,0.000025,2026-09-22"
    assert preflight.affordable(price, "25.00")
    assert "ok      run ceiling 25.00" in capsys.readouterr().out
    assert not preflight.affordable(price, None), f"{CEILING} is below one call"
    assert "set run_ceiling to at least" in capsys.readouterr().out
    assert not preflight.affordable("not,a,price", "25.00")
    # AR-06: a price for another endpoint is found here, not by the worker.
    assert preflight.affordable(price, "25.00", endpoint="databricks-claude-opus-5")
    assert not preflight.affordable(price, "25.00", endpoint="enterprise-claude")
    assert "not endpoint enterprise-claude" in capsys.readouterr().out
    assert (
        preflight.main(
            [
                "--endpoint",
                "e",
                "--catalog",
                "c",
                "--schema",
                "s",
                "--lakebase-instance",
                "i",
                "--price",
                price,
                "--run-ceiling",
                "1.00",
            ]
        )
        == 1
    )


def _bundle_default(name: str) -> str:
    """A variable's default as `databricks.yml` declares it."""
    text = (REPO / "databricks.yml").read_text(encoding="utf-8")
    block = text[text.index(f"\n  {name}:\n") :]
    found = re.search(r"\n    default: \"?([^\"\n]+)\"?\n", block)
    assert found is not None, name
    return found.group(1)


def _widest_profile_spend(price: ModelPrice) -> Decimal:
    """What the widest execution profile reserves when every node carries its
    whole delivered authority and every upstream section at its bound: the
    widest-node test's request, per node, priced. Evidence is excluded -- it is
    the headroom the one worst-case call beside this pays for."""
    spends = []
    for profile in CATALOG["profiles"].values():
        edges = profile["edges"]
        nodes = {edge["target"] for edge in edges} | {edge["source"] for edge in edges}
        total = Decimal(0)
        for node in nodes:
            upstreams = sum(1 for edge in edges if edge["target"] == node)
            files = delivered_authority(BUNDLE, node).files
            prompt = "\n".join(
                [
                    *(data.decode("utf-8", "replace") for _name, data in files),
                    *("x" * MAX_UPSTREAM_HANDOFF_BYTES for _ in range(upstreams)),
                    _HOST_STEPS,
                    _INSTRUCTION,
                    _FINAL_CHECK,
                ]
            )
            total += priced_request(price, len(encode_request("m", prompt)))
        spends.append(total)
    return max(spends)


def test_the_default_run_ceiling_finishes_the_widest_profile() -> None:
    """D29 (CF-008): the bundle's default ceiling covers the widest profile at
    its section bounds plus one worst-case call (the gate's evidence, or one
    D30 second attempt) at the bundle's default price; 25.00 could not finish
    a LITE_CREDIT_22 route. Every copy of the default is the bundle's."""
    price = price_from_environment(
        _bundle_default("model_endpoint"), _bundle_default("model_price")
    )
    default = Decimal(_bundle_default("run_ceiling"))
    assert default >= _widest_profile_spend(price) + worst_case(price), default
    deploy_sh = (REPO / "scripts" / "enterprise_deploy.sh").read_text(encoding="utf-8")
    deploy_py = (REPO / "scripts" / "enterprise_deploy.py").read_text(encoding="utf-8")
    assert f'CEILING="${{7:-{default}}}"' in deploy_sh
    assert f'"--run-ceiling", default="{default}"' in deploy_py


@pytest.mark.parametrize(
    "value",
    [
        "databricks-claude-opus-5,0,0.000025,2026-09-22",  # zero input
        "databricks-claude-opus-5,-0,0.000025,2026-09-22",  # negative zero input
        "databricks-claude-opus-5,0.000005,0,2026-09-22",  # zero output
        "databricks-claude-opus-5,0.000005,0.000025,2099-12-31",  # future date
        # Arabic-Indic and fullwidth digits, which `Decimal` reads at their value.
        f"databricks-claude-opus-5,0.00000{chr(0x665)},"
        f"0.0000{chr(0xFF12)}{chr(0xFF15)},2026-09-22",
        "databricks-claude-opus-5,5e-6,0.000025,2026-09-22",  # an exponent
        "databricks-claude-opus-5,+0.000005,0.000025,2026-09-22",  # a sign
        "databricks-claude-opus-5,0.000005,0.000025,20260922",  # not YYYY-MM-DD
    ],
)
def test_a_price_that_prices_nothing_or_is_not_in_force_is_refused(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """DF-10: a zero or negative-zero half priced every reservation and every
    charge at nothing for that half, a price dated 2099 was recorded as the
    one in force, and another script's digits were taken at their value. The
    worker's parser refuses each, and preflight, which reads the price through
    it, refuses the same values before a deploy."""
    from caos.pricing import price_from_environment

    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        price_from_environment("databricks-claude-opus-5", value)
    assert not preflight.affordable(value, "25.00")
    assert "fix model_price" in capsys.readouterr().out
    today = datetime.now(UTC).date().isoformat()
    in_force = f"databricks-claude-opus-5,0.000005,0.000025,{today}"
    assert price_from_environment("databricks-claude-opus-5", in_force).as_of == (
        datetime.now(UTC).date()
    )
