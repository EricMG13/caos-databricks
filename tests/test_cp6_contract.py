"""CP-6 and absorbed CP-6A on the disabled FULL portfolio-decision route."""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp6_route_fixtures import (
    FACTS,
    LIMITATION,
    MODULES,
    PACK,
    QUOTE,
    ROUTE,
    SELECTION,
    cp6_identity,
    cp6_markdown,
    debate_pack,
    direct_upstream,
)

from caos.graph.route import EdgeType
from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    HostIdentity,
    Projections,
    invocation_fields,
    validate_markdown,
)
from caos.refusals import Refusal, RefusalCode

REGISTERS = (
    "T6E.11",
    "T6E.4",
    "T6E.6",
    "T6E.7",
    "T6A.11",
    "T6A.4",
    "T6A.6",
    "T6A.7",
)
ISSUER_DIMENSIONS = {
    "Cash-flow durability",
    "Downside pathway severity",
    "Liquidity runway",
    "Refinancing / maturity risk",
    "Legal / covenant control",
    "Recovery / LGD protection",
    "Sponsor / governance alignment",
    "Relative value compensation",
    "Portfolio fit / sizing",
}
PORTFOLIO_DIMENSIONS = {
    "Spread / YTW Benefit",
    "Peer Relative Value",
    "Downside Pathway Severity",
    "Liquidity / Refinancing Risk",
    "Legal / Recovery Protection",
    "CCC-Basket / Downgrade Risk",
    "Concentration / Correlation Risk",
    "Mandate Compliance",
    "Implementation Liquidity",
}
IMPLICATIONS = {
    "Positive — Deleveraging",
    "Positive — Margin Expansion",
    "Positive — Revenue Growth",
    "Positive — Liquidity Improvement",
    "Positive — Covenant Headroom Expansion",
    "Neutral — Stable",
    "Negative — Leverage Increase",
    "Negative — Margin Compression",
    "Negative — Revenue Decline",
    "Negative — Liquidity Deterioration",
    "Negative — Covenant Erosion",
    "Negative — Refinancing Risk",
    "Insufficient Information",
}


def _identity(*, include_cp3d: bool = True) -> HostIdentity:
    return cp6_identity(direct_upstream(include_cp3d))


def _validate(ident: HostIdentity, markdown: bytes) -> Projections:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-6"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-6"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp6_catalog_identity_and_qa_gate_are_real_and_enabled() -> None:
    assert MODULES == ("CP-0", "CP-1", "CP-3D", "CP-2", "CP-4", "CP-3", "CP-5", "CP-6")
    assert [(edge.source, edge.target, edge.type) for edge in ROUTE.edges] == [
        ("CP-0", "CP-1", EdgeType.REQUIRED),
        ("CP-0", "CP-2", EdgeType.REQUIRED),
        ("CP-0", "CP-3", EdgeType.REQUIRED),
        ("CP-0", "CP-4", EdgeType.REQUIRED),
        ("CP-0", "CP-5", EdgeType.REQUIRED),
        ("CP-0", "CP-6", EdgeType.REQUIRED),
        ("CP-1", "CP-2", EdgeType.REQUIRED),
        ("CP-1", "CP-3", EdgeType.REQUIRED),
        ("CP-1", "CP-4", EdgeType.REQUIRED),
        ("CP-1", "CP-6", EdgeType.REQUIRED),
        ("CP-2", "CP-3", EdgeType.REQUIRED),
        ("CP-2", "CP-6", EdgeType.REQUIRED),
        ("CP-3", "CP-6", EdgeType.REQUIRED),
        ("CP-5", "CP-6", EdgeType.QA_GATE),
        ("CP-1", "CP-5", EdgeType.ADVISORY),
        ("CP-2", "CP-5", EdgeType.ADVISORY),
        ("CP-3", "CP-5", EdgeType.ADVISORY),
        ("CP-4", "CP-5", EdgeType.ADVISORY),
        ("CP-4", "CP-3", EdgeType.ADVISORY),
        ("CP-0", "CP-3D", EdgeType.REQUIRED),
        ("CP-3D", "CP-3", EdgeType.OPTIONAL),
        ("CP-3D", "CP-5", EdgeType.ADVISORY),
        ("CP-3D", "CP-6", EdgeType.OPTIONAL),
    ]
    assert tuple(ref.module_id for ref in _identity().upstream) == (
        "CP-0",
        "CP-1",
        "CP-2",
        "CP-3D",
        "CP-3",
        "CP-5",
    )
    without_optional = _identity(include_cp3d=False)
    assert (
        _validate(without_optional, cp6_markdown(without_optional)).qa_status
        == "Restricted"
    )
    assert "CP-6" in ADAPTER_MODULES and SELECTION in ADAPTER_ROUTES


