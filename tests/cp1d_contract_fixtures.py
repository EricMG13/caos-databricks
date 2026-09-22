"""Source-derived CP-1D contract fixture for FULL credit assessment."""

# ruff: noqa: E501 -- fixture cells mirror the vendored Markdown table schema.

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from canonical_fixtures import AUTHORED, BUNDLE, CATALOG, CONTRACT, RUN, skill
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256

SELECTION = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
ROUTE = resolve_route(CATALOG, *SELECTION)
REGISTERS = (
    "T1E.1",
    "T1E.2",
    "T1E.3",
    "T1E.4",
    "T1E.5",
    "T1E.6",
    "T1D.1",
    "T1D.2",
    "T1D.3",
    "T1D.4",
    "T1D.5",
    "T1D.6",
    "T1D.7",
)
LIMITATION = (
    "No rating-agency debt convention or transaction-specific covenant EBITDA "
    "definition was delivered; both restatements are analytical only"
)
SOURCE_QUOTE = "Restructuring expenses | ( 13 )"


@dataclass(frozen=True)
class EarningsFacts:
    reported_operating_income: Decimal = Decimal("4483")
    depreciation: Decimal = Decimal("2790")
    ship_sale_gain: Decimal = Decimal("110")
    restructuring: Decimal = Decimal("13")
    prior_restructuring: tuple[Decimal, Decimal] = (Decimal("21"), Decimal("19"))
    cfo: Decimal = Decimal("6218")
    reported_debt: Decimal = Decimal("27383")
    operating_lease_liability: Decimal = Decimal("1353")


FACTS = EarningsFacts()


def earnings_pack(facts: EarningsFacts = FACTS) -> bytes:
    return f"""Carnival Corporation & plc FY2025 earnings-quality extract
CP-1 recorded reported operating income ${facts.reported_operating_income}m and depreciation and amortization ${facts.depreciation}m.
CP-1 recorded a ${facts.ship_sale_gain}m ship-sale gain removal and a ${facts.restructuring}m restructuring add-back.
Restructuring expenses were ${facts.restructuring}m in 2025, ${facts.prior_restructuring[0]}m in 2024 and ${facts.prior_restructuring[1]}m in 2023.
Net cash provided by operating activities was ${facts.cfo}m in 2025.
Reported fixed and floating debt totalled ${facts.reported_debt}m; current and long-term operating lease liabilities totalled ${facts.operating_lease_liability}m under ASC 842.
""".encode()


PACK = earnings_pack()


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
            edge.source == node.module_id and edge.target == "CP-1D"
            for edge in ROUTE.edges
        )
    )


def cp1d_identity() -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == "CP-1D")
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        "CP-1D",
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module["CP-1D"]["module_name"],
        "CCL",
        "Carnival Corporation & plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        direct_upstream(),
    )


def earnings_calculation(facts: EarningsFacts = FACTS) -> dict[str, Decimal]:
    reported_ebitda = facts.reported_operating_income + facts.depreciation
    adjusted_ebitda = reported_ebitda - facts.ship_sale_gain + facts.restructuring
    quality_ebitda = adjusted_ebitda - facts.restructuring
    adjusted_debt = facts.reported_debt + facts.operating_lease_liability
    return {
        "reported_ebitda": reported_ebitda,
        "adjusted_ebitda": adjusted_ebitda,
        "quality_ebitda": quality_ebitda,
        "cash_conversion": facts.cfo / adjusted_ebitda,
        "cash_gap": adjusted_ebitda - facts.cfo,
        "reported_leverage": facts.reported_debt / reported_ebitda,
        "adjusted_leverage": facts.reported_debt / adjusted_ebitda,
        "quality_leverage": facts.reported_debt / quality_ebitda,
        "adjusted_debt": adjusted_debt,
        "lease_adjusted_leverage": adjusted_debt / quality_ebitda,
    }


