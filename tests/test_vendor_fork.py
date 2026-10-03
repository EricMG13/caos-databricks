"""The deployment fork of the vendored bundle (D31): the contract as the host
loads it no longer refuses what its own method tells a model to write.

Each case is a conflict the three prompt reviews and the live runs of 23
September 2026 found (`docs/rebuild/next.md` N55), checked on the real vendor
code the host runs (`load_vendor_contract`), never on a copy. Fork r3's cases
follow the prompt review's ledger rows (`docs/rebuild/prompt-review-2026-09-23.md`).
"""

from __future__ import annotations

import re
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from canonical_fixtures import (
    BUNDLE,
    CATALOG,
    CONTRACT,
    RUN,
    _table,
    handoff_markdown,
    identity,
    research_brief,
    skill,
)

from caos.methodology.bundle import verified_bytes, verified_root_bytes
from caos.methodology.tables import figure_value

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


def test_a_heading_binds_its_table_before_a_prose_mention() -> None:
    """Fork r2: a takeaway line naming another register ("reconciles to the
    T4.4 revenue base") under `### T4.5` no longer captures the table (G2-7)."""
    text = (
        "### T4.5 — Cash flow statement\n"
        "This reconciles to the T4.4 revenue base.\n\n"
        "| Line Item | FY2025 |\n|---|---|\n| CFO | 6,218 |\n"
    )
    assert set(CHECK.find_registers(text, ["T4.4", "T4.5"])) == {"T4.5"}


def test_a_contract_column_inside_one_longer_header_cell_is_found() -> None:
    """Fork r2: the method files spell `Source File Name` where the contract
    says `File Name`; two candidate cells are ambiguous and match nothing."""
    resolve = CHECK._resolve_columns
    assert resolve(["File Name"], ["Source File Name", "Tier"]) == {
        "File Name": ["Source File Name"]
    }
    assert resolve(["File Name"], ["Source File Name", "Target File Name"]) == {
        "File Name": []
    }


def test_a_value_in_backticks_is_the_same_value() -> None:
    """Fork r2: CP-L10's topic IDs are shown in backticks in its own examples."""
    rule = {
        "register_id": "TL10.2",
        "rule_id": "r",
        "rule": "required_values",
        "column": "topic_id",
        "values": ["SOURCE_BASIS"],
    }
    present = {"TL10.2": (["topic_id"], [{"topic_id": "`SOURCE_BASIS`"}])}
    assert CHECK._semantic_violations([rule], present) == []


def test_cp2e_ratchet_is_one_column() -> None:
    """Fork r2: `Ratchet (direction; bps)` split on its `;` into two columns
    every answer failed; the contract now names one (G3-5)."""
    contract = CHECK.load_contract(skill("CP-2E").decode(), "CP-2E")
    assert "Ratchet (direction, bps)" in contract["registers"]["T2G.5"]["columns"]


def test_a_blocked_answer_is_honoured_before_the_completeness_check() -> None:
    """D34: the vendor's Blocked answer is a blocked statement, not a full run;
    it refused `HANDOFF_INCOMPLETE` for registers it was never meant to hold."""
    from caos.methodology.handoff import validate_markdown
    from caos.refusals import Refusal, RefusalCode

    markdown = handoff_markdown(
        identity("CP-0"),
        authored={
            "qa_status": "Blocked",
            "confidence_score": 30,
            "confidence_band": "Insufficient Information",
        },
        omit_register="T5",
    )
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-0"),
            markdown,
            identity=identity("CP-0"),
            gate_expects=frozenset({"CP-L10", "CP-5"}),
        )
    assert refused.value.code is RefusalCode.HANDOFF_BLOCKED


# --- Fork r3: the prompt review's remaining vendor rows -----------------------

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"


def _register(register: str, columns: list[str], rows: list[list[str]]) -> str:
    return f"#### {register}\n\n" + _table(columns, rows)


def _authority(module_id: str, name: str) -> str:
    return verified_bytes(BUNDLE, module_id, name).decode()


def _canon() -> str:
    return verified_root_bytes(BUNDLE, "CANON_SHARED.md").decode()


