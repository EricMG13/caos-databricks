"""CP-CF is host-owned, pinned and never an arbitrary code selector."""

from __future__ import annotations

from pathlib import Path

import pytest
from canonical_fixtures import BUNDLE, CATALOG

from caos.graph.route import RouteExtensions, resolve_route
from caos.methodology.bundle import assemble_authority, delivered_authority
from caos.refusals import Refusal, RefusalCode


def test_forecast_extension_has_complete_verified_host_authority() -> None:
    from host_manifest import generate_host_manifest

    from caos.methodology.host import HOST_ROOT, host_skill

    assert (
        generate_host_manifest() == (HOST_ROOT / "HOST_INTEGRITY_v1.json").read_bytes()
    )
    assert host_skill()["module_id"] == "CP-CF"
    authority = assemble_authority(BUNDLE, "CP-CF")
    assert "SKILL.md" in authority.files
    assert b"cash_flow_forecast" in authority.files["SKILL.md"]
    assert delivered_authority(BUNDLE, "CP-CF").files[0][0] == "SKILL.md"


def test_forecast_extension_pin_binds_the_host_manifest() -> None:
    from caos.methodology.host import verify_extension
    from caos.methodology.host_pin import HOST_MANIFEST_SHA256

    route = resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    assert dict(route.predicates)["host_manifest_sha256"] == HOST_MANIFEST_SHA256
    verify_extension(route)


def test_forecast_extension_refuses_changed_host_bytes(tmp_path: Path) -> None:
    import shutil

    from caos.methodology.host import HOST_ROOT, verified_host_bytes

    root = tmp_path / "host"
    shutil.copytree(HOST_ROOT, root)
    (root / "stages/cp-cf/references/SKILL.md").write_text("altered")
    with pytest.raises(Refusal) as caught:
        verified_host_bytes("SKILL.md", root=root)
    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_forecast_extension_refuses_stale_or_absent_pin() -> None:
    from dataclasses import replace

    from caos.methodology.host import verify_extension

    route = resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    for predicates in ((), (("host_manifest_sha256", "0" * 64),)):
        with pytest.raises(Refusal) as caught:
            verify_extension(replace(route, predicates=predicates))
        assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_the_bundle_pin_is_the_vendored_manifest_s_digest() -> None:
    """F66: `scripts/host_manifest.py` compiles the pin the runtime checks."""
    from host_manifest import bundle_manifest_sha256

    from caos.methodology.bundle_pin import BUNDLE_MANIFEST_SHA256

    assert bundle_manifest_sha256() == BUNDLE_MANIFEST_SHA256
    assert BUNDLE.manifest_sha256 == BUNDLE_MANIFEST_SHA256
