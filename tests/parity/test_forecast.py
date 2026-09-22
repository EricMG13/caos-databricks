"""Parity: forecast.

`methodology.forecast.forecast_projection`, `forecast_inputs`,
`validate_forecast_bindings` and `validate_driver_mapping` over
`tests/forecast_fixtures.py` and the route request of `tests/test_forecast_route.py`.
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "forecast"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_forecast_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_forecast_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