def _dossier(claim_type: str, source_type: str) -> tuple[SimpleNamespace, Any]:
    """A two-question CP-DR dossier: one ANSWERED on primary evidence, one
    UNRESOLVED citing the E-2 row, whose kind is the caller's."""
    research = CONTRACT.research
    brief = {**research_brief("ACME", "Acme Holdings plc"), "run_id": RUN}
    first, second = (q["question_id"] for q in brief["questions"])
    evidence = [
        [
            "E-1",
            first,
            "Undrawn committed facilities of 400 USD million at year end",
            "fact",
            "results-release.txt",
            "p1",
            "2026-02-12",
            "primary",
            "Issuer disclosure",
            "Acme Holdings plc; FY2025; USD million; consolidated",
        ],
        [
            "E-2",
            second,
            "No supplied document names an agency rating or outlook",
            claim_type,
            "results-release.txt; facility.txt",
            "whole documents searched",
            "—",
            source_type,
            "—",
            "—",
        ],
    ]
    findings = [
        [
            first,
            "Acme reported 400 USD million of undrawn committed facilities",
            "E-1",
            "Both documents searched for a later figure; none found",
            "ANSWERED",
            "The figure is the issuer's own",
            "The headroom assumption may rest on it",
        ],
        [
            second,
            "The supplied documents state no agency rating",
            "E-2",
            "Both documents searched for an agency name or symbol; none found",
            "UNRESOLVED",
            "Cannot be settled from the supplied evidence",
            "Rating-dependent assumptions stay open",
        ],
    ]
    text = "".join(
        f"<!-- table-id: {tag} -->\n" + _table(list(columns), rows)
        for tag, columns, rows in (
            (
                "cpdr.questions",
                research.QUESTION_COLUMNS,
                [[q[c] for c in research.QUESTION_COLUMNS] for q in brief["questions"]],
            ),
            ("cpdr.evidence", research.EVIDENCE_COLUMNS, evidence),
            ("cpdr.findings", research.FINDING_COLUMNS, findings),
        )
    )
    fields = {
        "approved_plan_hash": "sha256:" + CONTRACT.envelope.digest(brief),
        **{k: brief[k] for k in ("scope_type", "scope_key", "subject_name")},
        "source_mode": brief["source_mode"],
        "research_mode": brief["mode"],
        "run_id": RUN,
        "coverage_score": 50,
        "research_status": "Complete with Gaps",
    }
    return SimpleNamespace(fields=fields, text=text), brief


def test_a_research_gap_row_takes_the_canon_null_and_is_cited() -> None:
    """G1-4: a gap row's date, family and perimeter are the canon's `—`, its
    claim_type is `gap`, and the UNRESOLVED finding cites it; the validator
    refused every `—` and had no gap claim type, so a model that recorded a
    gap without inventing a source was refused."""
    CONTRACT.research.validate_dossier(*_dossier("gap", "gap"))
    for claim_type, source_type in (("fact", "primary"), ("gap", "primary")):
        with pytest.raises(ValueError):
            CONTRACT.research.validate_dossier(*_dossier(claim_type, source_type))
    brief = verified_bytes(
        BUNDLE, "CP-OS", "references/CP_DR_RESEARCH_BRIEF_V1.md"
    ).decode()
    steps = _authority("CP-DR", "references/REF_CP-DR_STEPS.md")
    assert "An UNRESOLVED finding cites its own question's gap row" in brief
    assert "Missing evidence alone is never `Blocked`." in steps


def test_cp0_tables_cp_dr_on_the_routes_that_carry_it() -> None:
    """G1-6: the host requires CP-DR in T8 on a deep-research route; CP-0's
    references said never to recommend it."""
    assert "CP-L10, CP-DR. Never recommend CP-X, CP-PARSE, a retired alias, " in (
        _authority("CP-0", "references/REF_CP-0_STEPS.md")
    )
    schema = _authority("CP-0", "references/CP-0_SCHEMA_REFERENCE.md")
    assert "CP-MEMO and CP-DR are never recommendation rows" not in schema
    assert "`DEEP_RESEARCH`, `LITE_DEEP_RESEARCH`" in skill("CP-0").decode()
    markdown = handoff_markdown(identity("CP-0")).decode()
    row = "| 1 | CP-5 | Run CP-5 | Run CP-5 |"
    assert row in markdown
    research = markdown.replace(row, "| 1 | CP-DR | Run CP-DR | Run CP-DR |")
    nav = CONTRACT.navigation
    parsed = nav.parse_t8(research, nav.validate_catalog(CATALOG))
    assert "CP-DR" in {r.module_id for r in parsed}


def test_cp5_is_cp6s_qa_gate_in_both_modules_texts() -> None:
    """G1-14: CP-6 named CP-5 its downstream and CP-5 named CP-6 its upstream,
    where the catalog runs CP-5 first and gates CP-6 on it."""
    cp6 = skill("CP-6").decode()
    assert "**Downstream (QA):** CP-5" not in cp6
    assert cp6.count("**Upstream (QA gate):** CP-5, CP-5A") == 2
    runbook = _authority("CP-5", "references/CP-5_RUNBOOK.md")
    assert "CP-6, CP-6A)" not in runbook
    assert "DOWN (QA gate): CP-6, CP-6A" in runbook
    edges = {
        (e["source"], e["target"], e["type"])
        for e in CATALOG["profiles"]["FULL_CREDIT_32"]["edges"]
    }
    assert ("CP-5", "CP-6", "QA_GATE") in edges


def test_cp0_and_cp_l10_smaller_confusions() -> None:
    """G1-18: CP-0 assesses against the pathway's use case when no objective
    is delivered; CP-L10 has one opening heading, a gap register that may be
    empty as its payload's may, and asks for research only where the brief is
    delivered."""
    assert "the selected pathway's use case" in skill("CP-0").decode()
    lite = skill("CP-L10").decode()
    assert lite.count("- **opening_h3**: ###") == 1
    assert lite.count("Open `## Analysis` with `###") == 1
    assert "is delivered with this module, use it" in lite
    contract = CHECK.load_contract(lite, "CP-L10")
    columns = contract["registers"]["TL10.4"]["columns"]
    violations, _, _ = CHECK.check(lite, _register("TL10.4", columns, []), "CP-L10")
    assert _about([str(v) for v in violations], "TL10.4") == []


