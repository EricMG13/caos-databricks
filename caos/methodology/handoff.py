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
import unicodedata
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
from caos.evidence.citations import (
    ANY_RUN,
    CITATION_RULES,
    EXCERPT,
    MIN_EXCERPT_WORDS,
    REANCHORING_RULES,
    AnchoredCitation,
    Citation,
    CitationRule,
    Rect,
    within_line,
)
from caos.evidence.ingest import GROUP_WIDTH
from caos.graph.route import MODEL_MODULE
from caos.methodology.citation_markers import MARKER, body
from caos.methodology.vendor import VendorContract
from caos.provider import MAX_RESPONSE_BYTES
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
# The catalog pathways a contract test proves end to end: adapter modules on
# any other pathway stay disabled.
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
# The most Markdown the host accepts as a handoff, on model output and on
# stored reads alike (`_text`): the response bound the transport accepts
# (N39, owner-approved). No answer is longer than that, and a handoff's
# Markdown is never longer than the JSON body it arrived in, since an escape
# only ever shortens when read. The vendor's reader goes to `MAX_FILE_BYTES`,
# where validation took 6-22 s on every read of an accepted handoff.
MAX_HANDOFF_BYTES = MAX_RESPONSE_BYTES
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
    any vendor call and on stored bytes as well as model output. Which bound
    refused is named to a node's guided retry (`_text_bound`), never the
    text.
    """
    text, _bound = _text_bound(markdown)
    if text is None:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    return text


def _text_bound(markdown: bytes) -> tuple[str | None, str]:
    """`_text`'s reading: the text and `""`, or None and the host bound the
    bytes break, in the words a second attempt is told (G1-16). One reading
    serves both, so the bound named is the one that refused."""
    if len(markdown) > MAX_HANDOFF_BYTES:
        return None, f"the Markdown is longer than {MAX_HANDOFF_BYTES} bytes"
    try:
        text = markdown.decode("utf-8")
    except UnicodeDecodeError:
        return None, "the Markdown is not UTF-8"
    bound = _broken_bound(text)
    return (None, bound) if bound else (text, "")


def _broken_bound(text: str) -> str:
    """The first of `_text`'s bounds on decoded text that `text` breaks, named;
    `""` when it breaks none."""
    # Canonical Markdown is LF-only; a CR would let the host and the vendor
    # disagree about where lines, and so the front matter, end.
    if "\r" in text:
        return (
            "a line ends in a carriage return; canonical Markdown ends every line"
            " with a line feed alone"
        )
    if INVISIBLE.intersection(text):
        return (
            "the Markdown carries a line separator (U+2028), paragraph separator"
            " (U+2029) or byte order mark (U+FEFF)"
        )
    # Tags, a zero-width space, a word joiner: text a reviewer of the committee
    # page cannot see and the next module reads as an instruction (AI-2).
    if hides_text(text):
        return (
            "the Markdown carries a character no reader can see (a zero-width,"
            " tag, variation-selector or other invisible code point)"
        )
    # One C-level substring search, whatever the document does. Tabs are read
    # as spaces so that a run mixing the two is one run, and `str.replace`
    # gives back the same object when there is no tab to replace.
    spaced = text.replace("\t", " ")
    if " " * (MAX_WHITESPACE_RUN + 1) in spaced:
        return f"a line carries a run of more than {MAX_WHITESPACE_RUN} spaces or tabs"
    if _heading_backtracks(text, spaced):
        return (
            f"a heading's title carries a run of more than {MAX_HEADING_RUN}"
            " spaces, tabs or # characters"
        )
    if not _clean(text):
        return _unclean_bound(text)
    lines = text.split("\n")
    if any(len(line.encode()) > MAX_LINE_BYTES for line in lines):
        return f"a line is longer than {MAX_LINE_BYTES} bytes"
    closing = (
        lines.index("---", 1) if lines[:1] == ["---"] and "---" in lines[1:] else 0
    )
    if len("\n".join(lines[: closing + 1]).encode()) > MAX_FRONTMATTER_BYTES:
        return f"the front matter is longer than {MAX_FRONTMATTER_BYTES} bytes"
    return ""


def _clean(text: str) -> bool:
    """Whether `BoundaryText` keeps `text` exactly: NFC already, and no control
    but CR, LF and tab, lone surrogate or bidirectional control."""
    try:
        return BoundaryText.of(text, limit=len(text)).value == text
    except Refusal:
        return False


_UNCLEAN = (
    "the Markdown carries a control character other than a line feed or"
    " tab, or text that is not in Unicode NFC form"
)

# The C0 controls and DEL by their ISO 6429 names, which `unicodedata.name`
# does not give: a retry is told what it wrote, not only where (F499).
_C0_NAMES = (
    *"NULL|START OF HEADING|START OF TEXT|END OF TEXT|END OF TRANSMISSION"
    "|ENQUIRY|ACKNOWLEDGE|BELL|BACKSPACE|CHARACTER TABULATION|LINE FEED"
    "|LINE TABULATION|FORM FEED|CARRIAGE RETURN|SHIFT OUT|SHIFT IN"
    "|DATA LINK ESCAPE|DEVICE CONTROL ONE|DEVICE CONTROL TWO"
    "|DEVICE CONTROL THREE|DEVICE CONTROL FOUR|NEGATIVE ACKNOWLEDGE"
    "|SYNCHRONOUS IDLE|END OF TRANSMISSION BLOCK|CANCEL|END OF MEDIUM"
    "|SUBSTITUTE|ESCAPE|INFORMATION SEPARATOR FOUR|INFORMATION SEPARATOR THREE"
    "|INFORMATION SEPARATOR TWO|INFORMATION SEPARATOR ONE".split("|"),
)


def _unclean_bound(text: str) -> str:
    """`_clean`'s refusal, located (F499): the first line, 1-based, holding a
    character `BoundaryText` refuses, that character by code point and name,
    and how many lines hold one; else the first line NFC changes and the code
    points it changes there. Code points and line numbers only, never the
    text; across `BoundaryText` like every feedback line, and the unlocated
    words when it will not cross or nothing is found."""
    unclean = [
        (number, line)
        for number, line in enumerate(text.split("\n"), 1)
        if not _clean(line)
    ]
    refused = [(number, ch) for number, line in unclean if (ch := _first_refused(line))]
    if refused:
        number, ch = refused[0]
        # `hides_text` has already refused every bidirectional control, and
        # UTF-8 decodes no lone surrogate: what is left is a control.
        said = (
            f"line {number} of the Markdown carries {_code_point_named(ch)}, a"
            " control character other than a line feed or tab"
            f" ({_line_count(len(refused))} in all); remove it"
        )
    elif unclean:
        number, line = unclean[0]
        said = (
            f"line {number} of the Markdown is not in Unicode NFC form (first at"
            f" {_decomposed(line)}; {_line_count(len(unclean))} in all); write it"
            " in composed form"
        )
    else:
        return _UNCLEAN
    with suppress(Refusal):
        return BoundaryText.of(said, limit=MAX_FEEDBACK_CHARS).value
    return _UNCLEAN


def _first_refused(line: str) -> str:
    """The first character of `line` that `BoundaryText` refuses, or `""`."""
    for ch in line:
        try:
            BoundaryText.of(ch, limit=len(ch) * 3)
        except Refusal:
            return ch
    return ""


def _code_point_named(ch: str) -> str:
    """`U+XXXX (NAME)`, or `U+XXXX` alone for a code point with no name."""
    code = ord(ch)
    name = unicodedata.name(ch, "") or (
        _C0_NAMES[code] if code < len(_C0_NAMES) else "DELETE" if code == 0x7F else ""
    )
    return f"U+{code:04X} ({name})" if name else f"U+{code:04X}"


def _decomposed(line: str) -> str:
    """The code points from where NFC first changes `line`: the first that
    differs and the combining marks after it, at most four."""
    composed = unicodedata.normalize("NFC", line)
    at = next(
        (i for i, (a, b) in enumerate(zip(line, composed, strict=False)) if a != b),
        min(len(line), len(composed)),
    )
    end = at + 1
    while end < len(line) and end - at < 4 and unicodedata.combining(line[end]):
        end += 1
    return " ".join(f"U+{ord(ch):04X}" for ch in line[at:end])


def _line_count(count: int) -> str:
    return f"{count} line" if count == 1 else f"{count} lines"


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
    a Blocked `qa_status` (D34), register completeness, gate readiness. A
    validated Blocked handoff refuses `HANDOFF_BLOCKED` only once it is proven
    to be this invocation's, so the caller can record it as a diagnostic
    outcome; it is not held to the registers of a run it says could not be done.

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

    # A validated Blocked answer is the vendor's "blocked statement only": it
    # is honoured before the completeness check it was never meant to meet
    # (D34), and ends the run as before once its quotes anchor.
    if fields["qa_status"] == "Blocked":
        raise Refusal(RefusalCode.HANDOFF_BLOCKED)
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
# What the record codec reads and writes (`record_bytes`, `_decoded_record`),
# raised whenever a record this build writes is one an older build would
# refuse: 1 since D106 (`unverified`, `linked`), 2 since D107 (`marker`). A
# build with another value, or none, cannot read this build's records, so
# `scripts/rollback_check.py` refuses a rollback across a change of it.
RECORD_CODEC_VERSION = 2
# A validated Blocked answer's citations, judged as any answer's (D106).
BLOCKED_FORMAT = "caos-blocked-citations-v1"
# A body may carry the largest Markdown the host accepts plus its citations
# and the JSON wrapper. Sized from `MAX_RESPONSE_BYTES` (D45's handoff bound)
# rather than from the vendor's file-read ceiling, `MAX_FILE_BYTES` (nothing
# here parses a whole file against it): a live model call can never answer
# past `MAX_RESPONSE_BYTES` (`models.py` refuses PROVIDER_RESPONSE_INVALID
# first). `feedback_lines` parses a body directly, though, ahead of that
# gate, so the margin the vendor bound once gave the wrapper and citations
# over the raw Markdown is kept here too, in the new bound's terms.
MAX_TRANSPORT_CHARS = 2 * MAX_RESPONSE_BYTES
MAX_PAGE = 2**31 - 1  # the store's integer page
# How many citations one handoff may carry. Every citation is checked against
# the body here and anchored in the token index by `verify_citations` later,
# and both are re-done on every replay of the attempt: a few thousand of them
# spent about a minute of worker time each time, which is what makes health
# report `WORKERS_STALE` (AI-5). A real handoff's Evidence Trace carries tens.
MAX_CITATIONS = 512
# The anchoring refusals that leave a citation unverified rather than refuse
# its answer (D106): a quote on no line of its cited page, on it more than
# once, or on evidence the node was not given.
UNVERIFIED_CODES = frozenset(
    {
        RefusalCode.CITATION_NOT_LOCATED,
        RefusalCode.CITATION_AMBIGUOUS,
        RefusalCode.CITATION_NOT_DELIVERED,
    }
)
_UNVERIFIED_KEYS = WIRE_CITATION_KEYS | {"code"}


@dataclass(frozen=True, slots=True)
class UnverifiedCitation:
    """A citation of an accepted answer that did not anchor (D106): the
    module's own locator and quote, never host-verified and never
    re-anchored by any reader, and the anchoring refusal that made it
    unverified (`UNVERIFIED_CODES`). Its quote has crossed `BoundaryText`
    and hides no text (`unverified_citation`). The claim it supports is
    Deploy V's lineage class "Untraced". `linked` and `marker` are as for an
    anchored citation (`AnchoredCitation`): `linked` written only when
    false, `marker` on every citation accepted since D107."""

    source_id: UUID
    page: int
    matched_text: str
    code: RefusalCode
    linked: bool = True
    marker: int | None = None


def unverified_citation(
    citation: Citation,
    code: RefusalCode,
    *,
    linked: bool = True,
    marker: int | None = None,
) -> UnverifiedCitation:
    """`citation` kept as unverified for `code` (D106), its quote as it
    crosses `BoundaryText`, whether a marker names it (`linked`) and its
    place in the answer's list (`marker`, D107).
    `HANDOFF_MALFORMED` for a quote that will not cross or hides text: a
    host text check, never a citation fault, so the answer is refused
    rather than the quote stored or dropped."""
    quote = _crossed(citation.matched_text)
    if code not in UNVERIFIED_CODES or quote is None:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    return UnverifiedCitation(
        citation.source_id, citation.page, quote, code, linked, marker
    )


def _crossed(text: str) -> str | None:
    """`text` as it crosses `BoundaryText` (NFC), or None when it will not,
    hides text (AI-2), or is longer than any evidence line can be
    (`GROUP_WIDTH`, a shown block's bound), so no excerpt of one."""
    if hides_text(text):
        return None
    with suppress(Refusal):
        return BoundaryText.of(text, limit=GROUP_WIDTH).value
    return None


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    """The host's record beside one accepted Markdown handoff (§41.2).

    Host-written and bound to the Markdown by `artifact_sha256`. It carries no
    model-authored summary and no claims: the Markdown is the authority, and
    `projections` is a sidecar a reader re-derives from it and compares.
    `delivered_authority_digest` binds exactly the authority files the prompt
    carried (§45.1); `lineage` is the whole accepted chain behind the direct
    upstream, ordered by route node id, each pair read from the stored records
    (§45.4). `citation_rule` is how `citations` were located when it was
    accepted (N28), and so how a reader re-anchors them: `ANY_RUN` for every
    record written before the whole-line rule, which carries no such field,
    `WHOLE_LINE_AS_STORED` for one accepted under that rule's first reading,
    `WHOLE_LINE` for one accepted under its second (W6, N13), and `EXCERPT`
    for one accepted since D105, whose citations each keep the line they
    anchored in (`AnchoredCitation.line_text`).

    `citations` holds anchored citations only, each host-verified, and
    `unverified` the answer's citations that did not anchor (D106), apart
    and never mixed in: `_lines_held` holds `citations` alone, and no
    reader re-anchors `unverified`. Since D106 either list may be empty but
    not both; only an `EXCERPT` record holds an unverified citation or an
    anchored one not linked to a statement (`AnchoredCitation.linked`).
    Since D107 every citation of either list holds its `marker`, together
    the places 1 to n of the answer's list, so a marker in the body names
    exactly one of them; a record from before holds none (`_markers_held`).
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
    citation_rule: CitationRule = ANY_RUN
    unverified: tuple[UnverifiedCitation, ...] = ()


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


# D107: the body names a citation by its 1-based place in the list, `[C3]`,
# or several in one bracket, `[C3, C4]` (`citation_markers.MARKER`), read
# anywhere after the front matter, fenced code included. Anything else is
# text -- `[c3]`, `[C 3]`, `[C3-C5]`, `[C3,4]`, `[C1,  C2]` -- and only told
# as a hint (`_NEAR_MARKER`, `_unmarked_line`), never refused.
_MARKER_NUMBER = re.compile(r"[0-9]+")
# The most digits a marker that names a citation can have: more names none.
MARKER_DIGITS = 9
# A bracket that reads like a marker and is not one: a `c` of either case and
# a digit, spaces allowed between them, then anything short up to its close.
_NEAR_MARKER = re.compile(r"\[ *[Cc] *[0-9][^\[\]\n]{0,24}\]")


def _written(text: str) -> list[str]:
    """Every marker's number as the body writes it, in order: `[C03]` is
    `03`, `[C3, C4]` is `3` and `4`."""
    return [
        number
        for found in MARKER.finditer(body(text))
        for number in _MARKER_NUMBER.findall(found.group(1))
    ]


def _place(written: str) -> int:
    """The citation a marker's number names: its value (`[C03]` is 3), or 0,
    which names none, past `MARKER_DIGITS` digits."""
    return int(written) if len(written) <= MARKER_DIGITS else 0


def markers(text: str) -> tuple[int, ...]:
    """Every citation number the Markdown body names (D107), in order, a
    repeat included: `[C3]` is 3, `[C3, C4]` is 3 and 4; a number of more
    than `MARKER_DIGITS` digits is 0, a marker that names no citation."""
    return tuple(_place(number) for number in _written(text))


def _dangling(text: str, count: int) -> list[str]:
    """The markers that name no citation of `count`, as written, each once,
    in the body's order: structural, refusing the answer (D107)."""
    return list(dict.fromkeys(n for n in _written(text) if not 1 <= _place(n) <= count))


def parse_response(
    body: str,
) -> tuple[bytes, tuple[Citation, ...], tuple[bool, ...]]:
    """The exact Markdown bytes, the citation requests beside them, and
    whether a marker in the body names each (D107), or a refusal.

    The transport is `{"canonical_markdown", "citations"}` and nothing else, at
    either level, with duplicate keys refused, and at most `MAX_CITATIONS` of
    them; a transport that is not this refuses `HANDOFF_MALFORMED`, and so
    does a body whose marker names no citation (`[C9]` beside 8): which one
    it meant is undecidable. A citation naming evidence the node was not
    given is kept as unverified (D106), and one no marker names is flagged
    not linked to a statement (`AnchoredCitation.linked`) -- the citation's
    fault, never the answer's.
    Anchoring in the token index needs the store and is the executor's step.
    """
    markdown, text, citations = _or_refuse(
        RefusalCode.HANDOFF_MALFORMED, lambda: _transport(body)
    )
    if _dangling(text, len(citations)):
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    held = frozenset(markers(text))
    return markdown, citations, tuple(n in held for n in range(1, len(citations) + 1))


# What a node's guided retry may carry (D30, D82): at most this many checks,
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
    """The checks a refused answer failed, for the node's guided retry (D30, D82).

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
    return capped(feedback_lines(contract, catalog, identity, body, skill=skill))


def carried_answer(body: str) -> str | None:
    """The refused answer a guided retry carries back to be corrected (D104):
    the stored body as it crosses `BoundaryText`, or None when it is not the
    transport (N50), holds text no reader can see, or will not cross -- then
    the retry asks for the whole answer again, as before. Like the checks'
    lines it goes into that one request only, never a log, refusal or row."""
    parsed, _reason = _transport_or_reason(body)
    if parsed is None or hides_text(body):
        return None
    with suppress(Refusal):
        return BoundaryText.of(body, limit=MAX_TRANSPORT_CHARS).value
    return None


def feedback_lines(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    identity: HostIdentity,
    body: str,
    *,
    skill: bytes = b"",
) -> tuple[str, ...]:
    """`retry_feedback`'s lines before the cap, most telling first: the
    transport, the host's own bounds on the text, the quotes, the front
    matter's host-owned and undeclared fields, the missing IDs, CP-0's blocker
    cells, the register rows a cell short or long, then the vendor's own
    messages."""
    parsed, reason = _transport_or_reason(body)
    if parsed is None:
        return (reason,)
    markdown, text, citations = parsed
    checked = _checked(contract, catalog, identity, markdown)
    host = (
        _text_line(markdown),
        _uncrossed_line(citations),
        _dangling_line(text, len(citations)),
        _unmarked_line(text, len(citations)),
        *_front_matter_lines(contract, identity, getattr(checked, "fields", None)),
        _absent_ids_line(contract, identity.module_id, text, skill),
        _blocker_line(contract, catalog, text)
        if identity.module_id == GATE_MODULE
        else None,
        *_width_lines(contract, identity.module_id, text, skill),
    )
    lines = [line for line in host if line]
    lines += _vendor_lines(contract, catalog, identity, (text, checked), skill)
    return tuple(lines)


def _checked(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    identity: HostIdentity,
    markdown: bytes,
) -> object:
    """The vendor validator's result on an answer within the host's bounds,
    or None: past a bound the validator never reads it (`validate_markdown`),
    and a validator that raises is nothing to report."""
    with suppress(Exception):
        text = _text(markdown)
        scope = _decision_scope(catalog, identity)
        return contract.validate_handoff.validate_text(text, decision_scope=scope)
    return None


def _text_line(markdown: bytes) -> str | None:
    """The host bound the answer's Markdown breaks (`_text`), named and never
    quoted (G1-16): no validator ever read such an answer, so nothing else
    says why it was refused."""
    _text_read, bound = _text_bound(markdown)
    return f"host text check: {bound}" if bound else None


# A front matter field name a line may show: the vendor's own key grammar
# (`TOP_LEVEL_KEY_RE`), at most 64 characters. Anything else is counted.
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")


def _front_matter_lines(
    contract: VendorContract, identity: HostIdentity, fields: object
) -> list[str]:
    """What `validate_markdown` refuses in the front matter, by field name only
    (owner-approved 2026-09-23, G1-16): a host-owned field missing or not the
    host's, value and JSON type (`HANDOFF_IDENTITY_MISMATCH`), an upgrade key
    set on a run that upgrades nothing, and a field no handoff may carry
    (`HANDOFF_UNDECLARED_FIELD`). Never a value, which is the model's text or
    another run's. Nothing about host-owned fields for an identity the host
    itself cannot build: no answer can fix that."""
    if not isinstance(fields, dict):
        return []
    lines: list[str] = []
    with suppress(Refusal):
        host = invocation_fields(contract, identity)
        differ = sorted(
            key
            for key, value in host.items()
            if key not in fields or not _same(fields[key], value)
        )
        if differ:
            one = len(differ) == 1
            lines.append(
                f"host identity check: the host-owned {_plural('field', differ)}"
                f" {_field_names(differ)} {'is' if one else 'are'} missing or not"
                f" the {'one' if one else 'ones'} the HOST-OWNED FRONT MATTER block"
                f" gives; copy {'it' if one else 'them'} exactly, value and type"
            )
    upgraded = sorted(key for key in _UPGRADE_KEYS if fields.get(key) is not None)
    if upgraded:
        lines.append(
            f"host identity check: {_field_names(upgraded)} must be absent or"
            " null: this run upgrades no earlier run"
        )
    undeclared = sorted(
        str(key) for key in set(fields) - _declared_keys(contract, identity.module_id)
    )
    if undeclared:
        one = len(undeclared) == 1
        lines.append(
            f"host front matter check: the front matter carries"
            f" {_field_names(undeclared)}, {'a field' if one else 'fields'} no"
            f" handoff may carry; remove {'it' if one else 'them'}"
        )
    return lines


def _plural(noun: str, names: Sequence[str]) -> str:
    return noun if len(names) == 1 else noun + "s"


def _field_names(names: Sequence[str]) -> str:
    """`a`, `b` and 3 more: at most `MAX_FEEDBACK_CITATIONS` field names, each
    in the vendor's key grammar and at most 64 characters; the rest counted."""
    shown = [name for name in names if _FIELD_NAME.fullmatch(name)]
    shown = shown[:MAX_FEEDBACK_CITATIONS]
    rest = len(names) - len(shown)
    parts = [f"`{name}`" for name in shown] + ([f"{rest} more"] if rest else [])
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _blocker_line(
    contract: VendorContract, catalog: Mapping[str, Any], text: str
) -> str | None:
    """The CONDITIONAL and BLOCKED T8 rows whose `Why now / blocker` cell
    `_blocker` refuses -- past `MAX_BLOCKER_CHARS`, or carrying a control or
    bidirectional character -- by module ID, the cell never quoted (G1-16).
    A row the gate cleared is held to nothing here, as `_readiness` holds it."""
    nav = contract.navigation
    try:
        rows = nav.parse_t8(text, nav.validate_catalog(catalog))
    except ValueError:  # the parser's own line already says why
        return None
    refused = sorted(
        str(row.module_id)
        for row in rows
        if row.readiness in UNCLEARED_READINESS
        and not _blocker_kept(row.why_now_or_blocker)
    )
    if not refused:
        return None
    one = len(refused) == 1
    return (
        "host readiness check: a CONDITIONAL or BLOCKED row's `Why now / blocker`"
        f" cell holds at most {MAX_BLOCKER_CHARS} characters and no control or"
        f" bidirectional character; the {_plural('row', refused)} for"
        f" {', '.join(refused)} {'breaks' if one else 'break'} it"
    )


def _blocker_kept(cell: object) -> bool:
    """Whether `_blocker` keeps this cell."""
    if not isinstance(cell, str):
        return False
    try:
        BoundaryText.of(cell, limit=MAX_BLOCKER_CHARS)
    except Refusal:
        return False
    return True


def capped(lines: Sequence[str]) -> tuple[str, ...]:
    """At most `MAX_FEEDBACK_MESSAGES` lines; when some are dropped, the last
    says how many, so a second attempt knows it was not told everything."""
    if len(lines) <= MAX_FEEDBACK_MESSAGES:
        return tuple(lines)
    kept = MAX_FEEDBACK_MESSAGES - 1
    return (
        *lines[:kept],
        f"host feedback: {len(lines) - kept} more check messages not shown",
    )


def readiness_set_line(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    body: str,
    expects: frozenset[str],
) -> str | None:
    """CP-0's T8 against the modules this route pins (`gate_expects`): the
    host's own readiness check, which refuses `HANDOFF_INCOMPLETE` and until
    now told the second attempt nothing. Names module IDs only."""
    parsed, _reason = _transport_or_reason(body)
    if parsed is None or not expects:
        return None
    nav = contract.navigation
    try:
        rows = nav.parse_t8(parsed[1], nav.validate_catalog(catalog))
    except ValueError:  # the parser's own line already says why
        return None
    named = frozenset(row.module_id for row in rows)
    if named == expects:
        return None
    parts = []
    if missing := sorted(expects - named):
        parts.append("it lacks " + ", ".join(missing))
    if extra := sorted(named - expects):
        parts.append("it names " + ", ".join(extra) + ", not on this route")
    return (
        "host readiness check: T8 must have one row for each of "
        + ", ".join(sorted(expects))
        + "; "
        + "; ".join(parts)
    )


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
        absent = sorted(
            register for register in registers if not _writes_id(text, register)
        )
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


def _writes_id(text: str, register: str) -> bool:
    """Whether `text` writes `register` whole, as the vendor's locator reads an
    ID (the `id_re` of vendor `tests/test_regressions.py:607`): not inside a longer ID (`T4.1` in `T4.10`),
    a sentence's full stop after it ending it (F520)."""
    whole = rf"(?<![A-Za-z0-9_.]){re.escape(register)}(?![A-Za-z0-9_]|\.[A-Za-z0-9])"
    return re.search(whole, text) is not None


# How many register rows of another width than their header a retry is told
# of (F509); the rest are counted on one more line.
MAX_WIDTH_ROWS = 5
_WIDTH_FAULT = "differs from its header"  # the vendor's own tagged-table line
# How a width line shows the row (F522): its first cell and its last
# `_READ_COLUMNS` columns as the vendor binds them, each cell cut at a word to
# at most `_QUOTE_CHARS` characters.
_READ_COLUMNS = 3
_QUOTE_CHARS = 40


@dataclass(frozen=True, slots=True)
class _PipeTable:
    """One pipe table as `find_registers` walks it: its header line's index,
    its header, its rows as the vendor binds them, each row's own cells as
    `_row_cells` reads them, and the table-id tag right above it, if any."""

    start: int
    header: list[str]
    rows: list[dict[str, str]]
    cells: tuple[tuple[str, ...], ...]
    tag: str | None


def _width_lines(
    contract: VendorContract, module_id: str, text: str, skill: bytes
) -> list[str]:
    """Every register row whose cell count is not its header's (F509), an
    advisory line: the vendor pads a short row with empty cells and drops a
    long row's extra ones, so its own message names only the critical cell
    left empty, and a model that sees that cell's text one column to the
    left cannot find the fault (LCR4 CP-3C, four times). The registers are
    the ones `check()` binds, the cells counted by the vendor's `_row_cells`;
    a tagged table the vendor already reports as of another width keeps its
    own line alone. At most `MAX_WIDTH_ROWS` rows, the rest counted."""
    if not skill or module_id == MODEL_MODULE:
        return []
    with suppress(Exception):  # a contract it cannot read is nothing to report
        faults = _width_faults(contract, module_id, text, skill)
        shown = faults[:MAX_WIDTH_ROWS]
        lines = [
            line
            for fault in shown
            if (line := _bounded("host table check", _width_message(*fault)))
        ]
        if rest := len(faults) - len(shown):
            rows = "row differs" if rest == 1 else "rows differ"
            lines.append(
                f"host table check: {rest} more register {rows} in width from"
                " the header"
            )
        return lines
    return []


def _width_faults(
    contract: VendorContract, module_id: str, text: str, skill: bytes
) -> list[tuple[str, int, tuple[str, ...], list[str]]]:
    """(register ID, row number, cells, header) for each register row of
    another width than its header, in the answer's order."""
    checker = contract.completeness_check
    loaded = checker.load_contract(skill.decode("utf-8"), module_id)
    found = checker.find_registers(
        text, loaded["registers"], loaded.get("retired_registers", ())
    )
    errors = contract.cp_tables.read_tables(text)[1]
    tables = _pipe_tables(contract, text)
    faults = []
    for reg_id, (header, rows) in found.items():
        table = next((t for t in tables if (t.header, t.rows) == (header, rows)), None)
        if table is None or _WIDTH_FAULT in str(errors.get(table.tag, "")):
            continue
        faults += [
            (table.start, n, reg_id, cells, header)
            for n, cells in enumerate(table.cells, 1)
            if len(cells) != len(header)
        ]
    return [
        (reg_id, n, cells, header)
        for _, n, reg_id, cells, header in sorted(faults, key=lambda f: f[:2])
    ]


def _pipe_tables(contract: VendorContract, text: str) -> list[_PipeTable]:
    """Every pipe table of the answer, walked as `find_registers` walks them."""
    tables = contract.cp_tables
    lines = tables.unfenced_markdown(text).splitlines()
    found: list[_PipeTable] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if (
            not line.startswith("|")
            or line.count("|") < 2
            or tables.SEPARATOR_RE.match(line)
        ):
            i += 1
            continue
        header = tables._split_row(line)
        j = i + 1
        if (
            j < len(lines)
            and tables.SEPARATOR_RE.match(lines[j].strip())
            and "|" in lines[j]
        ):
            j += 1
        cells = []
        while j < len(lines) and lines[j].strip().startswith("|"):
            cells.append(tables._row_cells(lines[j].strip(), len(header)))
            j += 1
        pad = [""] * len(header)
        rows = [
            dict(zip(header, [*row, *pad][: len(header)], strict=False))
            for row in cells
        ]
        found.append(
            _PipeTable(
                i,
                header,
                rows,
                tuple(map(tuple, cells)),
                _tag_above(tables.TABLE_ID_RE, lines, i),
            )
        )
        i = j
    return found


def _tag_above(pattern: re.Pattern[str], lines: list[str], start: int) -> str | None:
    """The table-id a tag binds to the table at `start` with nothing but
    blank and comment lines between, as the vendor's `read_tables` binds it."""
    for line in map(str.strip, reversed(lines[:start])):
        if tag := pattern.fullmatch(line):
            return tag.group(1)
        if line and not line.startswith("<!--"):
            return None
    return None


def _width_message(
    reg_id: str, n: int, cells: tuple[str, ...], header: list[str]
) -> str:
    """The width line (F509), naming the row by its first cell and showing how
    its last columns read (F522): told only "row 7 has 11 cells", LCR6's
    CP-3C rewrote that row three times and kept it 11 wide. The quotes are the
    model's own cells, into its retry request only, like the vendor's lines;
    a cell that will not cross `BoundaryText` drops the quotes, never the line."""
    size, width = len(header), len(cells)
    first = _quoted(cells[0]) if cells else None
    read = _read_as(cells, header) if first else None
    row = f"{reg_id} row {n}" + (f" ({first})" if read else "")
    last = _column(header[-1])
    if width < size:
        short = size - width
        shift = (
            f"the last column, {last}, reads empty"
            if short == 1
            else f"the last {short} columns, from {_column(header[-short])}, read empty"
        )
    else:
        extra = width - size
        shift = (
            f"the cell past the last column, {last}, is dropped"
            if extra == 1
            else f"the {extra} cells past the last column, {last}, are dropped"
        )
    plain = (
        f"{reg_id} row {n} has {width} cells under a {size}-cell header; a cell"
        f" is missing or extra, so its later columns shift ({shift})"
    )
    if not read:
        return plain
    shown = (
        f"{row} has {width} cells under a {size}-cell header; a cell is"
        f" missing or extra, so its later columns shift ({shift}); as read, {read}"
    )
    # Past the bound `_bounded` would cut mid-quote: keep the whole sentence.
    return shown if len(shown) <= MAX_FEEDBACK_CHARS else plain


def _column(name: str) -> str:
    """A header cell as a line names it: quoted, at most 64 characters."""
    return f"'{name[:64]}'"


def _read_as(cells: tuple[str, ...], header: list[str]) -> str | None:
    """What the row's last `_READ_COLUMNS` columns hold as the vendor binds
    it, and a long row's first dropped cell; None when any of those cells
    will not cross the boundary."""
    parts = []
    for i in range(max(len(header) - _READ_COLUMNS, 0), len(header)):
        quote = _quoted(cells[i]) if i < len(cells) else "nothing"
        if quote is None:
            return None
        parts.append(f"{_column(header[i])} holds {quote}")
    if len(cells) > len(header):
        quote = _quoted(cells[len(header)])
        if quote is None:
            return None
        parts.append(f"past it {quote} is dropped")
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def _quoted(cell: str) -> str | None:
    """One cell as a width line quotes it: whitespace collapsed, cut at a
    word to at most `_QUOTE_CHARS` characters, or None when it hides text or
    will not cross `BoundaryText`."""
    text = " ".join(cell.split())
    if len(text) > _QUOTE_CHARS:
        head = text[: _QUOTE_CHARS + 1]
        head = head.rsplit(" ", 1)[0] if " " in head else head
        text = head[:_QUOTE_CHARS].rstrip(" ,;") + "…"
    if hides_text(text):
        return None
    with suppress(Refusal):
        return f"«{BoundaryText.of(text, limit=_QUOTE_CHARS + 1).value}»"
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


def _uncrossed_line(citations: Sequence[Citation]) -> str | None:
    """Which citations' quotes the host could not keep as unverified
    (`unverified_citation`), by number and never quoted: a host text check
    that refuses the answer (D106)."""
    failed = [n for n, c in enumerate(citations, 1) if _crossed(c.matched_text) is None]
    if not failed:
        return None
    verb = "carries" if len(failed) == 1 else "carry"
    return (
        f"host citation check: {_numbered(failed)} of {len(citations)} {verb} a"
        " control, bidirectional, surrogate or invisible character, or runs"
        f" past {GROUP_WIDTH:,} characters, longer than any evidence line; copy"
        " each excerpt as the evidence shows it (numbered from 1 in the order"
        " given)"
    )


def _dangling_line(text: str, count: int) -> str | None:
    """The markers that name no citation (D107), each as `[C<n>]` as written
    -- the model's own number, cut past 12 digits, never its text -- and the
    count they must stay within: the check that refused the answer
    (`parse_response`)."""
    dangling = _dangling(text, count)
    if not dangling:
        return None
    shown = [
        f"[C{n if len(n) <= 12 else n[:12] + '...'}]"
        for n in dangling[:MAX_FEEDBACK_CITATIONS]
    ]
    rest = len(dangling) - len(shown)
    more = f" and {rest} more" if rest else ""
    names = "it names" if len(dangling) == 1 else "they name"
    cited = "citation" if count == 1 else "citations"
    return (
        f"host marker check: the Markdown body writes {', '.join(shown)}{more},"
        f" but the answer has {count} {cited}, so"
        f" {names} none; a marker [C<n>] names the citation at place n of the"
        f" list, from [C1] to [C{count}]"
    )


def _unmarked_line(text: str, count: int) -> str | None:
    """Which citations no marker names, by number (D107), and how many
    bracketed forms the body writes that read like a marker and are not one
    (`_NEAR_MARKER`). Advisory: such a citation is kept, not linked to a
    statement, and never refuses an answer, so the line rides only along a
    retry some other check earned (`ADVISORY`)."""
    named = frozenset(markers(text))
    failed = [n for n in range(1, count + 1) if n not in named]
    if not failed:
        return None
    near = sum(
        MARKER.fullmatch(found.group()) is None
        for found in _NEAR_MARKER.finditer(body(text))
    )
    one = len(failed) == 1
    hint = (
        f"; the body writes {near} bracketed {'form' if near == 1 else 'forms'}"
        " the host does not read as a marker: write each exactly as [C3], or"
        " [C3, C4] for several, an upper-case C and no space or range"
        if near
        else ""
    )
    return (
        f"host marker check: {_numbered(failed)} of {count} {'is' if one else 'are'}"
        " named by no [C<n>] marker in the Markdown body (numbered from 1 in the"
        f" order given){hint}{ADVISORY}"
    )


# What closes each citation line a retry carries (D106): advisory, never the
# reason the answer was refused.
ADVISORY = (
    "; advisory only: the host keeps such a citation, marked unverified or not"
    " linked to a statement, and does not refuse an answer for it"
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


# What anchoring found for a citation, singular and plural (N52). A citation
# refused `CITATION_NOT_LOCATED` that the host's search places (`LineHint`)
# is told where instead (D82); this wording is for the rest.
_ANCHORING = (
    (
        RefusalCode.CITATION_NOT_LOCATED,
        "is not an exact excerpt of one evidence line of its cited page",
        "are not each an exact excerpt of one evidence line of their cited pages",
    ),
    (
        RefusalCode.CITATION_AMBIGUOUS,
        "occurs more than once on its cited page; quote a longer excerpt that"
        " occurs once",
        "occur more than once on their cited pages; quote longer excerpts that"
        " each occur once",
    ),
    (
        RefusalCode.CITATION_NOT_DELIVERED,
        "names a page or line this node was not given",
        "name a page or line this node was not given",
    ),
)
_ABSENT = (
    "is in no evidence line of its source this node was given",
    "are in no evidence line of their sources this node was given",
)
# How many words of the line a near miss or a dropped-cells row begins with
# are shown (D82, F493, F495).
HINT_WORDS = 12
# How many of its last words show the line a quote runs past the end of (F496).
END_WORDS = 8
# The most the anchoring line may hold once it places citations (D82): the
# room of four vendor check lines, so a retry's prompt grows by a bounded
# amount however many or long the placed lines are.
MAX_ANCHORING_CHARS = 4 * MAX_FEEDBACK_CHARS


@dataclass(frozen=True, slots=True)
class LineHint:
    """Where the host's own search placed a citation refused
    `CITATION_NOT_LOCATED` (D82, `caos.evidence.citations.find_line`): that
    it holds fewer than `MIN_EXCERPT_WORDS` words of a longer line (`short`,
    D105), the other delivered pages it is an excerpt of a line of
    (`pages`), that no delivered line holds it (`absent`), or that it runs
    from one delivered line onto the next (`across`). Nothing set: found,
    but not as one excerpt, so nothing is said beyond the rule. `repeated`:
    a citation refused `CITATION_AMBIGUOUS` is a whole delivered line of its
    cited page. `near`: the page of the one delivered line of its
    source the quote nearly matches (F493, `near_line`), `begins` then that
    line's first words, and `moved` whether that page is not the cited
    one; with `cells`, that line is a table row the quote left cells out of
    (F495, `cells_line`); with `ends` set, the quote runs past the end of
    that line, whose last `END_WORDS` words `ends` holds (F496,
    `overrun_line`), and with `short` fewer than `MIN_EXCERPT_WORDS` of its
    words lie within it. `unknown_source`: a citation refused
    `CITATION_NOT_DELIVERED` names this source_id, not one of the request's
    own (F495), and `held_by` the one delivered source holding its quote as
    a whole line of its cited page, if exactly one does."""

    begins: str = ""
    pages: tuple[int, ...] = ()
    absent: bool = False
    short: bool = False
    repeated: bool = False
    across: bool = False
    near: int | None = None
    moved: bool = False
    cells: bool = False
    ends: str = ""
    unknown_source: str = ""
    held_by: str = ""


def anchoring_line(
    verdicts: Sequence[RefusalCode | None], hints: Sequence[LineHint | None] = ()
) -> str | None:
    """Which citations did not anchor in the delivered evidence, by number and
    reason: `verdicts` holds each citation's own anchoring refusal, `None`
    for one that anchored, and `hints` what the host's search found of each
    refused `CITATION_NOT_LOCATED`, in the same order.

    N52 said "never by text"; the owner amended it on 2 October 2026 (D82):
    a quote of fewer than `MIN_EXCERPT_WORDS` words of a longer line is told
    to quote at least that many, or the whole line if shorter (D105), and
    one that is an excerpt of a line of another delivered page is told that
    page; one
    that nearly matches exactly one delivered line of its source is shown
    that line's page and first words and told to copy it exactly, and to
    cite that page when it is not the cited one (F493); one that left cells
    out of exactly one delivered row is shown that row and told to quote
    every cell (F495); one that runs past the end of exactly one delivered
    line is shown that line's last words and told to stop where it ends
    (F496). At
    most `MAX_FEEDBACK_CITATIONS` citations are placed; the rest, and any the
    search could not place, keep the rule's wording. A citation refused
    `CITATION_NOT_DELIVERED` whose hint names an `unknown_source` is told
    that source_id is not one of the request's, grouped by that id (F495).
    Past `MAX_ANCHORING_CHARS`, placements, these included, are dropped from
    the last back, each citation keeping its number under the rule's wording.

    The line ends by naming every citation that anchored, to be kept exactly
    as it was, and the rule any added or changed citation must meet (F491):
    a retry that rewrote its whole citation list traded each fixed quote for
    a new partial one. Past `MAX_ANCHORING_CHARS` the kept list is dropped
    first, before any placement; the rule stays.

    Advisory since D106: a citation that does not anchor is kept as
    unverified and never refuses an answer, so the retry that carries this
    line was earned by another check, and says so (`canonical._anchoring_line`
    adds `ADVISORY`).
    """
    kept = [n for n, found in enumerate(verdicts, 1) if found is None]
    lost = [
        n
        for n, found in enumerate(verdicts, 1)
        if found is RefusalCode.CITATION_NOT_LOCATED
    ]
    placed = _placements(verdicts, lost, hints)
    line = _anchoring_text(verdicts, lost, placed, kept)
    if line is not None and len(line) > MAX_ANCHORING_CHARS:
        line = _anchoring_text(verdicts, lost, placed, ())
    while placed and line is not None and len(line) > MAX_ANCHORING_CHARS:
        del placed[next(reversed(placed))]
        line = _anchoring_text(verdicts, lost, placed, ())
    return line


def _placements(
    verdicts: Sequence[RefusalCode | None],
    lost: Sequence[int],
    hints: Sequence[LineHint | None],
) -> dict[int, LineHint]:
    """The citations `anchoring_line` places, by number in order: the first
    `MAX_FEEDBACK_CITATIONS` refused `CITATION_NOT_LOCATED` whose hint names
    something to fix, each refused `CITATION_AMBIGUOUS` that is a whole line
    (`repeated`), and each refused `CITATION_NOT_DELIVERED` naming a source
    the request never offered (`unknown_source`)."""
    told = dict(zip(range(1, len(verdicts) + 1), hints, strict=False))
    placed = {
        n: hint
        for n in lost[:MAX_FEEDBACK_CITATIONS]
        if (hint := told.get(n)) is not None
        and (
            hint.near is not None
            or hint.pages
            or hint.absent
            or hint.short
            or hint.across
        )
    }
    for n, found in enumerate(verdicts, 1):
        hint = told.get(n)
        if hint is not None and (
            (found is RefusalCode.CITATION_AMBIGUOUS and hint.repeated)
            or (found is RefusalCode.CITATION_NOT_DELIVERED and hint.unknown_source)
        ):
            placed[n] = hint
    return dict(sorted(placed.items()))


def _anchoring_text(
    verdicts: Sequence[RefusalCode | None],
    lost: Sequence[int],
    placed: Mapping[int, LineHint],
    kept: Sequence[int],
) -> str | None:
    """`anchoring_line` with exactly the citations in `placed` placed and
    those in `kept` named to keep."""
    total = len(verdicts)
    parts = [
        _placed(n, total, hint)
        for n, hint in placed.items()
        if not (hint.absent or hint.unknown_source)
    ]
    absent = [n for n, hint in placed.items() if hint.absent]
    if absent:
        parts.append(_counted(absent, total, *_ABSENT))
    parts += _unknown_sources(placed, total)
    groups = [([n for n in lost if n not in placed], *_ANCHORING[0][1:])] + [
        (
            [
                n
                for n, found in enumerate(verdicts, 1)
                if found is code and n not in placed
            ],
            one,
            many,
        )
        for code, one, many in _ANCHORING[1:]
    ]
    parts += [
        _counted(failed, total, one, many) for failed, one, many in groups if failed
    ]
    if not parts:
        return None
    if kept:
        parts.append(f"keep {_listed(kept)} exactly as {_KEEP[len(kept) > 1]}")
    parts.append(_RULE)
    return (
        "host anchoring check: "
        + "; ".join(parts)
        + " (numbered from 1 in the order given)"
    )


# The rule a retry's added or changed citation must meet, ending every
# anchoring line (F491), and how a kept citation is told to stay.
_RULE = (
    "any citation you add or change must be an exact excerpt of one evidence"
    f" line of its cited page, at least {MIN_EXCERPT_WORDS} consecutive words or"
    " the whole line if shorter"
)
_KEEP = ("it was", "they were")


def _listed(numbers: Sequence[int]) -> str:
    """`citation 2`, `citations 2 and 5`, `citations 1, 2 and 3`: every
    number, none counted, since a kept citation must be named to be kept;
    `MAX_ANCHORING_CHARS` bounds the list instead (F491)."""
    shown = [str(number) for number in numbers]
    if len(shown) == 1:
        return f"citation {shown[0]}"
    return f"citations {', '.join(shown[:-1])} and {shown[-1]}"


def _counted(failed: Sequence[int], total: int, one: str, many: str) -> str:
    """`citation 2 of 5 is ...` or `citations 2 and 3 of 5 are ...`."""
    return f"{_numbered(failed)} of {total} {one if len(failed) == 1 else many}"


def _unknown_sources(placed: Mapping[int, LineHint], total: int) -> list[str]:
    """One clause per source_id the request never offered (F495), its
    citations grouped, and the one delivered source holding their lines
    when each names the same one."""
    named: dict[tuple[str, str], list[int]] = {}
    for n, hint in placed.items():
        if hint.unknown_source:
            named.setdefault((hint.unknown_source, hint.held_by), []).append(n)
    clauses = []
    for (source, held_by), numbers in named.items():
        many = len(numbers) > 1
        clause = (
            f"{_numbered(numbers)} of {total} {'name' if many else 'names'}"
            f" source_id {source}, which is not one of this request's sources;"
            " use one of the source_id values listed in the final check"
        )
        if held_by:
            lines = "the lines are" if many else "the line is"
            clause += f", and {lines} in source {held_by}"
        clauses.append(clause)
    return clauses


def _placed(number: int, total: int, hint: LineHint) -> str:
    """One placed citation's clause (D82): the line it runs past the end of,
    nearly matches or left cells out of (`_near_clause`), a whole line found
    more than once on its page, a run onto the next line, too few words of
    its line (D105, fix round 1), or the other pages it is an excerpt of a
    line of, at most `MAX_FEEDBACK_CITATIONS` of them named."""
    cited = f"citation {number} of {total}"
    if hint.near is not None:
        return _near_clause(cited, hint)
    if hint.repeated:
        return (
            f"{cited} is a whole evidence line that appears more than once on its"
            " cited page, so it cannot be cited there; cite another line, or a"
            " longer excerpt where one exists"
        )
    if hint.across:
        return (
            f"{cited} runs from one evidence line onto the next; quote within one"
            f" line: at least {MIN_EXCERPT_WORDS} consecutive words of it, or the"
            " whole line if shorter"
        )
    if hint.short:
        return (
            f"{cited} quotes fewer than {MIN_EXCERPT_WORDS} words of its line;"
            f" quote at least {MIN_EXCERPT_WORDS} consecutive words, or the whole"
            " line if shorter"
        )
    shown = [str(page) for page in hint.pages[:MAX_FEEDBACK_CITATIONS]]
    rest = len(hint.pages) - len(shown)
    named = ", ".join(shown) + (f" and {rest} more" if rest else "")
    if not rest and len(shown) > 1:
        named = ", ".join(shown[:-1]) + f" and {shown[-1]}"
    return (
        f"{cited} is an excerpt of an evidence line of"
        f" {'page' if len(hint.pages) == 1 else 'pages'} {named}, not of its"
        " cited page"
    )


def _near_clause(cited: str, hint: LineHint) -> str:
    """The clause of a citation placed by one delivered line (`near`): the
    line it runs past the end of (F496) -- told to keep at least
    `MIN_EXCERPT_WORDS` of it when fewer lie within it (`short`) -- the row
    it left cells out of (F495), or the line it nearly matches (F493)."""
    moved = f", and cite page {hint.near}" if hint.moved else ""
    if hint.ends:
        where = f"page {hint.near}," + (" not its cited page," if hint.moved else "")
        keep = (
            f", keeping at least {MIN_EXCERPT_WORDS} words of it, or quote the"
            " whole line"
            if hint.short
            else ""
        )
        return (
            f"{cited} runs past the end of the evidence line of {where} which"
            f' ends "{hint.ends}"; stop where the line ends{keep}{moved}'
            " (text after it is a separate evidence line)"
        )
    where = f"page {hint.near}" + (", not its cited page," if hint.moved else "")
    if hint.cells:
        return (
            f"{cited} leaves out cells of the evidence line of {where} that"
            f' begins "{hint.begins}"; quote the whole row, every cell{moved}'
        )
    return (
        f"{cited} nearly matches the evidence line of {where} that begins"
        f' "{hint.begins}" but differs in wording; copy that line exactly,'
        f" character for character{moved}"
    )


def answer_citations(body: str) -> tuple[Citation, ...]:
    """The citations a stored answer asked for; none when it is not the
    transport, whose reason `retry_feedback` gives."""
    parsed, _reason = _transport_or_reason(body)
    return () if parsed is None else parsed[2]


def answer_markdown(body: str) -> bytes | None:
    """The Markdown a stored answer carried; None when it is not the
    transport, whose reason `retry_feedback` gives."""
    parsed, _reason = _transport_or_reason(body)
    return None if parsed is None else parsed[0]


def _vendor_lines(
    contract: VendorContract,
    catalog: Mapping[str, Any],
    identity: HostIdentity,
    read: tuple[str, object],
    skill: bytes,
) -> list[str]:
    """The vendor's own messages on the answer, labelled, bounded, as written.
    `read` is the answer's text and the validator's result on it (`_checked`),
    None when the validator never read it."""
    text, checked = read
    found: list[tuple[str, object]] = []
    with suppress(Exception):  # a result the host cannot read is nothing to report
        errors = getattr(checked, "errors", None) or ()
        found += [("validate_handoff", error) for error in errors]
    fields = getattr(checked, "fields", None)
    if identity.module_id == GATE_MODULE:
        found += _t8_messages(contract, catalog, text)
    if identity.module_id == RESEARCH_MODULE and fields is not None:
        found += _research_messages(contract, identity, fields, text)
    if skill and identity.module_id != MODEL_MODULE:
        with suppress(Exception):
            violations = contract.completeness_check.check(
                skill.decode("utf-8"), text, identity.module_id
            )[0]
            ordered = sorted(map(str, violations), key=_consequence)
            found += [("completeness_check", violation) for violation in ordered]
    return [line for label, message in found if (line := _bounded(label, message))]


# The vendor's two messages for an interface table no tag binds: missing, or
# (fork r11, D100) written under its register heading without its
# `<!-- table-id: -->` comment.
_UNBOUND_INTERFACE = ("interface table missing", "comment not found above the")


def _consequence(message: str) -> int:
    """A table that does not parse first, the registers it then voids last:
    one malformed interface table makes every one of them "missing"."""
    if "differs from its header" in message or "separator" in message:
        return 0
    return 2 if any(text in message for text in _UNBOUND_INTERFACE) else 1


def _research_messages(
    contract: VendorContract, identity: HostIdentity, fields: object, text: str
) -> list[tuple[str, object]]:
    """The vendor's research-dossier refusal (§96) for CP-DR, which refuses
    `HANDOFF_INCOMPLETE` and until now told the second attempt nothing."""
    try:
        contract.research.validate_dossier(
            SimpleNamespace(fields=fields, text=text), research_brief_of(identity)
        )
    except ValueError as refused:  # the vendor's own message, bounded
        # As text, here at the vendor's boundary: `_bounded` passes strings
        # alone, and the exception itself was dropped there (R24-07). Every
        # value it quotes is withheld (N7): the dossier's checks call Python's
        # own parsers on the answer's cells, whose messages quote the cell.
        return [("research", _without_values(_vendor_said(refused)))]
    except Refusal:  # no bound brief: a help line never stops a run
        return []
    return []


# A value a message quotes the way Python's `repr` writes one: in single
# quotes, or in double quotes when it holds a single one, with backslash
# escapes inside and never a line break. A quote with a letter or digit just
# before it is an apostrophe in the message's own words, not a value.
_QUOTED = re.compile(r"""(?<!\w)(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")""")
WITHHELD_VALUE = "<value withheld>"


def _without_values(message: str | None) -> str | None:
    """A relayed vendor message with every value it quotes withheld (N7):
    the field it names and the fault it states stay, so the second attempt
    knows what to fix, and no cell of the answer is quoted back into the
    host's section. `date.fromisoformat` over a `source_date` cell said
    `Invalid isoformat string: '<the cell>'`, and a cell can say anything."""
    return None if message is None else _QUOTED.sub(WITHHELD_VALUE, message)


def _t8_messages(
    contract: VendorContract, catalog: Mapping[str, Any], text: str
) -> list[tuple[str, object]]:
    """The T8 parser's own refusal of CP-0's readiness table, if it refuses."""
    nav = contract.navigation
    try:
        nav.parse_t8(text, nav.validate_catalog(catalog))
    except ValueError as refused:  # the vendor's NavigationError
        return [("navigation", _vendor_said(refused))]
    return []


def _vendor_said(refused: ValueError) -> str | None:
    """A vendor refusal's own message as text, or nothing when rendering it
    fails; `_bounded` then cuts and checks it like every vendor line."""
    with suppress(Exception):
        return str(refused)
    return None


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
    decoded record is the bytes it was decoded from. `citation_rule` is kept
    the same way (N28): written only when it is not `ANY_RUN`, the rule every
    record stored before the field existed was anchored by. A citation's
    `cited_page` likewise: written only where the host re-anchored the quote
    at its true page (D94). And its `line_text` (D105): held, and written,
    for every citation of an `EXCERPT` record and for no other
    (`_lines_held`), so every record stored before it is the same bytes; a
    record `_lines_held` refuses raises `ValueError` rather than being
    written without its lines. D106's two fields likewise (`_held`): a
    citation's `linked` is written only when false, and `unverified` only
    when it has entries, so every record stored before them is the same
    bytes. D107's `marker` is written where it is set, which is on every
    citation accepted since D107 and on none before (`_markers_held`).
    """
    _held(record.citations, record.unverified, record.citation_rule)
    document: dict[str, Any] = {"format": RECORD_FORMAT, **asdict(record)}
    if not document["projections"]["blockers"]:
        del document["projections"]["blockers"]
    if document["citation_rule"] == ANY_RUN:
        del document["citation_rule"]
    if document["identity"]["research_brief"] is None:
        del document["identity"]["research_brief"]
    for citation in document["citations"]:
        _written_citation(citation, record.citation_rule)
    document["unverified"] = [_unverified_document(e) for e in record.unverified]
    if not document["unverified"]:
        del document["unverified"]
    return canonical_json(document).encode("utf-8")


def _unverified_document(entry: UnverifiedCitation) -> dict[str, Any]:
    """One unverified citation as written: `linked` only when false (D106),
    `marker` only when set (D107)."""
    document: dict[str, Any] = {
        "source_id": str(entry.source_id),
        "page": entry.page,
        "matched_text": entry.matched_text,
        "code": entry.code.value,
    }
    if not entry.linked:
        document["linked"] = False
    if entry.marker is not None:
        document["marker"] = entry.marker
    return document


def blocked_citations_bytes(
    citations: tuple[AnchoredCitation, ...], unverified: tuple[UnverifiedCitation, ...]
) -> bytes:
    """A validated Blocked answer's citations as the host judged them (D106):
    its anchored ones, each with its line and `linked` as a record writes
    them, and its unverified ones, both lists always written. A Blocked
    answer writes no record, so this is what the blocked view reads to show
    each quote verified or unverified (`read_blocked_citations`)."""
    _held(citations, unverified, EXCERPT)
    anchored = [asdict(citation) for citation in citations]
    for citation in anchored:
        _written_citation(citation, EXCERPT)
    return canonical_json(
        {
            "format": BLOCKED_FORMAT,
            "citation_rule": EXCERPT,
            "citations": anchored,
            "unverified": [_unverified_document(e) for e in unverified],
        }
    ).encode("utf-8")


def read_blocked_citations(
    blobs: BlobStore, citations_sha256: str
) -> tuple[tuple[AnchoredCitation, ...], tuple[UnverifiedCitation, ...]]:
    """The citations `blocked_citations_bytes` stored, or
    `ARTIFACT_RECORD_MISMATCH` for bytes that are not its canonical form."""

    def read() -> tuple[tuple[AnchoredCitation, ...], tuple[UnverifiedCitation, ...]]:
        data = blobs.get(citations_sha256)
        document = _closed(
            strict_json(data.decode("utf-8")),
            frozenset({"format", "citation_rule", "citations", "unverified"}),
        )
        if (document["format"], document["citation_rule"]) != (BLOCKED_FORMAT, EXCERPT):
            raise ValueError
        citations = _each(_anchored)(document["citations"])
        unverified = _each(_unverified)(document["unverified"])
        if blocked_citations_bytes(citations, unverified) != data:
            raise ValueError
        return citations, unverified

    return _or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, read)


def _written_citation(citation: dict[str, Any], rule: CitationRule) -> None:
    """One anchored citation as `record_bytes` writes it: `cited_page` only
    when set (D94), `line_text` only under `EXCERPT` (D105), `linked` only
    when false (D106), `marker` only when set (D107), and every coordinate a
    float."""
    if citation["cited_page"] is None:
        del citation["cited_page"]
    if citation["marker"] is None:
        del citation["marker"]
    if rule != EXCERPT:
        del citation["line_text"]
    if citation["linked"]:
        del citation["linked"]
    for box in citation["bboxes"]:
        box.update({key: float(box[key]) for key in ("x0", "y0", "x1", "y1")})


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


def _with_rule(value: dict[str, Any]) -> dict[str, Any]:
    """Supply the `ANY_RUN` a record omits (every record written before the
    whole-line rule, N28), so `_typed`'s closed key set holds for both."""
    return value if "citation_rule" in value else {**value, "citation_rule": ANY_RUN}


def _citation_rule(value: object) -> CitationRule:
    """A stored rule this build names, or `ValueError`: a record naming a
    rule nothing here anchors by cannot be re-anchored as accepted."""
    for rule in CITATION_RULES:
        if value == rule:
            return rule
    raise ValueError


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


def _anchored(item: object) -> AnchoredCitation:
    """A stored citation. An absent `cited_page` is None (every citation found
    where it was cited, D94); a present one is another page than `page`. An
    absent `line_text` is None; a present one is the line an excerpt
    anchored in (D105), which only an `EXCERPT` record holds
    (`_lines_held`)."""
    if not isinstance(item, dict):
        raise TypeError
    cited = item.get("cited_page")
    if "cited_page" in item and (
        type(cited) is not int
        or not 1 <= cited <= MAX_PAGE
        or cited == item.get("page")
    ):
        raise ValueError
    line = item.get("line_text")
    if "line_text" in item and (type(line) is not str or not line):
        raise ValueError
    # Written only when false (D106): a present `true` is not this host's.
    if "linked" in item and item["linked"] is not False:
        raise ValueError
    return _typed(
        AnchoredCitation,
        {
            **item,
            "cited_page": cited,
            "line_text": line,
            "linked": "linked" not in item,
            "marker": _marker(item),
        },
        page=_int,
        bboxes=_rect,
        cited_page=lambda value: value,
        line_text=lambda value: value,
        linked=lambda value: value,
        marker=lambda value: value,
    )


def _marker(item: dict[str, Any]) -> int | None:
    """A stored citation's `marker` (D107): absent is None, a citation
    accepted before markers; a present one is a place in a list."""
    if "marker" not in item:
        return None
    if type(item["marker"]) is not int or not 1 <= item["marker"] <= MAX_CITATIONS:
        raise ValueError
    return item["marker"]


def _unverified(item: object) -> UnverifiedCitation:
    """A stored unverified citation (D106): the wire's own checks on its
    locator and quote (`_requested`), a quote already as it crosses
    `BoundaryText`, one of `UNVERIFIED_CODES`, and `linked` only as false
    (absent, linked)."""
    if not isinstance(item, dict) or item.get("linked", False) is not False:
        raise ValueError  # written only when false: a present `true` is not ours
    optional = {"linked", "marker"}
    entry = _closed(
        {k: v for k, v in item.items() if k not in optional}, _UNVERIFIED_KEYS
    )
    citation = _requested({key: entry[key] for key in WIRE_CITATION_KEYS})
    code = next((c for c in UNVERIFIED_CODES if entry["code"] == c.value), None)
    if code is None or type(entry["code"]) is not str:
        raise ValueError
    if _crossed(citation.matched_text) != citation.matched_text:
        raise ValueError
    return UnverifiedCitation(
        citation.source_id,
        citation.page,
        citation.matched_text,
        code,
        "linked" not in item,
        _marker(item),
    )


def _held(
    citations: tuple[AnchoredCitation, ...],
    unverified: tuple[UnverifiedCitation, ...],
    rule: CitationRule,
) -> None:
    """`_lines_held` on the anchored citations alone, and D106's shape:
    `ValueError` for a record with no citation of either kind or more than
    `MAX_CITATIONS` of both, or one not under `EXCERPT` that holds an
    unverified citation or an anchored one not linked to a statement --
    only an answer accepted since D106 can, and it is under `EXCERPT`."""
    _lines_held(citations, rule)
    if not 1 <= len(citations) + len(unverified) <= MAX_CITATIONS:
        raise ValueError
    unlinked = any(not citation.linked for citation in citations)
    if rule != EXCERPT and (unverified or unlinked):
        raise ValueError
    _markers_held(citations, unverified, rule)


def _markers_held(
    citations: tuple[AnchoredCitation, ...],
    unverified: tuple[UnverifiedCitation, ...],
    rule: CitationRule,
) -> None:
    """`ValueError` unless no citation holds a `marker` -- a record from
    before D107 -- or every one does under `EXCERPT`, each list in its
    answer order and the two together exactly the places 1 to n: so each
    marker the body writes names one citation, anchored or not (D107)."""
    places = [c.marker for c in citations] + [e.marker for e in unverified]
    numbers = [place for place in places if place is not None]
    if not numbers:
        return
    anchored, kept = numbers[: len(citations)], numbers[len(citations) :]
    if (
        rule != EXCERPT
        or len(numbers) != len(places)
        or sorted(numbers) != list(range(1, len(numbers) + 1))
        or anchored != sorted(anchored)
        or kept != sorted(kept)
    ):
        raise ValueError


def _lines_held(citations: tuple[AnchoredCitation, ...], rule: CitationRule) -> None:
    """`ValueError` unless every citation holds its line under `EXCERPT` and
    none does under any other rule (D105), and each held line could hold its
    quote (`within_line`): a line missing from an excerpt, held beside a
    quote that is its own line or no line, or one the quote cannot come
    from, is not one this host wrote -- refused when a record is read, and
    when one is written (fix round 1), never silently dropped. That the
    line is the one the quote anchors in is the proof's to re-derive."""
    held = [citation.line_text is not None for citation in citations]
    if (rule == EXCERPT and not all(held)) or (rule != EXCERPT and any(held)):
        raise ValueError
    for citation in citations:
        if citation.line_text and not within_line(
            citation.matched_text, citation.line_text
        ):
            raise ValueError


def _decoded_record(data: bytes) -> CanonicalRecord:
    document = strict_json(data.decode("utf-8"))
    if not isinstance(document, dict) or document.pop("format", None) != RECORD_FORMAT:
        raise ValueError
    citations = _each(_anchored)(document.get("citations"))
    # Written only when it has entries (D106): a present empty list is not
    # this host's.
    if document.get("unverified", None) == []:
        raise ValueError
    unverified = _each(_unverified)(document.setdefault("unverified", []))
    # Only `REANCHORING_RULES` re-anchor (D94): a `cited_page` under any
    # other rule is not one this host wrote.
    rule = _citation_rule(_with_rule(document)["citation_rule"])
    reanchored = any(citation.cited_page is not None for citation in citations)
    if reanchored and rule not in REANCHORING_RULES:
        raise ValueError
    _held(citations, unverified, rule)
    return _typed(
        CanonicalRecord,
        _with_rule(document),
        unverified=lambda _: unverified,
        citation_rule=_citation_rule,
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
            direct, record = _direct_link(blobs, known, ref, accepted)
            for link in (direct, *record.lineage):
                _admit_link(found, link, accepted)
        return tuple(found[key] for key in sorted(found))

    return _or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, chain)


def _direct_link(
    blobs: BlobStore,
    known: Mapping[str, CanonicalRecord],
    ref: UpstreamRef,
    accepted: Mapping[str, tuple[str, str | None]],
) -> tuple[LineageRef, CanonicalRecord]:
    """`ref`'s own link, from its node's accepted pair, and the record that
    names the rest of its chain: read from the store in its canonical form,
    unless `known` already holds it. `ValueError` for a pair that is not the
    accepted one, or a record that will not read or binds another artifact;
    `KeyError` for a node with no accepted pair."""
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
    direct = LineageRef(ref.route_node_id, ref.module_id, artifact, record_sha256)
    return direct, record


def _admit_link(
    found: dict[str, LineageRef],
    link: LineageRef,
    accepted: Mapping[str, tuple[str, str | None]],
) -> None:
    """Add `link` to the chain: `ValueError` for an ancestor whose accepted
    pair moved, or a second pair for a node already in it."""
    if accepted.get(link.route_node_id) != (link.artifact_sha256, link.record_sha256):
        raise ValueError  # an ancestor whose accepted pair moved
    if found.setdefault(link.route_node_id, link) != link:
        raise ValueError


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
