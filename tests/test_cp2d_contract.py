"""CP-2D's contract under ``FULL_CREDIT_32 / LIQUIDITY_REVIEW``."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import liquidity_route_fixtures as fixture_module
import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill, upstream_ref
from canonical_route_fixtures import HandoffKnobs
from liquidity_route_fixtures import (
    LIMITATION,
    LIQUIDITY_FACTS,
    MODULES,
    PACK,
    QUOTES,
    ROUTE,
    SELECTION,
    liquidity_identity,
    liquidity_markdown,
)

from caos.methodology.handoff import (
    ADAPTER_ROUTES,
    HostIdentity,
    invocation_fields,
    validate_markdown,
)
from caos.refusals import Refusal, RefusalCode

REGISTERS = (
    "T2E.1",
    "T2E.2",
    "T2E.3",
    "T2E.4",
    "T2E.5",
    "T2E.6",
    "T2E.7",
    "T2E.9",
)


def _identity(module: str) -> HostIdentity:
    refs = tuple(
        upstream_ref(
            liquidity_identity(edge.source),
            liquidity_markdown(liquidity_identity(edge.source)),
        )
        for edge in ROUTE.edges
        if edge.target == module
    )
    return liquidity_identity(module, refs)


def _vendor_bridge(inputs: dict[str, float]) -> dict[str, Any]:
    script = (
        Path(__file__).resolve().parents[1]
        / "vendor/deploy-v/skills/cp-2d-liquidity-cash-flow-bridge/scripts"
        / "liquidity_bridge.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script), "--json", json.dumps(inputs)],
        check=True,
        capture_output=True,
        text=True,
    )
    return cast(dict[str, Any], json.loads(completed.stdout))


def test_cp2d_fixture_meets_every_required_register() -> None:
    markdown = liquidity_markdown(liquidity_identity("CP-2D")).decode()
    rules = CONTRACT.completeness_check.load_contract(skill("CP-2D").decode(), "CP-2D")
    assert tuple(rules["registers"]) == REGISTERS
    assert (
        CONTRACT.completeness_check.check(skill("CP-2D").decode(), markdown, "CP-2D")[0]
        == []
    )


def test_liquidity_route_uses_the_catalog_identity_and_is_enabled() -> None:
    assert SELECTION in ADAPTER_ROUTES
    assert MODULES == ("CP-0", "CP-1", "CP-2", "CP-2D")
    assert ROUTE.nodes[-1].module_id == "CP-2D"
    assert {(edge.source, edge.target) for edge in ROUTE.edges} == {
        ("CP-0", "CP-1"),
        ("CP-0", "CP-2"),
        ("CP-1", "CP-2"),
        ("CP-0", "CP-2D"),
        ("CP-1", "CP-2D"),
        ("CP-2", "CP-2D"),
    }
    ident = liquidity_identity("CP-2D")
    assert ident.route_node_id == "RN-FULL_CREDIT_32-LIQUIDITY_REVIEW-04-CP-2D"
    assert {ref.module_id for ref in ident.upstream} == {"CP-0", "CP-1", "CP-2"}


def test_cp0_can_block_the_liquidity_route_before_downstream_work() -> None:
    markdown = liquidity_markdown(
        liquidity_identity("CP-0"), HandoffKnobs(readiness={"CP-1": "BLOCKED"})
    ).decode()
    assert "| CP-1 | Run CP-1 | DO NOT RUN |" in markdown
    assert "| Current handoff | BLOCKED |" in markdown


@pytest.mark.parametrize("module", MODULES)
def test_every_liquidity_handoff_is_vendor_valid_and_source_grounded(
    module: str,
) -> None:
    markdown = liquidity_markdown(liquidity_identity(module)).decode()
    assert CONTRACT.validate_handoff.validate_text(markdown).exit_code == 0
    assert (
        CONTRACT.completeness_check.check(skill(module).decode(), markdown, module)[0]
        == []
    )
    assert QUOTES[module] in markdown
    assert QUOTES[module].encode() in PACK


@pytest.mark.parametrize("register", REGISTERS)
def test_cp2d_refuses_each_missing_register(
    register: str,
) -> None:
    ident = _identity("CP-2D")
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-2D"),
            liquidity_markdown(ident, HandoffKnobs(omit_register=register)),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp2d_refuses_wrong_upstream_lineage() -> None:
    ident = _identity("CP-2D")
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-2D"),
            liquidity_markdown(
                ident, HandoffKnobs(fields=invocation_fields(CONTRACT, wrong))
            ),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_restricted_cp2d_keeps_its_limitation_and_full_scope() -> None:
    ident = _identity("CP-2D")
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-2D"),
        liquidity_markdown(ident, HandoffKnobs(qa_status="Restricted")),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "FULL"
    assert projection.limitation_flags == (LIMITATION,)


def test_cp2d_bridge_reconciles_with_the_vendor_calculator() -> None:
    facts = LIQUIDITY_FACTS
    bridge = _vendor_bridge(facts.bridge_inputs())
    markdown = liquidity_markdown(liquidity_identity("CP-2D")).decode()

    assert facts.inaccessible_revolver == 50
    assert (
        facts.beginning_accessible_liquidity == facts.cash + facts.accessible_revolver
    )
    assert facts.mandatory_uses == 125
    assert (
        bridge["beginning_accessible_liquidity"] == facts.beginning_accessible_liquidity
    )
    assert {
        component["component"]: component["value"] for component in bridge["components"]
    } == {
        key: value
        for key, value in facts.bridge_inputs().items()
        if key not in {"beginning_accessible_liquidity", "period_months"}
    }
    assert bridge["net_movement"] == facts.net_movement
    assert bridge["ending_accessible_liquidity"] == facts.ending_accessible_liquidity
    assert bridge["average_monthly_burn"] == facts.average_monthly_burn
    assert bridge["months_to_empty"] == facts.months_to_empty
    assert bridge["null_components"] == []

    for component, amount in (
        ("Cash", facts.cash),
        ("Restricted cash", facts.restricted_cash),
        ("Revolver commitment", facts.revolver_commitment),
        ("Accessible revolver availability", facts.accessible_revolver),
        ("Cash interest", facts.cash_interest),
        ("Cash taxes", facts.cash_taxes),
        ("Mandatory capex", facts.mandatory_capex),
        ("Debt amortization", facts.debt_amortisation_and_maturities),
        ("Lease payment", facts.other_cash_uses),
        ("Working-capital outflow | Reported outflow", facts.working_capital_movement),
        ("Beginning accessible liquidity", facts.beginning_accessible_liquidity),
        ("Operating cash flow", facts.operating_cash_flow),
        ("Working-capital movement", facts.working_capital_movement),
        ("Cash interest", -facts.cash_interest),
        ("Cash taxes", -facts.cash_taxes),
        ("Mandatory capex", -facts.mandatory_capex),
        ("Debt amortization and maturities", -facts.debt_amortisation_and_maturities),
        ("Other cash uses", -facts.other_cash_uses),
        ("Committed inflows", facts.committed_inflows),
        ("Net cash movement", facts.net_movement),
        ("Average monthly cash burn", f"{facts.average_monthly_burn:.6f}"),
        ("Ending accessible liquidity", facts.ending_accessible_liquidity),
        ("Months to Empty", f"{facts.months_to_empty:.2f} months"),
    ):
        assert f"| {component} | {amount} |" in markdown
    assert f"Do not count the inaccessible {facts.inaccessible_revolver}" in markdown
    assert f"| Cash | {facts.cash} | Accessible |" in markdown
    assert f"| Restricted cash | {facts.restricted_cash} | Inaccessible |" in markdown
    assert (
        f"| Revolver commitment | {facts.revolver_commitment} | Committed |" in markdown
    )


def test_one_changed_fact_updates_the_rendered_bridge() -> None:
    pack_builder = getattr(fixture_module, "liquidity_pack", None)
    assert pack_builder is not None, "the changed facts cannot rebuild their pack"
    facts = LIQUIDITY_FACTS
    changed = replace(facts, operating_cash_flow=facts.operating_cash_flow + 1)
    changed_pack = pack_builder(changed).decode()
    bridge = _vendor_bridge(changed.bridge_inputs())
    markdown = liquidity_markdown(liquidity_identity("CP-2D"), facts=changed).decode()
    assert bridge["net_movement"] == changed.net_movement == -19
    assert (
        bridge["ending_accessible_liquidity"]
        == (changed.ending_accessible_liquidity)
        == 231
    )
    assert bridge["average_monthly_burn"] == changed.average_monthly_burn
    assert bridge["months_to_empty"] == changed.months_to_empty
    assert f"| Operating cash flow | {changed.operating_cash_flow} |" in markdown
    assert (
        f"Twelve-month operating cash flow {changed.operating_cash_flow} "
        f"and working-capital outflow {-changed.working_capital_movement} USD million"
        in changed_pack
    )
    assert f"| Net cash movement | {changed.net_movement} |" in markdown
    assert (
        f"| Ending accessible liquidity | {changed.ending_accessible_liquidity} |"
        in markdown
    )
    assert (
        f"| Average monthly cash burn | {changed.average_monthly_burn:.6f} |"
        in markdown
    )
    assert f"| Months to Empty | {changed.months_to_empty:.2f} months |" in markdown