def test_the_checker_follows_the_method_columns_and_keeps_what_is_read() -> None:
    """G2-6: CP-1, CP-1B and CP-1C registers written as their step specs say
    now pass; the columns a host qualification key reads (CP-1B T4.12
    `values`/`changes`, CP-1C T4.5 `Total/Net/Sr Sec Leverage`) are kept, so
    every committed key stays locatable."""
    from caos.methodology.bundle import Bundle
    from caos.qualification.matrix import unlocatable_register_keys
    from caos.qualification.on_disk import load_qualification_set

    t414 = (
        "period_id | fiscal_year | fiscal_quarter | period_type | start_date | "
        "end_date | day_count | audit_status | currency | unit | accounting_basis"
        " | entity_perimeter | source_id | source_locator | component_period_ids"
    ).split(" | ")
    t412 = (
        "metric_id | current_period_id | reference_period_id | comparison_basis | "
        "current_value | reference_value | absolute_change | percentage_change | "
        "calculation_status | restatement_flag | basis_change_flag | "
        "perimeter_change_flag | definition_change_flag | values | changes"
    ).split(" | ")
    t45 = [
        "Entity",
        "Total/Net/Sr Sec Leverage",
        "Int Coverage",
        "Adj Int Coverage",
        "FFO/Debt",
        "Liquidity",
        "Period",
        "Currency",
        "Calc Status",
        "Comp Status",
    ]
    for module, register, columns in (
        ("CP-1", "T4.14", t414),
        ("CP-1B", "T4.12", t412),
        ("CP-1C", "T4.5", t45),
    ):
        text = _register(register, columns, [["x"] * len(columns)])
        assert _about(_violations(module, text), register) == [], module
    bundle = Bundle(VENDORED)
    root = Path(__file__).resolve().parents[1] / "qualification"
    for name in ("ccl-fy2025-earnings-update", "ccl-fy2025-relative-value"):
        assert (
            unlocatable_register_keys(bundle, load_qualification_set(root / name)) == ()
        )


def test_cp1d_carries_an_upstream_bridge_that_is_empty_by_permission() -> None:
    """G2-10: CP-1 may emit an empty add-back bridge; CP-1D's T1D.1-T1D.4 then
    hold one `NONE` row each, with `—` cells, instead of an invented add-back."""
    contract = CHECK.load_contract(skill("CP-1D").decode(), "CP-1D")
    text = "".join(
        _register(
            register,
            contract["registers"][register]["columns"],
            [
                [
                    "NONE" if c in {"Add-Back ID", "Step"} else "—"
                    for c in contract["registers"][register]["columns"]
                ]
            ],
        )
        for register in ("T1D.1", "T1D.2", "T1D.3", "T1D.4")
    )
    violations = _violations("CP-1D", text)
    for register in ("T1D.1", "T1D.2", "T1D.3", "T1D.4"):
        assert _about(violations, register) == [], register
    assert "An empty CP-1 bridge is a permitted upstream" in skill("CP-1D").decode()


def test_cp2d_months_to_empty_is_a_register_the_method_names() -> None:
    """G2-14: T2E.6 was prose in the method and a column-less register in
    the checker; both now name the same six columns."""
    columns = CHECK.load_contract(skill("CP-2D").decode(), "CP-2D")["registers"][
        "T2E.6"
    ]["columns"]
    assert columns == [
        "Calculation",
        "Result",
        "Formula / Inputs",
        "Cash-Burn Basis",
        "Status",
        "Source Trace",
    ]
    steps = _authority("CP-2D", "references/REF_CP-2D_STEPS.md")
    assert "T2E.6: `Calculation`|`Result`|`Formula / Inputs`" in steps
    row = [
        "Months to Empty",
        "Not Calculable",
        "250 / -4.0",
        "FY2025; cash-generative, no runway to exhaust",
        "Calculated",
        "T2E.5",
    ]
    text = _register("T2E.6", columns, [row])
    assert _about(_violations("CP-2D", text), "T2E.6") == []


def test_cp2_states_a_missing_direction_in_one_row() -> None:
    """G2-15: T2.10 must hold a Positive and a Negative row; a direction with
    no supported driver is one `None supported` row, never an invented one."""
    columns = [
        "Rank",
        "Driver",
        "Evidence",
        "Risk Mechanic",
        "Credit Implication",
        "Direction",
        "Confidence",
    ]
    rows = [
        [
            "1",
            "Maturity wall",
            "10-K note 9",
            "Refinancing",
            "Higher PD",
            "Negative",
            "High",
        ],
        [
            "2",
            "None supported",
            "Filings reviewed",
            "—",
            "—",
            "Positive",
            "Not Assessable",
        ],
    ]
    assert _about(_violations("CP-2", _register("T2.10", columns, rows)), "T2.10") == []
    assert "`Driver` `None supported`" in _authority(
        "CP-2", "references/REF_CP-2_STEPS.md"
    )


