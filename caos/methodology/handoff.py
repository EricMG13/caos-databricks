"""The canonical Markdown handoff: vendor conformance, then host identity (§41).

A module's output is one UTF-8 Markdown file whose SHA-256 is the lineage hash
downstream handoffs name. The vendor's validators decide whether it conforms;
this module decides whether it is *this* invocation's handoff. Every field the
host owns is compared type-exactly against what the host would have written,
because a provider-claimed identity never survives (invariant 3).

Pure: no clock, and no I/O but digest-verified blob reads (`read_record`'s two,
`stored_lineage`'s one per direct upstream record the caller has not verified).
The closed provider transport and the host record beside the Markdown live
here too, so one module owns the handoff's shape end to end. Every refusal is
a typed code raised outside the handler that caught the vendor's exception, so
neither the exception chain nor the refusal carries vendor text, which can
quote the document (invariant 2).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, NoReturn
from uuid import UUID

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText, hides_text
from caos.digest import canonical_json
from caos.evidence.citations import AnchoredCitation, Citation, Rect
from caos.graph.route import MODEL_MODULE
from caos.methodology.vendor import VendorContract
from caos.refusals import Refusal, RefusalCode

# Both sets are enforced together at one point, `gates.require_adapter_route`
# (execution input and acceptance); the readers below check modules alone.
# Extending the adapter means extending both, with the contract tests.
ADAPTER_MODULES = frozenset(
    {
        "CP-0",
        "CP-L10",
        "CP-5",
        "CP-1",
        "CP-4",
        "CP-1C",
        "CP-2A",
        "CP-3D",
        "CP-2",
        "CP-2G",
        "CP-1A",
        "CP-1D",
        "CP-2E",
        "CP-2H",
        "CP-4C",
        "CP-2D",
        "CP-1B",
        "CP-3",
        MODEL_MODULE,
        "CP-8",
        "CP-DR",
        "CP-3C",
        "CP-6",
    }
)
# The catalog pathways a contract test proves end to end (REPAIR_PLAN Phase 3
# work item 6): adapter modules on any other pathway stay disabled.
ADAPTER_ROUTES = frozenset(
    {
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_DECISION_LEDGER"),
        ("FULL_CREDIT_32", "DECISION_LEDGER"),
        # CP-0 -> CP-DR (§96), once build 6a5f1050's `parse_t8` read the CP-DR
        # row CP-0's contract permits (`tests/test_lite_deep_research_route.py`).
        ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH"),
        # The same CP-0 -> CP-DR contract under FULL identity, proven without
        # a provider or qualification claim (`test_full_deep_research_route`).
        ("FULL_CREDIT_32", "DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "LIQUIDITY_REVIEW"),
        ("FULL_CREDIT_32", "EARNINGS_UPDATE"),
        ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
        ("FULL_CREDIT_32", "COVENANT_REFINANCING"),
        ("FULL_CREDIT_32", "PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "MARKET_DISLOCATION"),
        ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING"),
        ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING"),
        ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN"),
        ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING"),
    }
)
GATE_MODULE = "CP-0"
# The one module a pinned research brief reaches (§96): its identity carries
# the host-bound brief, and its front matter the fields the vendor's own
# preparer emits from one.
RESEARCH_MODULE = "CP-DR"
# The research front-matter fields the host owns for CP-DR: exactly those the
# vendor's `prepare_invocation.prepare` writes from a linked brief. The three
# the model authors (`coverage_score`, `research_status`,
# `research_stop_reason`) are the rest of the vendor's `CP_DR_FIELDS`.
RESEARCH_HOST_FIELDS = (
    "research_mode",
    "research_question",
    "approved_plan_hash",
    "scope_type",
    "scope_key",
    "subject_name",
    "source_mode",
)
ZERO_SHA256 = "0" * 64
# The vendor's frozen reader limits (CREDIT_OS_RUNTIME_LIMITS_v1).
MAX_FILE_BYTES = 26_214_400
MAX_FRONTMATTER_BYTES = 262_144
MAX_LINE_BYTES = 65_536
# The longest run of spaces or tabs any line of a handoff may carry.
#
# The vendor's heading expressions are `^ {0,3}##(?!#)[ \t]+(.+?)[ \t]*$` and
# its sibling, which backtrack quadratically on a heading padded with a long
# whitespace run: 60,000 spaces measured about 60 s per validation, with the
# GIL held for about 40 s of it, and an accepted CP-0 is re-validated on every
# node pass and every read of the Run section (AI-1/SA-C5). Invariant 4 forbids
# editing the vendor file, so the line is refused here, before any vendor
# validator sees the text -- on model output and on stored bytes alike, because
# `validate_markdown` is the one door both go through. 256 is far past any
# indent a conforming handoff's tables or code fences use, and far below the
# 65,536-byte line bound that was the only thing above it.
MAX_WHITESPACE_RUN = 256
# The longest run of spaces or tabs, and of `#`, a heading's title may carry
# (EV-2). The bound above holds one run; the heading expressions backtrack over
# *every* run of a title, and the vendor's `_heading_text` (`[ \t]+#+[ \t]*$`)
# over every `#` run after one, so a 64 KB heading of 256-space runs cost
# 0.06 s per match and a conforming handoff of such lines seconds per
# validation, GIL held, on every read. Held to eight, a title costs a few steps
# a character whatever it is built of. Every heading the goldens, the fixtures
# and the bundle carry has runs of one or two.
MAX_HEADING_RUN = 8
# A line those expressions read: up to three spaces, then `##`.
_HEADING_LINE = re.compile(r"^ {0,3}##[^\n]*", re.MULTILINE)
# One T8 `Why now / blocker` cell, which the vendor's own contract asks a module
# to state "briefly". Bounded here because the cell reaches a pinned record and
# the wire, and nothing upstream bounds it.
MAX_BLOCKER_CHARS = 512
# Characters BoundaryText keeps that still make one text read as two. Public
# because the prompt builder must drop what this refuses, so that a filename
# the host renders can always be quoted back (invocation._printable).
INVISIBLE = frozenset("\u2028\u2029\ufeff")
_UPGRADE_KEYS = ("credit_os_parent_run_id", "credit_os_upgrade_source_sha256")


@dataclass(frozen=True, slots=True)
class UpstreamRef:
    """One accepted upstream handoff as the host recorded it."""

    route_node_id: str
    module_id: str
    run_id: str
    period: str
    sha256: str


@dataclass(frozen=True, slots=True)
class LineageRef:
    """One accepted ancestor handoff and the host record beside it (§45.4)."""

    route_node_id: str
    module_id: str
    artifact_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class HostIdentity:
    """Everything the host owns about one invocation. None of it is the model's."""

    run_id: str
    profile_id: str
    selection_id: str
    route_node_id: str
    module_id: str
    module_name: str
    issuer_id: str
    issuer_name: str
    reporting_period: str
    analysis_date: str
    ordinal: int
    authority_bundle_sha256: str
    upstream: tuple[UpstreamRef, ...]
    # CP-DR only (§96): the pinned brief with its host bindings written in --
    # this run's vendor id, the accepted CP-0's digest, the bundle's authority
    # digest -- as canonical JSON. None for every other module, and absent from
    # a serialised record when None, so no record written before it moved.
    research_brief: str | None = None


