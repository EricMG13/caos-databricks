"""Vendor-derived realistic canonical Markdown for the LITE route (Task 3.4a).

`tests/canonical_fixtures.py` proves the wire and identity contract with a
handoff whose every appendix cell reads `Recorded source p1` -- deliberately
generic, because that suite is about structure, not content. Slice 3.4a of
Task 3.4 needs handoffs realistic enough to prove the LITE route's own rules:
CP-L10's six canonical topics carrying policy-valid materiality / evidence
status / disposition values with one disclosed conflict, and CP-5 naming the
upstream handoffs it traces and grading them.

Register columns and minimum row counts are read from the vendor's own
`completeness_check.load_contract` (never hand-typed); CP-L10's canonical
topic order and set come from its own semantic rule
(`cp_l10.topic_ids_complete`) in its verified `SKILL.md`, cross-checked here
against the separately declared `payload_contract.topic_ids` list so the two
places the vendor states the same set cannot silently drift; materiality,
evidence-status and disposition values come from the CP LITE analysis
policy's own machine-readable JSON block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from canonical_fixtures import (
    AUTHORED,
    BUNDLE,
    CATALOG,
    CONTRACT,
    PINNED,
    QUOTE,
    RUN,
    RUN_PRICE,
    conforming_rows,
    fields_from_prompt,
    identity,
    skill,
    wire,
)

from caos.methodology.bundle import verified_bytes
from caos.methodology.handoff import (
    HostIdentity,
    expected_filename,
    invocation_fields,
)
from caos.pricing import ModelPrice
from caos.provider import Completion, encode_request

# Whole words, no punctuation: must match whole tokens in the delivered
# evidence exactly (invariant 11 / §41.3's word-boundary quoting rule).
CONFLICT_TEXT = (
    "Reported leverage conflicts across the covenant certificate and the "
    "earnings release"
)

_UPSTREAM_MODULES = ("CP-0", "CP-L10")
_GRADE_BY_QA = {"Passed": "Low", "Restricted": "Medium", "Blocked": "High"}


# --------------------------------------------------------------------------
# Vendor-derived canonical topic ids (never hand-typed)
# --------------------------------------------------------------------------


def _semantic_topic_ids(skill_text: str) -> tuple[str, ...]:
    """CP-L10's topic set from its own `cp_l10.topic_ids_complete` rule."""
    match = re.search(
        r"\*\*rule_id\*\*:\s*cp_l10\.topic_ids_complete\s*\r?\n"
        r"\s*-\s*\*\*values\*\*:\s*(?P<values>.+)",
        skill_text,
    )
    if match is None:
        msg = (
            "CP-L10 SKILL.md no longer states cp_l10.topic_ids_complete -- "
            "the semantic rule this fixture reads has moved or been renamed"
        )
        raise AssertionError(msg)
    return tuple(v.strip() for v in match.group("values").split(";") if v.strip())


def _payload_topic_ids(skill_text: str) -> tuple[str, ...]:
    """The same set, declared separately under `payload_contract.topic_ids`."""
    match = re.search(r"\*\*topic_ids\*\*:\s*(?P<values>.+)", skill_text)
    if match is None:
        msg = "CP-L10 SKILL.md no longer declares payload_contract.topic_ids"
        raise AssertionError(msg)
    return tuple(v.strip() for v in match.group("values").split(";") if v.strip())


def canonical_topic_ids() -> tuple[str, ...]:
    """CP-L10's six canonical topics, in the vendor's own order.

    Read from two independently anchored places in the verified `SKILL.md`
    (the semantic rule and the payload contract's own topic list) and refused
    if they disagree, so a future edit that moves one but not the other is
    caught here rather than baked into a fixture nobody re-checks.
    """
    text = skill("CP-L10").decode()
    semantic = _semantic_topic_ids(text)
    payload = _payload_topic_ids(text)
    if semantic != payload:
        msg = (
            f"CP-L10 SKILL.md's semantic rule {semantic!r} disagrees with its "
            f"payload_contract.topic_ids {payload!r}"
        )
        raise AssertionError(msg)
    return semantic