def test_absorbed_phases_read_as_one_contract() -> None:
    """G2-18: one opening heading per artifact, CP-1A's snapshot table listed
    once as unconditional, CP-2B's rules enforced in CP-2A's own profile, the
    canon's `Not Reviewed` never a handoff's status, and CP-1's segment
    allocation held to one condition."""
    for module in ("CP-1A", "CP-2A", "CP-1D"):
        assert skill(module).decode().count("- **opening_h3**: ###") == 1, module
    assert "**conditional_register_ids**: cp1a.cp_model_snapshot_fields" not in (
        skill("CP-1A").decode()
    )
    contract = CHECK.load_contract(skill("CP-2A").decode(), "CP-2A")
    assert "cp2b.cp_model_catalysts" in contract["unconditional_stable_tables"]
    assert {r["rule_id"] for r in contract["semantic_rules"]} >= {
        "cp2b.event_ids_unique",
        "cp2b.risk_probability_enum",
        "cp2b.monitoring_has_actionable_row",
    }
    assert "never Not Reviewed" in _canon()
    assert "qa_status is not a canonical enum value" in " ".join(
        str(e)
        for e in CONTRACT.validate_handoff.validate_text(
            handoff_markdown(
                identity("CP-0"), authored={"qa_status": "Not Reviewed"}
            ).decode()
        ).errors
    )
    steps = _authority("CP-1", "references/REF_CP-1_STEPS.md")
    assert "emit this allocation only when CP-2G is supplied" not in steps


def test_lite_routes_define_upgrade_where_it_is_used() -> None:
    """G3-8: CP-2H and CP-4C named FULL dependencies on LITE routes and an
    undefined `UPGRADE`; every block using it now defines it, and the host
    still reads each block's accepted objects."""
    from caos.methodology.invocation import lite_object_requirement

    assert "SEC5 UPGRADE" in _canon()
    for module in ("CP-1C", "CP-2A", "CP-2H", "CP-3C", "CP-4C", "CP-6"):
        assert "- **UPGRADE** (canon SEC5)" in skill(module).decode(), module
    for module, accepted in (
        (
            "CP-2H",
            frozenset(
                {"lite_fundamental_credit_screen", "lite_liquidity_sensitivity_screen"}
            ),
        ),
        ("CP-4C", frozenset({"lite_legal_structure_capacity_screen"})),
    ):
        text = skill(module).decode()
        assert "In LITE_CREDIT_22 require CP-0" in text, module
        read = lite_object_requirement(skill(module), module, "LITE_CREDIT_22")
        assert read == accepted, module
    assert "returns `Not Applicable` (Phase 1), which is a complete answer" in (
        skill("CP-4C").decode()
    )


def test_module_status_maps_to_qa_status_in_the_canon() -> None:
    """G3-12: a gaps status came back Passed without a MATERIAL finding; the
    canon now maps run-status words to `qa_status`, and each canon core says so."""
    assert "D1 FROM MODULE STATUS" in _canon()
    for module in ("CP-2H", "CP-3D", "CP-4C", "CP-DR"):
        assert "`qa_status` follows the run's own status (canon D1 map)" in (
            skill(module).decode()
        ), module


def test_cp2g_case_values_match_as_the_method_writes_them() -> None:
    """G3-13: `Base case` failed the rule that required a whole cell `base`."""
    columns = CHECK.load_contract(skill("CP-2G").decode(), "CP-2G")["registers"][
        "T2H.3"
    ]["columns"]
    rows = [
        [
            "A-1",
            "Revenue",
            "Base case",
            "FY2026",
            "2%",
            "pct",
            "calculated",
            "p4",
            "Guided",
        ],
        [
            "A-2",
            "Revenue",
            "Downside case",
            "FY2026",
            "-5%",
            "pct",
            "calculated",
            "p4",
            "Stress",
        ],
    ]
    assert (
        _about(_violations("CP-2G", _register("T2H.3", columns, rows)), "T2H.3") == []
    )
    rows[0][2] = "Baseline"
    assert _about(_violations("CP-2G", _register("T2H.3", columns, rows)), "T2H.3") == [
        "T2H.3: cp2g.requires_base_and_downside_cases -- column 'case' lacks 'base'"
    ]


def test_cp2h_cites_triggers_verbatim_and_may_paraphrase_them() -> None:
    """G3-14: the method told a model to paraphrase triggers while the host
    cites whole evidence lines verbatim."""
    text = skill("CP-2H").decode()
    assert "otherwise paraphrase with locator" not in text
    assert "quoting, verbatim, the complete evidence line" in text
    steps = _authority("CP-2H", "references/REF_CP-2H_STEPS.md")
    assert "A citation is different: it quotes, verbatim," in steps


def test_transcribed_script_outputs_carry_no_refused_placeholder() -> None:
    """G3-15: covenant_headroom wrote a bare `[Insufficient Information]` and
    recovery_waterfall `unknown` into cells the method says to transcribe."""
    scripts = VENDORED / "skills"
    covenant = runpy.run_path(
        str(scripts / "cp-4-legal-covenant-interpreter/scripts/covenant_headroom.py")
    )
    recovery = runpy.run_path(
        str(
            scripts
            / "cp-3-relative-value-security-selection/scripts/recovery_waterfall.py"
        )
    )
    row = covenant["headroom"](
        {"test": "L", "test_type": "max-ratio", "threshold": None, "current_ratio": 4}
    )
    assert (row["status"], row["headroom_display"]) == (
        "Not Calculable",
        "[Insufficient Information] — missing: threshold",
    )
    waterfall = recovery["waterfall"](100, [{"claim_id": "S", "amount": None}])
    assert waterfall["allocation_state"] == "Not Calculable"
    contract = CHECK.load_contract(skill("CP-4").decode(), "CP-4")
    for value in (
        row["status"],
        row["headroom_display"],
        waterfall["allocation_state"],
    ):
        assert value.casefold() not in contract["blocklist"], value