@dataclass(frozen=True, slots=True)
class Projections:
    """What the host reads back from a conforming handoff. Model-authored."""

    module_id: str
    qa_status: str
    committee_status: str
    confidence_score: int
    confidence_band: str
    limitation_flags: tuple[str, ...]
    validation_warnings: tuple[str, ...]
    downstream_consumers: tuple[str, ...]
    readiness: tuple[tuple[str, str], ...]
    # `(module_id, why_now_or_blocker)` for every T8 row the gate did not clear --
    # CONDITIONAL or BLOCKED. That cell is where CP-0 names the source the
    # effective set does not carry (§61), and so the only thing that tells a
    # reader of a run ended BLOCKED by readiness which source would discharge it.
    # Model-authored and vendor-required: bounded at `MAX_BLOCKER_CHARS` through
    # `BoundaryText`, never logged, empty for every row the gate cleared and for
    # every module but the gate. Absent from a serialised record when empty, so
    # that adding it moved no record's bytes (`record_bytes`).
    blockers: tuple[tuple[str, str], ...]
    # The pathway's catalog scope; `SCREENING_ONLY` is never committee clearance,
    # whatever `committee_status` the model wrote.
    decision_scope: str


def _or_refuse[T](code: RefusalCode, call: Callable[[], T]) -> T:
    with suppress(Exception):  # any failure inside is this refusal
        return call()
    # Raised after the handler has closed, so `__context__` holds no vendor or
    # document text.
    raise Refusal(code)


def expected_filename(identity: HostIdentity) -> str:
    compact = identity.analysis_date.replace("-", "")
    return f"{identity.issuer_id}_{identity.module_id}_{compact}.md"


def research_brief_of(identity: HostIdentity) -> dict[str, Any]:
    """The bound brief a CP-DR identity carries, or `HANDOFF_IDENTITY_MISMATCH`
    for a module that carries one and is not CP-DR, a CP-DR that carries none,
    or text that is not one JSON object."""
    if (identity.research_brief is None) != (identity.module_id != RESEARCH_MODULE):
        raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)
    brief = _or_refuse(
        RefusalCode.HANDOFF_IDENTITY_MISMATCH,
        lambda: strict_json(str(identity.research_brief)),
    )
    if not isinstance(brief, dict):
        raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)
    return brief


def research_fields(contract: VendorContract, identity: HostIdentity) -> dict[str, Any]:
    """The research front matter for a CP-DR invocation: the fields the vendor's
    `prepare_invocation.prepare` emits from a linked brief, and the plan hash
    computed by the vendor's own `envelope.digest` over the bound brief
    (`tests/test_handoff_invocation.py` holds the two equal against the
    vendor's preparer). Empty for every other module."""
    if identity.module_id != RESEARCH_MODULE:
        if identity.research_brief is not None:
            raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)
        return {}
    brief = research_brief_of(identity)
    return _or_refuse(
        RefusalCode.HANDOFF_IDENTITY_MISMATCH,
        lambda: {
            "research_mode": brief["mode"],
            "research_question": "; ".join(q["question"] for q in brief["questions"]),
            "approved_plan_hash": "sha256:" + contract.envelope.digest(brief),
            **{
                key: brief[key]
                for key in ("scope_type", "scope_key", "subject_name", "source_mode")
            },
        },
    )


