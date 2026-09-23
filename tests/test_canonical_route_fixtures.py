"""The independent issuer fixture meets every vendor register contract."""

from __future__ import annotations

import pytest
from canonical_fixtures import CONTRACT, skill
from canonical_route_fixtures import (
    MODULES,
    PACK,
    QUOTES,
    canonical_markdown,
    driver_schema,
    forecast_driver_rows,
    route_identity,
)


@pytest.mark.parametrize("module", MODULES)
def test_canonical_fixture_has_complete_vendor_registers(module: str) -> None:
    markdown = canonical_markdown(route_identity(module)).decode()
    assert CONTRACT.validate_handoff.validate_text(markdown).exit_code == 0
    violations = CONTRACT.completeness_check.check(
        skill(module).decode(), markdown, module
    )[0]
    assert violations == []
    assert QUOTES[module] in markdown and QUOTES[module].encode() in PACK


def test_cp2g_forecast_driver_columns_match_the_vendor_contract() -> None:
    schema = driver_schema()
    assert schema["required"] == [
        "driver_id",
        "slot_id",
        "case",
        "period_id",
        "fiscal_year",
        "value",
        "unit",
        "assumption_id",
        "status",
        "source_id",
        "source_locator",
        "as_of",
    ]
    rows = forecast_driver_rows()
    assert len(rows) == len({tuple(r[:4]) for r in rows}) == 42
    assert all(len(r) == len(schema["required"]) for r in rows)
    assert {r[0] for r in rows} == set(schema["properties"]["driver_id"]["enum"])
    assert {r[2] for r in rows} == {"BASE", "DOWNSIDE"}
    assert {r[3] for r in rows} == {"FY2026", "FY2027", "FY2028"}
    assert {r[8] for r in rows} == {"READY"}


def test_cp3_sample_workbooks_are_withheld_and_named() -> None:
    from canonical_fixtures import BUNDLE

    from caos.methodology.bundle import WITHHELD_AUTHORITY, delivered_authority
    from caos.methodology.invocation import _authority_sections

    authority = delivered_authority(BUNDLE, "CP-3")
    prompt = _authority_sections(authority, "test")
    assert not [n for n, _ in authority.files if n.endswith(".xlsx")]
    assert set(authority.withheld) == WITHHELD_AUTHORITY["CP-3"]
    assert "--- AUTHORITY test WITHHELD (host-owned note) ---" in prompt
    assert all(f"`{name}`" in prompt for name in authority.withheld)
    assert "base64" not in prompt


def test_module_without_withheld_files_gets_no_note() -> None:
    from canonical_fixtures import BUNDLE

    from caos.methodology.bundle import delivered_authority
    from caos.methodology.invocation import _authority_sections

    authority = delivered_authority(BUNDLE, "CP-1")
    assert authority.withheld == ()
    assert "WITHHELD" not in _authority_sections(authority, "test")


@pytest.mark.parametrize(
    "name", ["references/REF_CP-3_Sector_RV.xlsx", "references/broken.md"]
)
def test_binary_authority_refuses(name: str) -> None:
    from caos.methodology.bundle import DeliveredAuthority
    from caos.methodology.invocation import _authority_sections
    from caos.refusals import Refusal, RefusalCode

    authority = DeliveredAuthority("CP-3", "b" * 64, ((name, b"PK\x03\x04\xff\xfe"),))
    with pytest.raises(Refusal) as refused:
        _authority_sections(authority, "test")
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
