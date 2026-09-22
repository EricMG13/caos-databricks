"""Source-derived CP-2E contract fixture for FULL credit assessment."""

# ruff: noqa: E501 -- fixture cells mirror the vendored Markdown table schema.

from __future__ import annotations

import hashlib
import runpy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from canonical_fixtures import AUTHORED, BUNDLE, CATALOG, CONTRACT, RUN, skill
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256

SELECTION = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
ROUTE = resolve_route(CATALOG, *SELECTION)
REGISTERS = (
    "T2G.1",
    "T2G.2",
    "T2G.3",
    "T2G.4",
    "T2G.5",
    "T2G.6",
    "T2G.7",
    "T2G.8",
    "T2F.1",
    "T2F.2",
    "T2F.3",
    "T2F.4",
    "T2F.5",
    "T2F.6",
    "T2F.7",
    "T2F.8",
    "T2F.9",
)
LIMITATION = (
    "The annual report supplies market-risk sensitivities but not current derivative "
    "terms, fuel pass-through economics or independently assured transition forecasts"
)
SOURCE_QUOTE = (
    "Based on a 100 basis point change in the market interest rates, our annual "
    "interest expense on floating rate debt would change by approximately $42 million."
)


@dataclass(frozen=True)
class MacroFacts:
    total_debt: float = 27383.0
    fixed_debt: float = 23229.0
    floating_debt: float = 4154.0
    hedged_floating_debt: float = 0.0
    newbuild_commitment: float = 8400.0
    fx_move: float = 0.01
    fuel_cost: float = 1807.0
    fuel_move: float = 0.10
    ets_cost: float = 91.0


FACTS = MacroFacts()


def macro_pack(facts: MacroFacts = FACTS) -> bytes:
    return f"""Carnival Corporation & plc FY2025 Form 10-K market-risk extract
At November 30, 2025 fixed-rate debt carrying value was ${facts.fixed_debt:.0f} million, floating-rate debt was ${facts.floating_debt:.0f} million and total debt was ${facts.total_debt:.0f} million.
As of November 30, 2025 there were no remaining interest-rate swaps; the $1.0 billion SOFR swaps were terminated in July 2025.
Based on a 100 basis point change in market interest rates, annual interest expense on floating-rate debt would change by approximately ${facts.floating_debt * 0.01:.0f} million.
Euro-denominated newbuild commitments for non-euro functional-currency brands were ${facts.newbuild_commitment:.0f} million; a 1% EUR/USD move changes remaining cost by ${facts.newbuild_commitment * facts.fx_move:.0f} million.
FY2025 segment fuel expense was ${facts.fuel_cost:.0f} million; a 10% fuel-cost stress is an analyst scenario, not management guidance.
EU ETS cost was ${facts.ets_cost:.0f} million in 2025 and all in-scope emissions apply in 2026.
""".encode()


PACK = macro_pack()

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-2e-macro-fx-hedging-sensitivity/scripts/rate_fx_sensitivity.py"
)
_COMPUTE = cast(
    Callable[[dict[str, Any]], dict[str, Any]],
    runpy.run_path(str(_SCRIPT))["compute"],
)


def direct_upstream() -> tuple[UpstreamRef, ...]:
    return tuple(
        UpstreamRef(
            node.route_node_id,
            node.module_id,
            RUN,
            "FY2025",
            hashlib.sha256(node.module_id.encode()).hexdigest(),
        )
        for node in ROUTE.nodes
        if any(
            edge.source == node.module_id and edge.target == "CP-2E"
            for edge in ROUTE.edges
        )
    )


def cp2e_identity() -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == "CP-2E")
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        "CP-2E",
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module["CP-2E"]["module_name"],
        "CCL",
        "Carnival Corporation & plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        direct_upstream(),
    )


def sensitivity_result(facts: MacroFacts = FACTS) -> dict[str, Any]:
    return _COMPUTE(
        {
            "gross_floating_rate_debt": facts.floating_debt,
            "hedged_floating_rate_debt": facts.hedged_floating_debt,
            "total_debt": facts.total_debt,
            "fx_exposures": [
                {
                    "currency": "EUR",
                    "net_exposure": facts.newbuild_commitment,
                    "adverse_move_pct": facts.fx_move,
                }
            ],
            "cost_exposures": [
                {
                    "input": "fuel",
                    "annual_spend": facts.fuel_cost,
                    "adverse_move_pct": facts.fuel_move,
                }
            ],
        }
    )


