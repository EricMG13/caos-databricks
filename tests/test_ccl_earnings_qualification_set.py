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
    # F653 (N54, R29): keyed to the gate's verdict. CP-0 is expected to hold
    # CP-1, CP-1B and CP-2, so no module behind them runs and no citation,
    # projection or register key can be met; a run cannot be scored on one.
    assert case.expects_blocked == ("CP-1", "CP-1B", "CP-2")
    assert case.expects_ready == ()
    assert case.expects == ()
    assert case.expects_projection == ()
    assert case.expects_register == ()

    # The document still carries each figure the earlier key anchored, once,
    # so the set can be re-keyed to the answers when CP-0 clears the modules.
    evidence = document.read_text(encoding="utf-8")
    assert all(evidence.count(anchor) == 1 for anchor in ANCHORS)

    rules = CONTRACT.completeness_check.load_contract(skill("CP-1B").decode(), "CP-1B")
    comparator_columns = set(rules["registers"]["T4.12"]["columns"])
    # Fork r3 (G2-6): T4.12 follows the method's keyed comparator columns and
    # keeps the `values` and `changes` this key reads.
    assert comparator_columns == {
        "metric_id",
        "current_period_id",
        "reference_period_id",
        "comparison_basis",
        "current_value",
        "reference_value",
        "absolute_change",
        "percentage_change",
        "calculation_status",
        "restatement_flag",
        "basis_change_flag",
        "perimeter_change_flag",
        "definition_change_flag",
        "values",
        "changes",
    }
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
