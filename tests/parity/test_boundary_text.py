"""Parity: boundary_text.

`boundary_text.BoundaryText.of`: the accept/refuse table including NFC
composition before the bound, every bidi control, Cc controls, surrogates and
the format, separator and unassigned code points it lets through.
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "boundary_text"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_boundary_text_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_boundary_text_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