# --------------------------------------------------------------------------
# The CP LITE analysis policy's own value sets (never hand-typed)
# --------------------------------------------------------------------------


def _policy_values() -> dict[str, Any]:
    """The policy's normative-constants JSON block, from verified bytes."""
    text = verified_bytes(
        BUNDLE,
        "CP-L10",
        "references/CP-L10_CP_LITE_ANALYSIS_POLICY_v1.md",
    ).decode()
    match = re.search(r"```json\s*(?P<body>\{.*?\})\s*```", text, re.DOTALL)
    if match is None:
        msg = (
            "CP-L10_CP_LITE_ANALYSIS_POLICY_v1.md no longer carries its "
            "normative-constants JSON block"
        )
        raise AssertionError(msg)
    return dict(json.loads(match.group("body")))


def policy_materiality_values() -> tuple[str, ...]:
    return tuple(_policy_values()["materiality_values"])


def policy_evidence_status_values() -> tuple[str, ...]:
    return tuple(_policy_values()["evidence_status_values"])


def policy_disposition_values() -> tuple[str, ...]:
    return tuple(_policy_values()["disposition_values"])


# --------------------------------------------------------------------------
# Markdown builders
# --------------------------------------------------------------------------


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


def _t8_rows(readiness: dict[str, str]) -> list[list[str]]:
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
                "Source p1",
                "Current handoff",
                status,
                "Relevant source p1",
            ]
        )
    return rows


def cp_l10_topic_rows(*, conflict_text: str = CONFLICT_TEXT) -> list[list[str]]:
    """TL10.2's six topic rows, evidence-proportionate per the LITE policy.

    Exactly one `HIGH`-materiality topic is `CONFLICTED` / `GAP_ONLY` and
    carries `conflict_text`, per the policy's own
    `high_missing_or_conflicted_rule` (a `HIGH` topic with `MISSING` or
    `CONFLICTED` evidence must be `GAP_ONLY`).
    """
    materiality = policy_materiality_values()
    evidence_status = policy_evidence_status_values()
    disposition = policy_disposition_values()
    for value in ("HIGH", "MEDIUM", "LOW"):
        assert value in materiality, materiality
    for value in ("SUFFICIENT", "PARTIAL", "CONFLICTED"):
        assert value in evidence_status, evidence_status
    for value in ("DEEPEN", "SUMMARIZE", "GAP_ONLY"):
        assert value in disposition, disposition

    plan = {
        "SOURCE_BASIS": (
            "MEDIUM",
            "SUFFICIENT",
            "SUMMARIZE",
            "1",
            "Earnings release and covenant compliance certificate cover the "
            "same reporting period and consolidation perimeter.",
        ),
        "EARNINGS_MARGIN_CHANGE": (
            "HIGH",
            "SUFFICIENT",
            "DEEPEN",
            "2",
            "Revenue and margin both improved period over period per the "
            "earnings release.",
        ),
        "CASH_CONVERSION": (
            "MEDIUM",
            "PARTIAL",
            "SUMMARIZE",
            "4",
            "Operating cash flow was disclosed; free cash flow needs the "
            "CP-1 working capital detail.",
        ),
        "LEVERAGE_COVERAGE": (
            "HIGH",
            "CONFLICTED",
            "GAP_ONLY",
            "1",
            conflict_text + ". Missing evidence is the reconciled leverage "
            "calculation; required source is the credit agreement leverage "
            "definition; full upgrade module CP-1B.",
        ),
        "LIQUIDITY_MATURITIES": (
            "LOW",
            "SUFFICIENT",
            "SUMMARIZE",
            "5",
            "Cash and available facilities exceed near-term maturities per "
            "the covenant compliance certificate.",
        ),
        "KPI_COMPARABILITY": (
            "MEDIUM",
            "PARTIAL",
            "SUMMARIZE",
            "3",
            "Adjusted EBITDA definition was not restated this period; "
            "comparability against the prior period is partial.",
        ),
    }
    topics = canonical_topic_ids()
    if set(plan) != set(topics):
        msg = f"fixture plan {sorted(plan)} != vendor topics {topics}"
        raise AssertionError(msg)
    rows = []
    for topic_id in topics:
        mat, status, disp, rank, summary = plan[topic_id]
        rows.append(
            [
                topic_id,
                topic_id.replace("_", " ").title(),
                "CP-1; CP-1B",
                mat,
                status,
                disp,
                rank,
                summary,
                "Source p1",
                "CP-1B" if disp in {"DEEPEN", "GAP_ONLY"} else "",
            ]
        )
    return rows


