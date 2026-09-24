"""Deterministic handoffs for ``FULL_CREDIT_32 / LIQUIDITY_REVIEW``.

The authored Acme example proves CP-2D's contract and arithmetic only.  It is
not a qualification set and does not use the later CCL answer keys.
"""

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
    RUN_PRICE,
    conforming_rows,
    fields_from_prompt,
    skill,
    wire,
)
from canonical_route_fixtures import PACK as BASE_PACK
from canonical_route_fixtures import QUOTES as BASE_QUOTES
from canonical_route_fixtures import HandoffKnobs, canonical_markdown
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256
from caos.pricing import ModelPrice
from caos.provider import Completion, encode_request

SELECTION = ("FULL_CREDIT_32", "LIQUIDITY_REVIEW")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(node.module_id for node in ROUTE.nodes)


@dataclass(frozen=True)
class LiquidityFacts:
    cash: int = 100
    restricted_cash: int = 20
    revolver_commitment: int = 200
    accessible_revolver: int = 150
    operating_cash_flow: int = 140
    working_capital_movement: int = -35
    cash_interest: int = 30
    cash_taxes: int = 20
    mandatory_capex: int = 40
    debt_amortisation_and_maturities: int = 25
    other_cash_uses: int = 10
    committed_inflows: int = 0
    period_months: int = 12

    @property
    def inaccessible_revolver(self) -> int:
        return self.revolver_commitment - self.accessible_revolver

    @property
    def beginning_accessible_liquidity(self) -> int:
        return self.cash + self.accessible_revolver

    @property
    def mandatory_uses(self) -> int:
        return (
            self.cash_interest
            + self.cash_taxes
            + self.mandatory_capex
            + self.debt_amortisation_and_maturities
            + self.other_cash_uses
        )

    @property
    def net_movement(self) -> int:
        return (
            self.operating_cash_flow
            + self.working_capital_movement
            - self.mandatory_uses
            + self.committed_inflows
        )

    @property
    def ending_accessible_liquidity(self) -> int:
        return self.beginning_accessible_liquidity + self.net_movement

    @property
    def average_monthly_burn(self) -> float:
        return round(-self.net_movement / self.period_months, 6)

    @property
    def months_to_empty(self) -> float:
        return round(self.beginning_accessible_liquidity / self.average_monthly_burn, 2)

    def bridge_inputs(self) -> dict[str, float]:
        return {
            "beginning_accessible_liquidity": self.beginning_accessible_liquidity,
            "operating_cash_flow": self.operating_cash_flow,
            "working_capital_movement": self.working_capital_movement,
            "cash_interest": self.cash_interest,
            "cash_taxes": self.cash_taxes,
            "mandatory_capex": self.mandatory_capex,
            "debt_amortisation_and_maturities": (self.debt_amortisation_and_maturities),
            "other_cash_uses": self.other_cash_uses,
            "committed_inflows": self.committed_inflows,
            "period_months": self.period_months,
        }


def _liquidity_quote(facts: LiquidityFacts) -> str:
    return (
        f"Committed undrawn revolver {facts.revolver_commitment} USD million, "
        f"of which {facts.accessible_revolver} was accessible"
    )


def liquidity_pack(facts: LiquidityFacts) -> bytes:
    lines = (
        "Acme Holdings plc FY2025 liquidity schedule",
        (
            f"Cash {facts.cash} and restricted cash {facts.restricted_cash} "
            "USD million at 31 December 2025"
        ),
        _liquidity_quote(facts),
        (
            f"Twelve-month operating cash flow {facts.operating_cash_flow} and "
            f"working-capital outflow {-facts.working_capital_movement} USD million"
        ),
        (
            f"Cash interest {facts.cash_interest}, cash taxes {facts.cash_taxes} and "
            f"mandatory capex {facts.mandatory_capex} USD million"
        ),
        (
            f"Term amortization {facts.debt_amortisation_and_maturities} and lease "
            f"payments {facts.other_cash_uses} USD million"
        ),
        (
            f"Committed inflows {facts.committed_inflows} USD million were reported "
            "for the twelve months after 31 December 2025"
        ),
    )
    return BASE_PACK + ("\n".join(lines) + "\n").encode()


LIQUIDITY_FACTS = LiquidityFacts()
_LIQUIDITY_QUOTE = _liquidity_quote(LIQUIDITY_FACTS)
PACK = liquidity_pack(LIQUIDITY_FACTS)
QUOTES = {
    "CP-0": BASE_QUOTES["CP-0"],
    "CP-1": BASE_QUOTES["CP-1"],
    "CP-2": BASE_QUOTES["CP-2"],
    "CP-2D": _LIQUIDITY_QUOTE,
}
LIMITATION = "Monthly seasonality is not supplied; runway uses a 12-month average"


