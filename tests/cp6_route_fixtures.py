"""Source-derived CP-6/CP-6A contract fixture for FULL portfolio decision."""

# ruff: noqa: E501 -- fixture cells mirror the vendored Markdown table schema.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from canonical_fixtures import (
    AUTHORED,
    BUNDLE,
    CATALOG,
    CONTRACT,
    RUN,
    conforming_rows,
    fields_from_prompt,
    skill,
    whole_line,
    wire,
)
from canonical_route_fixtures import (
    PACK as CANONICAL_PACK,
)
from canonical_route_fixtures import (
    QUOTES as CANONICAL_QUOTES,
)
from canonical_route_fixtures import HandoffKnobs, canonical_markdown
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import (
    HostIdentity,
    UpstreamRef,
    expected_filename,
    invocation_fields,
)
from caos.methodology.vendor import authority_bundle_sha256
from caos.provider import Completion, encode_request

SELECTION = ("FULL_CREDIT_32", "PORTFOLIO_DECISION")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(node.module_id for node in ROUTE.nodes)
LIMITATION = (
    "Downside, liquidity, refinancing, recovery and sizing conclusions remain "
    "bounded by the supplied evidence and adjudication scope"
)


@dataclass(frozen=True)
class DebateFacts:
    revenue: int = 1_000
    ebitda: int = 200
    cash: int = 100
    debt: int = 600
    free_cash_flow: int = 100
    downside_revenue_change: int = -10
    covenant_limit: float = 4.0
    loan_price: int = 98
    loan_spread: int = 350
    peer_spread: int = 320
    maturity_year: int = 2030
    issuer_limit: float = 5.0
    current_exposure: float = 3.0
    proposed_exposure: float = 1.0
    ccc_bucket: float = 5.0
    ccc_limit: float = 10.0
    sector_exposure: float = 12.0
    sector_limit: float = 20.0
    exit_days: int = 5

    @property
    def net_leverage(self) -> float:
        return (self.debt - self.cash) / self.ebitda

    @property
    def spread_premium(self) -> int:
        return self.loan_spread - self.peer_spread

    @property
    def pro_forma_exposure(self) -> float:
        return self.current_exposure + self.proposed_exposure

    @property
    def concentration_headroom(self) -> float:
        return self.issuer_limit - self.pro_forma_exposure


FACTS = DebateFacts()


def debate_pack(facts: DebateFacts = FACTS) -> bytes:
    return f"""Acme Holdings plc FY2025 audited credit and portfolio pack
Revenue {facts.revenue} EBITDA {facts.ebitda} cash {facts.cash} debt {facts.debt} USD million
Free cash flow {facts.free_cash_flow} USD million in FY2025
Downside case revenue change {facts.downside_revenue_change} percent
Executed facility agreement maximum net leverage {facts.covenant_limit:.1f} times tested annually
Senior secured term loan matures in {facts.maturity_year}
Acme senior secured loan mid price {facts.loan_price} spread {facts.loan_spread} basis points dated 2026-09-19
Beta comparable loan spread {facts.peer_spread} basis points dated 2026-09-19
Portfolio mandate issuer concentration limit {facts.issuer_limit:.1f} percent
Current Acme exposure {facts.current_exposure:.1f} percent and proposed starter exposure {facts.proposed_exposure:.1f} percent
CCC bucket {facts.ccc_bucket:.1f} percent against a {facts.ccc_limit:.1f} percent limit
Cruise-sector exposure {facts.sector_exposure:.1f} percent against a {facts.sector_limit:.1f} percent limit
Trading report supports exit within {facts.exit_days} trading days at the proposed exposure
Widely held issuer with seven of nine directors classified as independent
""".encode()


PACK = debate_pack()
# The whole line CP-5 and CP-6 cite (N28).
QUOTE = whole_line(
    PACK, "Acme senior secured loan mid price 98 spread 350 basis points"
)
ROUTE_PACK = CANONICAL_PACK + PACK
ROUTE_QUOTES = {
    module: CANONICAL_QUOTES[module]
    for module in ("CP-0", "CP-1", "CP-3D", "CP-2", "CP-4", "CP-3")
}
ROUTE_QUOTES["CP-1"] = (
    "Revenue 1000 EBITDA 200 cash 100 debt 600 capex 40 interest 30 tax 20"
)
ROUTE_QUOTES.update({"CP-5": QUOTE, "CP-6": QUOTE})