def macro_rows(facts: MacroFacts = FACTS) -> dict[str, list[list[str]]]:
    result = sensitivity_result(facts)
    rate_impact = float(result["cash_interest_impact_plus_100bps"])
    fx_impact = float(result["fx_sensitivity"][0]["impact"])
    fuel_impact = float(result["cost_sensitivity"][0]["impact"])
    unhedged = float(result["unhedged_floating_rate_debt"])
    unhedged_pct = float(result["unhedged_debt_percentage"])
    return {
        "T2G.1": [
            [
                "Carnival Corporation & plc FY2025 Form 10-K",
                "Audited financial statements; issuer-authored risk disclosures",
                "Transition targets and future costs are issuer estimates",
                "Ready with Limitations",
            ]
        ],
        "T2G.2": [
            [
                "EU ETS and maritime transition costs",
                f"FY2025 10-K / 30 Nov 2025; ${facts.ets_cost:.0f}m ETS cost",
                "Emission allowances and compliant fuels raise operating costs and future capex",
                "Fuel expense, operating cash flow and fleet capex",
                "CCL-10K-ETS-2025",
            ]
        ],
        "T2G.3": [
            [
                "Crew and labour cost escalation",
                "FY2025 10-K risk factors / 30 Nov 2025",
                "Higher labour costs reduce cruise operating margin and cash generation",
                "Ongoing",
                "CCL-10K-LABOUR-RISK",
            ]
        ],
        "T2G.4": [
            [
                "Maritime emissions regulation",
                "Material — Quantified",
                f"EU ETS cost ${facts.ets_cost:.0f}m in 2025; full in-scope emissions begin in 2026",
                "2026 full phase-in and later IMO rulemaking",
                "CCL-10K-ETS-2025",
            ]
        ],
        "T2G.5": [
            [
                "No sustainability-linked instrument identified in the delivered 10-K",
                "No KPI term identified",
                "No SPT or test date identified",
                "No ratchet",
                "No bps term",
                "No symmetry term",
                "No contractual spread protection established",
                "No spread effect claimed",
                "CCL-10K-DEBT-TERMS",
            ]
        ],
        "T2G.6": [
            [
                "Emission allowance and compliant-fuel cost",
                "Adverse",
                f"Quantified historical ETS cost ${facts.ets_cost:.0f}m; future effect directional",
                "2026 full ETS scope and later fleet funding",
                "CCL-10K-ETS-2025",
            ]
        ],
        "T2G.7": [
            [
                "Maritime transition cost",
                "Regulation raises fuel, allowance and fleet-investment cash requirements",
                "Lower free cash flow can reduce debt-service and refinancing capacity",
                "Moderate — historical cost sourced, final future rules unsettled",
                "CCL-10K-ETS-2025",
            ]
        ],
        "T2G.8": [
            [
                "Transition forecast assurance",
                "Independently assured cost forecast and final IMO requirements",
                "Future cash and fleet-capex burden cannot be sized from historical cost alone",
                "Transition implication remains directional beyond the 2025 ETS cost",
                "Obtain assured forecast and final rule text when issued",
            ]
        ],
        "T2F.1": [
            [
                "ccl-fy2025-10k",
                "Carnival Corporation & plc FY2025 Form 10-K",
                "Filed annual report with audited financial statements",
                "FY2025",
                "Carnival Corporation & plc consolidated",
                "Debt mix, swaps, rate sensitivity, FX, fuel and transition costs",
                "Exact current derivative terms and fuel pass-through are not disclosed",
                "CP-6 and monitoring",
            ]
        ],
        "T2F.2": [
            [
                "Consolidated fixed-rate debt",
                f"${facts.fixed_debt:.0f}m",
                "Fixed-rate debt",
                "Fixed coupons by instrument",
                "Portfolio amount",
                "USD and EUR",
                "Multiple",
                "No rate hedge required for fixed-rate classification",
                "FY2025 10-K lines 1125-1128",
                "Limits near-term base-rate sensitivity",
            ],
            [
                "Consolidated floating-rate debt",
                f"${facts.floating_debt:.0f}m",
                "Floating-rate debt",
                "SOFR and EURIBOR",
                "Instrument margins vary",
                "USD and EUR",
                "Multiple",
                "Unhedged at 30 Nov 2025",
                "FY2025 10-K lines 1125-1146",
                "Base-rate moves transmit to annual cash interest",
            ],
        ],
        "T2F.3": [
            [
                "Interest-rate swap",
                "$0m remaining",
                "Consolidated floating-rate debt",
                "Prior receive-floating/pay-fixed swaps",
                "Terminated July 2025",
                "Expired",
                "FY2025 10-K line 1146",
                "The prior $1.0bn notional no longer protects FY2025 year-end exposure",
            ]
        ],
        "T2F.4": [
            [
                "Total debt",
                f"${facts.total_debt:.0f}m",
                "10-K fixed plus floating carrying values",
                "Reported",
                "Denominator for unhedged debt percentage",
                "FY2025 10-K lines 1125-1128",
            ],
            [
                "Gross floating-rate debt",
                f"${facts.floating_debt:.0f}m",
                "10-K carrying value",
                "Reported",
                "Exposed to SOFR and EURIBOR moves",
                "FY2025 10-K lines 1125-1128",
            ],
            [
                "Hedged floating-rate debt",
                "$0m",
                "No remaining interest-rate swaps",
                "Reported",
                "No year-end derivative offset to base-rate sensitivity",
                "FY2025 10-K line 1146",
            ],
            [
                "Unhedged floating-rate debt",
                f"${unhedged:.0f}m",
                "Gross floating debt less hedged floating debt",
                "Calculated",
                "A 100bp move affects annual cash interest",
                "rate_fx_sensitivity.py from 10-K inputs",
            ],
            [
                "Unhedged debt percentage",
                f"{unhedged_pct:.4f}",
                "Unhedged floating debt divided by total debt",
                "Calculated",
                f"About {unhedged_pct:.1%} of debt remains base-rate sensitive",
                "rate_fx_sensitivity.py from 10-K inputs",
            ],
        ],
        "T2F.5": [
            [
                "+100 bps base-rate sensitivity",
                "Unhedged floating-rate debt x 1.00%",
                f"${unhedged:.0f}m unhedged floating-rate debt",
                f"${rate_impact:.2f}m annual cash interest",
                "Reduces annual free cash flow and liquidity dollar-for-dollar before tax effects",
                f"Calculated; reconciles to issuer's approximately ${rate_impact:.0f}m disclosure",
                "rate_fx_sensitivity.py; FY2025 10-K line 687",
            ]
        ],
        "T2F.6": [
            [
                "Transaction exposure — euro newbuild commitments",
                "Cruise revenue across USD, EUR, GBP and AUD operations",
                "Euro-denominated shipbuilding cost for non-euro brands",
                "EUR commitment; brand functional currencies include USD",
                "Partial",
                f"${facts.newbuild_commitment:.0f}m commitment; 1% move equals ${fx_impact:.0f}m",
                "EUR appreciation raises remaining functional-currency ship cost",
                "Higher capex use can reduce liquidity available for debt service",
                "FY2025 10-K lines 679 and 1159",
                "Case-by-case derivatives are described but current terms are not supplied",
            ]
        ],
        "T2F.7": [
            [
                "Fuel price and emission-allowance cost",
                f"FY2025 fuel expense ${facts.fuel_cost:.0f}m",
                "Efficiency and consumption management; no contractual pass-through established",
                f"10% analyst stress equals ${fuel_impact:.1f}m before mitigants",
                "A price increase raises ship operating cost unless consumption falls",
                "Lower margin and free cash flow reduce deleveraging capacity",
                "rate_fx_sensitivity.py; FY2025 10-K segment and fuel-risk disclosures",
                "Scenario is analytical and excludes demand response and efficiency offsets",
            ]
        ],
        "T2F.8": [
            [
                "Base rates",
                f"${facts.floating_debt:.0f}m floating debt and no remaining swaps",
                "Higher SOFR or EURIBOR increases cash interest",
                f"${rate_impact:.2f}m annual use per 100bp",
                "Less retained cash for maturities and refinancing",
                "Floating debt, base rates and any new swaps",
                "FY2025 10-K lines 687 and 1146",
            ],
            [
                "EUR newbuild FX",
                f"${facts.newbuild_commitment:.0f}m commitment; ${fx_impact:.0f}m per 1% move",
                "EUR appreciation raises non-euro brand ship cost",
                "Higher capex funding need",
                "Can compete with deleveraging and refinancing cash",
                "EUR/USD and disclosed hedge coverage",
                "FY2025 10-K line 679",
            ],
            [
                "Fuel and transition cost",
                f"${facts.fuel_cost:.0f}m fuel expense and ${facts.ets_cost:.0f}m ETS cost",
                "Fuel prices and emission rules raise operating cost",
                f"${fuel_impact:.1f}m gross 10% fuel stress before mitigants",
                "Lower free cash flow can weaken refinancing flexibility",
                "Fuel cost per tonne, consumption and ETS phase-in",
                "FY2025 10-K lines 539, 568-570 and segment table",
            ],
        ],
        "T2F.9": [
            [
                "Current hedge terms",
                "Current FX derivative notionals, strikes, maturities and covered commitments",
                "The effective share of the euro newbuild exposure cannot be established",
                "T2F.3 and T2F.6 mitigation remain partial",
                "Obtain current derivative schedule and confirmations",
                "CP-6",
            ],
            [
                "Fuel pass-through economics",
                "Contractual or demonstrated price-recovery timing and demand elasticity",
                "Gross fuel stress cannot be converted into a net cash-flow forecast",
                "T2F.7 and T2F.8 remain directional after the gross scenario",
                "Obtain procurement, surcharge and booking-price evidence",
                "CP-2G and CP-6",
            ],
        ],
    }