def liquidity_identity(
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
            for source in ROUTE.nodes
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


def _cp2d_rows(
    facts: LiquidityFacts,
) -> dict[str, list[list[str]]]:
    trace = "Acme liquidity schedule, FY2025"
    return {
        "T2E.1": [
            [
                "acme-liquidity",
                "Acme Holdings FY2025 liquidity schedule",
                "Issuer reported",
                "FY2025",
                "Acme Holdings plc",
                "Cash, revolver, cash uses and cash flow",
                LIMITATION,
                "CP-2D liquidity bridge",
            ]
        ],
        "T2E.2": [
            [
                "Cash",
                str(facts.cash),
                "Accessible",
                trace,
                "No further restriction disclosed",
                "Funds opening uses",
                "Supports near-term liquidity",
            ],
            [
                "Restricted cash",
                str(facts.restricted_cash),
                "Inaccessible",
                trace,
                "Explicitly restricted",
                "Excluded from opening liquidity",
                "Cannot fund near-term uses",
            ],
            [
                "Revolver commitment",
                str(facts.revolver_commitment),
                "Committed",
                trace,
                f"Only {facts.accessible_revolver} disclosed accessible",
                "Headline commitment overstates availability",
                f"Do not count the inaccessible {facts.inaccessible_revolver}",
            ],
            [
                "Accessible revolver availability",
                str(facts.accessible_revolver),
                "Accessible",
                trace,
                f"Disclosure supports {facts.accessible_revolver} only",
                "Adds committed capacity",
                (
                    "Opening accessible liquidity is "
                    f"{facts.beginning_accessible_liquidity}"
                ),
            ],
        ],
        "T2E.3": [
            [
                label,
                amount,
                "Next 12 months",
                "Mandatory",
                trace,
                "Consumes liquidity",
                "Reduces accessible headroom",
                "Amount reported",
            ]
            for label, amount in (
                ("Cash interest", str(facts.cash_interest)),
                ("Cash taxes", str(facts.cash_taxes)),
                ("Mandatory capex", str(facts.mandatory_capex)),
                (
                    "Debt amortization",
                    str(facts.debt_amortisation_and_maturities),
                ),
                ("Lease payment", str(facts.other_cash_uses)),
            )
        ],
        "T2E.4": [
            [
                "Working-capital outflow",
                "Reported outflow",
                str(facts.working_capital_movement),
                "Consumes operating cash",
                "Reduces 12-month headroom",
                trace,
                LIMITATION,
            ],
            [
                "Mandatory capex",
                "Reported requirement",
                str(-facts.mandatory_capex),
                "Required investment consumes cash",
                "Reduces 12-month headroom",
                trace,
                "No deferral assumed",
            ],
        ],
        "T2E.5": [
            [
                "Beginning accessible liquidity",
                str(facts.beginning_accessible_liquidity),
                (
                    f"{facts.cash} cash + {facts.accessible_revolver} "
                    "accessible revolver"
                ),
                "Calculated",
                "Restricted cash and inaccessible revolver excluded",
                trace,
            ],
            [
                "Operating cash flow",
                str(facts.operating_cash_flow),
                "Issuer-reported twelve-month amount",
                "Reported",
                "Primary cash generation",
                trace,
            ],
            [
                "Working-capital movement",
                str(facts.working_capital_movement),
                "Issuer-reported outflow",
                "Reported",
                "Reduces cash generation",
                trace,
            ],
            [
                "Cash interest",
                str(-facts.cash_interest),
                "Issuer-reported use",
                "Reported",
                "Mandatory debt service",
                trace,
            ],
            [
                "Cash taxes",
                str(-facts.cash_taxes),
                "Issuer-reported use",
                "Reported",
                "Mandatory tax use",
                trace,
            ],
            [
                "Mandatory capex",
                str(-facts.mandatory_capex),
                "Issuer-reported use",
                "Reported",
                "No deferral assumed",
                trace,
            ],
            [
                "Debt amortization and maturities",
                str(-facts.debt_amortisation_and_maturities),
                "Issuer-reported term amortization",
                "Reported",
                "Mandatory debt use",
                trace,
            ],
            [
                "Other cash uses",
                str(-facts.other_cash_uses),
                "Issuer-reported lease payments",
                "Reported",
                "Mandatory lease use",
                trace,
            ],
            [
                "Committed inflows",
                str(facts.committed_inflows),
                (
                    "Issuer explicitly reported none"
                    if facts.committed_inflows == 0
                    else "Issuer-reported committed inflow"
                ),
                "Reported",
                "No unsupported inflow assumed",
                trace,
            ],
            [
                "Net cash movement",
                str(facts.net_movement),
                (
                    f"{facts.operating_cash_flow} + "
                    f"{facts.working_capital_movement} - "
                    f"{facts.mandatory_uses} + {facts.committed_inflows}"
                ),
                "Calculated",
                "Twelve-month cash burn",
                trace,
            ],
            [
                "Average monthly cash burn",
                f"{facts.average_monthly_burn:.6f}",
                (f"{-facts.net_movement} / {facts.period_months} months"),
                "Calculated",
                "Recurring average; monthly seasonality unavailable",
                trace,
            ],
            [
                "Ending accessible liquidity",
                str(facts.ending_accessible_liquidity),
                (f"{facts.beginning_accessible_liquidity} + {facts.net_movement}"),
                "Calculated",
                "Positive but below opening liquidity",
                trace,
            ],
        ],
        # T2E.6 is a register with the method's columns (fork r3, G2-14).
        "T2E.6": [
            [
                "Months to Empty",
                f"{facts.months_to_empty:.2f} months",
                (
                    f"{facts.beginning_accessible_liquidity} / "
                    f"({-facts.net_movement} / {facts.period_months})"
                ),
                "Twelve-month bridge; recurring average burn",
                "Calculated",
                trace,
            ]
        ],
        "T2E.7": [
            [
                "Accessible revolver",
                f"{facts.accessible_revolver} accessible",
                "Committed capacity supports liquidity",
                "Mitigates near-term burn",
                trace,
                f"{facts.inaccessible_revolver} of commitment is not counted",
            ],
            [
                "Restricted cash",
                f"{facts.restricted_cash} inaccessible",
                "Cannot fund uses",
                "Does not improve headroom",
                trace,
                "Excluded unless availability changes",
            ],
        ],
        "T2E.9": [
            [
                "Monthly seasonality",
                "Monthly cash-flow profile",
                "Average burn may hide intra-year lows",
                "Limits timing precision, not the 12-month reconciliation",
                "Obtain monthly liquidity forecast",
                "CP-2D",
            ]
        ],
    }


def _t8(readiness: dict[str, str]) -> list[list[str]]:
    return [
        [
            str(index),
            module,
            "Run " + module,
            (
                "Run " + module
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


def liquidity_markdown(
    ident: HostIdentity,
    knobs: HandoffKnobs | None = None,
    *,
    facts: LiquidityFacts = LIQUIDITY_FACTS,
) -> bytes:
    """A vendor-valid handoff on the route's actual host identity."""
    knobs = knobs or HandoffKnobs()
    if ident.module_id in {"CP-1", "CP-2"}:
        return canonical_markdown(ident, knobs)

    front: dict[str, Any] = {
        **(knobs.fields or invocation_fields(CONTRACT, ident)),
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": [],
        **AUTHORED[knobs.qa_status],
        "qa_status": knobs.qa_status,
    }
    if knobs.qa_status == "Restricted":
        front["limitation_flags"] = [LIMITATION]
    rules = CONTRACT.completeness_check.load_contract(
        skill(ident.module_id).decode(), ident.module_id
    )
    authored = _cp2d_rows(facts) if ident.module_id == "CP-2D" else {}
    quote = knobs.quote or (
        _liquidity_quote(facts)
        if ident.module_id == "CP-2D"
        else QUOTES[ident.module_id]
    )
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == knobs.omit_register:
            continue
        if ident.module_id == "CP-0" and register == "T8":
            columns, rows = CONTRACT.navigation.NEW_HEADERS, _t8(knobs.readiness)
        elif register in authored:
            columns = spec["columns"]
            rows = authored[register]
        else:
            columns = spec["columns"] or ["Evidence"]
            rows = conforming_rows(
                register,
                spec,
                rules,
                lambda column, _row: f"{column}: {quote}; extract only",
            )
        appendix += "#### " + register + "\n\n" + _table(columns, rows)
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (appendix if heading == "Analysis" else quote + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


@dataclass
class LiquidityCompletions:
    """Deterministic answers for the proven liquidity route."""

    source_id: UUID
    model: str = "a-model/for-the-test"
    price: ModelPrice | None = RUN_PRICE
    charge: Decimal = Decimal("0.0000041")
    qa_by_module: dict[str, str] = field(default_factory=dict)
    readiness: dict[str, str] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    answers: list[bytes] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        self.prompts.append(prompt)
        fields = fields_from_prompt(prompt)
        module = str(fields["module_id"])
        markdown = liquidity_markdown(
            liquidity_identity(module),
            HandoffKnobs(
                fields=fields,
                qa_status=self.qa_by_module.get(module, "Passed"),
                readiness=self.readiness,
            ),
        )
        self.answers.append(markdown)
        return Completion(
            wire(
                markdown,
                [
                    {
                        "source_id": str(self.source_id),
                        "page": 1,
                        "matched_text": QUOTES[module],
                    }
                ],
            ),
            self.charge,
            "gen-liquidity",
        )