def earnings_rows(facts: EarningsFacts = FACTS) -> dict[str, list[list[str]]]:
    calc = earnings_calculation(facts)
    return {
        "T1E.1": [
            [
                "Operating lease liabilities",
                "Operating leases",
                f"${facts.operating_lease_liability}m",
                "FY2025",
                "FY2025 10-K balance sheet and lease note",
                "Audited; current and long-term liabilities disclosed",
                "CCL-LEASE-2025",
            ]
        ],
        "T1E.2": [
            [
                "Operating lease liabilities",
                "Yes — analytical debt-like obligation",
                "Contractual lease cash payments are senior operating commitments",
                f"${facts.operating_lease_liability}m",
                "ASC 842 liability added once to reported debt",
                "Already on balance sheet but excluded from the disclosed debt table",
                "CCL-LEASE-2025",
            ]
        ],
        "T1E.3": [
            [
                "Reported debt",
                f"${facts.reported_debt}m",
                "CP-1 fixed plus floating debt",
                f"${facts.reported_debt}m",
                "CCL-DEBT-2025",
            ],
            [
                "Add operating lease liabilities",
                f"${facts.operating_lease_liability}m",
                "ASC 842 current plus long-term liabilities; no double count",
                f"${calc['adjusted_debt']}m",
                "CCL-LEASE-2025",
            ],
        ],
        "T1E.4": [
            [
                "Debt / quality-adjusted EBITDA",
                f"{calc['quality_leverage']:.2f}x",
                f"{calc['lease_adjusted_leverage']:.2f}x",
                f"{calc['lease_adjusted_leverage'] - calc['quality_leverage']:.2f}x",
                "Adding contractual lease liabilities increases the analytical numerator",
                "Higher leverage reduces refinancing and debt-service headroom",
                "CCL-DEBT-2025; CCL-LEASE-2025; CP-1D-QE",
            ]
        ],
        "T1E.5": [
            [
                "Operating lease liabilities",
                "No rating-agency convention delivered",
                "No agency treatment asserted",
                "Add disclosed ASC 842 liability once",
                "Analytical creditor view; comparison awaits primary agency criteria",
                "CCL-LEASE-2025",
            ]
        ],
        "T1E.6": [
            [
                "Agency convention",
                "Current agency lease and pension adjustment criteria",
                "Convention divergence cannot be measured without primary criteria",
                "Adjusted-debt comparison remains analytical only",
                "Obtain current agency methodology and issuer adjustment schedule",
            ]
        ],
        "T1D.1": [
            [
                "AB-RESTRUCTURING",
                "Restructuring expense added back in CP-1 bridge",
                f"${facts.restructuring}m",
                "FY2025",
                "One-Off Cost",
                "FY2025 10-K segment reconciliation",
                "Excluded from adjusted selling and administrative expense",
                "CCL-RESTRUCTURING-2025",
            ]
        ],
        "T1D.2": [
            [
                "AB-RESTRUCTURING",
                "Recurring-cost test under CP-1D hard rule",
                "Expense recorded in each of FY2023-FY2025",
                f"${facts.restructuring}m",
                f"${facts.restructuring}m expense recorded",
                "Already incurred in FY2025",
                "Audited three-period segment reconciliation",
                f"Prior charges ${facts.prior_restructuring[0]}m and ${facts.prior_restructuring[1]}m",
                "Rejected",
                "CCL-RESTRUCTURING-2023-2025",
            ]
        ],
        "T1D.3": [
            [
                "AB-RESTRUCTURING",
                "Yes",
                "FY2024 and FY2023",
                "Three consecutive annual charges",
                "Recurring",
                "Excluding a repeated cost overstates sustainable earnings",
                "Lower quality-adjusted EBITDA raises analytical leverage",
                "CCL-RESTRUCTURING-2023-2025",
            ]
        ],
        "T1D.4": [
            [
                "Reported EBITDA",
                f"${calc['reported_ebitda']}m",
                "CP-1 reported operating income plus D&A",
                "Supported",
                f"${calc['reported_ebitda']}m",
                "CP1-EBITDA-2025",
            ],
            [
                "Remove ship-sale gain",
                f"-${facts.ship_sale_gain}m",
                "CP-1 recorded non-operating gain normalization",
                "Supported",
                f"${calc['reported_ebitda'] - facts.ship_sale_gain}m",
                "CCL-SHIP-GAIN-2025",
            ],
            [
                "Add restructuring expense",
                f"${facts.restructuring}m",
                "CP-1 recorded add-back",
                "Rejected",
                f"${calc['adjusted_ebitda']}m before rejection; ${calc['quality_ebitda']}m quality-adjusted",
                "CCL-RESTRUCTURING-2023-2025",
            ],
        ],
        "T1D.5": [
            [
                "FY2025",
                f"${calc['adjusted_ebitda']}m",
                f"${facts.cfo}m",
                f"{calc['cash_conversion']:.2%}",
                f"${calc['cash_gap']}m",
                "Cash flow includes working-capital movements and non-cash reconciling items",
                "Conversion below EBITDA limits cash available for capex and debt reduction",
                "Persistent gap can slow deleveraging",
                "CCL-CFO-2025; CP1-EBITDA-2025",
            ]
        ],
        "T1D.6": [
            [
                "Reported debt / EBITDA",
                f"{calc['reported_leverage']:.2f}x",
                f"{calc['adjusted_leverage']:.2f}x",
                f"{calc['quality_leverage']:.2f}x",
                f"{calc['quality_leverage'] - calc['adjusted_leverage']:.2f}x",
                "Rejecting the recurring restructuring add-back modestly raises analytical leverage",
                "CCL-DEBT-2025; CP1-EBITDA-2025; CP-1D-QE",
            ]
        ],
        "T1D.7": [
            [
                "Covenant definition",
                "Transaction-specific permitted EBITDA adjustments",
                "This analysis cannot measure covenant capacity or baskets",
                "Quality-adjusted EBITDA remains analytical, not covenant EBITDA",
                "Obtain executed debt definitions and compliance certificate",
            ]
        ],
    }