def cp5_t51_rows(
    *, upstream_modules: tuple[str, ...] = _UPSTREAM_MODULES
) -> list[list[str]]:
    """T5.1 rows naming each upstream by its own expected filename and run id."""
    rows = []
    for module_id in upstream_modules:
        filename = expected_filename(identity(module_id))
        rows.append(
            [
                module_id,
                f"{filename} / {RUN}",
                "Full",
                "Sufficient",
                "Conforming",
                "Passed",
                f"Traced from the accepted {module_id} handoff.",
            ]
        )
    return rows


def cp5_t53_rows(*, conflict_text: str = CONFLICT_TEXT) -> list[list[str]]:
    """T5.3 carrying the CP-L10 leverage conflict unresolved."""
    return [
        [
            "Medium",
            "CP-L10",
            "Leverage coverage screening disposition",
            "Leverage definition not reconciled across delivered sources",
            conflict_text,
            "Obtain the covenant leverage definition from the CP-1B upgrade",
            "Restricted pending a FULL leverage reconciliation",
        ]
    ]


def cp5_t5b6_rows(*, qa_status: str) -> list[list[str]]:
    """T5B.6's traceability grade, consistent with `qa_status`."""
    grade = _GRADE_BY_QA.get(qa_status, "Medium")
    return [
        [
            grade,
            f"Traceability grade: {qa_status}",
            "Leverage coverage evidence conflict",
            "Confirmed",
            "Determines whether committee may rely on the leverage screen",
            "Resolve the leverage definition conflict in the CP-1B upgrade",
            "CP-L10 handoff",
        ]
    ]


def _body_note(quotes: tuple[str, ...]) -> str:
    return " ".join(
        f"{quote} was recorded in the delivered evidence." for quote in quotes
    )


@dataclass(frozen=True)
class LiteHandoffKnobs:
    """The realistic-fixture knobs `realistic_handoff_markdown` accepts.

    Grouped so the builder keeps a small parameter count: `qa_status` picks
    the authored front matter `tests/canonical_fixtures.py` already proved
    validates (`AUTHORED`); `readiness` sets CP-0's T8 rows; `conflict_text`
    is the disclosed CP-L10 leverage conflict, carried verbatim into CP-5's
    T5.3 and T5B.6 when the identity's module is CP-5.
    """

    fields: dict[str, Any] | None = None
    qa_status: str = "Passed"
    conflict_text: str = CONFLICT_TEXT
    readiness: dict[str, str] | None = None
    upstream_modules: tuple[str, ...] = _UPSTREAM_MODULES
    quotes: tuple[str, ...] = (QUOTE,)


def _register_rows(
    ident: HostIdentity, register_id: str, spec: dict[str, Any], knobs: LiteHandoffKnobs
) -> list[list[str]]:
    if ident.module_id == "CP-L10" and register_id == "TL10.2":
        return cp_l10_topic_rows(conflict_text=knobs.conflict_text)
    if ident.module_id == "CP-5" and register_id == "T5.1":
        return cp5_t51_rows(upstream_modules=knobs.upstream_modules)
    if ident.module_id == "CP-5" and register_id == "T5.3":
        return cp5_t53_rows(conflict_text=knobs.conflict_text)
    if ident.module_id == "CP-5" and register_id == "T5B.6":
        return cp5_t5b6_rows(qa_status=knobs.qa_status)
    quote = knobs.quotes[0] if knobs.quotes else QUOTE
    rules = CONTRACT.completeness_check.load_contract(
        skill(ident.module_id).decode(), ident.module_id
    )
    return conforming_rows(register_id, spec, rules, lambda _c, _n: quote)


