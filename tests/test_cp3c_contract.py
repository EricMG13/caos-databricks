"""CP-3C's FULL covenant/refinancing contract."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp3c_route_fixtures import (
    FACTS,
    LIMITATION,
    MODULES,
    PACK,
    QUOTE,
    ROUTE,
    SELECTION,
    RefinancingFacts,
    cp3c_identity,
    cp3c_markdown,
    direct_upstream,
    refinancing_pack,
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
    "T3D.1",
    "T3D.10",
    "T3D.11",
    "T3D.2",
    "T3D.3",
    "T3D.4",
    "T3D.5",
    "T3D.6",
    "T3D.7",
    "T3D.8",
    "T3D.9",
)


def _identity(*, include_cp4: bool = True) -> HostIdentity:
    return cp3c_identity("CP-3C", direct_upstream(include_cp4))


def _validate(ident: HostIdentity, markdown: bytes) -> Projections:
    return validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-3C"),
        markdown,
        identity=ident,
        gate_expects=frozenset(),
    )


def _gap(facts: RefinancingFacts = FACTS) -> dict[str, Any]:
    script = (
        Path(__file__).parents[1]
        / "vendor/deploy-v/skills/cp-3c-refinancing-lme-risk/scripts/funding_gap.py"
    )
    payload = {
        "horizon_years": 2,
        "currency": "USD",
        "cash": facts.cash,
        "forecast_fcf": facts.forecast_fcf,
        "instruments": [
            {
                "instrument": "Term loan",
                "amount": facts.carrying_debt,
                "gross_principal": facts.gross_principal,
                "years_to_maturity": facts.maturity_years,
            }
        ],
        "facilities": [
            {
                "facility": "RCF",
                "commitment": facts.facility_commitment,
                "drawn": facts.facility_drawn,
                "years_to_expiry": 3,
                "committed": True,
            }
        ],
        "pro_forma_instruments": [
            {
                "instrument": "Term loan after subsequent extension",
                "amount": facts.carrying_debt - facts.extension_amount,
                "gross_principal": facts.gross_principal - facts.extension_amount,
                "years_to_maturity": facts.maturity_years,
            }
        ],
    }
    return cast(
        dict[str, Any],
        json.loads(
            subprocess.run(
                [sys.executable, str(script), "--json", json.dumps(payload)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        ),
    )


def test_cp3c_catalog_identity_is_real_and_enabled() -> None:
    assert MODULES == ("CP-0", "CP-1", "CP-4", "CP-2", "CP-2D", "CP-3C", "CP-5")
    assert ROUTE.nodes[-1].module_id == "CP-5"
    assert {
        (edge.source, edge.target): edge.type
        for edge in ROUTE.edges
        if edge.target == "CP-3C"
    } == {
        ("CP-0", "CP-3C"): EdgeType.REQUIRED,
        ("CP-1", "CP-3C"): EdgeType.REQUIRED,
        ("CP-2D", "CP-3C"): EdgeType.REQUIRED,
        ("CP-4", "CP-3C"): EdgeType.OPTIONAL,
    }
    assert {ref.module_id for ref in _identity().upstream} == {
        "CP-0",
        "CP-1",
        "CP-2D",
        "CP-4",
    }
    assert {ref.module_id for ref in _identity(include_cp4=False).upstream} == {
        "CP-0",
        "CP-1",
        "CP-2D",
    }
    without_cp4 = _identity(include_cp4=False)
    assert _validate(without_cp4, cp3c_markdown(without_cp4)).qa_status == "Restricted"
    assert "CP-3C" in ADAPTER_MODULES and SELECTION in ADAPTER_ROUTES


def test_cp3c_emits_all_registers_and_source_derived_refinancing_analysis() -> None:
    markdown = cp3c_markdown(_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-3C").decode(), "CP-3C")
    assert tuple(rules["registers"]) == REGISTERS
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-3C").decode(), markdown, "CP-3C"
    )
    assert violations == []
    assert len(present["T3D.4"][1]) == 14
    assert {row["Dimension"] for row in present["T3D.7"][1]} == {
        "Refinancing pressure",
        "Legal capacity",
        "Sponsor willingness",
        "Market access",
        "Recovery impact",
        "Overall Prime/LME vulnerability",
    }
    assert {row["Path Type"] for row in present["T3D.6"][1]} == {
        "Consensual refinancing",
        "Priming debt",
    }
    assert "[Market Data Not Provided]" in markdown
    gap = _gap()["as_of_balance_sheet_date"]
    assert gap["maturity_wall"]["total_due"] == FACTS.carrying_debt
    assert gap["liquidity"]["total_available"] == FACTS.available_liquidity
    assert gap["gap"]["funding_gap"] == FACTS.funding_gap
    pro_forma = _gap()["pro_forma_for_subsequent_events"]
    assert (
        pro_forma["maturity_wall"]["total_due"]
        == FACTS.carrying_debt - FACTS.extension_amount
    )
    assert pro_forma["gap"]["funding_gap"] == FACTS.funding_gap - FACTS.extension_amount
    assert (
        gap["maturity_wall"]["definition_conflicts"][0]["gross_principal"]
        == FACTS.gross_principal
    )
    assert f"gross principal {FACTS.gross_principal}" in markdown
    assert "Subsequent event" in PACK.decode()
    assert FACTS.extension_date in markdown
    assert str(FACTS.carrying_debt - FACTS.extension_amount) in markdown
    assert "subsequent extension is pro-forma only" in markdown
    assert "Executed debt documents not supplied" in markdown
    assert QUOTE in markdown and QUOTE.encode() in PACK


@pytest.mark.parametrize("register", REGISTERS)
def test_cp3c_refuses_each_missing_register(register: str) -> None:
    ident = _identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp3c_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp3c_refuses_wrong_direct_upstream_identity() -> None:
    ident = _identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp3c_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp3c_keeps_real_legal_limitation_and_full_scope() -> None:
    projection = _validate(
        _identity(), cp3c_markdown(_identity(), qa_status="Restricted")
    )
    assert projection.qa_status == "Restricted" and projection.decision_scope == "FULL"
    assert projection.limitation_flags == (LIMITATION,)


def test_changed_maturity_rebuilds_pack_gap_and_authored_rows() -> None:
    changed = replace(
        FACTS,
        carrying_debt=FACTS.carrying_debt + 11,
        forecast_fcf=FACTS.forecast_fcf + 3,
        extension_amount=FACTS.extension_amount + 7,
    )
    pack = refinancing_pack(changed).decode()
    markdown = cp3c_markdown(_identity(), facts=changed).decode()
    gap = _gap(changed)["as_of_balance_sheet_date"]["gap"]
    assert f"carrying value {changed.carrying_debt}" in pack
    assert f"free cash flow {changed.forecast_fcf}" in pack
    assert (
        f"{changed.extension_amount} USD million of the term loan was extended" in pack
    )
    assert f"| Term loan | {changed.carrying_debt} | USD |" in markdown
    assert changed.extension_date in markdown
    assert gap["funding_gap"] != FACTS.funding_gap
    assert (
        changed.carrying_debt - changed.extension_amount
        != FACTS.carrying_debt - FACTS.extension_amount
    )
    assert (
        f"pro forma maturity wall {changed.carrying_debt - changed.extension_amount}"
        in markdown
    )
    assert f"{gap['funding_gap']:g} USD million shortfall" in markdown
    assert f"maturity wall and {gap['funding_gap']:g} funding gap" in markdown
