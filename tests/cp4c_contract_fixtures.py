"""Source-derived CP-4C contract fixture for FULL credit assessment."""

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
    "T4E.1",
    "T4E.10",
    "T4E.2",
    "T4E.3",
    "T4E.4",
    "T4E.5",
    "T4E.6",
    "T4E.7",
    "T4E.8",
    "T4E.9",
)
LIMITATION = (
    "The worked restructuring pack proves the analytical contract but omits a "
    "final court timetable and local-law opinions on class composition and cramdown"
)


@dataclass(frozen=True)
class RestructuringFacts:
    distress_date: str = "2026-07-26"
    rcf: float = 50.0
    tlb: float = 300.0
    unsecured: float = 200.0
    low_ev: float = 200.0
    base_ev: float = 400.0
    high_ev: float = 700.0


FACTS = RestructuringFacts()


def restructuring_pack(facts: RestructuringFacts = FACTS) -> bytes:
    return f"""Acme Holdings plc restructuring evidence pack
On {facts.distress_date}, Acme missed a scheduled interest payment under the senior secured term loan.
The English-law capital structure comprises a super-senior RCF claim of EUR {facts.rcf:.0f}m, senior secured TLB claim of EUR {facts.tlb:.0f}m and senior unsecured notes claim of EUR {facts.unsecured:.0f}m.
The supplied independent valuation cases are EUR {facts.low_ev:.0f}m low, EUR {facts.base_ev:.0f}m base and EUR {facts.high_ev:.0f}m high as of {facts.distress_date}.
The documented path is an English restructuring plan with class votes and possible cross-class cramdown.
No final court timetable or local-law opinions on class composition and cramdown were delivered.
""".encode()


PACK = restructuring_pack()

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-4c-restructuring-fulcrum/scripts/recovery_waterfall.py"
)
_SENSITIVITY = cast(
    Callable[
        [list[dict[str, Any]], list[dict[str, Any]], tuple[Any, ...]], dict[str, Any]
    ],
    runpy.run_path(str(_SCRIPT))["sensitivity"],
)
_WATERFALL = cast(
    Callable[[float, list[dict[str, Any]], tuple[Any, ...]], dict[str, Any]],
    runpy.run_path(str(_SCRIPT))["waterfall"],
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
            edge.source == node.module_id and edge.target == "CP-4C"
            for edge in ROUTE.edges
        )
    )


def cp4c_identity() -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == "CP-4C")
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        "CP-4C",
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module["CP-4C"]["module_name"],
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        direct_upstream(),
    )


def claims(facts: RestructuringFacts = FACTS) -> list[dict[str, Any]]:
    return [
        {"claim_id": "RCF", "class": "Super Senior", "amount": facts.rcf},
        {"claim_id": "TLB", "class": "Senior Secured", "amount": facts.tlb},
        {"claim_id": "SUN", "class": "Senior Unsecured", "amount": facts.unsecured},
    ]


def recovery_result(facts: RestructuringFacts = FACTS) -> dict[str, Any]:
    cases = [
        {"label": "LOW", "enterprise_value": facts.low_ev},
        {"label": "BASE", "enterprise_value": facts.base_ev},
        {"label": "HIGH", "enterprise_value": facts.high_ev},
    ]
    return {
        "sensitivity": _SENSITIVITY(claims(facts), cases, ()),
        "cases": {
            str(case["label"]): _WATERFALL(
                cast(float, case["enterprise_value"]), claims(facts), ()
            )
            for case in cases
        },
    }