def cp1d_markdown(
    ident: HostIdentity,
    *,
    facts: EarningsFacts = FACTS,
    fields: dict[str, Any] | None = None,
    omit_register: str | None = None,
) -> bytes:
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "validation_warnings": [],
        "downstream_consumers": ["CP-2", "CP-2G", "CP-4A"],
        **AUTHORED["Restricted"],
        "limitation_flags": [LIMITATION],
        "qa_status": "Restricted",
    }
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1D").decode(), "CP-1D")
    rows = earnings_rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += (
            "#### " + register + "\n\n" + _table(spec["columns"], rows[register])
        )

    calc = earnings_calculation(facts)
    opening = (
        "Carnival's FY2025 restructuring add-back is not supported as a one-off. "
        f"The ${facts.restructuring}m charge follows ${facts.prior_restructuring[0]}m "
        f"in FY2024 and ${facts.prior_restructuring[1]}m in FY2023, so CP-1D's hard "
        f"recurrence rule removes it and leaves ${calc['quality_ebitda']}m of analytical "
        f"quality-adjusted EBITDA. FY2025 CFO of ${facts.cfo}m converts at "
        f"{calc['cash_conversion']:.1%} of CP-1 adjusted EBITDA. Adding the disclosed "
        f"${facts.operating_lease_liability}m ASC 842 lease liability to "
        f"${facts.reported_debt}m of reported debt raises analytical leverage from "
        f"{calc['quality_leverage']:.2f}x to {calc['lease_adjusted_leverage']:.2f}x. "
        "The strongest counterpoint is the small size of the rejected add-back; an "
        "executed covenant definition and agency criteria are still required before "
        "either restatement can inform covenant or formal rating capacity."
    )
    content = {
        "Audit Summary": "Restricted: recurring add-back rejected; debt restatement analytical.\n\n",
        "Analysis": "### Earnings quality read-through\n\n"
        + opening
        + "\n\n"
        + appendix,
        "Evidence Trace": SOURCE_QUOTE + "; FY2024 $21m; FY2023 $19m.\n\n",
        "Source Registry": "Carnival Corporation & plc FY2025 Form 10-K; CP-1 and CP-1B handoffs.\n\n",
        "Gaps & Conflicts": LIMITATION + ".\n\n",
        "QA Validation": "Restricted: complete registers and reconciled arithmetic.\n\n",
    }
    body = "".join(
        "## " + heading + "\n\n" + content[heading]
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()
