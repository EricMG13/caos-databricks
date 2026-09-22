"""CP-1A on the disabled FULL credit-assessment route."""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill
from cp1a_contract_fixtures import (
    FACTS,
    LIMITATION,
    MODEL_FIELDS,
    PACK,
    REGISTERS,
    ROUTE,
    SELECTION,
    cp1a_identity,
    cp1a_markdown,
    cp1a_rows,
    model_rows,
    transaction_pack,
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
            "caos.methodology.handoff.ADAPTER_MODULES", ADAPTER_MODULES | {"CP-1A"}
        )
        return validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-1A"),
            markdown,
            identity=ident,
            gate_expects=frozenset(),
        )


def test_cp1a_real_route_identity_is_proven_and_enabled() -> None:
    ident = cp1a_identity()
    assert tuple(ref.module_id for ref in ident.upstream) == ("CP-0",)
    assert tuple(edge.source for edge in ROUTE.edges if edge.target == "CP-1A") == (
        "CP-0",
    )
    assert _validate(ident, cp1a_markdown(ident)).qa_status == "Restricted"
    assert "CP-1A" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES


def test_cp1a_emits_every_register_and_exact_model_projection() -> None:
    markdown = cp1a_markdown(cp1a_identity()).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1A").decode(), "CP-1A")
    violations, _, present = CONTRACT.completeness_check.check(
        skill("CP-1A").decode(), markdown, "CP-1A"
    )
    assert tuple(rules["registers"]) == REGISTERS
    assert violations == []
    assert all(present[register][1] for register in REGISTERS)

    tables = CONTRACT.completeness_check.parse_tables(markdown)
    model = tables["cp1a.cp_model_snapshot_fields"]
    assert model.columns == [
        "field_id",
        "value",
        "status",
        "source_id",
        "source_locator",
        "as_of",
    ]
    assert tuple(row["field_id"] for row in model.rows) == MODEL_FIELDS
    assert all(row["status"] == "READY" for row in model.rows)


@pytest.mark.parametrize("register", REGISTERS)
def test_cp1a_refuses_each_missing_register(register: str) -> None:
    ident = cp1a_identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp1a_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp1a_refuses_wrong_direct_upstream_identity() -> None:
    ident = cp1a_identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64),),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp1a_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp1a_keeps_diligence_limit_and_full_scope() -> None:
    projection = _validate(cp1a_identity(), cp1a_markdown(cp1a_identity()))
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert (projection.confidence_score, projection.confidence_band) == (50, "Low")
    assert projection.committee_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)


def test_transaction_and_projection_are_source_derived() -> None:
    changed = replace(
        FACTS,
        close_date="2026-08-15",
        purchase_price=1000,
        debt_funding=550,
        equity_funding=450,
        revenue=780,
        sponsor_interest=90,
    )
    assert PACK != transaction_pack(changed)
    assert "EUR 1000m" in transaction_pack(changed).decode()
    assert "EUR 1000m" in cp1a_rows(changed)["transaction_summary"][0][0]
    assert cp1a_rows(changed)["T2D.6"][0][5] == (
        "EUR 550m acquisition debt increases leverage"
    )
    assert model_rows(changed)[3][1] == "Sponsor Alpha Fund IV (90%)"
    assert model_rows(changed)[4][1].endswith("EUR 1000m")
