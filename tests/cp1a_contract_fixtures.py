"""Deterministic CP-1A transaction pack for the disabled FULL route."""

# ruff: noqa: E501 -- fixture cells mirror the vendored Markdown table schema.

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from canonical_fixtures import (
    AUTHORED,
    BUNDLE,
    CATALOG,
    CONTRACT,
    RUN,
    conforming_rows,
    skill,
)
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256

SELECTION = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
ROUTE = resolve_route(CATALOG, *SELECTION)
REGISTERS = (
    "T2D.1",
    "T2D.10",
    "T2D.11",
    "T2D.2",
    "T2D.3",
    "T2D.4",
    "T2D.5",
    "T2D.6",
    "T2D.7",
    "T2D.8",
    "T2D.9",
    "company_description",
    "conflict_log",
    "credit_translation",
    "downstream_readiness",
    "events_timeline",
    "gaps_ledger",
    "operating_model",
    "ownership_register",
    "revenue_business_mix",
    "source_classification",
    "transaction_summary",
)
MODEL_FIELDS = (
    "issuer_name",
    "sector",
    "country",
    "shareholders",
    "transaction_summary",
    "business_description",
)
LIMITATION = (
    "The worked transaction pack omits customer concentration and the final "
    "legal review of restricted-payment capacity"
)


@dataclass(frozen=True)
class TransactionFacts:
    close_date: str = "2026-06-30"
    purchase_price: int = 900
    debt_funding: int = 500
    equity_funding: int = 400
    revenue: int = 720
    sponsor_interest: int = 100


FACTS = TransactionFacts()


def transaction_pack(facts: TransactionFacts = FACTS) -> bytes:
    return f"""Acme Holdings plc acquisition evidence pack
Sponsor Alpha Fund IV acquired {facts.sponsor_interest}% of Acme Holdings plc on {facts.close_date} for EUR {facts.purchase_price}m.
The sources and uses schedule records EUR {facts.debt_funding}m senior secured debt and EUR {facts.equity_funding}m sponsor equity.
Acme supplies subscription maintenance software to European industrial customers and reported FY2025 revenue of EUR {facts.revenue}m.
The board agreement gives Sponsor Alpha Fund IV appointment control. Monthly lender reporting and quarterly covenant certificates are required.
The pack does not include customer concentration or final legal review of restricted-payment capacity.
""".encode()


PACK = transaction_pack()


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
            edge.source == node.module_id and edge.target == "CP-1A"
            for edge in ROUTE.edges
        )
    )


def cp1a_identity() -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == "CP-1A")
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        "CP-1A",
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module["CP-1A"]["module_name"],
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        direct_upstream(),
    )


