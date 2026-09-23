"""Deterministic CP-1B handoffs for the enabled earnings-update route."""

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
    wire,
)
from lite_route_fixtures import _table, _yaml

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256
from caos.provider import Completion, encode_request

SELECTION = ("FULL_CREDIT_32", "EARNINGS_UPDATE")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(node.module_id for node in ROUTE.nodes)
LIMITATION = "Two annual periods only; quarterly seasonality is not supplied"


@dataclass(frozen=True)
class EarningsFacts:
    prior_revenue: int = 1000
    current_revenue: int = 1100
    prior_ebitda: int = 200
    current_ebitda: int = 220
    prior_operating_cash_flow: int = 140
    current_operating_cash_flow: int = 155
    prior_capex: int = 40
    current_capex: int = 45
    prior_cash: int = 100
    current_cash: int = 120
    prior_debt: int = 600
    current_debt: int = 580

    @property
    def revenue_change(self) -> int:
        return self.current_revenue - self.prior_revenue


EARNINGS_FACTS = EarningsFacts()


def _cp1_values(facts: EarningsFacts) -> dict[str, int | float]:
    return {
        "revenue": facts.current_revenue,
        "cogs": 500,
        "opex_including_da": 300,
        "depreciation_amortization": 80,
        "ebitda": facts.current_ebitda,
        "adjusted_ebitda": facts.current_ebitda,
        "cfo_ncfo": facts.current_operating_cash_flow,
        "capex_and_intangible_investment": facts.current_capex,
        "cash_interest_paid": 30,
        "cash_taxes_paid": 20,
        "cash_lease_payments": 10,
        "working_capital_change": -35,
        "acquisitions_disposals": 0,
        "net_debt_issue_repay": -20,
        "net_equity_issue_repay": 0,
        "dividends_paid": 0,
        "other_investing_financing": 0,
        "net_cash_change": 20,
        "cash_and_equivalents": facts.current_cash,
        "total_debt": facts.current_debt,
        "senior_secured_debt": 500,
        "unsecured_debt": 80,
        "rcf_drawn": 0,
        "rcf_commitment": 200,
        "net_accounts_receivable": 150,
        "inventory": 100,
        "accounts_payable": 130,
        "effective_tax_rate": 0.2,
    }


def earnings_pack(facts: EarningsFacts) -> bytes:
    prior = (
        f"FY2024 revenue {facts.prior_revenue} EBITDA {facts.prior_ebitda} "
        f"operating cash flow {facts.prior_operating_cash_flow} "
        f"capex {facts.prior_capex} cash {facts.prior_cash} "
        f"debt {facts.prior_debt} USD million; adjusted EBITDA equals EBITDA; "
        "no add-backs disclosed\n"
    )
    current = (
        f"FY2025 revenue {facts.current_revenue} EBITDA {facts.current_ebitda} "
        f"operating cash flow {facts.current_operating_cash_flow} "
        f"capex {facts.current_capex} cash {facts.current_cash} "
        f"debt {facts.current_debt} USD million; adjusted EBITDA equals EBITDA; "
        "no add-backs disclosed\n"
    )
    accounts = " ".join(
        f"{metric} {value}" for metric, value in _cp1_values(facts).items()
    )
    facility = (
        "FY2025 term debt carrying value, principal, drawn amount and commitment "
        "580 USD million; secured senior fixed rate; maturity 2030-12-31\n"
    )
    return (
        "Acme Holdings plc annual results\n"
        + prior
        + current
        + "FY2025 model accounts "
        + accounts
        + "; no segment schedule disclosed\n"
        + facility
    ).encode()


PACK = earnings_pack(EARNINGS_FACTS)
QUOTES = {
    "CP-0": "FY2025 revenue 1100 EBITDA 220 operating cash flow 155",
    "CP-1": "FY2025 revenue 1100 EBITDA 220",
    "CP-1B": "FY2025 revenue 1100 EBITDA 220 operating cash flow 155",
    "CP-2": "FY2025 revenue 1100 EBITDA 220 operating cash flow 155",
    "CP-5": "FY2025 revenue 1100 EBITDA 220 operating cash flow 155",
}


