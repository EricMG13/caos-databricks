"""Deterministic handoffs for the 19-node FULL credit assessment route."""

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
from canonical_route_fixtures import (
    PACK as CANONICAL_PACK,
)
from canonical_route_fixtures import (
    QUOTES as CANONICAL_QUOTES,
)
from canonical_route_fixtures import (
    HandoffKnobs,
    canonical_markdown,
)
from cp1a_contract_fixtures import LIMITATION as CP1A_LIMITATION
from cp1a_contract_fixtures import PACK as CP1A_PACK
from cp1a_contract_fixtures import cp1a_markdown
from cp1b_route_fixtures import PACK as CP1B_PACK
from cp1b_route_fixtures import QUOTES as CP1B_QUOTES
from cp1b_route_fixtures import cp1b_markdown
from cp1d_contract_fixtures import PACK as CP1D_PACK
from cp1d_contract_fixtures import cp1d_markdown
from cp2e_contract_fixtures import PACK as CP2E_PACK
from cp2e_contract_fixtures import cp2e_markdown
from cp2h_contract_fixtures import LIMITATION as CP2H_LIMITATION
from cp2h_contract_fixtures import PACK as CP2H_PACK
from cp2h_contract_fixtures import cp2h_markdown
from cp3c_route_fixtures import LIMITATION as CP3C_LIMITATION
from cp3c_route_fixtures import PACK as CP3C_PACK
from cp3c_route_fixtures import QUOTE as CP3C_QUOTE
from cp3c_route_fixtures import cp3c_markdown
from cp4c_contract_fixtures import LIMITATION as CP4C_LIMITATION
from cp4c_contract_fixtures import PACK as CP4C_PACK
from cp4c_contract_fixtures import cp4c_markdown
from cp6_route_fixtures import PACK as CP6_PACK
from cp6_route_fixtures import QUOTE as CP6_QUOTE
from cp6_route_fixtures import cp6_markdown
from liquidity_route_fixtures import PACK as CP2D_PACK
from liquidity_route_fixtures import QUOTES as CP2D_QUOTES
from liquidity_route_fixtures import liquidity_markdown
from lite_route_fixtures import (
    LiteHandoffKnobs,
    _table,
    _yaml,
    realistic_handoff_markdown,
)

from caos.evidence.extract import LINES_PER_PAGE
from caos.graph.route import resolve_route
from caos.methodology.handoff import (
    HostIdentity,
    UpstreamRef,
    expected_filename,
)
from caos.methodology.vendor import authority_bundle_sha256
from caos.provider import Completion, encode_request

SELECTION = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(node.module_id for node in ROUTE.nodes)
QA_QUOTE = "Full assessment traceability review"
CP1A_QUOTE = "Sponsor Alpha Fund IV owns"
RESTRICTED_UPSTREAM = frozenset({"CP-1A", "CP-1B", "CP-2E", "CP-2H", "CP-3C", "CP-4C"})
LITE_SCREEN_RESTRICTIONS = {
    "CP-1A": CP1A_LIMITATION,
    "CP-2H": CP2H_LIMITATION,
    "CP-3C": CP3C_LIMITATION,
    "CP-4C": CP4C_LIMITATION,
}
ROUTE_QUOTES = {
    **{module: CANONICAL_QUOTES[module] for module in CANONICAL_QUOTES},
    "CP-1": "Revenue 1000 EBITDA 200 cash 100 debt 600 capex 40 interest 30 tax 20",
    "CP-1A": CP1A_QUOTE,
    "CP-1B": CP1B_QUOTES["CP-1B"],
    "CP-1D": "recurring restructuring add-back",
    "CP-2D": CP2D_QUOTES["CP-2D"],
    "CP-2E": "current hedge terms",
    "CP-2H": "secondary rating evidence",
    "CP-3C": CP3C_QUOTE,
    "CP-4C": "English restructuring plan",
    "CP-5": QA_QUOTE,
    "CP-6": CP6_QUOTE,
}
# Each quoted line once, on a page of its own: two modules citing one line
# cite the one line, and a line shown twice on a page is ambiguous (N28).
_QUOTED_LINES = tuple(dict.fromkeys(ROUTE_QUOTES.values()))
_QUOTE_PAGE = "\n".join(
    (
        *_QUOTED_LINES,
        *(
            f"Full assessment evidence-page spacer {index}"
            for index in range(LINES_PER_PAGE - len(_QUOTED_LINES))
        ),
    )
).encode()
ROUTE_PACK = b"\n".join(
    (
        _QUOTE_PAGE,
        CANONICAL_PACK,
        CP1A_PACK,
        CP1B_PACK,
        CP1D_PACK,
        CP2D_PACK.removeprefix(CANONICAL_PACK),
        CP2E_PACK,
        CP2H_PACK,
        CP3C_PACK,
        CP4C_PACK,
        CP6_PACK,
    )
)


def route_identity(
    module: str, *, selection: tuple[str, str] = SELECTION
) -> HostIdentity:
    route = resolve_route(CATALOG, *selection)
    node = next(node for node in route.nodes if node.module_id == module)
    upstream = tuple(
        UpstreamRef(
            source.route_node_id,
            source.module_id,
            RUN,
            "FY2025",
            hashlib.sha256(source.module_id.encode()).hexdigest(),
        )
        for source in route.nodes
        if any(
            edge.source == source.module_id and edge.target == module
            for edge in route.edges
        )
    )
    return HostIdentity(
        RUN,
        *selection,
        node.route_node_id,
        module,
        CONTRACT.routing.Route(CATALOG, *selection).by_module[module]["module_name"],
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-19",
        1,
        authority_bundle_sha256(BUNDLE),
        upstream,
    )