def realistic_handoff_markdown(
    ident: HostIdentity, knobs: LiteHandoffKnobs | None = None
) -> bytes:
    """A handoff the vendor validators accept for `ident`, filled with
    vendor-derived realistic content rather than a single repeated cell.
    """
    knobs = knobs or LiteHandoffKnobs()
    host_fields = (
        knobs.fields if knobs.fields is not None else invocation_fields(CONTRACT, ident)
    )
    front: dict[str, Any] = {
        **host_fields,
        "confidence_score": 90,
        "confidence_band": "High",
        "committee_status": "Draft Only",
        "limitation_flags": [],
        "validation_warnings": [],
        "downstream_consumers": [],
        **AUTHORED[knobs.qa_status],
        "qa_status": knobs.qa_status,
    }
    rules = CONTRACT.completeness_check.load_contract(
        skill(ident.module_id).decode(), ident.module_id
    )
    appendix = "### Analytical appendix — complete canonical registers\n\n"
    for register_id, spec in rules["registers"].items():
        appendix += "#### " + register_id + "\n\n"
        if ident.module_id == "CP-0" and register_id == "T8":
            appendix += _table(
                CONTRACT.navigation.NEW_HEADERS, _t8_rows(knobs.readiness or {})
            )
            continue
        rows = _register_rows(ident, register_id, spec, knobs)
        appendix += _table(spec["columns"] or ["Evidence"], rows)
    for table_id in rules["unconditional_stable_tables"]:
        stable = _table(["source_locator"], [["Source p1"]])
        appendix += "<!-- table-id: " + table_id + " -->\n" + stable
    headings = CONTRACT.validate_handoff.CANONICAL_HEADINGS
    note = _body_note(knobs.quotes)
    body = "".join(
        "## " + h + "\n\n" + (appendix if h == "Analysis" else note + "\n\n")
        for h in headings
    )
    return ("---\n" + _yaml(front) + "\n---\n" + body).encode()


@dataclass
class RealisticLiteCompletions:
    """A provider answering with realistic LITE handoffs, keyed by module.

    Mirrors `tests.canonical_fixtures.CanonicalCompletions`'s shape (prompts,
    answers, bodies recorded verbatim) but fills content the way
    `realistic_handoff_markdown` does instead of one repeated cell, so a
    caller driving a real route through this provider sees the same
    vendor-derived registers a standalone fixture test does.
    """

    source_id: UUID
    charge: Decimal | None = Decimal("0.0000041")
    model: str = "a-model/for-the-test"
    price: ModelPrice | None = RUN_PRICE
    generation_id: str = "gen-lite-realistic-test"
    qa_status: str = "Passed"
    qa_by_module: dict[str, str] = field(default_factory=dict)
    readiness: dict[str, str] = field(default_factory=dict)
    conflict_text: str = CONFLICT_TEXT
    quotes: tuple[str, ...] = (QUOTE,)
    prompts: list[str] = field(default_factory=list)
    answers: list[bytes] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        assert json_object
        self.prompts.append(prompt)
        fields = fields_from_prompt(prompt)
        module_id = str(fields["module_id"])
        qa = self.qa_by_module.get(module_id, self.qa_status)
        markdown = realistic_handoff_markdown(
            identity(module_id),
            LiteHandoffKnobs(
                fields=fields,
                qa_status=qa,
                conflict_text=self.conflict_text,
                readiness=self.readiness,
                quotes=self.quotes,
            ),
        )
        self.answers.append(markdown)
        citations = [
            {"source_id": str(self.source_id), "page": 1, "matched_text": quote}
            for quote in self.quotes
        ]
        self.bodies.append(wire(markdown, citations))
        return Completion(self.bodies[-1], self.charge, self.generation_id)


__all__ = [
    "CATALOG",
    "CONFLICT_TEXT",
    "LiteHandoffKnobs",
    "RealisticLiteCompletions",
    "canonical_topic_ids",
    "cp5_t5b6_rows",
    "cp5_t51_rows",
    "cp5_t53_rows",
    "cp_l10_topic_rows",
    "policy_disposition_values",
    "policy_evidence_status_values",
    "policy_materiality_values",
    "realistic_handoff_markdown",
]
