"""The deployment fork of the vendored bundle (D31): the contract as the host
loads it no longer refuses what its own method tells a model to write.

Each case is a conflict the three prompt reviews and the live runs of 23
September 2026 found (`docs/rebuild/next.md` N55), checked on the real vendor
code the host runs (`load_vendor_contract`), never on a copy.
"""

from __future__ import annotations

from canonical_fixtures import CATALOG, CONTRACT, handoff_markdown, identity, skill

CHECK = CONTRACT.completeness_check


def _violations(module_id: str, text: str) -> list[str]:
    violations, _contract, _present = CHECK.check(
        skill(module_id).decode(), text, module_id
    )
    return [str(violation) for violation in violations]


def _about(violations: list[str], register: str) -> list[str]:
    return [
        v
        for v in violations
        if v.startswith(register + ":") or v.startswith(register + " row")
    ]


def test_a_template_column_takes_the_period_columns_a_model_writes() -> None:
    """CP-1 T4.4 is `Line Item; Period 1…N`: one column per period, which the
    checker used to demand as a literal header (G1, CP-1 refused six times)."""
    text = (
        "#### T4.4 — Income statement\n\n| Line Item | FY2025 | FY2024 |\n"
        "|---|---|---|\n| Revenue | 26,622 | 25,021 |\n"
    )
    assert _about(_violations("CP-1", text), "T4.4") == []
    blank = text.replace("| Revenue | 26,622 | 25,021 |", "| Revenue | n/a | 25,021 |")
    assert any(
        "disqualifying placeholder" in v
        for v in _about(_violations("CP-1", blank), "T4.4")
    )


def test_a_column_label_matches_up_to_case_spacing_and_dashes() -> None:
    """The method files spell columns `Claim / Tranche`, and `Score (1-5)` with
    an en dash, where the contract says `Claim/Tranche` and a hyphen."""
    key = CHECK._column_key
    assert key("Claim / Tranche") == key("Claim/Tranche")
    assert key("Score (1" + chr(0x2013) + "5)") == key("Score (1-5)")
    assert key("`Evidence ID`") == key("evidence id")
    assert key("Issuer") != key("Issuer Name")


def test_a_snake_case_register_is_found_under_its_title_heading() -> None:
    """CP-1A live wrote `#### Company description` for `company_description`
    and was refused eleven times for registers it had written (D5)."""
    registers = CHECK.find_registers(
        "#### Company description\n\n| A |\n|---|\n| x |\n", ["company_description"]
    )
    assert set(registers) == {"company_description"}
    # Prose, not a heading, never binds a register by its title.
    prose = CHECK.find_registers(
        "The company description follows.\n\n| A |\n|---|\n| x |\n",
        ["company_description"],
    )
    assert prose == {}


def test_a_register_id_ends_at_a_sentence_full_stop() -> None:
    found = CHECK.find_registers("### T1. Input gate\n\n| A |\n|---|\n| x |\n", ["T1"])
    assert set(found) == {"T1"}
    assert CHECK.find_registers("### T1.2 Other\n\n| A |\n|---|\n| x |\n", ["T1"]) == {}


def test_a_value_list_label_is_a_value_and_a_bare_placeholder_is_not() -> None:
    """The vendor's own closed lists include `Insufficient Information`,
    `Not Assessable` and `Unknown`; its canon's bare `[Insufficient
    Information]` still needs the missing item after it."""
    contract = CHECK.load_contract(skill("CP-3D").decode(), "CP-3D")
    assert "insufficient information" not in contract["blocklist"]
    assert "unknown" not in contract["blocklist"]
    assert "[insufficient information]" in contract["blocklist"]
    cell = CHECK._cell_violations
    assert cell(contract, "T3E.2", 1, "duration", "Insufficient Information") == []
    assert cell(contract, "T3E.2", 1, "duration", "[Insufficient Information]") != []
    assert (
        cell(
            contract,
            "T3E.2",
            1,
            "duration",
            "[Insufficient Information] — TRACE reports a last trade only",
        )
        == []
    )


def _cp0_with(table: str, section: str, qa_status: str) -> list[str]:
    markdown = handoff_markdown(
        identity("CP-0"),
        authored={
            "qa_status": qa_status,
            "confidence_score": 35,
            "confidence_band": "Insufficient Information",
        },
    ).decode()
    heading = f"## {section}\n\n"
    assert heading in markdown
    text = markdown.replace(heading, heading + table + "\n", 1)
    result = CONTRACT.validate_handoff.validate_text(
        text, decision_scope="SCREENING_ONLY"
    )
    return [str(error) for error in result.errors]


GAP = (
    "| ID | Gap | Severity |\n|---|---|---|\n"
    "| G-1 | Audited statements missing | CRITICAL |\n"
)


def test_an_analytical_severity_is_not_a_qa_finding() -> None:
    """A CRITICAL source gap routes its consumer; read as a QA finding it
    forced qa_status Blocked and ended the whole run (G1-1, G2-4, G3-4)."""
    assert not any(
        "CRITICAL finding" in e
        for e in _cp0_with(GAP, "Gaps & Conflicts", "Restricted")
    )
    assert any(
        "CRITICAL finding" in e for e in _cp0_with(GAP, "QA Validation", "Restricted")
    )
    resolved = (
        GAP.replace("| Severity |", "| Severity | Status |")
        .replace("|---|---|---|", "|---|---|---|---|")
        .replace("| CRITICAL |", "| CRITICAL | Resolved |")
    )
    assert not any(
        "CRITICAL finding" in e
        for e in _cp0_with(resolved, "QA Validation", "Restricted")
    )


def test_t8_accepts_a_readiness_written_in_backticks() -> None:
    """The vendor's own T8 example cells are backticked (D6 was refused for it)."""
    markdown = handoff_markdown(
        identity("CP-0"), readiness={"CP-L10": "READY", "CP-5": "READY"}
    ).decode()
    ticked = markdown.replace("| READY |", "| `READY` |")
    assert ticked != markdown
    nav = CONTRACT.navigation
    rows = nav.parse_t8(ticked, nav.validate_catalog(CATALOG))
    assert {row.readiness for row in rows} == {"READY"}
