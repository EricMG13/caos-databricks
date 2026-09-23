"""The generator reproduces the committed manifests from `caos`, and the
package-agnostic helpers it rests on pin values the way the goldens assume."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest

from caos.methodology.handoff import ADAPTER_MODULES
from caos.methodology.handoff import ADAPTER_ROUTES as LIVE_ROUTES
from caos.refusals import Refusal, RefusalCode
from parity import generate_goldens
from parity.cases import (
    ADAPTER_ROUTES,
    DOCUMENTS,
    GROUP_NAMES,
    GROUPS,
    UNCOVERED_PROMPT_MODULES,
    Target,
    attr,
    call,
    canonical,
    jsonable,
    refusal_or,
    sha256_hex,
)
from parity.goldens import (
    GOLDEN_DIR,
    MANIFEST,
    caos_target,
    golden_path,
    manifest_path,
    read_golden,
    read_manifest,
    write_group,
)

REPO = Path(__file__).resolve().parents[2]


class _Colour(Enum):
    RED = "red"


@dataclass(frozen=True)
class _Row:
    amount: Decimal
    colour: _Colour


def test_generate_reproduces_the_committed_manifests(tmp_path: Path) -> None:
    groups = ("digest", "budget", "boundary_text")
    manifests = generate_goldens.generate(caos_target(), tmp_path, groups)
    assert tuple(manifests) == groups
    for group, cases in manifests.items():
        assert cases == read_manifest(group)
        assert read_manifest(group, tmp_path, package="caos") == cases
        assert manifest_path(group, tmp_path).name == MANIFEST


def test_main_writes_one_group_to_the_named_directory(tmp_path: Path) -> None:
    argv = ["--package", "caos", "--root", str(REPO), "--out", str(tmp_path)]
    assert generate_goldens.main([*argv, "--group", "digest"]) == 0
    assert read_golden("digest", "key_order", tmp_path) == read_golden(
        "digest", "key_order"
    )


def test_parse_args_defaults_to_every_group_and_the_golden_directory() -> None:
    args = generate_goldens.parse_args(["--package", "caos", "--root", "."])
    assert args.out == GOLDEN_DIR
    assert args.group is None


def test_load_target_refuses_a_package_outside_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(ValueError, match="imported from"):
        generate_goldens.load_target("caos", tmp_path)
    assert generate_goldens.load_target("caos", REPO).root == REPO


def test_target_maps_the_legacy_engine_package_onto_graph() -> None:
    target = caos_target()
    assert isinstance(target, Target)
    assert target.name == "caos"
    assert target.root == REPO
    assert target.module("engine.route").__name__ == "caos.graph.route"
    assert target.module("digest").__name__ == "caos.digest"
    assert target.fixture("forecast_fixtures").__name__ == "forecast_fixtures"
    assert attr(target.module("boundary_text"), "DEFAULT_LIMIT") == 4096
    assert call(target.module("digest"), "canonical_json", {"b": 1, "a": 2}) == (
        '{"a":2,"b":1}'
    )


def test_jsonable_pins_every_non_json_value_the_same_way() -> None:
    value = {
        "decimal": Decimal("1.10"),
        "bytes": b"ab",
        "set": frozenset({2, 1}),
        "uuid": UUID(int=1),
        "tuple": (1, "two"),
        "enum": _Colour.RED,
        "row": _Row(Decimal("-0.00"), _Colour.RED),
        3: None,
    }
    assert jsonable(value) == {
        "decimal": "1.10",
        "bytes": {"sha256": sha256_hex(b"ab"), "length": 2},
        "set": [1, 2],
        "uuid": "00000000-0000-0000-0000-000000000001",
        "tuple": [1, "two"],
        "enum": "red",
        "row": {"amount": "-0.00", "colour": "red"},
        "3": None,
    }
    with pytest.raises(TypeError, match="no JSON form"):
        jsonable(object())


def test_canonical_is_sorted_compact_and_keeps_non_ascii() -> None:
    assert canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
    with pytest.raises(ValueError, match="Out of range"):
        canonical(float("inf"))


def test_refusal_or_records_the_code_and_never_the_message() -> None:
    target = caos_target()

    def refuse() -> None:
        raise Refusal(RefusalCode.MONEY_INVALID)

    assert refusal_or(target, refuse) == {"refusal": "MONEY_INVALID"}
    assert refusal_or(target, lambda: Decimal(1)) == "1"


def test_write_group_round_trips_through_the_readers(tmp_path: Path) -> None:
    digests = write_group("demo", {"one": {"a": 1}}, package="caos", base=tmp_path)
    assert digests == {"one": sha256_hex(b'{"a":1}')}
    assert read_manifest("demo", tmp_path, package="caos") == digests
    with pytest.raises(TypeError, match="written from 'caos'"):
        read_manifest("demo", tmp_path)  # F57: not the legacy snapshot
    assert read_golden("demo", "one", tmp_path) == {"a": 1}
    assert golden_path("demo", "one", tmp_path).read_text() == '{"a":1}\n'


def test_the_static_route_table_is_the_package_s_adapter_routes() -> None:
    assert set(ADAPTER_ROUTES) == LIVE_ROUTES
    assert len(ADAPTER_ROUTES) == len(LIVE_ROUTES) == 18


def test_every_adapter_module_has_a_prompt_case_or_is_named_uncovered() -> None:
    covered = {name.split("__")[1] for name in GROUPS["prompt"]}
    assert not covered & set(UNCOVERED_PROMPT_MODULES)
    assert covered | set(UNCOVERED_PROMPT_MODULES) == ADAPTER_MODULES


def test_every_group_has_a_committed_manifest_with_at_least_one_case() -> None:
    assert len(GROUP_NAMES) == 11
    for group in GROUP_NAMES:
        assert read_manifest(group), group


def test_the_extraction_documents_are_public_plain_text() -> None:
    for qualification_set, filename in DOCUMENTS:
        path = REPO / "qualification" / qualification_set / "documents" / filename
        assert path.suffix == ".txt"
        assert path.stat().st_size < 60_000
