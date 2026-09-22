"""Parity: budget.

`store.budget.validate_spend` over `tests/test_budget.py`'s amounts, and the
default `CEILING`. `remaining`, `ceiling_of` and `reserved_for` read the store
and are covered by the store suite, not here.
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "budget"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_budget_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_budget_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