def test_cp2e_has_one_opening_heading() -> None:
    """G3-17: CP-2E opened with `Macro and hedging view` and its absorbed
    CP-2F phase with `Credit implication`."""
    text = skill("CP-2E").decode()
    assert text.count("- **opening_h3**: ###") == 1
    assert text.count("open `## Analysis` with `###") == 1


def test_figures_read_every_digit_group_space_and_refuse_underflow() -> None:
    """N57: the thin space was the one digit-group space `parse_figure` kept,
    and `1e-400` underflowed to 0.0; the host's restatement agrees. The two
    percent readings stay as their callers take them, documented at both."""
    parse = CONTRACT.cp_tables.parse_figure
    for spaced in ("1\u2009234", "1\u202f234", "1\u00a0234"):
        assert parse(spaced) == 1234.0
        assert figure_value(CONTRACT, spaced) == "1234"
    with pytest.raises(ValueError):
        parse("1e-400")
    assert parse("10.4%") == 10.4
    assert figure_value(CONTRACT, "10.4%") == "10.4"
    assert "stays in\n    percentage points" in (
        verified_bytes(BUNDLE, "CP-OS", "scripts/cp_tables.py").decode()
    )


# --- Fork r4: what fork r3 left outside its rows (N70) -------------------------

_T210 = [
    "Rank",
    "Driver",
    "Evidence",
    "Risk Mechanic",
    "Credit Implication",
    "Direction",
    "Confidence",
]


def test_a_driver_that_cuts_both_ways_is_split_never_mixed() -> None:
    """N70: the canon deprecates `Mixed` (split), and CP-2's method and
    checker allowed it as a T2.10 direction beside a directional credit
    implication. Both now split it into a Positive and a Negative row."""
    split = [
        [
            "1",
            "Asset sale",
            "p2",
            "Paydown",
            "Positive — Deleveraging",
            "Positive",
            "High",
        ],
        [
            "2",
            "Asset sale",
            "p2",
            "Lost EBITDA",
            "Negative — Revenue Decline",
            "Negative",
            "High",
        ],
    ]
    assert _about(_violations("CP-2", _register("T2.10", _T210, split)), "T2.10") == []
    mixed = [
        *split,
        ["3", "Asset sale", "p2", "Both", "Neutral — Stable", "Mixed", "Low"],
    ]
    assert any(
        "cp2.materiality_direction_enum" in v
        for v in _about(_violations("CP-2", _register("T2.10", _T210, mixed)), "T2.10")
    )
    assert "DEPRECATED: Positive(unqualified)->specify | Mixed->split" in _canon()
    for name in (
        "references/REF_CP-2_STEPS.md",
        "references/CP-2_SCHEMA_REFERENCE.md",
        "references/CP-2_SYSTEM_REFERENCE.md",
    ):
        text = _authority("CP-2", name)
        assert "Mixed->split" in text and "Negative / Mixed" not in text, name


def test_the_cp_model_tables_are_unconditional_and_listed_once() -> None:
    """N70: CP-2's and CP-2G's CP-MODEL tables were listed as conditional
    appendix registers and as unconditional stable tables; the checker
    requires them on every run, as each `SKILL.md`'s own prose says."""
    for module, table in (
        ("CP-2", "cp2.cp_model_strengths_weaknesses"),
        ("CP-2G", "cp2g.cp_model_forecast_drivers"),
    ):
        text = skill(module).decode()
        assert "  - **conditional_register_ids**: none\n" in text, module
        assert f"**conditional_register_ids**: {table}" not in text, module
        contract = CHECK.load_contract(text, module)
        assert table in contract["unconditional_stable_tables"], module


def test_the_research_brief_is_followed_only_where_it_is_delivered() -> None:
    """N70: every module's research paragraph but CP-L10's told a model to use
    CP-OS's research brief, which the host delivers to CP-DR alone. Each now
    uses it where it is delivered and otherwise records the question as a
    gap; the canon says the same."""
    from caos.methodology.bundle import delivered_authority
    from caos.methodology.handoff import ADAPTER_MODULES

    brief = "../cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md"
    conditioned = f"where `{brief}` is delivered with this module"
    for module in sorted(ADAPTER_MODULES):
        text = skill(module).decode()
        delivered = {name for name, _ in delivered_authority(BUNDLE, module).files}
        assert (brief in delivered) == (module == "CP-DR"), module
        assert f"Otherwise use `{brief}`" not in text, module
        if "Research questions and adoption" in text:
            assert conditioned in text, module
    assert "is delivered with a module, follow it; where it is not" in _canon()


def _module_status_map() -> dict[str, str]:
    """The canon's `D1 FROM MODULE STATUS` map (D40): each run-status word
    to the `qa_status` it sets, read from the delivered canon's own line."""
    [line] = [
        text
        for text in _canon().splitlines()
        if text.startswith("D1 FROM MODULE STATUS:")
    ]
    mapped = line.split("hard caps): ", 1)[1].split(". ", 1)[0]
    status: dict[str, str] = {}
    for clause in mapped.split("; "):
        words, qa_status = clause.split(" -> ")
        status.update(dict.fromkeys(words.split(" | "), qa_status))
    return status