def direct_upstream(include_cp3d: bool = True) -> tuple[UpstreamRef, ...]:
    return tuple(
        UpstreamRef(
            node.route_node_id,
            node.module_id,
            RUN,
            "FY2025",
            hashlib.sha256(node.module_id.encode()).hexdigest(),
        )
        for node in sorted(ROUTE.nodes, key=lambda item: item.route_node_id)
        if (include_cp3d or node.module_id != "CP-3D")
        and any(
            edge.source == node.module_id and edge.target == "CP-6"
            for edge in ROUTE.edges
        )
    )


def route_identity(
    module: str, upstream: tuple[UpstreamRef, ...] | None = None
) -> HostIdentity:
    node = next(node for node in ROUTE.nodes if node.module_id == module)
    if upstream is None:
        upstream = tuple(
            UpstreamRef(
                source.route_node_id,
                source.module_id,
                RUN,
                "FY2025",
                hashlib.sha256(source.module_id.encode()).hexdigest(),
            )
            for source in sorted(ROUTE.nodes, key=lambda item: item.route_node_id)
            if any(
                edge.source == source.module_id and edge.target == module
                for edge in ROUTE.edges
            )
        )
    return HostIdentity(
        RUN,
        *SELECTION,
        node.route_node_id,
        module,
        CONTRACT.routing.Route(CATALOG, *SELECTION).by_module[module]["module_name"],
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        upstream,
    )


def cp6_identity(upstream: tuple[UpstreamRef, ...] | None = None) -> HostIdentity:
    return route_identity("CP-6", direct_upstream() if upstream is None else upstream)


