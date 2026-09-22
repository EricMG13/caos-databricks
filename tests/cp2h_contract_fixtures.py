"""Source-derived CP-2H contract fixture for FULL credit assessment."""

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
    "T2R.1",
    "T2R.10",
    "T2R.2",
    "T2R.3",
    "T2R.4",
    "T2R.5",
    "T2R.6",
    "T2R.7",
    "T2R.8",
    "T2R.9",
)
LIMITATION = (
    "Agency-issued rating actions and current criteria were not delivered; "
    "issuer disclosure is secondary evidence and the migration case is provisional"
)


@dataclass(frozen=True)
class RatingFacts:
    rating: str = "BB"
    outlook: str = "Negative"
    effective_date: str = "2025-12-31"
    trigger_threshold: float = 5.0
    base_leverage: float = 3.5
    downside_leverage: float = 5.4
    instrument: str = "Senior secured notes 2029"
    liquidity: int = 150


FACTS = RatingFacts()


def rating_pack(facts: RatingFacts = FACTS) -> bytes:
    return f"""Acme Holdings plc FY2025 annual report ratings extract
Issuer disclosure reports S&P corporate rating {facts.rating}, outlook {facts.outlook}, effective {facts.effective_date}
Issuer disclosure reports an S&P downside trigger above {facts.trigger_threshold:.1f}x debt to EBITDA
CP-2G FY2026 base debt to EBITDA {facts.base_leverage:.1f}x and downside debt to EBITDA {facts.downside_leverage:.1f}x
CP-1 reports {facts.liquidity} USD million liquidity at FY2025
Rated instrument {facts.instrument}
No agency-issued action, criteria publication or recovery-rating report was delivered
""".encode()


PACK = rating_pack()
QUOTE = "Issuer disclosure reports S&P corporate rating BB, outlook Negative"

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/scripts/covenant_headroom.py"
)
_TRIGGER_HEADROOM = cast(
    Callable[[dict[str, Any]], dict[str, Any]],
    runpy.run_path(str(_SCRIPT))["trigger_headroom"],
)


def direct_upstream(*, include_cp1d: bool = True) -> tuple[UpstreamRef, ...]:
    return tuple(
        UpstreamRef(
            node.route_node_id,
            node.module_id,
            RUN,
            "FY2025",
            hashlib.sha256(node.module_id.encode()).hexdigest(),
        )
        for node in ROUTE.nodes
        if (include_cp1d or node.module_id != "CP-1D")
        and any(
            edge.source == node.module_id and edge.target == "CP-2H"
            for edge in ROUTE.edges
        )
    )


def cp2h_identity(*, include_cp1d: bool = True) -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == "CP-2H")
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        "CP-2H",
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module["CP-2H"]["module_name"],
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        direct_upstream(include_cp1d=include_cp1d),
    )


def trigger_result(facts: RatingFacts = FACTS) -> dict[str, Any]:
    return _TRIGGER_HEADROOM(
        {
            "trigger": "Debt to EBITDA downside trigger",
            "trigger_direction": "max-ratio",
            "threshold": facts.trigger_threshold,
            "cases": [
                {"case": "BASE", "period": "FY2026", "value": facts.base_leverage},
                {
                    "case": "DOWNSIDE",
                    "period": "FY2026",
                    "value": facts.downside_leverage,
                },
            ],
        }
    )


def _headroom_rows(facts: RatingFacts) -> list[list[str]]:
    result = trigger_result(facts)
    return [
        [
            "S&P",
            "Issuer",
            "max-ratio",
            "Debt to EBITDA",
            f"{facts.trigger_threshold:.1f}x",
            f"{row['case']} / {row['period']} {float(row['value']):.1f}x",
            f"{float(row['binding_headroom']):.1f}x",
            str(row["status"]),
        ]
        for row in result["periods"]
    ]


