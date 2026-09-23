"""The vendor's own validators, loaded from verified bytes without touching the
interpreter's import state (Phase 3 Task 3.1, brief correction 4)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from test_bundle_pin import VENDOR, clear_vendor_bytecode

from caos.methodology import vendor as vendor_module
from caos.methodology.bundle import Bundle
from caos.methodology.vendor import (
    VendorContract,
    authority_bundle_sha256,
    load_vendor_contract,
)
from caos.refusals import Refusal, RefusalCode

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"
GENERIC = (
    "validate_handoff",
    "completeness_check",
    "cp_tables",
    "credit_os",
    "credit_os_v",
)


def _import_state() -> tuple[object, ...]:
    return (
        list(sys.path),
        list(sys.meta_path),
        dict(sys.path_importer_cache),
        sys.dont_write_bytecode,
    )


def test_vendor_loader_leaves_sys_path_untouched() -> None:
    # Another process's bytecode is not this loader's; clearing it first keeps
    # the assertion below about what `load_vendor_contract` writes.
    clear_vendor_bytecode(VENDOR)
    before = _import_state()
    with vendor_module._LOCK:
        registered_before = {
            name for name in sys.modules if name.split(".")[0] in GENERIC
        }
    contract = load_vendor_contract(Bundle(VENDORED))
    assert _import_state() == before
    assert isinstance(contract, VendorContract)
    # Standard-library imports the vendor code makes are ordinary; this load
    # leaves no vendor module behind. Compare with entry state because another
    # suite may already hold an independently loaded generic module. Hold the
    # loader lock so another thread cannot expose its deliberately transient
    # private modules between return and assertion.
    with vendor_module._LOCK:
        registered_after = {
            name for name in sys.modules if name.split(".")[0] in GENERIC
        }
        assert not any(name.startswith("_caos_vendor") for name in sys.modules)
    assert registered_after == registered_before
    assert not list(VENDORED.rglob("__pycache__"))
    # The loaded code is the vendor's: its validator rejects an empty handoff.
    assert contract.validate_handoff.validate_text("", filename="x.md").exit_code != 0


def test_authority_bundle_sha256_reads_the_vendor_declared_digest() -> None:
    digest = authority_bundle_sha256(Bundle(VENDORED))
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_authority_bundle_sha256_refuses_undeclared_or_malformed_digests(
    tmp_path: Path,
) -> None:
    import shutil

    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    anchor = (
        root / "skills/cp-os-credit-os/references/CREDIT_OS_V_AUTHORITY_BUNDLE_v2.json"
    )
    anchor.write_text("{}")
    with pytest.raises(Refusal) as refused:
        authority_bundle_sha256(Bundle(root))
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


@pytest.mark.parametrize("script", ["validate_handoff.py", "cp_tables.py"])
def test_vendor_code_that_moved_refuses(tmp_path: Path, script: str) -> None:
    import shutil

    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    target = root / "skills/cp-os-credit-os/scripts" / script
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(Refusal) as refused:
        load_vendor_contract(Bundle(root))
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_the_table_reader_is_the_one_the_completeness_checker_calls() -> None:
    """One reader of tagged tables: what the checker accepted at acceptance is
    what a section read derives its tables from."""
    contract = load_vendor_contract(Bundle(VENDORED))
    assert contract.cp_tables.parse_tables is contract.completeness_check.parse_tables
    assert contract.cp_tables.parse_figure("(1,234)") == -1234.0