def test_the_cp_dr_fixture_reports_its_status_by_the_canon_map() -> None:
    """N70: the host's CP-DR fixture answered `Complete with Gaps` beside
    `qa_status: Passed`, and nothing held it to D40's map. It follows the
    canon now, and this pins the map's rows the fixture relies on."""
    from canonical_route_fixtures import (
        RESEARCH_GAPS_QA_STATUS,
        HandoffKnobs,
        bound_research_brief_text,
        research_identity,
        research_markdown,
    )

    from caos.methodology.handoff import invocation_fields

    status = _module_status_map()
    assert status["Complete"] == "Passed"
    assert status["Complete with Gaps"] == RESEARCH_GAPS_QA_STATUS == "Restricted"
    assert status["Blocked"] == "Blocked"
    ident = research_identity(
        "CP-DR", research_brief=bound_research_brief_text("a" * 64)
    )
    fields = invocation_fields(CONTRACT, ident)
    for knobs in (HandoffKnobs(), HandoffKnobs(qa_status="Blocked")):
        front = research_markdown(ident, fields, knobs).decode().split("\n---\n")[0]
        research = re.search(r'^research_status: "([^"]+)"$', front, re.MULTILINE)
        qa = re.search(r'^qa_status: "([^"]+)"$', front, re.MULTILINE)
        assert research is not None and qa is not None
        assert status[research.group(1)] == qa.group(1)


# Fork r5 (D85): CP-1's interface registers and the tagged table each one is.
_INTERFACE_REGISTERS = {
    "T4.14": "cp1.model_period_register",
    "T4.15": "cp1.model_account_register",
    "T4.16": "cp1.segment_revenue_schedule",
    "T4.17": "cp1.adjusted_ebitda_bridge",
    "T4.18": "cp1.debt_facility_register",
    "T4.19": "cp1.model_reconciliation_register",
}


def _with_nulls(block: str) -> str:
    """`block`'s empty table cells written `null`, the spelling fork r5 gives."""
    lines = []
    for line in block.splitlines():
        if line.startswith("| "):
            cells = line[1:-1].split("|")
            line = "|" + "|".join(c if c.strip() else " null " for c in cells) + "|"
        lines.append(line + "\n")
    return "".join(lines)


def _single_table(markdown: str) -> str:
    """A two-copy CP-1 re-rendered in fork r5's form: each tagged copy moved
    under its T4.x heading in place of the untagged register."""
    for register, table_id in _INTERFACE_REGISTERS.items():
        tagged = re.search(
            rf"<!-- table-id: {re.escape(table_id)} -->\n(?:\|.*\n)+\n", markdown
        )
        assert tagged is not None, table_id
        markdown = markdown[: tagged.start()] + markdown[tagged.end() :]
        under = re.search(rf"(#### {re.escape(register)}\n\n)(?:\|.*\n)+\n", markdown)
        assert under is not None, register
        markdown = (
            markdown[: under.end(1)]
            + _with_nulls(tagged.group(0))
            + "\n"
            + markdown[under.end() :]
        )
    return markdown


def test_cp1_writes_each_interface_register_once_as_one_tagged_table(
    tmp_path: Path,
) -> None:
    """D85: a CP-1 that wrote T4.14-T4.19 untagged and again as tagged copies
    ran to 84 KB on 2 October and its copies drifted from its registers. One
    tagged table, absent values `null`, passes the validator, the register
    check, the host's table reader and CP-MODEL's own input validator, as the
    two-copy form still does."""
    import subprocess
    import sys

    from cp1b_route_fixtures import cp1b_identity, cp1b_markdown

    from caos.methodology.tables import handoff_tables

    reference = verified_bytes(BUNDLE, "CP-1", "references/REF_CP-1_STEPS.md").decode()
    assert (
        "never write the register untagged and repeat it as a tagged copy" in reference
    )
    assert "in these CP-1 tables write `null`, which\nthe register check" in reference
    # D95: only a value-bearing null is a gap; a reference column's null is not.
    assert (
        "Every `null` in a value-bearing column is also listed in `## Gaps & Conflicts`"
        in reference
    )
    assert "reference column means none applies: it is not a gap" in reference
    assert "is also listed in `## Gaps & Conflicts`" in skill("CP-1").decode()
    two_copy = cp1b_markdown(cp1b_identity("CP-1")).decode()
    single = _single_table(two_copy)
    assert single.count("<!-- table-id: ") == two_copy.count("<!-- table-id: ")
    assert len(single.encode()) < 0.7 * len(two_copy.encode())
    cp1b = tmp_path / "cp1b.md"
    cp1b.write_bytes(cp1b_markdown(cp1b_identity("CP-1B")))
    validator = BUNDLE.root / "skills/cp-model/scripts/validate_cp_model_inputs.py"
    served: dict[str, list[tuple[str, tuple[str, ...], list[list[str | None]]]]] = {}
    for form, text in (("two-copy", two_copy), ("single", single)):
        assert CONTRACT.validate_handoff.validate_text(text).exit_code == 0, form
        assert _violations("CP-1", text) == [], form
        tables = handoff_tables(CONTRACT, text)
        assert tables.unavailable_reason is None, form
        served[form] = [
            (t.table_id, t.columns, [[cell.value for cell in row] for row in t.rows])
            for t in tables.tables
        ]
        cp1 = tmp_path / f"{form}.md"
        cp1.write_text(text, encoding="utf-8")
        checked = subprocess.run(
            [sys.executable, "-B", str(validator), str(cp1), str(cp1b)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr
    assert served["single"] == served["two-copy"]


# Fork r6 (D88, D89): the readers tolerate what the 2 and 3 October answers
# wrote, and still refuse a malformed table or a tag with no table of its own.
def _cp1_single() -> str:
    from cp1b_route_fixtures import cp1b_identity, cp1b_markdown

    return _single_table(cp1b_markdown(cp1b_identity("CP-1")).decode())


def _cp_model_reads(tmp_path: Path, cp1: str) -> int:
    """The exit code of CP-MODEL's own input validator over `cp1`."""
    import subprocess
    import sys

    from cp1b_route_fixtures import cp1b_identity, cp1b_markdown

    validator = BUNDLE.root / "skills/cp-model/scripts/validate_cp_model_inputs.py"
    (tmp_path / "cp1.md").write_text(cp1, encoding="utf-8")
    (tmp_path / "cp1b.md").write_bytes(cp1b_markdown(cp1b_identity("CP-1B")))
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(validator),
            *(str(tmp_path / n) for n in ("cp1.md", "cp1b.md")),
        ],
        capture_output=True,
        check=False,
    ).returncode


