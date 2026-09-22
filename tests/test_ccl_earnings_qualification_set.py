"""The offline CCL FULL earnings-update qualification set."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from canonical_fixtures import CONTRACT, skill

from caos.qualification.matrix import assert_measurable, assert_unambiguous
from caos.qualification.on_disk import load_qualification_set

REPO = Path(__file__).resolve().parents[1]
SET_ROOT = REPO / "qualification" / "ccl-fy2025-earnings-update"
DOCUMENT_SHA256 = "8fa7fceda34be50b3b9b5406e0c9269b5269870d1cd8c2bdafb682755a1c88e6"
ANCHORS = {
    "Total Revenues | 26,622 | 25,021 | 21,593 |",
    "Operating Income | 4,483 | 3,574 | 1,956 |",
    "Net cash provided by operating activities | 6,218 | 5,923 | 4,281 |",
    "Purchases of property and equipment | ( 3,611 ) | ( 4,626 ) | ( 3,284 ) |",
    "Total Debt, net of unamortized debt issuance costs and discounts | "
    "26,640 | 27,475 |",
}
COMPARATOR_DELTAS = {
    "revenue": ("26622", "25021", "1601"),
    "ebit": ("4483", "3574", "909"),
    "cfo_ncfo": ("6218", "5923", "295"),
    "capex_and_intangible_investment": ("-3611", "-4626", "1015"),
    "total_debt": ("26640", "27475", "-835"),
}


def test_ccl_earnings_set_is_a_complete_offline_copy_with_pinned_keys() -> None:
    inventory = {
        path.relative_to(SET_ROOT).as_posix()
        for path in SET_ROOT.rglob("*")
        if path.is_file()
    }
    assert inventory == {
        "qualification.json",
        "RESULT.md",
        "documents/CCL_FY2025_10K.txt",
    }
    document = SET_ROOT / "documents" / "CCL_FY2025_10K.txt"
    source = REPO / "qualification/ccl-fy2025/documents/CCL_FY2025_10K.txt"
    assert document.read_bytes() == source.read_bytes()
    assert sha256(document.read_bytes()).hexdigest() == DOCUMENT_SHA256

    qualification = load_qualification_set(SET_ROOT)
    assert_measurable(qualification)
    assert_unambiguous(qualification)
    [case] = qualification.cases
    assert (case.profile_id, case.selection_id) == (
        "FULL_CREDIT_32",
        "EARNINGS_UPDATE",
    )
    assert case.expects_ready == ("CP-1", "CP-1B", "CP-2", "CP-5")
    assert {
        (key.module_id, key.field, key.value) for key in case.expects_projection
    } == {("CP-5", "decision_scope", "FULL")}

    citations = {
        (key.module_id, key.document_sha256, key.matched_text) for key in case.expects
    }
    assert {module for module, _digest, _text in citations} == {
        "CP-1",
        "CP-1B",
        "CP-2",
        "CP-5",
    }
    assert {text for _module, _digest, text in citations} == ANCHORS
    assert all(digest == DOCUMENT_SHA256 for _module, digest, _text in citations)
    evidence = document.read_text(encoding="utf-8")
    assert all(evidence.count(anchor) == 1 for anchor in ANCHORS)

    comparator_cells = {
        (key.row_key, key.column, key.expected)
        for key in case.expects_register
        if key.register_id == "T4.12"
    }
    expected_comparator_cells = {
        ((("metric_id", metric),), column, expected)
        for metric, values in COMPARATOR_DELTAS.items()
        for column, expected in (
            ("values", f"{values[0]}/{values[1]}"),
            ("changes", values[2]),
        )
    }
    assert comparator_cells == expected_comparator_cells
    assert all(key.module_id == "CP-1B" for key in case.expects_register)
    assert len(case.expects_register) == len(comparator_cells)

    rules = CONTRACT.completeness_check.load_contract(skill("CP-1B").decode(), "CP-1B")
    comparator_columns = set(rules["registers"]["T4.12"]["columns"])
    assert comparator_columns == {
        "metric_id",
        "current/reference period IDs",
        "basis",
        "values",
        "changes",
        "status",
        "comparability flags",
    }
    assert all(
        key.column in comparator_columns
        and all(column in comparator_columns for column, _value in key.row_key)
        for key in case.expects_register
        if key.register_id == "T4.12"
    )
    assert all(key.register_id == "T4.12" for key in case.expects_register)

    cp1_reference = (
        REPO
        / "vendor/deploy-v/skills/cp-1-canonical-data-foundation/references"
        / "REF_CP-1_STEPS.md"
    ).read_text(encoding="utf-8")
    assert all(f"`{metric}`" in cp1_reference for metric in COMPARATOR_DELTAS)
    assert "outflows negative" in cp1_reference


def test_ccl_earnings_copy_is_registered_as_offline_evidence_only() -> None:
    register = json.loads(
        (REPO / "qualification/documents.json").read_text(encoding="utf-8")
    )
    [row] = [
        item
        for item in register["documents"]
        if item["id"] == "ccl-fy2025-10k-earnings-update"
    ]
    assert row["modules"] == ["CP-0", "CP-1", "CP-1B", "CP-2", "CP-5"]
    assert row["pathways"] == ["EARNINGS_UPDATE"]
    assert row["status"] == "in_hand"
    assert row["local_path"] == (
        "qualification/ccl-fy2025-earnings-update/documents/CCL_FY2025_10K.txt"
    )
    assert "no provider run or qualification" in row["note"]
