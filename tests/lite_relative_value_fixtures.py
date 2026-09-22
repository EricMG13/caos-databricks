"""Deterministic handoffs for `LITE_CREDIT_22 / LITE_RELATIVE_VALUE` (Task 9.2).

CP-0 -> CP-L10 -> CP-1C, every edge REQUIRED, `decision_scope:
SCREENING_ONLY`. CP-1C is a FULL module that stays a FULL run under the LITE
profile: its `SKILL.md` retains `NAMED_LITE_OBJECT_ACCEPTED` for
`lite_financial_change_screen`, which CP-L10 owns, so the host holds it until
CP-L10 is accepted (§46.1).

Kept in its own module rather than appended to `canonical_route_fixtures.py`
so the LITE route's fixtures share nothing mutable with the FULL route's, and
so CP-0's T8 names this route's pinned consumers without monkeypatching the
LITE earnings fixtures' `PINNED`.

The pack is `canonical_route_fixtures.PACK`: its `Acme peer and market table`
lines are the peer table extract CP-1C quotes. Register shapes, minimum rows
and semantic rules are the vendor's own (`load_contract`, `conforming_rows`);
CP-L10's topics are `lite_route_fixtures.cp_l10_topic_rows`, which reads them
from CP-L10's verified `SKILL.md` and the LITE policy. CP-1C's handoff is the
FULL route's builder over a LITE identity -- the same registers, the same
authored `T4.3` peer row -- because the module's contract does not change
with the profile; only the scope the host projects does.
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
    conforming_rows,
    fields_from_prompt,
    skill,
    wire,
)
from canonical_route_fixtures import QUOTES, HandoffKnobs, canonical_markdown
from lite_route_fixtures import _table, _yaml, cp_l10_topic_rows

from caos.graph.route import resolve_route
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256
from caos.provider import Completion, encode_request

SELECTION = ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE")
ROUTE = resolve_route(CATALOG, *SELECTION)
MODULES = tuple(n.module_id for n in ROUTE.nodes)
CONSUMERS = tuple(m for m in MODULES if m != "CP-0")
# Whole-token lines of `canonical_route_fixtures.PACK`. CP-1C's is the peer
# table's fact line, the evidence a peer benchmark rests on.
LITE_QUOTES = {
    "CP-0": QUOTES["CP-0"],
    "CP-L10": QUOTES["CP-1"],
    "CP-1C": QUOTES["CP-1C"],
}
# The flag a Restricted CP-0 or CP-L10 carries. Distinct from the FULL
# builder's `LIMITATION` (which a Restricted CP-1C carries), so a test can say
# which node's limitation reached where.
LITE_LIMITATION = (
    "Screen rests on one annual extract; leverage is not reconciled to a "
    "covenant definition"
)


def lite_identity(
    module: str, upstream: tuple[UpstreamRef, ...] | None = None
) -> HostIdentity:
    """The host identity of one node of this route; upstream digests default
    to a stand-in per direct input, as `canonical_route_fixtures` does."""
    node = next(n for n in ROUTE.nodes if n.module_id == module)
    if upstream is None:
        upstream = tuple(
            UpstreamRef(
                n.route_node_id,
                n.module_id,
                RUN,
                "FY2025",
                hashlib.sha256(n.module_id.encode()).hexdigest(),
            )
            for n in ROUTE.nodes
            if any(e.source == n.module_id and e.target == module for e in ROUTE.edges)
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
        "2026-09-08",
        1,
        authority_bundle_sha256(BUNDLE),
        upstream,
    )


def _t8(readiness: dict[str, str]) -> list[list[str]]:
    """CP-0's T8 over exactly this route's pinned consumers (`gate_expects`)."""
    rows = []
    for n, module in enumerate(CONSUMERS, 1):
        status = readiness.get(module, "READY")
        command = "Run " + module
        runnable = status in {"READY", "READY_WITH_LIMITATIONS"}
        rows.append(
            [
                str(n),
                module,
                command,
                command if runnable else "DO NOT RUN",
                "issuer-pack p1",
                "Current handoff",
                status,
                "issuer-pack p1",
            ]
        )
    return rows


def lite_markdown(ident: HostIdentity, knobs: HandoffKnobs | None = None) -> bytes:
    """A handoff the vendor validators accept for `ident` on this route."""
    knobs = knobs or HandoffKnobs()
    if ident.module_id == "CP-1C":
        return canonical_markdown(ident, knobs)
    quote = knobs.quote or LITE_QUOTES[ident.module_id]
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
        front["limitation_flags"] = [LITE_LIMITATION]
    rules = CONTRACT.completeness_check.load_contract(
        skill(ident.module_id).decode(), ident.module_id
    )
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == knobs.omit_register:
            continue
        columns = spec["columns"] or ["Evidence"]
        if ident.module_id == "CP-0" and register == "T8":
            columns, rows = CONTRACT.navigation.NEW_HEADERS, _t8(knobs.readiness)
        elif ident.module_id == "CP-L10" and register == "TL10.2":
            rows = cp_l10_topic_rows()
        else:
            rows = conforming_rows(
                register, spec, rules, lambda c, _n: f"{c}: {quote}; extract only"
            )
        appendix += "#### " + register + "\n\n" + _table(columns, rows)
    for table_id in rules["unconditional_stable_tables"]:
        appendix += f"<!-- table-id: {table_id} -->\n" + _table(
            ["source_locator"], [["issuer-pack p1"]]
        )
    body = "".join(
        "## " + h + "\n\n" + (appendix if h == "Analysis" else quote + "\n\n")
        for h in CONTRACT.validate_handoff.CANONICAL_HEADINGS
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


@dataclass
class LiteRelativeValueCompletions:
    """A provider answering this route's nodes from the prompt's host fields."""

    source_id: UUID
    model: str = "a-model/for-the-test"
    charge: Decimal = Decimal("0.0000041")
    qa_by_module: dict[str, str] = field(default_factory=dict)
    readiness: dict[str, str] = field(default_factory=dict)
    quotes_by_module: dict[str, str] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    answers: list[bytes] = field(default_factory=list)
    # Every response body exactly as sent: what an attempt's diagnostic holds.
    bodies: list[str] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        self.prompts.append(prompt)
        fields = fields_from_prompt(prompt)
        module = str(fields["module_id"])
        quote = self.quotes_by_module.get(module, LITE_QUOTES[module])
        markdown = lite_markdown(
            lite_identity(module),
            HandoffKnobs(
                fields=fields,
                qa_status=self.qa_by_module.get(module, "Passed"),
                readiness=self.readiness,
                quote=quote,
            ),
        )
        self.answers.append(markdown)
        self.bodies.append(
            wire(
                markdown,
                [{"source_id": str(self.source_id), "page": 1, "matched_text": quote}],
            )
        )
        return Completion(self.bodies[-1], self.charge, "gen-lite-relative-value")