def test_cp6_emits_both_complete_evidence_led_debate_methods() -> None:
    markdown = cp6_markdown(_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-6").decode(), "CP-6")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-6").decode(), markdown, "CP-6"
    )
    assert tuple(rules["registers"]) == REGISTERS and violations == []
    assert {register: len(present[register][1]) for register in REGISTERS} == {
        "T6E.11": 4,
        "T6E.4": 3,
        "T6E.6": 9,
        "T6E.7": 3,
        "T6A.11": 3,
        "T6A.4": 3,
        "T6A.6": 9,
        "T6A.7": 3,
    }
    assert {row["Dimension"] for row in present["T6A.6"][1]} == ISSUER_DIMENSIONS
    assert {row["Dimension"] for row in present["T6E.6"][1]} == PORTFOLIO_DIMENSIONS
    assert all(
        row["Score (1-5)"] in {"1", "2", "3", "4", "5"}
        for register in ("T6A.6", "T6E.6")
        for row in present[register][1]
    )
    assert {row["Resolution"] for row in present["T6A.7"][1]} <= {
        "Bull Sustained",
        "Bear Sustained",
        "Partially Mitigated",
        "Unresolved",
        "Insufficient Information",
    }
    assert {row["Resolution"] for row in present["T6E.7"][1]} <= {
        "RV Sustained",
        "Compliance Sustained",
        "Partially Mitigated",
        "Unresolved",
        "Insufficient Information",
    }
    assert all(
        row[column] in IMPLICATIONS
        for register, column in (
            ("T6A.4", "Credit Implication"),
            ("T6A.7", "Credit Implication"),
            ("T6E.4", "Credit Implication"),
            ("T6E.7", "Credit / Portfolio Implication"),
        )
        for row in present[register][1]
    )
    decision = markdown.split("### Decision\n\n", 1)[1].split("\n\n", 1)[0]
    assert 90 <= len(decision.split()) <= 150
    assert markdown.count("**Claim ") == 3 and markdown.count("**RV Bullet ") == 3
    assert "Final Action Bias: Starter Position." in markdown
    assert "Final Sizing Posture: Requires More Work." in markdown
    assert "Exact Portfolio Constraint: Data quality." in markdown
    for heading in (
        "IC Debate Source Gate",
        "Pre-Debate Thesis Map",
        "Bull Analyst Opening Statement",
        "Bear Analyst Cross-Examination",
        "Bull Analyst Defense",
        "IC Chair Evidence Weighting",
        "Debate Resolution Matrix",
        "Action Bias Determination",
        "Single Greatest Uncertainty",
        "IC Chair Final Memo",
        "Portfolio Debate Source Gate",
        "Pre-Debate Portfolio Thesis Map",
        "The RV Trader's Pitch",
        "The Mandate Compliance Officer's Attack",
        "The RV Trader's Defense",
        "CIO Evidence Weighting",
        "Allocation Decision Matrix",
        "Final Sizing Posture",
        "Exact Portfolio Constraint",
        "CIO Final Memo",
    ):
        assert f"#### {heading}" in markdown
    assert markdown.count("#### Gaps Ledger") == 2
    assert [row["Gap ID"] for row in present["T6A.11"][1]] == [
        "CP-6-GAP-001",
        "CP-6-GAP-002",
        "CP-6-GAP-003",
    ]
    assert [row["Gap ID"] for row in present["T6E.11"][1]] == [
        "CP-6A-GAP-001",
        "CP-6A-GAP-002",
        "CP-6A-GAP-003",
        "CP-6A-GAP-004",
    ]
    assert QUOTE in markdown and QUOTE.encode() in PACK


def test_cp6_binary_authority_is_lossless_and_explicit() -> None:
    import base64

    from canonical_fixtures import BUNDLE

    from caos.methodology.bundle import delivered_authority
    from caos.methodology.invocation import _authority_text

    authority = delivered_authority(BUNDLE, "CP-6")
    [(name, data)] = [item for item in authority.files if item[0].endswith(".xlsx")]
    encoded = _authority_text("CP-6", name, data)
    assert encoded.startswith("ENCODING: base64")
    assert base64.b64decode(encoded.split("\n", 1)[1], validate=True) == data


@pytest.mark.parametrize("register", REGISTERS)
def test_cp6_refuses_each_missing_register(register: str) -> None:
    ident = _identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp6_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp6_refuses_wrong_direct_upstream_identity() -> None:
    ident = _identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp6_markdown(ident, fields=invocation_fields(CONTRACT, wrong)))
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp6_keeps_the_real_route_limitation_and_full_scope() -> None:
    projection = _validate(_identity(), cp6_markdown(_identity()))
    assert projection.qa_status == "Restricted" and projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_changed_market_and_exposure_facts_rebuild_pack_and_debates() -> None:
    changed = replace(
        FACTS,
        loan_spread=FACTS.loan_spread + 20,
        current_exposure=FACTS.current_exposure + 0.5,
    )
    pack = debate_pack(changed).decode()
    markdown = cp6_markdown(_identity(), facts=changed).decode()
    assert f"spread {changed.loan_spread} basis points" in pack
    assert f"Current Acme exposure {changed.current_exposure:.1f} percent" in pack
    assert f"{changed.spread_premium}bp spread premium" in markdown
    assert (
        f"{changed.pro_forma_exposure:.1f}% versus a {changed.issuer_limit:.1f}% limit"
        in markdown
    )
    assert changed.spread_premium != FACTS.spread_premium
    assert changed.concentration_headroom != FACTS.concentration_headroom
