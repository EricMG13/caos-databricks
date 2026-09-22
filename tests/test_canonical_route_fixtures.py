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


def test_cp3_binary_authority_is_lossless_and_explicit() -> None:
    import base64

    from canonical_fixtures import BUNDLE

    from caos.methodology.bundle import delivered_authority
    from caos.methodology.invocation import _authority_sections, _authority_text

    authority = delivered_authority(BUNDLE, "CP-3")
    prompt = _authority_sections(authority, "test")
    binary = [(n, b) for n, b in authority.files if n.endswith(".xlsx")]
    assert len(binary) == 2
    for name, data in binary:
        encoded = _authority_text("CP-3", name, data)
        assert encoded.startswith("ENCODING: base64")
        assert base64.b64decode(encoded.split("\n", 1)[1], validate=True) == data
        assert name in prompt and encoded in prompt


@pytest.mark.parametrize(
    ("module", "name", "data"),
    [
        ("CP-3", "references/unlisted.xlsx", b"\xff\xfe"),
        ("CP-1", "references/REF_CP-3_Sector_RV.xlsx", b"\xff\xfe"),
        ("CP-3", "references/REF_CP-3_Sector_RV.xlsx", b"PK\x03\x04invalid"),
        ("CP-3", "references/broken.md", b"\xff\xfe"),
    ],
)
def test_unlisted_or_invalid_binary_authority_refuses(
    module: str, name: str, data: bytes
) -> None:
    from caos.methodology.invocation import _authority_text
    from caos.refusals import Refusal, RefusalCode

    with pytest.raises(Refusal) as refused:
        _authority_text(module, name, data)
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