def test_a_tag_above_a_heading_naming_no_register_binds_for_every_reader(
    tmp_path: Path,
) -> None:
    """P1 CP-1 #3 wrote the readiness tag above `#### CP-MODEL Readiness`,
    which broke the bind: every reader now crosses a heading naming no
    register to the next table, and reads it as the table written under the
    tag. A heading naming a register is never crossed (fix round 1, C1)."""
    from caos.methodology.tables import handoff_tables

    single = _cp1_single()
    crossed = single
    for table_id in _INTERFACE_REGISTERS.values():
        tag = f"<!-- table-id: {table_id} -->\n"
        assert crossed.count(tag) == 1, table_id
        crossed = re.sub(
            rf"({re.escape(tag)}\n?)",
            r"\1\n##### CP-MODEL interface table\n\n",
            crossed,
        )
    assert crossed != single
    assert _violations("CP-1", crossed) == []
    assert handoff_tables(CONTRACT, crossed) == handoff_tables(CONTRACT, single)
    assert _cp_model_reads(tmp_path, crossed) == 0
    # Prose between a tag and its table still breaks the bind: the table is missing.
    tag = "<!-- table-id: cp1.model_period_register -->\n"
    for name, moved in (
        ("prose", crossed.replace(tag, tag + "A note.\n")),
        ("above its register heading", _tag_above_heading(single, "T4.14", tag)),
    ):
        missing = "cp1.model_period_register: CP-MODEL interface table missing"
        assert missing in " ".join(_violations("CP-1", moved)), name
    # Directly below an untagged table, with no heading between, a tag may be
    # that table's: it crosses nothing.
    readiness = "<!-- table-id: cp1.downstream_readiness -->\n"
    below = single.replace(readiness, readiness + "\n##### CP-MODEL Readiness\n\n")
    assert "cp1.downstream_readiness: CP-MODEL interface table missing" in " ".join(
        _violations("CP-1", below)
    )


def _tag_above_heading(markdown: str, register: str, tag: str) -> str:
    heading = re.search(rf"#### {re.escape(register)}\b[^\n]*\n\n", markdown)
    assert heading is not None and tag in markdown
    markdown = markdown.replace(tag, "", 1)
    return markdown[: heading.start()] + tag + "\n" + markdown[heading.start() :]


def test_a_tag_below_its_table_binds_no_other_table(tmp_path: Path) -> None:
    """Fix round 1 (C1): with each T4.14-T4.19 tag written below its table,
    each tag crossed the next register's heading and bound that register's
    table. Each interface table is missing, as before the tolerance, and no
    reader serves a table under another's id."""
    from caos.methodology.tables import handoff_tables

    below = _cp1_single()
    for table_id in _INTERFACE_REGISTERS.values():
        found = re.search(
            rf"<!-- table-id: {re.escape(table_id)} -->\n\n?((?:\|.*\n)+)", below
        )
        assert found is not None, table_id
        below = (
            below[: found.start()]
            + found.group(1)
            + f"\n<!-- table-id: {table_id} -->\n"
            + below[found.end() :]
        )
    violations = _violations("CP-1", below)
    assert sorted(v.split(":")[0] for v in violations) == sorted(
        _INTERFACE_REGISTERS.values()
    ), violations
    assert all("interface table missing" in v for v in violations)
    served = {t.table_id for t in handoff_tables(CONTRACT, below).tables}
    assert not served & set(_INTERFACE_REGISTERS.values())
    assert _cp_model_reads(tmp_path, below) != 0