def rating_rows(facts: RatingFacts = FACTS) -> dict[str, list[list[str]]]:
    headroom = trigger_result(facts)
    base, downside = headroom["periods"]
    return {
        "T2R.1": [
            [
                "S&P",
                "Acme Holdings plc / issuer",
                facts.rating,
                facts.outlook,
                facts.effective_date,
                "FY2025 annual report",
                "ratings extract line 2",
                "Issuer-reported; agency primary pending",
            ]
        ],
        "T2R.2": [
            [
                "S&P",
                "Corporate methodology named by issuer disclosure",
                facts.effective_date,
                "Acme Holdings plc and issuer rating",
                "Agency publication was not delivered; applicability is provisional",
            ]
        ],
        "T2R.3": [
            [
                "Debt to EBITDA",
                "CP-2G debt to EBITDA",
                "Issuer-reported agency adjustments were not delivered",
                "FY2026 / consolidated issuer",
                "debt divided by EBITDA",
                "CP-2G-FY2026-LEVERAGE",
            ]
        ],
        "T2R.4": _headroom_rows(facts),
        "T2R.5": [
            [
                "S&P",
                "Liquidity",
                f"CP-1 reports {facts.liquidity} USD million liquidity",
                "neutral",
                "Liquidity is sourced but no agency assessment was delivered",
                "ratings extract line 5",
            ]
        ],
        "T2R.6": [
            [
                "S&P",
                "BASE",
                "within_current_range",
                "FY2026 review",
                f"Debt to EBITDA remains {facts.base_leverage:.1f}x",
                "Low — issuer-reported trigger only",
                "CP-2G-FY2026-LEVERAGE; ratings extract line 3",
            ],
            [
                "S&P",
                "DOWNSIDE",
                "trigger_breach",
                "FY2026 review",
                f"Debt to EBITDA reaches {facts.downside_leverage:.1f}x",
                "Low — point-in-time breach is not an agency action",
                "CP-2G-FY2026-LEVERAGE; ratings extract line 3",
            ],
        ],
        "T2R.7": [
            [
                "Primary-evidence gap",
                f"Issuer reports S&P {facts.rating}; no second-agency position supplied",
                "Issuer disclosure cannot establish current agency methodology or timing",
                "A later agency action could supersede the issuer-reported position",
            ]
        ],
        "T2R.8": [
            [
                facts.instrument,
                f"Linked to issuer-reported S&P {facts.rating}",
                "Senior secured status in issuer disclosure; no recovery-rating report",
                "Negative if the issuer trigger remains breached",
                "Notching and recovery direction remain provisional",
            ]
        ],
        "T2R.9": [
            [
                "Debt to EBITDA downside trigger",
                (
                    f"Base {float(base['binding_headroom']):.1f}x; "
                    f"downside {float(downside['binding_headroom']):.1f}x"
                ),
                "Quarterly debt to EBITDA",
                "Next results or agency action",
                "CP-3, CP-3C, CP-3D, CP-6",
            ]
        ],
        "T2R.10": [
            [
                "Agency-issued action, current criteria and recovery-rating report",
                "S&P issuer trigger and instrument notching",
                "Formal rating posture, methodology fit and notching cannot be confirmed",
                "Supply the dated agency action, criteria and instrument report",
            ]
        ],
    }


def cp2h_markdown(
    ident: HostIdentity,
    *,
    facts: RatingFacts = FACTS,
    fields: dict[str, Any] | None = None,
    omit_register: str | None = None,
) -> bytes:
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "validation_warnings": [],
        "downstream_consumers": ["CP-3", "CP-3C", "CP-3D", "CP-6"],
        **AUTHORED["Restricted"],
        "limitation_flags": [LIMITATION],
        "qa_status": "Restricted",
    }
    rules = CONTRACT.completeness_check.load_contract(skill("CP-2H").decode(), "CP-2H")
    rows = rating_rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += (
            "#### " + register + "\n\n" + _table(spec["columns"], rows[register])
        )

    opening = (
        f"Acme remains source-limited rather than agency-confirmed. Its FY2025 annual "
        f"report says S&P rated the issuer {facts.rating} with a {facts.outlook} outlook, "
        "but no agency action or current criteria publication was delivered. That makes "
        "the rating secondary evidence, not a formal action asserted by this analysis. "
        f"The issuer-reported {facts.trigger_threshold:.1f}x debt-to-EBITDA trigger leaves "
        f"{facts.trigger_threshold - facts.base_leverage:.1f}x base-case headroom, while "
        f"the {facts.downside_leverage:.1f}x downside is a point-in-time breach and not "
        "automatically a sustained trigger. The nearest review catalyst is the next "
        "results release or a dated agency action. Instrument notching and recovery "
        "direction remain provisional until primary agency evidence is supplied."
    )
    content = {
        "Audit Summary": "Restricted: secondary rating evidence only.\n\n",
        "Analysis": "### Rating transition view\n\n" + opening + "\n\n" + appendix,
        "Evidence Trace": QUOTE + "; CP-2G FY2026 leverage cases.\n\n",
        "Source Registry": "Acme FY2025 annual report ratings extract.\n\n",
        "Gaps & Conflicts": LIMITATION + ".\n\n",
        "QA Validation": (
            "Restricted: downside leverage breach; next results or agency action.\n\n"
        ),
    }
    body = "".join(
        "## " + heading + "\n\n" + content[heading]
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()