def invocation_fields(
    contract: VendorContract, identity: HostIdentity
) -> dict[str, Any]:
    """The host-owned front matter for this invocation, built by the vendor envelope."""
    research = research_fields(contract, identity)
    upstream = sorted(identity.upstream, key=lambda ref: ref.route_node_id)
    gate = [ref.sha256 for ref in upstream if ref.module_id == GATE_MODULE]
    envelope = _or_refuse(
        RefusalCode.HANDOFF_IDENTITY_MISMATCH,
        lambda: contract.envelope.build(
            run_id=identity.run_id,
            profile_id=identity.profile_id,
            selection_id=identity.selection_id,
            route_node_id=_envelope_node(identity),
            module_id=identity.module_id,
            module_name=identity.module_name,
            expected_output_filename=expected_filename(identity),
            authority_bundle_sha256=identity.authority_bundle_sha256,
            accepted_cp0_sha256=gate[0] if gate else ZERO_SHA256,
            required_upstream_digests={
                ref.route_node_id: ref.sha256 for ref in upstream
            },
            ordinal=identity.ordinal,
        ),
    )
    if identity.module_id == MODEL_MODULE:
        # The vendor grammar stops at stage 99. Validate its shared envelope
        # fields there, then bind our declared stage-100 host occurrence.
        envelope["route_node_id"] = identity.route_node_id
        seed = "\x00".join(
            (identity.run_id, identity.route_node_id, str(identity.ordinal))
        )
        envelope["attempt_id"] = "ATT-CP-CF-" + sha256(seed.encode()).hexdigest()[:16]
    return {
        "module_id": identity.module_id,
        "module_name": identity.module_name,
        "issuer_id": identity.issuer_id,
        "issuer_name": identity.issuer_name,
        "run_id": identity.run_id,
        "reporting_period": identity.reporting_period,
        "analysis_date": identity.analysis_date,
        "credit_os_run_id": identity.run_id,
        "credit_os_profile_id": identity.profile_id,
        "credit_os_selection_id": identity.selection_id,
        "credit_os_authority_bundle_sha256": identity.authority_bundle_sha256,
        "credit_os_attempt_id": envelope["attempt_id"],
        "credit_os_route_node_id": identity.route_node_id,
        "credit_os_invocation_sha256": _or_refuse(
            RefusalCode.HANDOFF_IDENTITY_MISMATCH,
            lambda: contract.envelope.digest(envelope),
        ),
        "upstream_artifacts_used": [
            {
                "module_id": ref.module_id,
                "run_id": ref.run_id,
                "period": ref.period,
                "sha256": ref.sha256,
            }
            for ref in upstream
        ],
        **research,
    }


def _envelope_node(identity: HostIdentity) -> str:
    if identity.module_id != MODEL_MODULE:
        return identity.route_node_id
    expected = f"RN-{identity.profile_id}-{identity.selection_id}-100-CP-CF"
    if identity.route_node_id != expected:
        raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)
    return f"RN-{identity.profile_id}-{identity.selection_id}-99-CP-CF"


def _text(markdown: bytes) -> str:
    """The handoff's text, or `HANDOFF_MALFORMED`: the bytes the vendor's
    validators are allowed to meet.

    Everything here is a bound on what the *host* will hand on -- size, LF-only
    lines, the invisible separators, text no reader can see, and the whitespace
    run the vendor's own expressions cannot read in linear time. It runs before
    any vendor call and on stored bytes as well as model output.
    """
    malformed = Refusal(RefusalCode.HANDOFF_MALFORMED)
    if len(markdown) > MAX_FILE_BYTES:
        raise malformed
    try:
        text = markdown.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    # Canonical Markdown is LF-only; a CR would let the host and the vendor
    # disagree about where lines, and so the front matter, end.
    if text is None or "\r" in text or INVISIBLE.intersection(text):
        raise malformed
    # Tags, a zero-width space, a word joiner: text a reviewer of the committee
    # page cannot see and the next module reads as an instruction (AI-2).
    if hides_text(text):
        raise malformed
    # One C-level substring search, whatever the document does. Tabs are read
    # as spaces so that a run mixing the two is one run, and `str.replace`
    # gives back the same object when there is no tab to replace.
    spaced = text.replace("\t", " ")
    if " " * (MAX_WHITESPACE_RUN + 1) in spaced or _heading_backtracks(text, spaced):
        raise malformed
    try:
        clean = BoundaryText.of(text, limit=len(text)).value == text
    except Refusal:
        clean = False
    lines = text.split("\n")
    closing = (
        lines.index("---", 1) if lines[:1] == ["---"] and "---" in lines[1:] else 0
    )
    if (
        not clean
        or any(len(line.encode()) > MAX_LINE_BYTES for line in lines)
        or len("\n".join(lines[: closing + 1]).encode()) > MAX_FRONTMATTER_BYTES
    ):
        raise malformed
    return text


def _heading_backtracks(text: str, spaced: str) -> bool:
    """Whether a heading's title carries a run the vendor's heading expressions
    cannot read in linear time (EV-2): more than `MAX_HEADING_RUN` spaces and
    tabs, or `#`.

    The title is what follows the line's `#` marker, less its trailing spaces
    and tabs, which `[ \\t]*$` reads once. `spaced` is `text` with its tabs
    read as spaces. Two substring searches first, so a handoff with no such
    run anywhere never reaches the loop over its headings.
    """
    long_space = " " * (MAX_HEADING_RUN + 1)
    long_hash = "#" * (MAX_HEADING_RUN + 1)
    if long_space not in spaced and long_hash not in text:
        return False
    for heading in _HEADING_LINE.finditer(text):
        # `rstrip(" ")`, not `rstrip()`: the expressions forgive only spaces
        # and tabs at the end, and a run before a no-break space is not there.
        title = heading.group().lstrip(" ").lstrip("#").replace("\t", " ").rstrip(" ")
        if long_space in title or long_hash in title:
            return True
    return False


def _same(left: object, right: object) -> bool:
    """Equal and of the same JSON type: `12345` is not `"12345"`, `true` is not `1`."""
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _declared_keys(contract: VendorContract, module_id: str) -> frozenset[str]:
    vendor = contract.validate_handoff
    research = (
        (*vendor.CP_DR_FIELDS, *RESEARCH_HOST_FIELDS)
        if module_id == RESEARCH_MODULE
        else ()
    )
    return frozenset(
        (
            *vendor.REQUIRED_FIELDS,
            *vendor.ISSUER_FIELDS,
            *contract.envelope.RUN_ANCHOR_FIELDS,
            *contract.envelope.ECHO_FIELDS,
            *_UPGRADE_KEYS,
            *research,
        )
    )


# The two T8 verdicts that stop a module running, and so the two whose
# `why_now_or_blocker` cell states a condition rather than orientation. The words
# are the vendor's (`navigation.RUNNABLE`'s complement over CP-0's four statuses);
# the host reads them and invents none.
UNCLEARED_READINESS = frozenset({"CONDITIONAL", "BLOCKED"})


