"""Parity: cash_flow.

`calculators.cash_flow.cash_flow_forecast` and `forecast_bytes` over every
request `tests/test_cash_flow_forecast.py` and `tests/forecast_fixtures.py` build.
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "cash_flow"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_cash_flow_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_cash_flow_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