def cp2e_markdown(
    ident: HostIdentity,
    *,
    facts: MacroFacts = FACTS,
    fields: dict[str, Any] | None = None,
    omit_register: str | None = None,
) -> bytes:
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "validation_warnings": [],
        "downstream_consumers": ["CP-6"],
        **AUTHORED["Restricted"],
        "limitation_flags": [LIMITATION],
        "qa_status": "Restricted",
    }
    rules = CONTRACT.completeness_check.load_contract(skill("CP-2E").decode(), "CP-2E")
    rows = macro_rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += (
            "#### " + register + "\n\n" + _table(spec["columns"], rows[register])
        )

    result = sensitivity_result(facts)
    fixed_pct = facts.fixed_debt / facts.total_debt
    opening = (
        "Carnival has moderate, source-bounded macro sensitivity. At 30 November "
        f"2025, ${facts.floating_debt:.0f}m of ${facts.total_debt:.0f}m debt was "
        "floating and no interest-rate swaps remained, so a 100bp move consumes "
        f"${float(result['cash_interest_impact_plus_100bps']):.2f}m of annual cash. "
        f"The ${facts.newbuild_commitment:.0f}m euro newbuild commitment moves "
        f"${float(result['fx_sensitivity'][0]['impact']):.0f}m per 1% EUR/USD change, "
        "while current derivative coverage is not disclosed. Fuel and emissions "
        f"costs are material: FY2025 fuel expense was ${facts.fuel_cost:.0f}m and "
        f"EU ETS cost was ${facts.ets_cost:.0f}m. The strongest counterpoint is the "
        f"{fixed_pct:.0%} fixed-rate debt mix and operational natural offsets; current hedge terms "
        "and pass-through evidence would be needed for that mitigation to support a "
        "higher-confidence conclusion."
    )
    content = {
        "Audit Summary": "Restricted: filed source supports sensitivities but not every mitigation term.\n\n",
        "Analysis": "### Macro and hedging view\n\n" + opening + "\n\n" + appendix,
        "Evidence Trace": SOURCE_QUOTE + "\n\n",
        "Source Registry": "Carnival Corporation & plc FY2025 Form 10-K.\n\n",
        "Gaps & Conflicts": LIMITATION + ".\n\n",
        "QA Validation": "Restricted: complete registers with source-bounded limitations.\n\n",
    }
    body = "".join(
        "## " + heading + "\n\n" + content[heading]
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()