def cp1b_identity(
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


def _rows(facts: EarningsFacts) -> dict[str, list[list[str]]]:
    metrics = (
        ("Revenue", facts.prior_revenue, facts.current_revenue),
        ("EBITDA", facts.prior_ebitda, facts.current_ebitda),
        (
            "Operating cash flow",
            facts.prior_operating_cash_flow,
            facts.current_operating_cash_flow,
        ),
        ("Capex", facts.prior_capex, facts.current_capex),
        ("Cash", facts.prior_cash, facts.current_cash),
        ("Debt", facts.prior_debt, facts.current_debt),
    )
    # The method's own columns (fork r3, G2-6): T4.12 keeps the `values` and
    # `changes` a qualification key reads beside the keyed comparator's columns.
    return {
        "T4.4": [
            [
                name,
                f"FY2024 {prior}; FY2025 {current}",
                str(current - prior),
                f"{(current - prior) / prior:.1%}",
                "same annual basis",
            ]
            for name, prior, current in metrics
        ],
        "T4.6": [
            [
                name,
                "YoY",
                str(prior),
                str(current),
                str(current - prior),
                f"{(current - prior) / prior:.1%}",
                "reported annual results",
                "annual comparison",
                "period-specific credit signal",
            ]
            for name, prior, current in metrics
        ],
        "T4.12": [
            [
                name.lower().replace(" ", "_"),
                "FY2025",
                "FY2024",
                "LTM_PRIOR",
                str(current),
                str(prior),
                str(current - prior),
                f"{(current - prior) / prior:.1%}",
                "Supported",
                "false",
                "false",
                "false",
                "false",
                f"{current}/{prior}",
                str(current - prior),
            ]
            for name, prior, current in metrics
        ],
        "T4.13": [
            [
                "revenue",
                "FY2025",
                str(facts.current_revenue),
                str(facts.current_revenue),
                "0",
                "0",
                "PASS",
                "CP-1 canonical value retained",
                "annual-results",
            ]
        ],
        "T4.14": [
            [
                "NONE",
                "FY2025",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
                "No add-backs disclosed; adjusted EBITDA equals EBITDA",
                "annual-results",
            ]
        ],
        "T4.15": [
            [
                "CP-MODEL",
                "READY",
                "none",
                "none",
                "none",
                "two-period historical snapshot supplied",
            ]
        ],
    }


def _stable_tables(
    facts: EarningsFacts,
) -> dict[str, tuple[tuple[str, ...], list[list[str]]]]:
    metrics = (
        ("revenue", facts.prior_revenue, facts.current_revenue),
        ("ebitda", facts.prior_ebitda, facts.current_ebitda),
        ("adjusted_ebitda", facts.prior_ebitda, facts.current_ebitda),
        (
            "cfo_ncfo",
            facts.prior_operating_cash_flow,
            facts.current_operating_cash_flow,
        ),
        (
            "capex_and_intangible_investment",
            facts.prior_capex,
            facts.current_capex,
        ),
        ("cash_and_equivalents", facts.prior_cash, facts.current_cash),
        ("total_debt", facts.prior_debt, facts.current_debt),
    )
    return {
        "cp1b.model_comparator_register": (
            tuple(
                "metric_id|current_period_id|reference_period_id|comparison_basis|"
                "current_value|reference_value|absolute_change|percentage_change|"
                "calculation_status|restatement_flag|basis_change_flag|"
                "perimeter_change_flag|definition_change_flag".split("|")
            ),
            [
                [
                    metric,
                    "FY2025",
                    "FY2024",
                    "LTM_PRIOR",
                    str(current),
                    str(prior),
                    str(current - prior),
                    f"{(current - prior) / prior:.1%}",
                    "Supported",
                    "false",
                    "false",
                    "false",
                    "false",
                ]
                for metric, prior, current in metrics
            ],
        ),
        "cp1b.model_validation_register": (
            tuple(
                "metric_id|period_id|cp1_value|cp1b_comparison_value|difference|"
                "tolerance|status|explanation|source_or_conflict_ref".split("|")
            ),
            [
                [
                    metric,
                    "FY2025",
                    str(current),
                    str(current),
                    "0",
                    "0",
                    "PASS",
                    "CP-1 canonical value retained",
                    "annual-results",
                ]
                for metric, _prior, current in metrics
            ],
        ),
        "cp1b.addback_validation_register": (
            tuple(
                "addback_id|period_id|cp1_value|cp1b_comparison_value|difference|"
                "tolerance|status|label_match|definition_change_flag|explanation|"
                "source_or_conflict_ref".split("|")
            ),
            [],
        ),
        "cp1b.cp_model_snapshot_fields": (
            ("field_id", "value", "status", "source_id", "source_locator", "as_of"),
            [
                [
                    "historical_performance",
                    f"Revenue changed from {facts.prior_revenue} to "
                    f"{facts.current_revenue}; EBITDA changed from "
                    f"{facts.prior_ebitda} to {facts.current_ebitda}",
                    "READY",
                    "annual-results",
                    "FY2024/FY2025 annual results",
                    "2026-09-19",
                ]
            ],
        ),
        "cp1b.model_readiness": (
            (
                "downstream_module",
                "status",
                "blocking_metric_ids",
                "blocking_period_ids",
                "conflict_refs",
                "explanation",
            ),
            [["CP-MODEL", "ready", "", "", "", "two periods reconciled"]],
        ),
    }


def _cp1_stable_tables(
    facts: EarningsFacts,
) -> dict[str, tuple[tuple[str, ...], list[list[str]]]]:
    def cols(value: str) -> tuple[str, ...]:
        return tuple(value.split("|"))

    return {
        "cp1.model_period_register": (
            cols(
                "period_id|fiscal_year|fiscal_quarter|period_type|start_date|end_date|day_count|audit_status|currency|unit|accounting_basis|entity_perimeter|source_id|source_locator|component_period_ids"
            ),
            [
                [
                    "FY2024",
                    "2024",
                    "",
                    "PERIOD_END",
                    "",
                    "2024-12-31",
                    "",
                    "AUDITED",
                    "USD",
                    "MILLIONS",
                    "IFRS",
                    "consolidated",
                    "annual-results",
                    "FY2024 annual results",
                    "",
                ],
                [
                    "FY2025",
                    "2025",
                    "",
                    "FY",
                    "2025-01-01",
                    "2025-12-31",
                    "365",
                    "AUDITED",
                    "USD",
                    "MILLIONS",
                    "IFRS",
                    "consolidated",
                    "annual-results",
                    "FY2025 annual results",
                    "",
                ],
            ],
        ),
        "cp1.model_account_register": (
            cols(
                "metric_id|period_id|value|sign_convention|value_class|calculation_status|source_id|source_locator|conflict_refs|limitation_refs"
            ),
            [
                [
                    metric,
                    "FY2025",
                    str(value),
                    "SIGNED_AS_REPORTED",
                    "REPORTED",
                    "Supported",
                    "annual-results",
                    "FY2025 annual results",
                    "",
                    "",
                ]
                for metric, value in _cp1_values(facts).items()
            ],
        ),
        "cp1.segment_revenue_schedule": (
            cols(
                "segment_id|segment_name|segment_type|display_priority|period_id|revenue|status|source_id|source_locator"
            ),
            [],
        ),
        "cp1.adjusted_ebitda_bridge": (
            cols(
                "addback_id|addback_label|addback_classification|realization_status|display_priority|period_id|value|status|source_definition|source_id|source_locator"
            ),
            [],
        ),
        "cp1.debt_facility_register": (
            cols(
                "facility_id|facility_name|period_id|facility_type|carrying_value|principal|drawn_amount|commitment|secured_status|seniority|currency|margin_or_coupon|maturity_date|lease_classification|source_id|source_locator"
            ),
            [
                [
                    "term",
                    "Term debt",
                    "FY2025",
                    "TERM_LOAN",
                    "580",
                    "580",
                    "580",
                    "580",
                    "SECURED",
                    "SENIOR",
                    "USD",
                    "fixed",
                    "2030-12-31",
                    "NOT_LEASE",
                    "annual-results",
                    "FY2025 annual results",
                ]
            ],
        ),
        "cp1.model_reconciliation_register": (
            cols(
                "check_id|period_id|check_type|reported_value|calculated_value|difference|tolerance|status|explanation|source_refs"
            ),
            [
                [
                    "segments",
                    "FY2025",
                    "SEGMENT_REVENUE",
                    str(facts.current_revenue),
                    "null",
                    "null",
                    "0",
                    "WARN",
                    "No segment schedule disclosed",
                    "annual-results",
                ],
                [
                    "adjusted",
                    "FY2025",
                    "ADJUSTED_EBITDA_BRIDGE",
                    str(facts.current_ebitda),
                    str(facts.current_ebitda),
                    "0",
                    "0",
                    "PASS",
                    "No add-backs disclosed",
                    "annual-results",
                ],
            ],
        ),
        "cp1.downstream_readiness": (
            cols(
                "downstream_module|status|missing_metric_ids|conflict_refs|explanation"
            ),
            [["CP-MODEL", "ready", "", "", "two-period comparator inputs supplied"]],
        ),
    }


def _t8(readiness: dict[str, str]) -> list[list[str]]:
    return [
        [
            str(index),
            module,
            f"Run {module}",
            f"Run {module}"
            if readiness.get(module, "READY") in {"READY", "READY_WITH_LIMITATIONS"}
            else "DO NOT RUN",
            "annual-results p1",
            "Current handoff",
            readiness.get(module, "READY"),
            "annual-results p1",
        ]
        for index, module in enumerate(MODULES[1:], 1)
    ]


def _quote(facts: EarningsFacts) -> str:
    return (
        f"FY2025 revenue {facts.current_revenue} EBITDA {facts.current_ebitda} "
        f"operating cash flow {facts.current_operating_cash_flow}"
    )


def _generic_markdown(
    ident: HostIdentity,
    facts: EarningsFacts,
    fields: dict[str, Any] | None,
    qa_status: str,
    readiness: dict[str, str],
) -> bytes:
    rules = CONTRACT.completeness_check.load_contract(
        skill(ident.module_id).decode(), ident.module_id
    )
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": ["CP-MODEL"] if ident.module_id == "CP-1" else [],
        **AUTHORED[qa_status],
        "qa_status": qa_status,
    }
    if qa_status == "Restricted":
        front["limitation_flags"] = [LIMITATION]
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        rows = (
            _t8(readiness)
            if ident.module_id == "CP-0" and register == "T8"
            else conforming_rows(
                register,
                spec,
                rules,
                lambda column, _row: f"{column}: {_quote(facts)}; extract only",
            )
        )
        columns = (
            CONTRACT.navigation.NEW_HEADERS
            if ident.module_id == "CP-0" and register == "T8"
            else spec["columns"] or ["Evidence"]
        )
        appendix += "#### " + register + "\n\n" + _table(columns, rows)
    stable_tables = _cp1_stable_tables(facts) if ident.module_id == "CP-1" else {}
    for table_id in rules["unconditional_stable_tables"]:
        columns, rows = stable_tables.get(
            table_id, (("source_locator",), [["FY2024/FY2025 annual results"]])
        )
        appendix += f"<!-- table-id: {table_id} -->\n" + _table(columns, rows)
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (appendix if heading == "Analysis" else _quote(facts) + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


def cp1b_markdown(  # noqa: PLR0913 - explicit independent contract knobs
    ident: HostIdentity,
    *,
    facts: EarningsFacts = EARNINGS_FACTS,
    omit_register: str | None = None,
    fields: dict[str, Any] | None = None,
    qa_status: str = "Passed",
    readiness: dict[str, str] | None = None,
) -> bytes:
    if ident.module_id != "CP-1B":
        return _generic_markdown(ident, facts, fields, qa_status, readiness or {})
    rules = CONTRACT.completeness_check.load_contract(skill("CP-1B").decode(), "CP-1B")
    front = {
        **(fields or invocation_fields(CONTRACT, ident)),
        "confidence_score": 55 if qa_status == "Restricted" else 90,
        "confidence_band": "Low" if qa_status == "Restricted" else "High",
        "committee_status": "Restricted" if qa_status == "Restricted" else "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": ["CP-MODEL"],
        **AUTHORED[qa_status],
        "qa_status": qa_status,
    }
    if qa_status == "Restricted":
        front["limitation_flags"] = [LIMITATION]
    authored = _rows(facts)
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        rows = authored.get(register) or conforming_rows(
            register,
            spec,
            rules,
            lambda column, _row: f"{column}: FY2025 annual results; extract only",
        )
        appendix += (
            "#### " + register + "\n\n" + _table(spec["columns"] or ["Evidence"], rows)
        )
    stable_tables = _stable_tables(facts)
    for table_id in rules["unconditional_stable_tables"]:
        columns, rows = stable_tables[table_id]
        appendix += f"<!-- table-id: {table_id} -->\n" + _table(columns, rows)
    quote = _quote(facts)
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (appendix if heading == "Analysis" else quote + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


@dataclass
class EarningsCompletions:
    source_id: UUID
    model: str = "a-model/for-the-test"
    charge: Decimal = Decimal("0.0000041")
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
        markdown = cp1b_markdown(
            cp1b_identity(module), fields=fields, readiness=self.readiness
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
            "gen-earnings",
        )