def _authored_rows(facts: TransactionFacts) -> dict[str, list[list[str]]]:
    source = "ACME-OM / transaction summary and sources-and-uses"
    transaction = (
        f"Sponsor acquisition closed {facts.close_date} for EUR {facts.purchase_price}m; "
        f"funded by EUR {facts.debt_funding}m debt and EUR {facts.equity_funding}m equity"
    )
    return {
        "company_description": [
            [
                "Acme Holdings plc",
                "Subscription maintenance software supplier",
                "United Kingdom",
                "Business software",
            ]
        ],
        "conflict_log": [
            [
                "Purchase price and sources-and-uses reconcile",
                "ACME-OM and funds-flow schedule",
                "Low",
                "No unresolved numerical conflict",
                "Use documented values",
            ]
        ],
        "credit_translation": [
            [
                transaction,
                "Debt-funded acquisition raises fixed claims while recurring revenue supports service",
                "Leverage and customer concentration require monitoring",
                "Medium",
                LIMITATION,
            ]
        ],
        "downstream_readiness": [
            [
                "CP-2",
                "READY",
                "Customer concentration absent",
                "Stress recurring-revenue durability",
            ],
            [
                "CP-2C",
                "READY",
                "Legal capacity review pending",
                "Separate documented willingness from capacity",
            ],
            ["CP-MODEL", "READY", "No display-field gap", "Import six stable fields"],
            [
                "CP-6",
                "READY",
                "Customer concentration absent",
                "Carry limitation into committee debate",
            ],
        ],
        "events_timeline": [
            [
                facts.close_date,
                "Sponsor acquisition closed",
                "New debt and ownership control",
                "Completed",
                source,
            ]
        ],
        "gaps_ledger": [
            [
                "Customer concentration",
                "Revenue durability",
                "Material",
                "Obtain top-customer schedule",
                "Open",
            ]
        ],
        "operating_model": [
            [
                "Subscription renewals",
                f"FY2025 revenue EUR {facts.revenue}m",
                "FY2025",
                "Documented",
                "Recurring revenue supports debt service",
            ]
        ],
        "ownership_register": [
            [
                "Sponsor Alpha Fund IV",
                "Board appointment control",
                f"{facts.sponsor_interest}%",
                "Control informs governance and financial-policy analysis",
                source,
            ]
        ],
        "revenue_business_mix": [
            [
                "Subscription maintenance software",
                f"EUR {facts.revenue}m",
                "FY2025",
                "Documented",
                "Customer concentration not supplied",
            ]
        ],
        "source_classification": [
            [
                "ACME-OM",
                "transaction document",
                "High",
                "Transaction, business, ownership and operating facts",
                LIMITATION,
            ]
        ],
        "transaction_summary": [
            [
                transaction,
                "Completed",
                "Introduces acquisition debt and sponsor control",
                source,
            ]
        ],
        "T2D.1": [
            [
                "ACME-OM",
                "Acme acquisition memorandum",
                "High",
                "FY2025 / 2026 close",
                "Acme Holdings plc",
                "Transaction, ownership, operating and governance facts",
                LIMITATION,
                "CP-2; CP-2C; CP-6",
            ]
        ],
        "T2D.2": [
            [
                "Sponsor ownership and control",
                f"Sponsor Alpha Fund IV owns {facts.sponsor_interest}% and appoints the board",
                "High",
                source,
                "Concentrated control directs financial policy",
                "Monitor creditor alignment",
                "Fund life not supplied",
            ]
        ],
        "T2D.3": [
            [
                "Lender reporting",
                "Monthly lender reporting and quarterly covenant certificates",
                "Supportive",
                "Frequent reporting improves visibility",
                "Earlier covenant and liquidity monitoring",
                "High",
                source,
                "Basket tracker not supplied",
            ]
        ],
        "T2D.4": [
            [
                "CP-2C-FLAG-001",
                "acquisition",
                transaction,
                "Neutral / Mixed",
                f"EUR {facts.debt_funding}m debt / EUR {facts.equity_funding}m equity",
                "Final legal review pending",
                "Debt raises fixed claims while equity absorbs first loss",
                "Leverage increases but equity contribution aligns incentives",
                "High",
                source,
                LIMITATION,
            ]
        ],
        "T2D.5": [
            [
                "Acquisition funding",
                transaction,
                "Mixed",
                "Debt and equity jointly fund the acquisition",
                "Debt service rises with an equity cushion",
                "High",
                source,
                LIMITATION,
            ]
        ],
        "T2D.6": [
            [
                "Acme acquisition / 2026",
                transaction,
                "Debt and equity",
                "Purchase price documented; pro forma EBITDA excluded",
                "Board control and lender reporting documented",
                f"EUR {facts.debt_funding}m acquisition debt increases leverage",
                "Integration and leverage execution drive liquidity",
                "Track covenant headroom and retention",
                source,
                LIMITATION,
            ]
        ],
        "T2D.7": [
            [
                "Customer concentration",
                "No",
                "Revenue total supplied without customer schedule",
                "Monitoring and PD",
                "Material",
                source,
                "Obtain top-customer schedule",
            ]
        ],
        "T2D.8": [
            [
                "Acquisition appetite",
                "Mixed",
                transaction,
                "Material debt funding raises leverage",
                "Monitor integration and deleveraging",
                "3",
                "High",
                source,
                LIMITATION,
            ]
        ],
        "T2D.9": [
            [
                "Acquisition funding",
                transaction,
                "Debt increases fixed claims; equity provides loss absorption",
                "Medium governance-risk input for PD and refinancing",
                "High",
                source,
                "Monthly lender reporting and equity contribution",
                LIMITATION,
            ]
        ],
        "T2D.10": [
            [
                "CP-6",
                "CP-2C-HANDOFF-CP-6",
                "Sponsor acquisition funding and control",
                "Shapes committee governance debate",
                "Test deleveraging and customer concentration",
                "CP-2C-FLAG-001 / ACME-OM",
                LIMITATION,
            ]
        ],
        "T2D.11": [
            [
                "CP-2C-GAP-001",
                "Final restricted-payment capacity review",
                "Separates legal capacity from willingness",
                "T2D.4 / CP-2C-FLAG-001",
                "Medium",
                "Final legal memorandum",
            ]
        ],
    }


