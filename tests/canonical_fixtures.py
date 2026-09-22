"""Deterministic canonical Markdown handoffs for the LITE earnings route.

Built the way `vendor/deploy-v/tests/test_module_workflow.py` builds them:
structural scenarios over CP-0 -> CP-L10 -> CP-5, not issuer analysis. Shared
by every suite that needs a handoff the vendor validators accept.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from caos.methodology.bundle import Bundle, verified_bytes
from caos.methodology.handoff import HostIdentity, UpstreamRef, invocation_fields
from caos.methodology.vendor import authority_bundle_sha256, load_vendor_contract
from caos.provider import Completion, encode_request

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"
BUNDLE = Bundle(VENDORED)
CONTRACT = load_vendor_contract(BUNDLE)
CATALOG = json.loads(
    (
        VENDORED
        / "skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
    ).read_text()
)
LITE_PROFILE = "LITE_CREDIT_22"
LITE_SELECTION = "LITE_EARNINGS_UPDATE"
ROUTE = CONTRACT.routing.Route(CATALOG, LITE_PROFILE, LITE_SELECTION)
RUN = "COS-20260908T120000Z-" + "1" * 32
PINNED = frozenset({"CP-L10", "CP-5"})

# A caller's research brief as `pin_run_input` takes it (§96): every
# `CP_DR_RESEARCH_BRIEF_V1` field but the three the host binds -- `run_id`,
# `cp0_sha256`, `authority_sha256`. Two questions, so a dossier can answer one
# and leave one UNRESOLVED; consumer `NONE` after `CP-0`, the placement the
# vendor requires on a route whose terminal deliverable is CP-DR itself.
RESEARCH_QUESTIONS: tuple[tuple[str, str], ...] = (
    (
        "RQ-headroom",
        "What undrawn committed facilities did the issuer report at year end?",
    ),
    (
        "RQ-rating",
        "What credit rating and outlook do the agencies currently assign?",
    ),
)


def research_brief(
    issuer_id: str = "EXAMPLE",
    issuer_name: str = "Example Holdings plc",
    *,
    questions: tuple[tuple[str, str], ...] = RESEARCH_QUESTIONS,
    placement: tuple[str, str] = ("NONE", "CP-0"),
    **changes: object,
) -> dict[str, Any]:
    """A caller's linked brief for `issuer_id`, with any top-level field
    replaced; `placement` is every question's `(consumer, after)` pair."""
    consumer, after = placement
    brief: dict[str, Any] = {
        "schema": "CP_DR_RESEARCH_BRIEF_V1",
        "mode": "linked",
        "scope_type": "issuer",
        "scope_key": issuer_id,
        "subject_name": issuer_name,
        "decision_context": "Test the liquidity assumption before the screen",
        "as_of_date": "2026-09-08",
        "time_horizon": "Next 12 months",
        "source_mode": "supplied_only",
        "budget": "standard",
        "authorization_basis": "The task instruction to research this issuer",
        "exclusions": "No web or model-memory sources; no trade recommendation",
        "questions": [
            {
                "question_id": question_id,
                "question": question,
                "decision_relevance": "Sets the liquidity headroom assumption",
                "consumer_module_id": consumer,
                "after_module_id": after,
                "evidence_needed": "The issuer's own year-end disclosure",
                "completion_test": "A supported answer with contrary evidence",
            }
            for question_id, question in questions
        ],
    }
    brief.update(changes)
    return brief


def identity(
    module_id: str, upstream: tuple[UpstreamRef, ...] = (), **changes: object
) -> HostIdentity:
    """The host identity of one LITE node, with any field replaced."""
    node = ROUTE.by_module[module_id]
    values: dict[str, Any] = {
        "run_id": RUN,
        "profile_id": ROUTE.profile_id,
        "selection_id": ROUTE.selection_id,
        "route_node_id": node["route_node_id"],
        "module_id": module_id,
        "module_name": node["module_name"],
        "issuer_id": "EXAMPLE",
        "issuer_name": "Example",
        "reporting_period": "FY2025",
        "analysis_date": "2026-09-08",
        "ordinal": 1,
        "authority_bundle_sha256": authority_bundle_sha256(BUNDLE),
        "upstream": upstream,
    }
    values.update(changes)
    return HostIdentity(**values)


def _table(columns: list[str] | tuple[str, ...], rows: list[list[str]]) -> str:
    head = (
        "| "
        + " | ".join(columns)
        + " |\n| "
        + " | ".join("---" for _ in columns)
        + " |\n"
    )
    return head + "".join("| " + " | ".join(row) + " |\n" for row in rows) + "\n"


def _yaml(fields: dict[str, Any]) -> str:
    lines = []
    for key, value in fields.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(key + ":")
            for item in value:
                for n, (k, v) in enumerate(item.items()):
                    lines.append(
                        ("  - " if n == 0 else "    ") + k + ": " + json.dumps(v)
                    )
        else:
            lines.append(key + ": " + json.dumps(value))
    return "\n".join(lines)