def _cp0_markdown(
    ident: HostIdentity,
    fields: dict[str, Any],
    readiness: dict[str, str],
    *,
    selection: tuple[str, str] = SELECTION,
) -> bytes:
    rendered = canonical_markdown(
        ident,
        HandoffKnobs(fields=fields, quote=ROUTE_QUOTES["CP-0"]),
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
        for index, module in enumerate(
            (node.module_id for node in resolve_route(CATALOG, *selection).nodes[1:]), 1
        )
    ]
    return (
        prefix
        + marker
        + _table(CONTRACT.navigation.NEW_HEADERS, rows)
        + boundary
        + suffix
    ).encode()


def _cp5_markdown(
    ident: HostIdentity,
    fields: dict[str, Any],
    qa_status: str,
    *,
    selection: tuple[str, str] = SELECTION,
) -> bytes:
    limitations = (
        tuple(
            LITE_SCREEN_RESTRICTIONS[ref.module_id]
            for ref in ident.upstream
            if ref.module_id in LITE_SCREEN_RESTRICTIONS
        )
        if selection == ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN")
        else ()
    )
    qa_status = "Restricted" if limitations else qa_status
    severity = {"Passed": "MINOR", "Restricted": "MATERIAL", "Blocked": "CRITICAL"}[
        qa_status
    ]
    route = resolve_route(CATALOG, *selection)
    front = {
        **fields,
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": list(limitations),
        "validation_warnings": [],
        "downstream_consumers": [
            edge.target for edge in route.edges if edge.source == "CP-5"
        ],
        **AUTHORED[qa_status],
        "qa_status": qa_status,
    }
    if limitations:
        front["limitation_flags"] = list(limitations)
    rules = CONTRACT.completeness_check.load_contract(skill("CP-5").decode(), "CP-5")
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        columns = spec["columns"] or ["Evidence"]
        if register == "T5.1":
            rows = [
                [
                    ref.module_id,
                    (
                        f"{
                            expected_filename(
                                route_identity(ref.module_id, selection=selection)
                            )
                        }"
                        f" / {RUN}"
                    ),
                    "Full",
                    "Sufficient",
                    "Conforming",
                    "Restricted" if ref.module_id in RESTRICTED_UPSTREAM else "Passed",
                    f"Traced from the accepted {ref.module_id} handoff.",
                ]
                for ref in ident.upstream
            ]
        else:
            rows = conforming_rows(
                register,
                spec,
                rules,
                lambda column, _row: f"{column}: {QA_QUOTE}; traced handoff",
            )
            if "Severity" in columns:
                for row in rows:
                    row[columns.index("Severity")] = severity
        appendix += f"#### {register}\n\n" + _table(columns, rows)
    body = "".join(
        "## "
        + heading
        + "\n\n"
        + (appendix if heading == "Analysis" else QA_QUOTE + "\n\n")
        for heading in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


def route_markdown(  # noqa: C901 - one explicit branch per proven module fixture
    module: str,
    fields: dict[str, Any],
    qa_status: str,
    readiness: dict[str, str],
    *,
    selection: tuple[str, str] = SELECTION,
) -> bytes:
    ident = route_identity(module, selection=selection)
    if module == "CP-0":
        return _cp0_markdown(ident, fields, readiness, selection=selection)
    if module == "CP-L10":
        return realistic_handoff_markdown(
            ident,
            LiteHandoffKnobs(
                fields=fields,
                qa_status=qa_status,
                readiness=readiness,
                quotes=(ROUTE_QUOTES["CP-0"],),
            ),
        )
    if module == "CP-1A":
        return cp1a_markdown(ident, fields=fields)
    if module == "CP-1B":
        return cp1b_markdown(ident, fields=fields, qa_status=qa_status)
    if module == "CP-1D":
        return cp1d_markdown(ident, fields=fields)
    if module == "CP-2D":
        return liquidity_markdown(
            ident,
            HandoffKnobs(
                fields=fields, qa_status=qa_status, quote=ROUTE_QUOTES[module]
            ),
        )
    if module == "CP-2E":
        return cp2e_markdown(ident, fields=fields)
    if module == "CP-2H":
        return cp2h_markdown(ident, fields=fields)
    if module == "CP-3C":
        return cp3c_markdown(ident, fields=fields, qa_status=qa_status)
    if module == "CP-4C":
        return cp4c_markdown(ident, fields=fields)
    if module == "CP-5":
        return _cp5_markdown(ident, fields, qa_status, selection=selection)
    if module == "CP-6":
        return cp6_markdown(ident, fields=fields, qa_status=qa_status)
    return canonical_markdown(
        ident,
        HandoffKnobs(
            fields=fields,
            qa_status=qa_status,
            quote=ROUTE_QUOTES[module],
        ),
    )


@dataclass
class FullAssessmentCompletions:
    source_id: UUID
    model: str = "a-model/for-the-test"
    charge: Decimal = Decimal("0.0000041")
    selection: tuple[str, str] = field(default=SELECTION, kw_only=True)
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
        markdown = route_markdown(
            module,
            fields,
            self.qa_by_module.get(
                module,
                "Restricted" if module in {"CP-1B", "CP-3C", "CP-6"} else "Passed",
            ),
            self.readiness,
            selection=self.selection,
        )
        self.answers.append(markdown)
        return Completion(
            wire(
                markdown,
                [
                    {
                        "source_id": str(self.source_id),
                        "page": 1,
                        "matched_text": ROUTE_QUOTES.get(
                            module, CANONICAL_QUOTES["CP-0"]
                        ),
                    }
                ],
            ),
            self.charge,
            "gen-full-credit-assessment",
        )
