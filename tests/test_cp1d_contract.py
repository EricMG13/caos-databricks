"""CP-1D on the disabled FULL credit-assessment route."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp1d_contract_fixtures import (
    FACTS,
    LIMITATION,
    PACK,
    REGISTERS,
    ROUTE,
    SELECTION,
    SOURCE_QUOTE,
    cp1d_identity,
    cp1d_markdown,
    earnings_calculation,
    earnings_pack,
    earnings_rows,
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
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-1D"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-1D"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp1d_real_route_identity_is_proven_and_enabled() -> None:
    ident = cp1d_identity()
    assert tuple(ref.module_id for ref in ident.upstream) == ("CP-0", "CP-1", "CP-1B")
    assert tuple(edge.source for edge in ROUTE.edges if edge.target == "CP-1D") == (
        "CP-0",
        "CP-1",
        "CP-1B",
    )
    assert _validate(ident, cp1d_markdown(ident)).qa_status == "Restricted"
    assert "CP-1D" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES


def test_cp1d_emits_every_earnings_quality_and_adjusted_debt_register() -> None:
    markdown = cp1d_markdown(cp1d_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1D").decode(), "CP-1D")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-1D").decode(), markdown, "CP-1D"
    )
    assert tuple(rules["registers"]) == REGISTERS
    assert violations == []
    assert {register: len(present[register][1]) for register in REGISTERS} == {
        **{register: 1 for register in REGISTERS},
        "T1E.3": 2,
        "T1D.4": 3,
    }
    assert SOURCE_QUOTE in markdown
    source = Path("qualification/ccl-fy2025/documents/CCL_FY2025_10K.txt").read_text()
    assert SOURCE_QUOTE in source


@pytest.mark.parametrize("register", REGISTERS)
def test_cp1d_refuses_each_missing_register(register: str) -> None:
    ident = cp1d_identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp1d_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp1d_refuses_wrong_direct_upstream_identity() -> None:
    ident = cp1d_identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp1d_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp1d_keeps_source_limit_and_full_scope() -> None:
    projection = _validate(cp1d_identity(), cp1d_markdown(cp1d_identity()))
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_earnings_and_debt_restatements_are_source_derived() -> None:
    baseline = earnings_calculation()
    assert baseline["reported_ebitda"] == Decimal("7273")
    assert baseline["adjusted_ebitda"] == Decimal("7176")
    assert baseline["quality_ebitda"] == Decimal("7163")
    assert baseline["adjusted_debt"] == Decimal("28736")

    changed = replace(
        FACTS,
        reported_operating_income=Decimal("4600"),
        restructuring=Decimal("20"),
        cfo=Decimal("6300"),
        operating_lease_liability=Decimal("1500"),
    )
    changed_calc = earnings_calculation(changed)
    changed_rows = earnings_rows(changed)
    assert "$20m in 2025" in earnings_pack(changed).decode()
    assert changed_calc["quality_ebitda"] == Decimal("7280")
    assert changed_calc["adjusted_debt"] == Decimal("28883")
    assert changed_rows["T1D.4"][2][4] == (
        "$7300m before rejection; $7280m quality-adjusted"
    )
    assert changed_calc != baseline
    assert PACK != earnings_pack(changed)
