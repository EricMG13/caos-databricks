"""The deployment's run ceiling (F28): named by the environment, priced policy."""

from __future__ import annotations

from decimal import Decimal

import preflight
import pytest

from caos.refusals import Refusal
from caos.store.budget import CEILING, CEILING_ENV, configured_ceiling


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
