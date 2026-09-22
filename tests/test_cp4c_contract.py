"""CP-4C on the disabled FULL credit-assessment route."""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp4c_contract_fixtures import (
    FACTS,
    LIMITATION,
    PACK,
    REGISTERS,
    ROUTE,
    SELECTION,
    cp4c_identity,
    cp4c_markdown,
    recovery_result,
    restructuring_pack,
    restructuring_rows,
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
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-4C"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-4C"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp4c_real_route_identity_is_proven_and_enabled() -> None:
    ident = cp4c_identity()
    assert tuple(ref.module_id for ref in ident.upstream) == (
        "CP-0",
        "CP-1",
        "CP-2A",
        "CP-4",
        "CP-2G",
        "CP-3C",
    )
    assert tuple(edge.source for edge in ROUTE.edges if edge.target == "CP-4C") == (
        "CP-0",
        "CP-1",
        "CP-2G",
        "CP-4",
        "CP-2A",
        "CP-3C",
    )
    assert _validate(ident, cp4c_markdown(ident)).qa_status == "Restricted"
    assert "CP-4C" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES


def test_cp4c_emits_every_restructuring_register() -> None:
    markdown = cp4c_markdown(cp4c_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-4C").decode(), "CP-4C")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-4C").decode(), markdown, "CP-4C"
    )
    assert tuple(rules["registers"]) == REGISTERS
    assert violations == []
    assert {register: len(present[register][1]) for register in REGISTERS} == {
        **{register: 1 for register in REGISTERS},
        "T4E.2": 3,
        "T4E.3": 3,
        "T4E.5": 3,
        "T4E.7": 9,
    }


@pytest.mark.parametrize("register", REGISTERS)
def test_cp4c_refuses_each_missing_register(register: str) -> None:
    ident = cp4c_identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp4c_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp4c_refuses_wrong_direct_upstream_identity() -> None:
    ident = cp4c_identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp4c_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp4c_keeps_legal_limit_and_full_scope() -> None:
    projection = _validate(cp4c_identity(), cp4c_markdown(cp4c_identity()))
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_fulcrum_and_recoveries_are_script_owned_and_source_derived() -> None:
    baseline = recovery_result()
    assert baseline["sensitivity"]["distinct_fulcra"] == ["SUN", "TLB"]
    assert baseline["sensitivity"]["fulcrum_stable"] is False
    assert baseline["cases"]["LOW"]["fulcrum_claim_id"] == "TLB"
    assert baseline["cases"]["BASE"]["fulcrum_claim_id"] == "SUN"
    assert baseline["cases"]["HIGH"]["residual_to_equity"] == 150.0

    changed = replace(FACTS, tlb=350.0, base_ev=450.0, high_ev=800.0)
    changed_result = recovery_result(changed)
    changed_rows = restructuring_rows(changed)
    assert "EUR 350m" in restructuring_pack(changed).decode()
    assert changed_result["cases"]["HIGH"]["residual_to_equity"] == 200.0
    assert changed_rows["T4E.7"][5][4] == "25.0%"
    assert changed_result != baseline
    assert PACK != restructuring_pack(changed)