def _rows(
    facts: DebateFacts, upstream_modules: frozenset[str]
) -> dict[str, list[list[str]]]:
    downside = (
        "CP-2A handoff independently tests the stress path"
        if "CP-2A" in upstream_modules
        else "No CP-2A handoff independently tests the stress path"
    )
    liquidity = (
        "CP-2D handoff supplies the liquidity runway"
        if "CP-2D" in upstream_modules
        else "No CP-2D handoff supplies a quantified runway"
    )
    refinancing = (
        "CP-3C handoff supplies refinancing-path analysis"
        if "CP-3C" in upstream_modules
        else "No CP-3C handoff supplies refinancing-path analysis"
    )
    # One row per governed scoring dimension is easier to audit.
    # fmt: off
    issuer_dimensions = (
        ("Cash-flow durability", "2", f"FY2025 FCF {facts.free_cash_flow}", f"Revenue stress {facts.downside_revenue_change}%", "Bull evidence is stronger but stress remains"),
        ("Downside pathway severity", "4", "Positive current FCF", downside, "Downside remains bounded by the supplied evidence"),
        ("Liquidity runway", "2", f"Cash {facts.cash} plus FCF {facts.free_cash_flow}", liquidity, "Liquidity remains bounded by the supplied evidence"),
        ("Refinancing / maturity risk", "3", f"Term loan matures {facts.maturity_year}", refinancing, "Maturity is known but execution remains monitored"),
        ("Legal / covenant control", "3", f"Net leverage {facts.net_leverage:.1f}x versus {facts.covenant_limit:.1f}x", "Annual testing delays lender control", "Current headroom and delayed control balance"),
        ("Recovery / LGD protection", "3", "Senior secured status", "No stressed recovery value is supplied", "Priority is sourced but stressed recovery is not"),
        ("Sponsor / governance alignment", "3", "Seven of nine directors are independent", "No sponsor-behaviour history in the pack", "Governance structure is sourced but behaviour is untested"),
        ("Relative value compensation", "2", f"Current spread {facts.loan_spread}bp", f"Only one peer at {facts.peer_spread}bp", "Dated pricing supports Bull with limited breadth"),
        ("Portfolio fit / sizing", "3", f"Issuer limit {facts.issuer_limit:.1f}%", "Full-portfolio correlation effects are not quantified", "Mandate arithmetic does not replace portfolio adjudication"),
    )
    portfolio_dimensions = (
        ("Spread / YTW Benefit", "2", f"Current spread {facts.loan_spread}bp", f"Peer spread {facts.peer_spread}bp", "RV has a dated premium"),
        ("Peer Relative Value", "2", f"Premium {facts.spread_premium}bp", "Only one comparable issuer", "RV leads, with limited comparison breadth"),
        ("Downside Pathway Severity", "4", "Positive current FCF", downside, "Compliance leads on downside evidence quality"),
        ("Liquidity / Refinancing Risk", "3", f"Exit within {facts.exit_days} days", f"{liquidity}; {refinancing}", "Implementation liquidity is sourced; refinancing remains monitored"),
        ("Legal / Recovery Protection", "3", "Senior secured and covenant terms sourced", "Stressed recovery and legal leakage are not quantified", "Legal and recovery evidence is incomplete"),
        ("CCC-Basket / Downgrade Risk", "2", f"CCC bucket {facts.ccc_bucket:.1f}%", f"Limit {facts.ccc_limit:.1f}%", "Direct mandate data shows headroom"),
        ("Concentration / Correlation Risk", "2", f"Sector exposure {facts.sector_exposure:.1f}%", f"Sector limit {facts.sector_limit:.1f}%", "Direct exposure data shows headroom"),
        ("Mandate Compliance", "2", f"Pro-forma issuer exposure {facts.pro_forma_exposure:.1f}%", f"Issuer limit {facts.issuer_limit:.1f}%", "Arithmetic shows headroom but not full-portfolio fit"),
        ("Implementation Liquidity", "2", f"Exit within {facts.exit_days} days", "Evidence is sized only to the proposed exposure", "Dated trading evidence supports RV"),
    )
    # fmt: on
    return {
        "T6A.4": [
            [
                "Claim 1 — cash-flow durability",
                f"Downside revenue change is {facts.downside_revenue_change}%",
                "Lower revenue can compress EBITDA and free cash flow",
                f"Annual {facts.covenant_limit:.1f}x test delays lender intervention",
                "Lower cash generation raises net leverage and reduces debt-service capacity",
                "Negative — Leverage Increase",
                f"Free cash flow remains at least {facts.free_cash_flow} under the downside case",
            ],
            [
                "Claim 2 — structural protection",
                f"Net leverage is {facts.net_leverage:.1f}x but the covenant tests annually",
                "Headroom can erode between annual tests",
                "Annual testing permits deterioration before a formal test",
                "Delayed control can increase leakage before lenders can respond",
                "Negative — Covenant Erosion",
                "Executed documents evidence an earlier control trigger",
            ],
            [
                "Claim 3 — relative-value compensation",
                f"The spread premium is only {facts.spread_premium}bp to one peer",
                "A narrow peer premium may not absorb downside volatility",
                "Weak control could make the premium inadequate for priming risk",
                "Limited compensation can close before credit risk improves",
                "Negative — Refinancing Risk",
                "A broader current peer set confirms the premium",
            ],
        ],
        "T6A.6": [
            [dimension, score, bull, bear, assessment]
            for dimension, score, bull, bear, assessment in issuer_dimensions
        ],
        "T6A.7": [
            [
                "Cash-flow durability",
                f"FY2025 free cash flow is {facts.free_cash_flow}",
                f"Revenue downside is {facts.downside_revenue_change}%",
                "Partially Mitigated",
                "Audited cash flow offsets but does not eliminate the downside case",
                "Neutral — Stable",
            ],
            [
                "Legal control",
                f"Current net leverage is {facts.net_leverage:.1f}x",
                "Annual testing delays lender control",
                "Bear Sustained",
                "Executed facility terms confirm annual testing",
                "Negative — Covenant Erosion",
            ],
            [
                "Relative value",
                f"Acme offers a {facts.spread_premium}bp peer premium",
                "The peer set contains one comparable",
                "Partially Mitigated",
                "Current pricing is direct but breadth is limited",
                "Neutral — Stable",
            ],
        ],
        "T6A.11": [
            [
                "CP-6-GAP-001",
                (
                    "CP-2A downside handoff is supplied but remains source-bounded"
                    if "CP-2A" in upstream_modules
                    else "No independent CP-2A downside handoff on this route"
                ),
                "The supplied evidence does not resolve every downside sensitivity",
                "Limits Bear-path and Chair conviction",
                "Extend the pinned downside evidence before increasing conviction",
            ],
            [
                "CP-6-GAP-002",
                f"{liquidity}; {refinancing}",
                "Cash and maturity facts do not establish a quantified runway or refinancing path",
                "Caps liquidity and refinancing conclusions",
                "Extend the pinned liquidity and refinancing evidence",
            ],
            [
                "CP-6-GAP-003",
                "Stressed recovery and legal leakage are not quantified",
                "Seniority and covenant terms do not establish stressed recovery or basket capacity",
                "Caps legal-control and recovery conviction",
                "Supply stressed recovery and legal-capacity evidence",
            ],
        ],
        "T6E.4": [
            [
                "Bullet 1 — spread pickup",
                f"The {facts.spread_premium}bp premium uses one peer",
                "Data quality",
                "A narrow benchmark can overstate relative value",
                "Neutral — Stable",
                "A broader current peer set preserves the premium",
            ],
            [
                "Bullet 2 — instrument mispricing",
                "Annual covenant testing weakens control between tests",
                "Legal / Recovery",
                "Legal leakage may consume the apparent price discount",
                "Negative — Covenant Erosion",
                "Executed terms evidence tighter lender controls",
            ],
            [
                "Bullet 3 — portfolio implementation",
                "Full-portfolio correlation effects are not quantified",
                "Data quality",
                "Direct mandate arithmetic is not a substitute for portfolio-fit adjudication",
                "Neutral — Stable",
                "Current portfolio analysis confirms the allocation against the complete portfolio",
            ],
        ],
        "T6E.6": [
            [dimension, score, rv, compliance, assessment]
            for dimension, score, rv, compliance, assessment in portfolio_dimensions
        ],
        "T6E.7": [
            [
                "Peer compensation",
                f"Acme offers {facts.spread_premium}bp over Beta",
                "The peer sample has one issuer",
                "Partially Mitigated",
                "Current direct prices, limited comparison breadth",
                "Neutral — Stable",
            ],
            [
                "Issuer concentration",
                f"Pro-forma exposure is {facts.pro_forma_exposure:.1f}% versus a {facts.issuer_limit:.1f}% limit",
                "Full-portfolio correlation effects are not quantified",
                "Unresolved",
                f"Mandate arithmetic shows {facts.concentration_headroom:.1f}% headroom but not full-portfolio fit",
                "Neutral — Stable",
            ],
            [
                "Implementation liquidity",
                f"Trading report supports exit within {facts.exit_days} days",
                "Exit evidence covers only the proposed exposure",
                "RV Sustained",
                "Dated trading report is sized to the proposed exposure",
                "Positive — Liquidity Improvement",
            ],
        ],
        "T6E.11": [
            [
                "CP-6A-GAP-001",
                "Full-portfolio correlation and risk-budget effects are not quantified",
                "Mandate arithmetic alone cannot test correlation and full risk-budget effects",
                "Caps the CIO posture at Requires More Work",
                "Run current portfolio analysis against the mandate and exposure report",
            ],
            [
                "CP-6A-GAP-002",
                (
                    "CP-2A downside handoff is supplied but remains source-bounded"
                    if "CP-2A" in upstream_modules
                    else "No independent CP-2A downside handoff"
                ),
                "Source-stated stress does not establish total downside-budget consumption",
                "Strengthens the Compliance case",
                "Extend the pinned downside evidence before approving a position size",
            ],
            [
                "CP-6A-GAP-003",
                f"{liquidity}; {refinancing}",
                "Maturity and cash facts do not establish execution capacity",
                "Caps liquidity and refinancing confidence",
                "Extend the pinned liquidity and refinancing evidence",
            ],
            [
                "CP-6A-GAP-004",
                "Stressed recovery and legal leakage are not quantified",
                "Instrument priority does not quantify stressed recovery or legal leakage",
                "Keeps legal and recovery scoring balanced",
                "Supply stressed recovery and legal-capacity evidence before final sizing",
            ],
        ],
    }