def skill(module_id: str) -> bytes:
    """The module's verified `SKILL.md`."""
    return verified_bytes(BUNDLE, module_id, "SKILL.md")


def conforming_rows(
    register: str,
    spec: dict[str, Any],
    rules: dict[str, Any],
    fill: Callable[[str, int], str],
) -> list[list[str]]:
    """Body rows for `register` that satisfy the profile's `semantic_rules`.

    `fill(column, row)` is the cell a builder would otherwise write. Since §92
    the bundle's checker enforces the rules its profiles declare, so a fixture
    that repeats one cell no longer conforms; the rows are derived from the
    vendor's own declarations rather than hand-typed. A `required_values` or
    `exact_values` column carries each declared value once, an `allowed_values`
    column carries only declared values, and a `unique_columns` column never
    repeats; any other cell is `fill`'s.
    """
    columns = spec["columns"] or ["Evidence"]
    mine = [
        r for r in rules.get("semantic_rules", ()) if r.get("register_id") == register
    ]
    exact = {
        r["column"]: list(r["values"]) for r in mine if r["rule"] == "exact_values"
    }
    required = {
        r["column"]: list(r["values"]) for r in mine if r["rule"] == "required_values"
    }
    # An enum may permit a value the placeholder blocklist refuses in a
    # critical column (`Not Assessable`); a conforming row takes the first
    # value that is not one.
    blocklist = rules.get("blocklist", set())
    allowed = {
        r["column"]: [v for v in r["values"] if v.casefold() not in blocklist]
        for r in mine
        if r["rule"] == "allowed_values"
    }
    unique = {c for r in mine if r["rule"] == "unique_columns" for c in r["columns"]}
    count = max(
        [max(1, spec["minimum_body_rows"]), *(len(v) for v in required.values())]
    )
    if exact:
        count = max(len(v) for v in exact.values())
        assert count >= spec["minimum_body_rows"], (register, exact)
    rows: list[list[str]] = []
    for n in range(count):
        row = []
        for column in columns:
            if column in exact:
                cell = exact[column][n]
            elif column in required and n < len(required[column]):
                cell = required[column][n]
            elif column in allowed:
                cell = allowed[column][0]
            else:
                cell = fill(column, n)
                if column in unique:
                    cell = f"{cell} {n + 1}"
            row.append(cell)
        rows.append(row)
    return rows


