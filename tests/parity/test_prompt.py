"""Parity: prompt.

`methodology.invocation.build_handoff_prompt`: the rendered prompt for one
assignment per adapter module the fixtures build without a store. CP-CF is
not covered: its delivered authority carries `scripts/cash_flow.py`, whose
bytes differ between the packages by the import rename alone.
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "prompt"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_prompt_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_prompt_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