def _blocker(cell: str) -> str:
    """One T8 blocker cell across the boundary: bounded, NFC, no controls.

    `HANDOFF_MALFORMED` past the bound, raised outside the handler so neither
    the chain nor the refusal carries the cell's text (invariant 2).
    """
    return _or_refuse(
        RefusalCode.HANDOFF_MALFORMED,
        lambda: BoundaryText.of(cell, limit=MAX_BLOCKER_CHARS).value,
    )


def _readiness(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    text: str,
    gate_expects: frozenset[str],
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """The gate's `(module, readiness)` rows, and the blocker cell of each row it
    did not clear. Both sorted by module; the second is a subset of the first's
    modules and is empty when every one of them may run."""
    nav = contract.navigation
    rows = _or_refuse(
        RefusalCode.HANDOFF_INCOMPLETE,
        lambda: nav.parse_t8(text, nav.validate_catalog(catalog)),
    )
    readiness = tuple(sorted((row.module_id, row.readiness) for row in rows))
    if frozenset(module for module, _ in readiness) != gate_expects:
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    blockers = tuple(
        sorted(
            (row.module_id, _blocker(row.why_now_or_blocker))
            for row in rows
            if row.readiness in UNCLEARED_READINESS
        )
    )
    return readiness, blockers


def _decision_scope(catalog: Mapping[str, Any], identity: HostIdentity) -> str:
    try:
        pathway = catalog["profiles"][identity.profile_id]["pathways"]
        scope = pathway[identity.selection_id]["decision_scope"]
    except (KeyError, TypeError):
        scope = None
    if not isinstance(scope, str) or not scope:
        raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)
    return scope


def validate_markdown(  # noqa: PLR0913 -- the brief's pure signature
    contract: VendorContract,
    catalog: Mapping[str, Any],
    skill: bytes,
    markdown: bytes,
    *,
    identity: HostIdentity,
    gate_expects: frozenset[str],
) -> Projections:
    """Refuse anything but this invocation's conforming handoff; project the rest.

    Order is the contract: bytes, vendor structure, declared keys, host identity,
    register completeness, gate readiness, then `qa_status`. A validated Blocked
    handoff refuses `HANDOFF_BLOCKED` only once it is proven to be this
    invocation's, so the caller can record it as a diagnostic outcome.

    `skill` is the module's verified `SKILL.md`. Since §92 the vendor's own
    checker enforces its `semantic_rules` and fixture markers, and its
    validator refuses a `committee_status` the pathway's `decision_scope` does
    not permit -- the host hands it the scope it already reads from the
    catalog and adds no rule of its own. The vendor's
    `required_payload_fields` judge a JSON payload the canonical adapter
    never receives, so nothing here calls `check_payload`.
    """
    if identity.module_id not in ADAPTER_MODULES:
        raise Refusal(RefusalCode.HANDOFF_MODULE_UNSUPPORTED)
    text = _text(markdown)
    scope = _decision_scope(catalog, identity)
    result = _or_refuse(
        RefusalCode.HANDOFF_MALFORMED,
        lambda: contract.validate_handoff.validate_text(text, decision_scope=scope),
    )
    if result.errors or result.fields is None:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    fields: dict[str, Any] = result.fields
    if not _declared_keys(contract, identity.module_id).issuperset(fields):
        raise Refusal(RefusalCode.HANDOFF_UNDECLARED_FIELD)

    host = invocation_fields(contract, identity)
    if any(
        key not in fields or not _same(fields[key], value)
        for key, value in host.items()
    ) or any(fields.get(key) is not None for key in _UPGRADE_KEYS):
        raise Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH)

    violations = (
        []
        if identity.module_id == MODEL_MODULE
        else _or_refuse(
            RefusalCode.HANDOFF_INCOMPLETE,
            lambda: contract.completeness_check.check(
                skill.decode("utf-8"), text, identity.module_id
            )[0],
        )
    )
    if violations:
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    if identity.module_id == MODEL_MODULE:
        from caos.methodology.forecast import forecast_projection

        forecast_projection(markdown)
        if fields["committee_status"] not in {"Draft Only", "Restricted"}:
            raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    readiness, blockers = (
        _readiness(contract, catalog, text, gate_expects)
        if identity.module_id == GATE_MODULE
        else ((), ())
    )
    if fields["qa_status"] == "Blocked":
        raise Refusal(RefusalCode.HANDOFF_BLOCKED)
    if identity.module_id == RESEARCH_MODULE:
        # The vendor's research contract (§96): TDR.1 is the locked brief's
        # questions exactly, every finding cites its own question's evidence,
        # ANSWERED rests on primary or attributed evidence or two independent
        # families, and coverage and status follow from the count. After the
        # Blocked check because a Blocked dossier is held to none of it -- it
        # is recorded and unaccepted, as the vendor's SKILL.md says.
        brief = research_brief_of(identity)
        _or_refuse(
            RefusalCode.HANDOFF_INCOMPLETE,
            lambda: contract.research.validate_dossier(
                SimpleNamespace(fields=fields, text=text), brief
            ),
        )
    return Projections(
        module_id=identity.module_id,
        qa_status=fields["qa_status"],
        committee_status=fields["committee_status"],
        confidence_score=fields["confidence_score"],
        confidence_band=fields["confidence_band"],
        limitation_flags=tuple(fields["limitation_flags"]),
        validation_warnings=tuple(fields["validation_warnings"]),
        downstream_consumers=tuple(fields["downstream_consumers"]),
        readiness=readiness,
        blockers=blockers,
        decision_scope=scope,
    )