def _decision(facts: DebateFacts) -> str:
    return (
        "### Decision\n\n"
        "Starter Position is the surviving issuer action bias, while portfolio sizing remains "
        "Requires More Work. FY2025 free cash flow of "
        f"{facts.free_cash_flow} USD million, {facts.net_leverage:.1f}x net leverage and a "
        f"{facts.spread_premium}bp spread premium give the Bull the stronger cash-flow case. "
        f"The strongest counterargument is the {facts.downside_revenue_change}% revenue stress "
        f"combined with an annual {facts.covenant_limit:.1f}x covenant test, which delays lender "
        "control and prevents a higher-conviction bias. The greatest uncertainty is independent "
        "portfolio fit because full-portfolio correlation effects are not quantified. Conviction improves only when current portfolio analysis "
        f"confirms that {facts.pro_forma_exposure:.1f}% exposure fits the complete portfolio; an "
        "adverse fit result moves the posture to Avoid.\n\n"
    )


def _method(facts: DebateFacts, upstream_modules: frozenset[str]) -> str:
    downside_gate = (
        "CP-2A is supplied as direct upstream"
        if "CP-2A" in upstream_modules
        else "CP-2A is not a route input"
    )
    liquidity_gate = (
        "CP-2D is supplied as direct upstream"
        if "CP-2D" in upstream_modules
        else "CP-2D is not a route input"
    )
    refinancing_gate = (
        "CP-3C is supplied as direct upstream"
        if "CP-3C" in upstream_modules
        else "CP-3C is not a route input"
    )
    return f"""### CP-6 issuer debate

#### IC Debate Source Gate

Ready with Limitations: CP-0, CP-1, CP-2, CP-3, CP-5 and CP-3D are direct upstream; CP-4 is mediated through CP-3/CP-5; {downside_gate}; {liquidity_gate}; {refinancing_gate}. Stressed recovery remains evidence-bounded.

#### Pre-Debate Thesis Map

Strong audited cash flow, moderate liquidity and legal evidence, current but narrow relative-value evidence, and weak independent downside evidence make the central controversy whether {facts.spread_premium}bp compensates for delayed lender control.

#### Bull Analyst Opening Statement

**Claim 1 — cash flow.** Evidence: FY2025 FCF {facts.free_cash_flow}. Risk mechanic: retained cash services debt. Credit implication: Neutral — Stable. Monitoring signal: FCF below {facts.free_cash_flow}.

**Claim 2 — structure.** Evidence: {facts.net_leverage:.1f}x versus {facts.covenant_limit:.1f}x. Risk mechanic: headroom absorbs stress. Credit implication: Positive — Covenant Headroom Expansion. Monitoring signal: leverage above 3.0x.

**Claim 3 — relative value.** Evidence: {facts.loan_spread}bp versus {facts.peer_spread}bp. Risk mechanic: premium compensates limited uncertainty. Credit implication: Neutral — Stable. Monitoring signal: premium below {facts.spread_premium}bp.

#### Bear Analyst Cross-Examination

The exact three claims are challenged in T6A.4; the Zero-Bound path runs from {facts.downside_revenue_change}% revenue stress through EBITDA and FCF compression to higher leverage, delayed covenant control and refinancing risk.

#### Bull Analyst Defense

Claim 1 is Partially Rebutted by positive FCF; Claim 2 is Partially Rebutted by current headroom; Claim 3 is Partially Rebutted by dated pricing. No new claim is introduced.

#### IC Chair Evidence Weighting

All nine required dimensions are scored in T6A.6 without averaging away the downside evidence limitation.

#### Debate Resolution Matrix

T6A.7 resolves cash flow, legal control and relative value using the permitted labels.

#### Action Bias Determination

Final Action Bias: Starter Position. The decision is driven by positive FY2025 FCF and current spread premium, because retained cash and compensation absorb part of the identified stress, which implies stable debt service with constrained portfolio risk. The main factor preventing a higher-conviction recommendation is source-bounded downside evidence. Bull wins narrowly because cash flow is direct while the downside path remains constrained.

#### Single Greatest Uncertainty

The single uncertainty is independently adjudicated downside severity. It matters because a completed stress path could move the bias to Watchlist; evidence showing protected FCF supports Core Hold, while evidence showing covenant erosion supports Avoid.

#### IC Chair Final Memo

Decision: Starter Position. Bull wins narrowly on FCF; Bear's annual-test attack is strongest. Legal control is delayed, liquidity is positive but refinancing remains monitored, and the {facts.spread_premium}bp premium supports only limited sizing. Extend the pinned downside evidence before increasing conviction.

#### Gaps Ledger

All three grouped issuer gaps are recorded sequentially in T6A.11.

### CP-6A portfolio debate

#### Portfolio Debate Source Gate

Ready with Limitations: CP-3, current pricing, mandate and exposure inputs are available; {downside_gate}; {liquidity_gate}; {refinancing_gate}. Recovery and sizing remain evidence-bounded.

#### Pre-Debate Portfolio Thesis Map

Current pricing, downside, legal, concentration, mandate and liquidity evidence frame whether a {facts.spread_premium}bp premium compensates for the missing independent portfolio-fit adjudication.

#### The RV Trader's Pitch

**RV Bullet 1 — spread.** Evidence: {facts.loan_spread}bp versus {facts.peer_spread}bp. Risk mechanic: yield pickup. Credit implication: Neutral — Stable. Monitoring signal: premium compression.

**RV Bullet 2 — instrument.** Evidence: price {facts.loan_price} and senior secured status. Risk mechanic: discount and priority protect value. Credit implication: Neutral — Stable. Monitoring signal: legal-control erosion.

**RV Bullet 3 — implementation.** Evidence: {facts.pro_forma_exposure:.1f}% versus {facts.issuer_limit:.1f}% mandate limit. Risk mechanic: stated headroom limits concentration use. Credit implication: Neutral — Stable. Monitoring signal: exposure above {facts.pro_forma_exposure:.1f}%.

#### The Mandate Compliance Officer's Attack

The exact three bullets are challenged in T6E.4 against data-quality and legal/recovery constraints.

#### The RV Trader's Defense

Bullets 1 and 2 are Partially Rebutted by current pricing and executed terms; Bullet 3 is Partially Rebutted by mandate arithmetic, but no exact size is approved without complete portfolio analysis.

#### CIO Evidence Weighting

All nine allocation dimensions are scored in T6E.6, with the portfolio-analysis gap retained.

#### Allocation Decision Matrix

T6E.7 resolves peer compensation, concentration and implementation liquidity.

#### Final Sizing Posture

Final Sizing Posture: Requires More Work. The decision is driven by incomplete portfolio-fit evidence, because direct mandate arithmetic cannot test correlation and total risk-budget use, which implies no decision-useful final size. Requires More Work maps to Requires More Work. Neither persona wins because market evidence is current but portfolio-fit evidence is incomplete.

#### Exact Portfolio Constraint

Exact Portfolio Constraint: Data quality. Evidence: full-portfolio correlation effects are not quantified. Risk mechanic: untested correlation and risk-budget effects cap sizing. Credit / Portfolio Implication: no final allocation. Evidence Needed to Resolve: current analysis over the complete portfolio.

#### CIO Final Memo

Decision: Requires More Work, mapped unchanged. Neither persona wins. The {facts.spread_premium}bp premium is the best RV evidence; incomplete portfolio-fit evidence is the decisive Compliance attack. Legal control tests annually, liquidity supports a {facts.exit_days}-day exit, mandate headroom is arithmetically positive, and complete portfolio analysis is required before sizing.

#### Gaps Ledger

All four grouped portfolio gaps are recorded sequentially in T6E.11.

"""