def cp1a_rows(facts: TransactionFacts = FACTS) -> dict[str, list[list[str]]]:
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1A").decode(), "CP-1A")
    rows = _authored_rows(facts)
    for register, spec in rules["registers"].items():
        rows.setdefault(
            register,
            conforming_rows(
                register,
                spec,
                rules,
                lambda column, _row: f"{column}: ACME-OM documented fact",
            ),
        )
    return rows


def model_rows(facts: TransactionFacts = FACTS) -> list[list[str]]:
    values = {
        "issuer_name": "Acme Holdings plc",
        "sector": "Business software",
        "country": "United Kingdom",
        "shareholders": f"Sponsor Alpha Fund IV ({facts.sponsor_interest}%)",
        "transaction_summary": f"Sponsor acquisition closed {facts.close_date} for EUR {facts.purchase_price}m",
        "business_description": "Subscription maintenance software supplier to European industrial customers",
    }
    return [
        [field, values[field], "READY", "ACME-OM", f"ACME-OM / {field}", "2026-09-19"]
        for field in MODEL_FIELDS
    ]


def cp1a_markdown(
    ident: HostIdentity,
    *,
    facts: TransactionFacts = FACTS,
    omit_register: str | None = None,
    fields: dict[str, Any] | None = None,
) -> bytes:
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        **AUTHORED["Restricted"],
        "qa_status": "Restricted",
        "limitation_flags": [LIMITATION],
        "validation_warnings": [],
        "downstream_consumers": ["CP-2", "CP-2C", "CP-MODEL", "CP-6"],
    }
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1A").decode(), "CP-1A")
    rows = cp1a_rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register != omit_register:
            appendix += (
                "#### " + register + "\n\n" + _table(spec["columns"], rows[register])
            )
    appendix += "<!-- table-id: cp1a.cp_model_snapshot_fields -->\n" + _table(
        ("field_id", "value", "status", "source_id", "source_locator", "as_of"),
        model_rows(facts),
    )
    summary = (
        f"Acme's EUR {facts.purchase_price}m sponsor acquisition closed {facts.close_date}; "
        f"EUR {facts.debt_funding}m debt increases fixed claims while EUR {facts.equity_funding}m "
        "equity provides first-loss capital. Recurring software revenue supports service, but "
        "customer concentration and restricted-payment capacity remain open."
    )
    content = {
        "Audit Summary": "Restricted: transaction and operating facts proven; two material diligence items remain.\n\n",
        "Analysis": "### Transaction view\n\n" + summary + "\n\n" + appendix,
        "Evidence Trace": "ACME-OM transaction summary, sources-and-uses, business description and board agreement.\n\n",
        "Source Registry": "ACME-OM / acquisition memorandum and funds-flow schedule.\n\n",
        "Gaps & Conflicts": LIMITATION + ".\n\n",
        "QA Validation": "Restricted: all canonical registers and six CP-MODEL fields present.\n\n",
    }
    body = "".join(
        "## " + heading + "\n\n" + content[heading]
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()