# The closed provider transport (§41.3) and the host record's own format.
WIRE_KEYS = frozenset({"canonical_markdown", "citations"})
WIRE_CITATION_KEYS = frozenset({"source_id", "page", "matched_text"})
RECORD_FORMAT = "caos-canonical-record-v2"
# A body may carry the largest Markdown the vendor reads plus its citations.
MAX_TRANSPORT_CHARS = 2 * MAX_FILE_BYTES
MAX_PAGE = 2**31 - 1  # the store's integer page
# How many citations one handoff may carry. Every citation is checked against
# the body here and anchored in the token index by `verify_citations` later,
# and both are re-done on every replay of the attempt: a few thousand of them
# spent about a minute of worker time each time, which is what makes health
# report `WORKERS_STALE` (AI-5). A real handoff's Evidence Trace carries tens.
MAX_CITATIONS = 512


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    """The host's record beside one accepted Markdown handoff (§41.2).

    Host-written and bound to the Markdown by `artifact_sha256`. It carries no
    model-authored summary and no claims: the Markdown is the authority, and
    `projections` is a sidecar a reader re-derives from it and compares.
    `delivered_authority_digest` binds exactly the authority files the prompt
    carried (§45.1); `lineage` is the whole accepted chain behind the direct
    upstream, ordered by route node id, each pair read from the stored records
    (§45.4).
    """

    artifact_sha256: str
    adapter_version: str
    build_id: str
    manifest_sha256: str
    authority_bundle_sha256: str
    authority_digest: str
    delivered_authority_digest: str
    identity: HostIdentity
    lineage: tuple[LineageRef, ...]
    projections: Projections
    citations: tuple[AnchoredCitation, ...]


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded = dict(pairs)
    if len(decoded) != len(pairs):
        raise ValueError  # a duplicate key: which value is meant is undecidable
    return decoded


def _no_constant(_: str) -> NoReturn:
    raise ValueError  # NaN and the infinities are not JSON


def strict_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_unique, parse_constant=_no_constant)