def test_a_second_tag_of_a_crossed_id_unbinds_it(tmp_path: Path) -> None:
    """Fix round 1 (I1): a crossed tag stayed bound when its id was tagged
    again before a malformed copy or prose, and CP-MODEL refused the
    duplicate; a crossed tag now binds only an id tagged once."""
    single = _cp1_single()
    tag = "<!-- table-id: cp1.model_period_register -->\n"
    crossed = single.replace(tag, tag + "\n##### CP-MODEL interface table\n", 1)
    assert _violations("CP-1", crossed) == []
    anchor = re.search(r"#### T4\.15\b", crossed)
    assert anchor is not None
    for name, again in (
        ("malformed", "#### Restated\n\n| period_id |\n| --- |\n| a | b |\n\n"),
        ("prose", "#### Restated\n\nRestated below.\n\n"),
    ):
        text = (
            crossed[: anchor.start()] + tag + "\n" + again + crossed[anchor.start() :]
        )
        missing = "cp1.model_period_register: CP-MODEL interface table missing"
        assert missing in " ".join(_violations("CP-1", text)), name
        assert _cp_model_reads(tmp_path, text) != 0, name


@pytest.mark.parametrize(
    ("table_id", "register", "column", "value"),
    [
        ("cp1.model_account_register", "T4.15", "limitation_refs", ""),
        ("cp1.model_account_register", "T4.15", "limitation_refs", "n/a"),
        ("cp1.model_period_register", "T4.14", "component_period_ids", "TBD"),
    ],
)
def test_an_escaped_pipe_never_hides_a_critical_placeholder(
    table_id: str, register: str, column: str, value: str
) -> None:
    """Fix round 1 (C2): the interface reader read `\\|` in a source locator
    as text while the register check split at it, so a blank, `n/a` or `TBD`
    in the row's last critical column slid out of the header's width."""
    from caos.methodology.tables import handoff_tables

    single = _cp1_single()
    found = re.search(
        rf"<!-- table-id: {re.escape(table_id)} -->\n\n?(\|.*\n)(?:\|.*\n)(\|.*\n)",
        single,
    )
    assert found is not None
    header = [c.strip() for c in found.group(1).strip().strip("|").split("|")]
    cells = [c.strip() for c in found.group(2).strip().strip("|").split("|")]
    cells[header.index("source_locator")] += " \\| note 4"
    cells[header.index(column)] = value
    text = single.replace(found.group(2), "| " + " | ".join(cells) + " |\n", 1)
    assert f"{register} row 1: critical column {column!r} holds a disqualifying" in (
        " ".join(_violations("CP-1", text))
    )
    [served] = [
        t for t in handoff_tables(CONTRACT, text).tables if t.table_id == table_id
    ]
    assert served.rows[0][header.index("source_locator")].text.endswith(" | note 4")


def test_a_short_interface_row_names_only_its_table(tmp_path: Path) -> None:
    """P1 CP-1 #1 and N3 CP-1 #2 each lost one cell of one period-register row,
    and the check reported all seven interface tables missing. The short row
    is still refused -- by the check, the host's table reader and CP-MODEL --
    and the check names that table alone."""
    from caos.methodology.tables import handoff_tables

    single = _cp1_single()
    period = re.search(
        r"<!-- table-id: cp1\.model_period_register -->\n\n?(?:\|.*\n){2}(\|.*)\|\n",
        single,
    )
    assert period is not None
    short = single.replace(
        period.group(0),
        period.group(0).replace(
            period.group(1) + "|", period.group(1).rsplit("|", 1)[0] + "|", 1
        ),
        1,
    )
    assert short != single
    violations = _violations("CP-1", short)
    interface = [v for v in violations if v.startswith("cp1.")]
    assert len(interface) == 1, violations
    assert re.fullmatch(
        r"cp1\.model_period_register: row 1 \(first cell `[^`]*`\) has (\d+) cells, "
        r"header has (\d+) -- table row width differs from its header",
        interface[0],
    ), interface
    assert handoff_tables(CONTRACT, short).unavailable_reason == "TABLES_MALFORMED"
    assert _cp_model_reads(tmp_path, short) != 0


def test_cp_l10_writes_a_gap_once_and_keeps_every_screen_s_rows() -> None:
    """D96 (V8): on the six stored CP-L10 answers no absorbed screen's
    source-and-scope table repeated another's (0 of 60 pairs shared a row) and
    every evidence-less topic row held a materiality and rank no other register
    holds, so all twenty registers, each screen's scope rows and its six topic
    rows stay required; only the restated gap and prohibitions are dropped."""
    lite = skill("CP-L10").decode()
    assert lite.count("## Written once — binding on all five screens") == 1
    assert "not again in the summary" in lite
    assert "no cell or line repeats that no conclusion" in lite
    contract = CHECK.load_contract(lite, "CP-L10")
    assert contract["retired_registers"] == []
    registers = contract["registers"]
    for phase in ("10", "20", "23", "30", "40"):
        assert registers[f"TL{phase}.1"]["minimum_body_rows"] == 1, phase
        assert registers[f"TL{phase}.2"]["minimum_body_rows"] == 6, phase
    rules = {rule["rule_id"] for rule in contract["semantic_rules"]}
    assert "cp_l10.topic_ids_complete" in rules
