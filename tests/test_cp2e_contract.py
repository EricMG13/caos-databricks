"""CP-2E on the disabled FULL credit-assessment route."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp2e_contract_fixtures import (
    FACTS,
    LIMITATION,
    PACK,
    REGISTERS,
    ROUTE,
    SELECTION,
    SOURCE_QUOTE,
    cp2e_identity,
    cp2e_markdown,
    macro_pack,
    macro_rows,
    sensitivity_result,
)

from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    HostIdentity,
    Projections,
    invocation_fields,
    validate_markdown,
)
from caos.refusals import Refusal, RefusalCode


def _validate(ident: HostIdentity, markdown: bytes) -> Projections:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-2E"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-2E"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp2e_real_route_identity_is_proven_and_enabled() -> None:
    ident = cp2e_identity()
    assert tuple(ref.module_id for ref in ident.upstream) == ("CP-0",)
    assert tuple(edge.source for edge in ROUTE.edges if edge.target == "CP-2E") == (
        "CP-0",
    )
    assert _validate(ident, cp2e_markdown(ident)).qa_status == "Restricted"
    assert "CP-2E" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES


def test_cp2e_emits_every_macro_and_absorbed_esg_register() -> None:
    markdown = cp2e_markdown(cp2e_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-2E").decode(), "CP-2E")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-2E").decode(), markdown, "CP-2E"
    )
    assert tuple(rules["registers"]) == REGISTERS
    assert violations == []
    assert {register: len(present[register][1]) for register in REGISTERS} == {
        **{register: 1 for register in REGISTERS},
        "T2F.2": 2,
        "T2F.4": 5,
        "T2F.8": 3,
        "T2F.9": 2,
    }
    assert SOURCE_QUOTE in markdown
    source = Path("qualification/ccl-fy2025/documents/CCL_FY2025_10K.txt").read_text()
    assert SOURCE_QUOTE in source


@pytest.mark.parametrize("register", REGISTERS)
def test_cp2e_refuses_each_missing_register(register: str) -> None:
    ident = cp2e_identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp2e_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp2e_refuses_wrong_direct_upstream_identity() -> None:
    ident = cp2e_identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64),),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp2e_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp2e_keeps_source_limit_and_full_scope() -> None:
    projection = _validate(cp2e_identity(), cp2e_markdown(cp2e_identity()))
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_rate_fx_and_fuel_sensitivities_are_script_owned_and_source_derived() -> None:
    baseline = sensitivity_result()
    assert baseline["unhedged_floating_rate_debt"] == 4154.0
    assert baseline["unhedged_debt_percentage"] == 0.1517
    assert baseline["cash_interest_impact_plus_100bps"] == 41.54
    assert baseline["fx_sensitivity"][0]["impact"] == 84.0
    assert baseline["cost_sensitivity"][0]["impact"] == 180.7

    changed = replace(
        FACTS,
        total_debt=28383.0,
        floating_debt=5154.0,
        newbuild_commitment=9000.0,
        fuel_cost=2000.0,
    )
    changed_result = sensitivity_result(changed)
    changed_pack = macro_pack(changed).decode()
    changed_rows = macro_rows(changed)
    assert "$5154 million" in changed_pack
    assert changed_result["cash_interest_impact_plus_100bps"] == 51.54
    assert changed_result["fx_sensitivity"][0]["impact"] == 90.0
    assert changed_result["cost_sensitivity"][0]["impact"] == 200.0
    assert changed_rows["T2F.4"][4][4] == (
        "About 18.2% of debt remains base-rate sensitive"
    )
    assert changed_rows["T2F.5"][0][3] == "$51.54m annual cash interest"
    assert changed_rows["T2F.5"][0][5].endswith("approximately $52m disclosure")
    assert b"82% fixed-rate debt mix" in cp2e_markdown(cp2e_identity(), facts=changed)
    assert changed_result != baseline
    assert PACK != macro_pack(changed)