def _closed(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError
    return value


def _requested(item: object) -> Citation:
    citation = _closed(item, WIRE_CITATION_KEYS)
    source_id, page = citation["source_id"], citation["page"]
    quote = citation["matched_text"]
    # Only the canonical spelling of the id the prompt handed over: a UUID
    # accepts braces, a URN prefix and upper case, none of which the host wrote.
    if not isinstance(source_id, str) or str(UUID(source_id)) != source_id:
        raise ValueError
    if type(page) is not int or not 1 <= page <= MAX_PAGE:
        raise ValueError
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError
    return Citation(source_id=UUID(source_id), page=page, matched_text=quote)


def _transport(body: str) -> tuple[bytes, str, tuple[Citation, ...]]:
    if len(body) > MAX_TRANSPORT_CHARS:
        raise ValueError
    wire = _closed(strict_json(body), WIRE_KEYS)
    text, citations = wire["canonical_markdown"], wire["citations"]
    if not isinstance(text, str) or not isinstance(citations, list) or not citations:
        raise ValueError
    if len(citations) > MAX_CITATIONS:
        raise ValueError
    # A lone surrogate survives `json.loads` and fails here, inside the guard.
    requested = tuple(_requested(c) for c in citations)
    if len(frozenset(requested)) != len(requested):
        raise ValueError  # the same citation twice is not two citations
    return text.encode("utf-8"), text, requested


# CommonMark's backslash escape: a backslash before ASCII punctuation is how
# Markdown writes that mark, so `\"` reads `"` (F149).
# ponytail: code spans keep their backslashes literally; unescaped here too.
_MARKDOWN_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")


def _body_words(text: str) -> list[str]:
    """The Markdown after its front matter, as whitespace tokens, with its
    backslash escapes read as the marks they write.

    The front matter is host identity, not analysis, so no quote may rest on it;
    and a quote matches whole tokens, as anchoring in the evidence does.
    """
    lines = text.split("\n")
    has_front = lines[:1] == ["---"] and "---" in lines[1:]
    closing = lines.index("---", 1) if has_front else 0
    return _MARKDOWN_ESCAPE.sub(r"\1", "\n".join(lines[closing + 1 :])).split()


# Marks a body may put around a quotation without making it a different quote.
# The backtick is Markdown's code span, which a module uses the same way.
_QUOTATION = "\"'`\u2018\u2019\u201c\u201d\u201e\u201f\u00ab\u00bb"
# And what prose puts before and after one: an opening bracket; a closing
# bracket or the sentence's own punctuation (F148).
_OPENING = _QUOTATION + "([{"
_CLOSING = _QUOTATION + ".,;:!?)]}"


def _wears(token: str, word: str, before: str, after: str) -> bool:
    """Whether `token` is `word` with only `before` marks ahead of it and only
    `after` marks behind it: typography, never another word."""
    at = token.find(word)
    while at != -1:
        ahead, behind = token[:at], token[at + len(word) :]
        if all(mark in before for mark in ahead) and all(
            mark in after for mark in behind
        ):
            return True
        at = token.find(word, at + 1)
    return False


def _openings(words: list[str]) -> dict[str, tuple[int, ...]]:
    """Where in the body a quote's first word could begin.

    A run matches at `start` only if `words[start]` is the quote's first word
    as written, or is that word wearing an opening quotation mark, or -- for a
    one-word quote -- wearing one at either end. So the three spellings of each
    body word are the whole key, and the positions under them are a superset of
    the starts `_quoted` has to look at: the predicate below is unchanged, it
    is simply asked about a handful of positions rather than about every
    position in the body once per citation (AI-5).

    A word wearing no quotation mark has one spelling, so an ordinary body
    holds one entry per distinct word and one integer per word.
    """
    found: dict[str, list[int]] = {}
    for position, word in enumerate(words):
        opened = word.lstrip(_OPENING)
        for key in {word, opened, opened.rstrip(_CLOSING)}:
            found.setdefault(key, []).append(position)
    return {key: tuple(positions) for key, positions in found.items()}


def _quoted(words: list[str], openings: dict[str, tuple[int, ...]], quote: str) -> bool:
    """Whether the body quotes this text as whole tokens, typography aside.

    A module writes its Evidence Trace as prose, and prose puts quotation marks
    around a quotation: the body's tokens are then `\u201cRecorded` and `p1\u201d`
    where the quote's are `Recorded` and `p1`. Refusing that is a host defect
    recorded as the model's answer, which is what the CP-L10 attempt of the
    second paid Terra run died of.

    Only the two outer tokens may wear anything, and only typography --
    quotation marks, an opening bracket, a closing bracket or the sentence's
    punctuation (F148) -- so the quote's own words and its internal
    punctuation still have to match exactly.
    Nothing here widens what may be *cited*: `verify_citations` anchors against
    the document's own tokens and is untouched. This decides only whether the
    module quoted, in its own narrative, what it says it quoted.
    """
    wanted = quote.split()
    if not wanted:
        return False
    span = len(wanted)
    return any(
        _carried(words[start : start + span], wanted)
        for start in openings.get(wanted[0], ())
        if start + span <= len(words)
    )


def _carried(window: list[str], wanted: list[str]) -> bool:
    """One run of the body carries the quote: its inner words exactly, and its
    edge words wearing only typography -- quotation marks, an opening bracket
    before, a closing bracket or the sentence's punctuation after (F148)."""
    if window == wanted:
        return True
    if window[1:-1] != wanted[1:-1]:
        return False
    if len(wanted) == 1:
        return _wears(window[0], wanted[0], _OPENING, _CLOSING)
    return _wears(window[0], wanted[0], _OPENING, "") and _wears(
        window[-1], wanted[-1], "", _CLOSING
    )


def parse_response(
    body: str, *, delivered: frozenset[UUID]
) -> tuple[bytes, tuple[Citation, ...]]:
    """The exact Markdown bytes and the citation requests beside them, or a refusal.

    The transport is `{"canonical_markdown", "citations"}` and nothing else, at
    either level, with duplicate keys refused, and at most `MAX_CITATIONS` of
    them. A citation must name delivered evidence and quote the Markdown
    verbatim; one that does not refuses the whole handoff, because the Markdown
    cannot be edited to drop what rests on it.
    Anchoring in the token index needs the store and is the executor's step.
    """
    markdown, text, citations = _or_refuse(
        RefusalCode.HANDOFF_MALFORMED, lambda: _transport(body)
    )
    if any(citation.source_id not in delivered for citation in citations):
        raise Refusal(RefusalCode.CITATION_NOT_DELIVERED)
    words = _body_words(text)
    openings = _openings(words)
    if any(
        not _quoted(words, openings, citation.matched_text) for citation in citations
    ):
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    return markdown, citations


# What a node's one second attempt may carry (D30): at most this many checks,
# each cut to this many characters before it crosses the boundary, naming at
# most this many failed citations by their place in the list (N51).
MAX_FEEDBACK_MESSAGES = 16
MAX_FEEDBACK_CHARS = 512
MAX_FEEDBACK_CITATIONS = 20
_TRANSPORT_JSON = "host transport check: the answer is not one JSON object ({})"
_TRANSPORT_SHAPE = (
    "host transport check: the answer is not the JSON object with only"
    " canonical_markdown and a non-empty list of citations"
)
_ESCAPES = "; a newline or tab inside a JSON string must be written \\n or \\t"


def retry_feedback(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    identity: HostIdentity,
    body: str,
    *,
    skill: bytes = b"",
) -> tuple[str, ...]:
    """The checks a refused answer failed, for the node's one second attempt (D30).

    Three sources, none of them the host restating a vendor rule (invariant
    4): why the answer is not the transport, in the JSON parser's fixed words
    (N50); which citations the body does not carry verbatim, by their place in
    the list (N51); and the vendor's own messages on the stored answer, as
    written -- `validate_handoff`'s, the completeness checker's against the
    module's `skill`, and CP-0's T8 parser's -- so the second attempt is told
    every check it would meet, not only the first. Each vendor line crosses
    `BoundaryText` after a cut to `MAX_FEEDBACK_CHARS`; a line that will not is
    dropped, never repaired. A vendor message may quote a line of the model's
    own answer back to it. These lines go into that one request and nowhere
    else: never a log, a refusal or a row.
    """
    parsed, reason = _transport_or_reason(body)
    if parsed is None:
        return (reason,)
    _markdown, text, citations = parsed
    quote = _quote_line(text, citations)
    lines = [quote] if quote else []
    absent = _absent_ids_line(contract, identity.module_id, text, skill)
    lines += [absent] if absent else []
    lines += _vendor_lines(contract, catalog, identity, text, skill)
    return tuple(lines[:MAX_FEEDBACK_MESSAGES])


def _absent_ids_line(
    contract: VendorContract, module_id: str, text: str, skill: bytes
) -> str | None:
    """Which of the module's register IDs the answer never writes (N52): a
    fact about the answer, not a rule. The checker finds a register by its ID
    and says only that it is missing; CP-1A live wrote every register under a
    human title and its second attempt, told eleven were missing, could not see
    why. At most `MAX_FEEDBACK_CITATIONS` IDs are named, the rest counted."""
    if not skill or module_id == MODEL_MODULE:
        return None
    with suppress(Exception):  # a contract it cannot read is nothing to report
        registers = contract.completeness_check.load_contract(
            skill.decode("utf-8"), module_id
        )["registers"]
        absent = sorted(register for register in registers if register not in text)
        if absent:
            shown = absent[:MAX_FEEDBACK_CITATIONS]
            rest = len(absent) - len(shown)
            named = ", ".join(f"`{register}`" for register in shown)
            named += f" and {rest} more" if rest else ""
            subject = "register ID" if len(absent) == 1 else "register IDs"
            verb = "appears" if len(absent) == 1 else "appear"
            return (
                f"host register check: the {subject} {named} {verb} nowhere"
                " in the answer"
            )
    return None


def _transport_or_reason(
    body: str,
) -> tuple[tuple[bytes, str, tuple[Citation, ...]] | None, str]:
    """The transport, or the host's reason it is not one (N50)."""
    with suppress(Exception):  # any failure is named below, never quoted
        return _transport(body), ""
    try:
        json.loads(body)  # only to name why, in the parser's own words
    except json.JSONDecodeError as bad:
        hint = _ESCAPES if bad.msg.startswith("Invalid control character") else ""
        return None, _TRANSPORT_JSON.format(bad.msg) + hint
    except (RecursionError, ValueError):
        pass
    return None, _TRANSPORT_SHAPE


def _quote_line(text: str, citations: Sequence[Citation]) -> str | None:
    """Which citations the body does not quote verbatim, by number (N51)."""
    words = _body_words(text)
    openings = _openings(words)
    failed = [
        number
        for number, citation in enumerate(citations, 1)
        if not _quoted(words, openings, citation.matched_text)
    ]
    if not failed:
        return None
    verb = "quotes" if len(failed) == 1 else "quote"
    return (
        f"host citation check: {_numbered(failed)} of {len(citations)} {verb} text"
        " that does not appear verbatim in the Markdown body (numbered from 1 in"
        " the order given)"
    )


def _numbered(failed: Sequence[int]) -> str:
    """`citation 2`, `citations 2 and 5`, `citations 1, 2 and 3`: at most
    `MAX_FEEDBACK_CITATIONS` numbers, the rest counted."""
    shown = [str(number) for number in failed[:MAX_FEEDBACK_CITATIONS]]
    rest = len(failed) - len(shown)
    named = ", ".join(shown) + (f" and {rest} more" if rest else "")
    if not rest and len(shown) > 1:
        named = ", ".join(shown[:-1]) + f" and {shown[-1]}"
    return f"citation {named}" if len(failed) == 1 else f"citations {named}"


# What anchoring found for a citation, singular and plural (N52).
_ANCHORING = (
    (
        RefusalCode.CITATION_NOT_LOCATED,
        "is not one evidence line of its cited page",
        "are not each one evidence line of their cited pages",
    ),
    (
        RefusalCode.CITATION_AMBIGUOUS,
        "is on its cited page more than once",
        "are on their cited pages more than once",
    ),
    (
        RefusalCode.CITATION_NOT_DELIVERED,
        "names a page or line this node was not given",
        "name a page or line this node was not given",
    ),
)


def anchoring_line(verdicts: Sequence[RefusalCode | None]) -> str | None:
    """Which citations did not anchor in the delivered evidence, by number and
    reason, never by text (N52): `verdicts` holds each citation's own
    anchoring refusal, `None` for one that anchored."""
    parts = [
        f"{_numbered(failed)} of {len(verdicts)} {one if len(failed) == 1 else many}"
        for code, one, many in _ANCHORING
        if (failed := [n for n, found in enumerate(verdicts, 1) if found is code])
    ]
    if not parts:
        return None
    return (
        "host anchoring check: "
        + "; ".join(parts)
        + " (numbered from 1 in the order given)"
    )


def answer_citations(body: str) -> tuple[Citation, ...]:
    """The citations a stored answer asked for; none when it is not the
    transport, whose reason `retry_feedback` gives."""
    parsed, _reason = _transport_or_reason(body)
    return () if parsed is None else parsed[2]


def _vendor_lines(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    identity: HostIdentity,
    text: str,
    skill: bytes,
) -> list[str]:
    """The vendor's own messages on the answer, labelled, bounded, as written."""
    found: list[tuple[str, object]] = []
    with suppress(Exception):  # the vendor's checker raising is nothing to report
        _text(text.encode("utf-8"))
        scope = _decision_scope(catalog, identity)
        checked = contract.validate_handoff.validate_text(text, decision_scope=scope)
        found += [("validate_handoff", error) for error in checked.errors or ()]
    if skill and identity.module_id != MODEL_MODULE:
        with suppress(Exception):
            violations = contract.completeness_check.check(
                skill.decode("utf-8"), text, identity.module_id
            )[0]
            found += [("completeness_check", violation) for violation in violations]
    if identity.module_id == GATE_MODULE:
        found += _t8_messages(contract, catalog, text)
    return [line for label, message in found if (line := _bounded(label, message))]


def _t8_messages(
    contract: VendorContract, catalog: Mapping[str, Any], text: str
) -> list[tuple[str, object]]:
    """The T8 parser's own refusal of CP-0's readiness table, if it refuses."""
    nav = contract.navigation
    try:
        nav.parse_t8(text, nav.validate_catalog(catalog))
    except ValueError as refused:  # the vendor's NavigationError
        return [("navigation", str(refused))]
    return []


def _bounded(label: str, message: object) -> str | None:
    """One vendor message across the boundary, cut and checked, or nothing."""
    if not isinstance(message, str) or hides_text(message):
        return None
    with suppress(Refusal):
        cut = BoundaryText.of(message[:MAX_FEEDBACK_CHARS], limit=MAX_FEEDBACK_CHARS)
        return f"{label}: {cut.value}"
    return None


def record_bytes(record: CanonicalRecord) -> bytes:
    """The record's one canonical serialisation; its SHA-256 is `record_sha256`.

    `projections.blockers` is written only when it has rows. That keeps the v2
    format the same shape it has always had for every record whose gate cleared
    every module -- every non-gate record, and every gate record of a run that
    ran -- so a field added for the CONDITIONAL case did not invalidate records
    already stored. The mapping is still one-to-one: absent means no row, and
    `_decoded_record` reads it back as the empty tuple, so `record_bytes` of a
    decoded record is the bytes it was decoded from.
    """
    document: dict[str, Any] = {"format": RECORD_FORMAT, **asdict(record)}
    if not document["projections"]["blockers"]:
        del document["projections"]["blockers"]
    if document["identity"]["research_brief"] is None:
        del document["identity"]["research_brief"]
    for citation in document["citations"]:
        for box in citation["bboxes"]:
            box.update({key: float(box[key]) for key in ("x0", "y0", "x1", "y1")})
    return canonical_json(document).encode("utf-8")


def _exact[T](kind: type[T]) -> Callable[[object], T]:
    def parse(value: object) -> T:
        if type(value) is not kind:
            raise TypeError  # `true` is not 1, and 1 is not 1.0
        return value

    return parse


def _each[T](parse: Callable[[object], T]) -> Callable[[object], tuple[T, ...]]:
    def parse_all(value: object) -> tuple[T, ...]:
        if not isinstance(value, list):
            raise TypeError
        return tuple(parse(item) for item in value)

    return parse_all


def _typed[T](kind: type[T], value: object, **special: Callable[[object], Any]) -> T:
    """`kind` from a closed object whose fields are strings unless named."""
    document = _closed(value, frozenset(f.name for f in fields(kind)))  # type: ignore[arg-type]
    parsed = {
        name: special.get(name, _exact(str))(item) for name, item in document.items()
    }
    return kind(**parsed)


def _pair(value: object) -> tuple[str, str]:
    module_id, readiness = _each(_exact(str))(value)
    return module_id, readiness


def _with_blockers(value: object) -> dict[str, Any]:
    """Supply the empty `blockers` a record omits, so `_typed`'s closed key set
    holds for both spellings and no record that predates the field refuses."""
    if not isinstance(value, dict) or "blockers" in value:
        return value if isinstance(value, dict) else {}
    return {**value, "blockers": []}


def _with_research(value: object) -> dict[str, Any]:
    """Supply the absent `research_brief` an identity omits (every module but
    CP-DR, and every record written before §96), read back as None."""
    if not isinstance(value, dict) or "research_brief" in value:
        return value if isinstance(value, dict) else {}
    return {**value, "research_brief": None}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _exact(str)(value)


_int, _strs = _exact(int), _each(_exact(str))
_rect = _each(
    lambda box: _typed(
        Rect, box, page=_int, **dict.fromkeys(("x0", "y0", "x1", "y1"), _exact(float))
    )
)


def _decoded_record(data: bytes) -> CanonicalRecord:
    document = strict_json(data.decode("utf-8"))
    if not isinstance(document, dict) or document.pop("format", None) != RECORD_FORMAT:
        raise ValueError
    citations = _each(
        lambda item: _typed(AnchoredCitation, item, page=_int, bboxes=_rect)
    )(document.get("citations"))
    if not citations:
        raise ValueError
    return _typed(
        CanonicalRecord,
        document,
        identity=lambda item: _typed(
            HostIdentity,
            _with_research(item),
            ordinal=_int,
            upstream=_each(lambda ref: _typed(UpstreamRef, ref)),
            research_brief=_optional_str,
        ),
        lineage=_each(lambda ref: _typed(LineageRef, ref)),
        projections=lambda item: _typed(
            Projections,
            _with_blockers(item),
            confidence_score=_int,
            limitation_flags=_strs,
            validation_warnings=_strs,
            downstream_consumers=_strs,
            readiness=_each(_pair),
            blockers=_each(_pair),
        ),
        citations=lambda _: citations,
    )


def stored_lineage(
    blobs: BlobStore,
    upstream: Sequence[UpstreamRef],
    accepted: Mapping[str, tuple[str, str | None]],
    *,
    verified: Mapping[str, CanonicalRecord] | None = None,
) -> tuple[LineageRef, ...]:
    """The whole accepted chain behind `upstream`, read from the stored records.

    `accepted` maps each accepted route node to its (artifact, record) pair.
    Every direct ref with its pair, then every ancestor its stored record names,
    each of which must still be the accepted pair for its node; ordered by route
    node id. Never recomputed from prompt text. `verified` maps a record digest
    to the record a caller already read through `read_record` in this unit, so
    that blob is not read again. `ARTIFACT_RECORD_MISMATCH`, with no text, for a
    pair that is not accepted, a record that will not read or binds another
    artifact, or two pairs for one node.
    """
    known = verified or {}

    def chain() -> tuple[LineageRef, ...]:
        found: dict[str, LineageRef] = {}
        for ref in upstream:
            artifact, record_sha256 = accepted[ref.route_node_id]
            if artifact != ref.sha256 or record_sha256 is None:
                raise ValueError
            record = known.get(record_sha256)
            if record is None:
                data = blobs.get(record_sha256)
                record = _decoded_record(data)
                if record_bytes(record) != data:
                    raise ValueError
            if record.artifact_sha256 != artifact:
                raise ValueError
            direct = LineageRef(
                ref.route_node_id, ref.module_id, artifact, record_sha256
            )
            for link in (direct, *record.lineage):
                pair = (link.artifact_sha256, link.record_sha256)
                if accepted.get(link.route_node_id) != pair:
                    raise ValueError  # an ancestor whose accepted pair moved
                if found.setdefault(link.route_node_id, link) != link:
                    raise ValueError
        return tuple(found[key] for key in sorted(found))

    return _or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, chain)


def read_record(
    blobs: BlobStore,
    *,
    artifact_sha256: str,
    record_sha256: str,
    expected: HostIdentity,
) -> CanonicalRecord:
    """The record bound to this artifact and this invocation, or a refusal.

    Both blobs are read, so both digests are proven; the record must parse
    strictly, be in its own canonical form, name this Markdown and carry exactly
    `expected`. Every failure is `ARTIFACT_RECORD_MISMATCH` with no text.

    The record is still not fact (§41.2): re-parsing the projections from the
    Markdown and re-anchoring the citations are the readers' steps (3.1d), since
    they need the vendor contract and the store.
    """

    def read() -> CanonicalRecord:
        blobs.get(artifact_sha256)
        data = blobs.get(record_sha256)
        record = _decoded_record(data)
        if (
            record_bytes(record) != data
            or record.artifact_sha256 != artifact_sha256
            or record.identity != expected
            or record.authority_bundle_sha256 != expected.authority_bundle_sha256
        ):
            raise ValueError
        return record

    return _or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, read)
