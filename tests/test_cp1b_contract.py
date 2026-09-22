"""CP-1B's FULL earnings-update contract."""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill, upstream_ref
from cp1b_route_fixtures import (
    EARNINGS_FACTS,
    LIMITATION,
    MODULES,
    PACK,
    QUOTES,
    ROUTE,
    SELECTION,
    cp1b_identity,
    cp1b_markdown,
    earnings_pack,
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

REGISTERS = tuple(f"T4.{number}" for number in range(1, 16))


def _identity() -> HostIdentity:
    return cp1b_identity(
        "CP-1B",
        tuple(
            upstream_ref(
                cp1b_identity(edge.source), cp1b_markdown(cp1b_identity(edge.source))
            )
            for edge in ROUTE.edges
            if edge.target == "CP-1B"
        ),
    )


def _validate(ident: HostIdentity, markdown: bytes) -> Projections:
    return validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-1B"),
        markdown,
        identity=ident,
        gate_expects=frozenset(),
    )


def test_cp1b_catalog_identity_is_enabled() -> None:
    assert ROUTE.nodes[-1].module_id == "CP-5"
    assert tuple(ref.module_id for ref in _identity().upstream) == ("CP-0", "CP-1")
    assert SELECTION in ADAPTER_ROUTES and "CP-1B" in ADAPTER_MODULES


def test_cp1b_emits_every_register_with_two_period_delta_rows() -> None:
    markdown = cp1b_markdown(cp1b_identity("CP-1B")).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1B").decode(), "CP-1B")
    assert set(rules["registers"]) == set(REGISTERS)
    assert (
        CONTRACT.completeness_check.check(skill("CP-1B").decode(), markdown, "CP-1B")[0]
        == []
    )
    for table_id in rules["unconditional_stable_tables"]:
        assert f"<!-- table-id: {table_id} -->" in markdown
    stable = CONTRACT.completeness_check.parse_tables(markdown)
    assert stable["cp1b.model_comparator_register"].columns == [
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
    ]
    assert stable["cp1b.model_validation_register"].columns == [
        "metric_id",
        "period_id",
        "cp1_value",
        "cp1b_comparison_value",
        "difference",
        "tolerance",
        "status",
        "explanation",
        "source_or_conflict_ref",
    ]
    assert stable["cp1b.addback_validation_register"].columns == [
        "addback_id",
        "period_id",
        "cp1_value",
        "cp1b_comparison_value",
        "difference",
        "tolerance",
        "status",
        "label_match",
        "definition_change_flag",
        "explanation",
        "source_or_conflict_ref",
    ]
    assert stable["cp1b.cp_model_snapshot_fields"].columns == [
        "field_id",
        "value",
        "status",
        "source_id",
        "source_locator",
        "as_of",
    ]
    assert stable["cp1b.model_readiness"].columns == [
        "downstream_module",
        "status",
        "blocking_metric_ids",
        "blocking_period_ids",
        "conflict_refs",
        "explanation",
    ]
    assert stable["cp1b.addback_validation_register"].rows == []
    assert b"adjusted EBITDA equals EBITDA; no add-backs disclosed" in PACK
    assert QUOTES["CP-1B"] in markdown and QUOTES["CP-1B"].encode() in PACK
    for metric, prior, current, change in (
        ("Revenue", 1000, 1100, 100),
        ("EBITDA", 200, 220, 20),
        ("Operating cash flow", 140, 155, 15),
        ("Capex", 40, 45, 5),
        ("Cash", 100, 120, 20),
        ("Debt", 600, 580, -20),
    ):
        assert (
            f"| {metric} | FY2024 {prior}; FY2025 {current} | {change} / "
            f"{change / prior:.1%} |" in markdown
        )
    assert "| CP-MODEL | READY |" in markdown


@pytest.mark.parametrize("module", MODULES)
def test_every_earnings_update_handoff_is_vendor_valid_and_source_grounded(
    module: str,
) -> None:
    markdown = cp1b_markdown(cp1b_identity(module)).decode()
    assert CONTRACT.validate_handoff.validate_text(markdown).exit_code == 0
    assert (
        CONTRACT.completeness_check.check(skill(module).decode(), markdown, module)[0]
        == []
    )
    assert QUOTES[module] in markdown and QUOTES[module].encode() in PACK


@pytest.mark.parametrize("register", REGISTERS)
def test_cp1b_refuses_each_missing_register(register: str) -> None:
    ident = _identity()
    with pytest.raises(Refusal) as refused:
        _validate(ident, cp1b_markdown(ident, omit_register=register))
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp1b_refuses_wrong_upstream_lineage() -> None:
    ident = _identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        _validate(
            ident, cp1b_markdown(ident, fields=invocation_fields(CONTRACT, wrong))
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp1b_keeps_a_real_limitation_and_full_scope() -> None:
    projection = _validate(
        _identity(), cp1b_markdown(_identity(), qa_status="Restricted")
    )
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert projection.limitation_flags == (LIMITATION,)


def test_changed_current_fact_rebuilds_pack_and_all_dependent_rows() -> None:
    changed = replace(
        EARNINGS_FACTS, current_revenue=EARNINGS_FACTS.current_revenue + 1
    )
    pack = earnings_pack(changed).decode()
    markdown = cp1b_markdown(cp1b_identity("CP-1B"), facts=changed).decode()
    assert f"FY2025 revenue {changed.current_revenue}" in pack
    revenue_row = (
        f"| Revenue | FY2024 {changed.prior_revenue}; FY2025 "
        f"{changed.current_revenue} | {changed.revenue_change} / "
        f"{changed.revenue_change / changed.prior_revenue:.1%} |"
    )
    assert revenue_row in markdown
    assert (
        f"| Revenue | YoY | {changed.prior_revenue}/{changed.current_revenue} | "
        f"{changed.revenue_change} |" in markdown
    )
    comparator_row = (
        f"| revenue | FY2025/FY2024 | YoY | {changed.current_revenue}/"
        f"{changed.prior_revenue} | {changed.revenue_change} |"
    )
    assert comparator_row in markdown
    assert (
        f"| revenue | FY2025 | {changed.current_revenue} | "
        f"{changed.current_revenue} | 0 |" in markdown
    )
    assert (
        f"| revenue | FY2025 | FY2024 | LTM_PRIOR | {changed.current_revenue} | "
        f"{changed.prior_revenue} | {changed.revenue_change} | "
        f"{changed.revenue_change / changed.prior_revenue:.1%} |" in markdown
    )
    assert (
        f"| revenue | FY2025 | {changed.current_revenue} | "
        f"{changed.current_revenue} | 0 | 0 | PASS |" in markdown
    )
    assert (
        f"| historical_performance | Revenue changed from {changed.prior_revenue} "
        f"to {changed.current_revenue}; EBITDA changed from " in markdown
    )
    quote = (
        f"FY2025 revenue {changed.current_revenue} EBITDA {changed.current_ebitda} "
        f"operating cash flow {changed.current_operating_cash_flow}"
    )
    assert quote in pack and quote in markdown
