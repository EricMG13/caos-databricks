"""Parity: routes.

`graph.route.resolve_route` (legacy `engine.route`) for every `ADAPTER_ROUTES`
pair, plain and with the research and model extensions: node order, typed
edges, predicates, `route_digest`, `frontier`, `node_states` and
`predecessors`. The host pin predicate is masked (see `parity.cases`).
"""

from __future__ import annotations

import pytest

from parity.cases import GROUPS, canonical, compute, sha256_hex
from parity.goldens import caos_target, read_golden, read_manifest

GROUP = "routes"


@pytest.mark.parametrize("name", sorted(GROUPS[GROUP]))
def test_routes_case_matches_the_legacy_golden(name: str) -> None:
    recomputed = compute(caos_target(), GROUP, name)
    golden = read_golden(GROUP, name)
    assert recomputed == golden
    assert canonical(recomputed) == canonical(golden)
    digest = sha256_hex(canonical(recomputed).encode("utf-8"))
    assert digest == read_manifest(GROUP)[name]


def test_routes_manifest_names_exactly_the_registered_cases() -> None:
    assert sorted(read_manifest(GROUP)) == sorted(GROUPS[GROUP])