def handoff_markdown(  # noqa: PLR0913 -- one knob per fixture variant
    identity: HostIdentity,
    *,
    fields: dict[str, Any] | None = None,
    authored: dict[str, Any] | None = None,
    override: dict[str, Any] | None = None,
    omit_register: str | None = None,
    drop: str | None = None,
    body_note: str = "Recorded source p1.",
    readiness: dict[str, str] | None = None,
    blockers: dict[str, str] | None = None,
    source_files: dict[str, str] | None = None,
) -> bytes:
    """A handoff the vendor validators accept for `identity`, then varied.

    `fields` replaces the host-owned front matter (a fake provider copies what
    the prompt handed it); `readiness` sets CP-0's T8 status per pinned module,
    `blockers` that row's `Why now / blocker` cell, and `source_files` its
    `Source files to attach` cell (§95; "Source p1" when unset, which names no
    pinned member and so selects nothing).
    """
    front: dict[str, Any] = {
        **(fields if fields is not None else invocation_fields(CONTRACT, identity)),
        "confidence_score": 90,
        "confidence_band": "High",
        "qa_status": "Passed",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": [],
        **(authored or {}),
        **(override or {}),
    }
    front.pop(drop or "", None)
    rules = CONTRACT.completeness_check.load_contract(
        skill(identity.module_id).decode(), identity.module_id
    )
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register, spec in rules["registers"].items():
        if register == omit_register:
            continue
        appendix += "#### " + register + "\n\n"
        if identity.module_id == "CP-0" and register == "T8":
            appendix += _table(
                CONTRACT.navigation.NEW_HEADERS,
                _t8(readiness or {}, blockers or {}, source_files or {}),
            )
        else:
            columns = spec["columns"] or ["Evidence"]
            appendix += _table(
                columns,
                conforming_rows(
                    register, spec, rules, lambda _c, _n: "Recorded source p1"
                ),
            )
    for table_id in rules["unconditional_stable_tables"]:
        appendix += (
            "<!-- table-id: "
            + table_id
            + " -->\n"
            + _table(["source_locator"], [["Source p1"]])
        )
    headings = CONTRACT.validate_handoff.CANONICAL_HEADINGS
    body = "".join(
        "## " + h + "\n\n" + (appendix if h == "Analysis" else body_note + "\n\n")
        for h in headings
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


def _t8(
    readiness: dict[str, str],
    blockers: dict[str, str],
    source_files: dict[str, str] | None = None,
) -> list[list[str]]:
    rows = []
    for n, module in enumerate(sorted(PINNED), 1):
        status = readiness.get(module, "READY")
        runnable = status in {"READY", "READY_WITH_LIMITATIONS"}
        command = "Run " + module
        rows.append(
            [
                str(n),
                module,
                command,
                command if runnable else "DO NOT RUN",
                (source_files or {}).get(module, "Source p1"),
                "Current handoff",
                status,
                blockers.get(module, "Relevant source p1"),
            ]
        )
    return rows


def upstream_ref(identity: HostIdentity, markdown: bytes) -> UpstreamRef:
    """How a downstream node names this accepted handoff."""
    return UpstreamRef(
        route_node_id=identity.route_node_id,
        module_id=identity.module_id,
        run_id=identity.run_id,
        period=identity.reporting_period,
        sha256=hashlib.sha256(markdown).hexdigest(),
    )


def wire(markdown: bytes, citations: list[dict[str, object]]) -> str:
    """The closed provider transport `{canonical_markdown, citations}` (§41)."""
    return json.dumps(
        {"canonical_markdown": markdown.decode("utf-8"), "citations": citations}
    )


def fields_from_prompt(prompt: str) -> dict[str, Any]:
    """The host-owned front matter a prompt handed over, parsed by the vendor."""
    found = re.search(
        r"--- HOST-OWNED FRONT MATTER ([0-9a-f]{16}) \(copy exactly\) ---\n", prompt
    )
    assert found is not None
    end = prompt.index(f"\n--- END HOST-OWNED FRONT MATTER {found.group(1)} ---")
    block = prompt[found.end() : end]
    parsed, _body = CONTRACT.validate_handoff.parse_restricted_frontmatter(
        "---\n" + block + "\n---\n"
    )
    return dict(parsed)


# Whole words of the harness report's page 1, repeated in every handoff body.
QUOTE = "Total debt at 31 December 2026"
# Whole words of the body that no evidence carries.
UNANCHORED = "Leverage was unchanged"
# The authored fields a validated `qa_status` must agree with.
AUTHORED = {
    "Passed": {},
    "Restricted": {
        "confidence_score": 50,
        "confidence_band": "Low",
        "committee_status": "Restricted",
        "limitation_flags": ["Only one source report was delivered"],
    },
    "Blocked": {
        "confidence_score": 30,
        "confidence_band": "Insufficient Information",
        "committee_status": "Blocked",
    },
}


@dataclass
class CanonicalCompletions:
    """A provider that copies the prompt's host front matter into a handoff.

    `mutate` edits the copied fields (identity tampering); `content` replaces the
    whole answer; `during` runs inside the call, before the answer.
    `qa_by_module` overrides `qa_status` per module on a whole route.
    """

    source_id: UUID
    charge: Decimal | None = Decimal("0.0000041")
    model: str = "a-model/for-the-test"
    generation_id: str = "gen-canonical-test"
    qa_status: str = "Passed"
    qa_by_module: dict[str, str] = field(default_factory=dict)
    readiness: dict[str, str] = field(default_factory=dict)
    blockers: dict[str, str] = field(default_factory=dict)
    quotes: tuple[str, ...] = (QUOTE,)
    # §95: CP-0's `Source files to attach` cell per consumer module, and a
    # consumer's own quotes of another pinned source, `(source_id, quote)`,
    # cited beside `quotes` and written into the body so they are quoted.
    source_files: dict[str, str] = field(default_factory=dict)
    # A third element is the page cited (§98); without one it is page 1.
    cited: tuple[tuple[UUID, str] | tuple[UUID, str, int], ...] = ()
    mutate: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    content: str | None = None
    during: Callable[[], None] | None = None
    prompts: list[str] = field(default_factory=list)
    answers: list[bytes] = field(default_factory=list)
    # Every response body exactly as sent: what the attempt's diagnostic holds.
    bodies: list[str] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        self.prompts.append(prompt)
        if self.during is not None:
            self.during()
        if self.content is not None:
            self.bodies.append(self.content)
            return Completion(self.content, self.charge, self.generation_id)
        fields = fields_from_prompt(prompt)
        if self.mutate is not None:
            fields = self.mutate(fields)
        module_id = str(fields["module_id"])
        qa = self.qa_by_module.get(module_id, self.qa_status)
        markdown = handoff_markdown(
            identity(module_id),
            fields=fields,
            authored={**AUTHORED[qa], "qa_status": qa},
            readiness=self.readiness,
            blockers=self.blockers,
            source_files=self.source_files,
            body_note=" ".join(
                (
                    f"{QUOTE} was recorded. {UNANCHORED} here.",
                    *(c[1] for c in self.cited),
                )
            ),
        )
        self.answers.append(markdown)
        citations: list[dict[str, object]] = [
            {"source_id": str(self.source_id), "page": 1, "matched_text": quote}
            for quote in self.quotes
        ] + [
            {
                "source_id": str(c[0]),
                "page": c[2] if len(c) > 2 else 1,
                "matched_text": c[1],
            }
            for c in self.cited
        ]
        self.bodies.append(wire(markdown, citations))
        return Completion(self.bodies[-1], self.charge, self.generation_id)