def restructuring_rows(
    facts: RestructuringFacts = FACTS,
) -> dict[str, list[list[str]]]:
    result = recovery_result(facts)
    case_results = result["cases"]
    recovery_rows: list[list[str]] = []
    allocation_rows: list[list[str]] = []
    for label, case in case_results.items():
        allocation_rows.append(
            [
                label,
                "Acme Holdings plc",
                f"EUR {float(case['enterprise_value']):.0f}m",
                "RCF then TLB then SUN",
                "Script-owned waterfall",
                f"EUR {float(case['residual_to_equity']):.0f}m",
                "ACME-CLAIMS; ENGLISH-LAW-PRIORITY",
            ]
        )
        for row in case["claims"]:
            recovery_rows.append(
                [
                    label,
                    f"{row['class']} / {row['claim_id']}",
                    f"EUR {float(row['amount']):.0f}m",
                    f"EUR {float(row['recovered']):.0f}m value",
                    f"{float(row['recovery_pct']):.1%}",
                    "At plan effective date",
                    "EUR",
                ]
            )
    sensitivity = result["sensitivity"]
    return {
        "T4E.1": [
            [
                "Missed scheduled TLB interest payment",
                f"Facility notice / {facts.distress_date}",
                "Acme Holdings plc / senior secured TLB",
                "England and Wales",
                "Distress gate met",
                "Cure and acceleration status remain subject to legal advice",
            ]
        ],
        "T4E.10": [
            [
                "Local-law class and cramdown opinion",
                "English restructuring plan / all creditor classes",
                "Court path and class composition remain provisional",
                "Final counsel opinion and court timetable",
            ]
        ],
        "T4E.2": [
            [
                "RCF",
                "Acme Holdings plc",
                f"EUR {facts.rcf:.0f}m principal",
                "EUR",
                "Super-senior secured / parent guarantee",
                "First",
                "Undisputed in supplied claims schedule",
                "ACME-CLAIMS-RCF",
            ],
            [
                "TLB",
                "Acme Holdings plc",
                f"EUR {facts.tlb:.0f}m principal",
                "EUR",
                "Senior secured / parent guarantee",
                "Second",
                "Undisputed in supplied claims schedule",
                "ACME-CLAIMS-TLB",
            ],
            [
                "SUN",
                "Acme Holdings plc",
                f"EUR {facts.unsecured:.0f}m principal",
                "EUR",
                "Senior unsecured / parent claim",
                "Third",
                "Undisputed in supplied claims schedule",
                "ACME-CLAIMS-SUN",
            ],
        ],
        "T4E.3": [
            [
                label,
                facts.distress_date,
                "Independent enterprise value",
                "Supplied valuation case",
                f"EUR {ev:.0f}m",
                "ACME-VALUATION",
                "No alternate DCF supplied",
            ]
            for label, ev in (
                ("LOW", facts.low_ev),
                ("BASE", facts.base_ev),
                ("HIGH", facts.high_ev),
            )
        ],
        "T4E.4": [
            [
                "English restructuring plan",
                "Part 26A / England and Wales",
                "Class votes plus court sanction",
                "No new-money amount in supplied pack",
                "Value distributed by priority and sanctioned compromise",
                "Convening hearing, votes, sanction, effective date",
                "Class composition and cramdown opinion outstanding",
                "Credible but legally provisional",
            ]
        ],
        "T4E.5": allocation_rows,
        "T4E.6": [
            [
                f"EUR {facts.low_ev:.0f}m-{facts.high_ev:.0f}m",
                "RCF in every case; TLB at base/high; SUN only base/high",
                "TLB at low; SUN at base; none at high",
                "Moves from TLB (low) to SUN (base); all classes whole at high",
                str(sensitivity["note"]),
            ]
        ],
        "T4E.7": recovery_rows,
        "T4E.8": [
            [
                "Cross-class cramdown",
                "Dissenting impaired creditor class",
                "Part 26A statutory tests, class vote and court sanction",
                "Documented proposed English restructuring plan",
                "Plan may bind a dissenting class if statutory tests are met",
            ]
        ],
        "T4E.9": [
            [
                "Convening through sanction hearings",
                "After filing / final date not supplied",
                "Proposed plan path; court timetable pending",
                "Delays extend liquidity and execution risk",
                "CP-6",
            ]
        ],
    }


def cp4c_markdown(
    ident: HostIdentity,
    *,
    facts: RestructuringFacts = FACTS,
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
    rules = CONTRACT.completeness_check.load_contract(skill("CP-4C").decode(), "CP-4C")
    rows = restructuring_rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += (
            "#### " + register + "\n\n" + _table(spec["columns"], rows[register])
        )

    result = recovery_result(facts)
    opening = (
        f"Acme crossed the distress gate on {facts.distress_date} through a documented "
        "missed TLB interest payment. The supplied English-law claims schedule ranks "
        f"a EUR {facts.rcf:.0f}m super-senior RCF, EUR {facts.tlb:.0f}m secured TLB and "
        f"EUR {facts.unsecured:.0f}m unsecured notes. The shipped waterfall shows the "
        f"fulcrum moving from TLB at EUR {facts.low_ev:.0f}m EV to unsecured notes at "
        f"EUR {facts.base_ev:.0f}m; at EUR {facts.high_ev:.0f}m every debt class is whole "
        f"and EUR {float(result['cases']['HIGH']['residual_to_equity']):.0f}m reaches "
        "equity. That movement is the central creditor result, not a single recovery "
        "point. An English restructuring plan is documented, but final class-composition "
        "and cramdown opinions plus the court timetable are required before the path or "
        "timing can be treated as legally settled."
    )
    content = {
        "Audit Summary": "Restricted: distress and waterfall proven; legal execution provisional.\n\n",
        "Analysis": "### Restructuring view\n\n" + opening + "\n\n" + appendix,
        "Evidence Trace": f"Missed TLB interest payment on {facts.distress_date}; supplied claims and valuation pack.\n\n",
        "Source Registry": "Acme facility notice, claims schedule, valuation pack and proposed English plan.\n\n",
        "Gaps & Conflicts": LIMITATION + ".\n\n",
        "QA Validation": "Restricted: script-owned recoveries; legal path remains provisional.\n\n",
    }
    body = "".join(
        "## " + heading + "\n\n" + content[heading]
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()
