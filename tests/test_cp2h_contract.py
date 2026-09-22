"""CP-2H on the disabled FULL credit-assessment route."""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp2h_contract_fixtures import (
    FACTS,
    LIMITATION,
    PACK,
    REGISTERS,
    ROUTE,
    SELECTION,
    cp2h_identity,
    cp2h_markdown,
    rating_pack,
    rating_rows,
    trigger_result,
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
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-2H"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-2H"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp2h_real_route_identity_is_proven_and_enabled() -> None:
    ident = cp2h_identity()
    assert tuple(ref.module_id for ref in ident.upstream) == (
        "CP-0",
        "CP-1",
        "CP-1D",
        "CP-2G",
    )
    assert tuple(edge.source for edge in ROUTE.edges if edge.target == "CP-2H") == (
        "CP-0",
        "CP-1",
        "CP-2G",
        "CP-1D",
    )
    assert _validate(ident, cp2h_markdown(ident)).qa_status == "Restricted"
    without_advisory = cp2h_identity(include_cp1d=False)
    assert _validate(without_advisory, cp2h_markdown(without_advisory)).qa_status == (
        "Restricted"
    )
    assert "CP-2H" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES


def test_cp2h_emits_the_complete_methodology_only_transition_case() -> None:
    markdown = cp2h_markdown(cp2h_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-2H").decode(), "CP-2H")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-2H").decode(), markdown, "CP-2H"
    )
    assert tuple(rules["registers"]) == REGISTERS
    assert violations == []
    assert {register: len(present[register][1]) for register in REGISTERS} == {
        **{register: 1 for register in REGISTERS},
        "T2R.4": 2,
        "T2R.6": 2,
    }
    assert {row["transition class"] for row in present["T2R.6"][1]} == {
        "within_current_range",
        "trigger_breach",
    }
    assert [row["status"] for row in present["T2R.4"][1]] == [
        "Compliant",
        "Breached",
    ]
    assert QUOTE_PREFIX in markdown and QUOTE_PREFIX.encode() in PACK


QUOTE_PREFIX = "Issuer disclosure reports S&P corporate rating BB, outlook Negative"


@pytest.mark.parametrize("register", REGISTERS)
def test_cp2h_refuses_each_missing_register(register: str) -> None:
    ident = cp2h_identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp2h_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp2h_refuses_wrong_direct_upstream_identity() -> None:
    ident = cp2h_identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp2h_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp2h_keeps_primary_evidence_limit_and_full_scope() -> None:
    projection = _validate(cp2h_identity(), cp2h_markdown(cp2h_identity()))
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_trigger_headroom_is_script_owned_and_source_derived() -> None:
    baseline = trigger_result()
    assert [row["binding_headroom"] for row in baseline["periods"]] == [1.5, -0.4]
    assert baseline["classification"] == (
        "point-in-time breach — not automatically a trigger"
    )

    changed = replace(FACTS, base_leverage=4.2, downside_leverage=5.6)
    changed_result = trigger_result(changed)
    changed_pack = rating_pack(changed).decode()
    changed_rows = rating_rows(changed)["T2R.4"]
    assert "base debt to EBITDA 4.2x" in changed_pack
    assert "downside debt to EBITDA 5.6x" in changed_pack
    assert [row["binding_headroom"] for row in changed_result["periods"]] == [
        0.8,
        -0.6,
    ]
    assert [row[6] for row in changed_rows] == ["0.8x", "-0.6x"]
    assert changed_result != baseline
    assert changed.base_leverage != FACTS.base_leverage