def cp6_markdown(
    ident: HostIdentity,
    *,
    facts: DebateFacts = FACTS,
    omit_register: str | None = None,
    fields: dict[str, Any] | None = None,
    qa_status: str = "Restricted",
) -> bytes:
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": [],
        **AUTHORED[qa_status],
        "qa_status": qa_status,
    }
    if qa_status == "Restricted":
        front["limitation_flags"] = [LIMITATION]
    rules = CONTRACT.completeness_check.load_contract(skill("CP-6").decode(), "CP-6")
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    upstream_modules = frozenset(ref.module_id for ref in ident.upstream)
    authored = _rows(facts, upstream_modules)
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += f"#### {register}\n\n" + _table(spec["columns"], authored[register])
    analysis = _decision(facts) + _method(facts, upstream_modules) + appendix
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (analysis if heading == "Analysis" else QUOTE + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


def _cp0_markdown(
    ident: HostIdentity, fields: dict[str, Any], readiness: dict[str, str]
) -> bytes:
    """Reuse the canonical CP-0 fixture with this route's exact T8 owners."""
    rendered = canonical_markdown(
        ident,
        HandoffKnobs(fields=fields, readiness=readiness, quote=ROUTE_QUOTES["CP-0"]),
    ).decode()
    marker, boundary = "#### T8\n\n", "\n## Evidence Trace\n"
    prefix, remainder = rendered.split(marker, 1)
    _old_t8, suffix = remainder.split(boundary, 1)
    rows = [
        [
            str(index),
            module,
            f"Run {module}",
            (
                f"Run {module}"
                if readiness.get(module, "READY") in {"READY", "READY_WITH_LIMITATIONS"}
                else "DO NOT RUN"
            ),
            "issuer-pack p1",
            "Current handoff",
            readiness.get(module, "READY"),
            "issuer-pack p1",
        ]
        for index, module in enumerate(MODULES[1:], 1)
    ]
    return (
        prefix
        + marker
        + _table(CONTRACT.navigation.NEW_HEADERS, rows)
        + boundary
        + suffix
    ).encode()


def _cp5_markdown(ident: HostIdentity, fields: dict[str, Any], qa_status: str) -> bytes:
    severity = {"Passed": "MINOR", "Restricted": "MATERIAL", "Blocked": "CRITICAL"}[
        qa_status
    ]
    finding = {
        "Passed": "One-peer benchmark breadth is a minor traceability limitation",
        "Restricted": LIMITATION,
        "Blocked": "A critical QA defect blocks downstream use",
    }[qa_status]
    front = {
        **fields,
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": [],
        **AUTHORED[qa_status],
        "qa_status": qa_status,
    }
    if qa_status == "Restricted":
        front["limitation_flags"] = [LIMITATION]
    rules = CONTRACT.completeness_check.load_contract(skill("CP-5").decode(), "CP-5")
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        columns = spec["columns"] or ["Evidence"]
        if register == "T5.1":
            rows = [
                [
                    ref.module_id,
                    f"{expected_filename(route_identity(ref.module_id))} / {RUN}",
                    "Full",
                    "Sufficient",
                    "Conforming",
                    "Passed",
                    f"Traced from the accepted {ref.module_id} handoff.",
                ]
                for ref in ident.upstream
            ]
        else:
            rows = conforming_rows(
                register,
                spec,
                rules,
                lambda column, _row: f"{column}: {finding}; {QUOTE}",
            )
            if "Severity" in columns:
                severity_index = columns.index("Severity")
                for row in rows:
                    row[severity_index] = severity
        appendix += f"#### {register}\n\n" + _table(columns, rows)
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (appendix if heading == "Analysis" else QUOTE + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


def route_markdown(
    module: str,
    fields: dict[str, Any],
    qa_status: str,
    readiness: dict[str, str],
) -> bytes:
    ident = route_identity(module)
    if module == "CP-0":
        return _cp0_markdown(ident, fields, readiness)
    if module == "CP-5":
        return _cp5_markdown(ident, fields, qa_status)
    if module == "CP-6":
        return cp6_markdown(ident, fields=fields, qa_status=qa_status)
    return canonical_markdown(
        ident,
        HandoffKnobs(fields=fields, qa_status=qa_status, quote=ROUTE_QUOTES[module]),
    )


@dataclass
class PortfolioDecisionCompletions:
    source_id: UUID
    model: str = "a-model/for-the-test"
    charge: Decimal = Decimal("0.0000041")
    qa_by_module: dict[str, str] = field(default_factory=dict)
    readiness: dict[str, str] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    answers: list[bytes] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        self.prompts.append(prompt)
        fields = fields_from_prompt(prompt)
        module = str(fields["module_id"])
        markdown = route_markdown(
            module,
            fields,
            self.qa_by_module.get(
                module, "Restricted" if module == "CP-6" else "Passed"
            ),
            self.readiness,
        )
        self.answers.append(markdown)
        body = wire(
            markdown,
            [
                {
                    "source_id": str(self.source_id),
                    "page": 1,
                    "matched_text": ROUTE_QUOTES[module],
                }
            ],
        )
        self.bodies.append(body)
        return Completion(body, self.charge, "gen-portfolio-decision")
