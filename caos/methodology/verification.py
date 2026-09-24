"""The one verification of an accepted canonical artifact (§42.4, §45.4).

Three readers -- the orchestration proof, the deliverable's payload and the
runtime's accepted read -- each ran their own copy of the same ten steps and
had drifted four ways. Invariants 3, 4 and 11 all pass through these steps, so
a step silently dropped for one caller is a hole in the host's identity,
authority or citation guarantees. `verify_accepted` is the one copy; each
reader is a call site that names only what is genuinely its own:

- `reanchor`: the proof and the freeze hand over the run's pinned live
  evidence, and every recorded quote is located in it again and must land on
  the recorded rectangles; the runtime hands over none (§42.4 -- the
  rectangles are the ones recorded at acceptance).
- `verify_authority`: the proof and the freeze re-read every authority file
  past the per-manifest digest cache; the frontier keeps the cache.
- `refuse`: which code each step answers. The proof says `ORCHESTRATION_*`,
  the deliverable `ARTIFACT_RECORD_MISMATCH`; `None` lets the step's own code
  through (a citation's, in the deliverable). What a reader refuses is what an
  API serves and a test asserts, so no code moves here.

Everything a step refuses is raised outside the handler that saw it, so no
refusal carries vendor or document text in its chain.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from caos.blobs import BlobStore
from caos.evidence.citations import (
    AnchoredCitation,
    Citation,
    TokenIndex,
    verify_citations,
)
from caos.graph.route import MODEL_MODULE, ResolvedRoute, RouteNode
from caos.methodology.bundle import Bundle, verified_bytes
from caos.methodology.handoff import (
    GATE_MODULE,
    CanonicalRecord,
    Projections,
    read_record,
    validate_markdown,
)
from caos.methodology.invocation import (
    accepted_lineage,
    call_time_identity,
    host_identity,
    record_authority_matches,
)
from caos.methodology.vendor import (
    VENDOR_MODULE,
    VendorContract,
    load_vendor_contract,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

_CATALOG = "references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
SKILL = "SKILL.md"


class Step(StrEnum):
    """The steps a caller answers with its own code, in the order they run."""

    # The row names a route node the pin does not carry.
    NODE_NOT_IN_ROUTE = "node_not_in_route"
    # A blob that will not read, or whose bytes no longer hash to its address.
    UNREADABLE = "unreadable"
    # `read_record`: the record does not bind this Markdown and the identity
    # rebuilt from the store.
    RECORD_BINDING = "record_binding"
    # `record_authority_matches`: written under another adapter, build,
    # manifest or authority (invariant 4).
    AUTHORITY_MOVED = "authority_moved"
    # The record's lineage is not the accepted chain the store holds now.
    LINEAGE = "lineage"
    # The Markdown no longer validates, or projects other than the record says.
    PROJECTIONS = "projections"
    # A citation names a document not among the pinned live sources.
    SOURCE_NOT_PINNED = "source_not_pinned"
    # `verify_citations` refused a quote (its own code when unmapped).
    CITATION_ANCHOR = "citation_anchor"
    # Every quote anchored, but not on the recorded rectangles.
    CITATION_MOVED = "citation_moved"


type Refuse = Callable[[Step], RefusalCode | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedRow:
    """One accepted artifact, as the `artifacts` table names it.

    Keyword-only, which is the whole point of the type: it replaced five
    positional neighbours of two repeated shapes -- two `UUID`s and two
    64-character digests -- where a caller could transpose either pair and be
    type-checked all the way to a wrong refusal. Every call site already passed
    by keyword; `kw_only` is what makes that a property of the type rather than
    a convention every future caller has to repeat.
    """

    run_id: UUID
    route_node_id: str
    attempt_id: UUID
    artifact_sha256: str
    record_sha256: str


@dataclass(frozen=True, slots=True)
class VendorAuthority:
    """The compiled vendor contract and catalog one read unit validates with."""

    contract: VendorContract
    catalog: Mapping[str, Any]


# FP-32: the one profile and selection CP-5's owner-restriction check narrows
# to (`caos/methodology/canonical.py`'s `_forecast_inputs`, and both
# deliverable-proof callers, `caos/deliverable/canonical.py` and
# `caos/qualification/proof.py`). CP-CF's own check is unconditional --
# `selection=None` -- because the forecast module carries no profile of its
# own to narrow by.
CREDIT_SCREEN_SELECTION: tuple[str, str] = ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN")


def verify_owner_restrictions(
    contract: VendorContract,
    markdown: bytes,
    owners: Iterable[bytes],
    *,
    refuse: RefusalCode,
    selection: tuple[str, str] | None,
) -> None:
    """Refuse an artifact that drops a direct owner's restrictions."""
    parse = contract.validate_handoff.validate_text
    fields = parse(markdown.decode()).fields
    if (
        selection is not None
        and (
            fields["credit_os_profile_id"],
            fields["credit_os_selection_id"],
        )
        != selection
    ):
        return
    for data in owners:
        owner = parse(data.decode()).fields
        if (
            owner["qa_status"] == "Restricted" and fields["qa_status"] != "Restricted"
        ) or any(
            not set(owner[key]) <= set(fields[key])
            for key in ("limitation_flags", "validation_warnings")
        ):
            raise Refusal(refuse)


def verify_owner_chain(
    contract: VendorContract,
    markdown: bytes,
    upstream_keys: Iterable[tuple[str, str]],
    cache: Mapping[tuple[str, str], bytes],
    *,
    selection: tuple[str, str] | None,
) -> None:
    """Resolve recorded upstream bytes once, then apply owner restrictions."""
    try:
        owners = tuple(cache[key] for key in upstream_keys)
    except KeyError:
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH) from None
    verify_owner_restrictions(
        contract,
        markdown,
        owners,
        refuse=RefusalCode.ARTIFACT_RECORD_MISMATCH,
        selection=selection,
    )


def load_vendor_authority(bundle: Bundle) -> VendorAuthority:
    """The proof's and the freeze's reading: compiled now, from the bytes here."""
    return VendorAuthority(
        load_vendor_contract(bundle),
        json.loads(verified_bytes(bundle, VENDOR_MODULE, _CATALOG)),
    )


@dataclass(frozen=True, slots=True)
class PinnedEvidence:
    """What a re-anchoring reader locates quotes in: the run's pinned live
    sources by document digest, the captured blocks each was handed, and one
    token index shared across the unit (records cluster on the same pages)."""

    sources: Mapping[str, UUID]
    delivered: Mapping[UUID, frozenset[str]]
    index: TokenIndex


@dataclass(frozen=True, slots=True)
class Verified:
    """What one accepted artifact proved: its exact bytes, its record, the
    projections re-derived from the Markdown, and -- when re-anchored -- the
    citations located again on the recorded rectangles."""

    markdown: bytes
    stored: bytes
    record: CanonicalRecord
    projections: Projections
    citations: tuple[AnchoredCitation, ...] | None


def verify_accepted(  # noqa: PLR0913 -- one accepted row and what its reader owns
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    row: AcceptedRow,
    *,
    vendor: VendorAuthority,
    accepted: Mapping[str, tuple[str, str | None]] | None,
    verify_authority: bool,
    reanchor: PinnedEvidence | None,
    refuse: Refuse,
) -> Verified:
    """The ten-step check every reader runs, inside the caller's read unit.

    Both blobs; the host identity rebuilt from the store and narrowed to what
    the call could name (`call_time_identity`, whose own codes -- an attempt
    without its ordinal, a blocking input with no accepted artifact -- are
    raised as they are, outside any handler); `read_record` against it;
    `record_authority_matches` for this build; the lineage against the
    accepted pairs; the module's `SKILL.md` (`AUTHORITY_BYTES_MISMATCH` as its
    own); `validate_markdown` and the projections compared with the record's;
    and, when `reanchor` names the pinned evidence, every citation located in
    it on exactly the recorded rectangles (None: the recorded rectangles
    stand, §42.4). `refuse` names the caller's code per `Step`, or
    `None` for the step's own: the code the step's call refused with, or
    `ARTIFACT_RECORD_MISMATCH` for a comparison that disagrees.
    """
    node = next((n for n in route.nodes if n.route_node_id == row.route_node_id), None)
    if node is None:
        raise _refusal(
            refuse, Step.NODE_NOT_IN_ROUTE, RefusalCode.ROUTE_IDENTITY_INVALID
        )
    markdown = _read(blobs, row.artifact_sha256)
    stored = _read(blobs, row.record_sha256)
    if markdown is None or stored is None:
        raise _refusal(refuse, Step.UNREADABLE, _MISMATCH)
    host = host_identity(
        conn,
        bundle,
        run_id=row.run_id,
        route=route,
        node=node,
        attempt_id=row.attempt_id,
    )
    expected = call_time_identity(
        conn, route, host, attempt_id=row.attempt_id, record=stored
    )
    record = _step(
        refuse,
        Step.RECORD_BINDING,
        lambda: read_record(
            blobs,
            artifact_sha256=row.artifact_sha256,
            record_sha256=row.record_sha256,
            expected=expected,
        ),
    )
    if not record_authority_matches(
        record, bundle=bundle, module_id=node.module_id, verify=verify_authority
    ):
        raise _refusal(
            refuse, Step.AUTHORITY_MOVED, RefusalCode.ORCHESTRATION_BUILD_MOVED
        )
    lineage = _step(
        refuse,
        Step.LINEAGE,
        lambda: accepted_lineage(
            conn,
            blobs,
            run_id=row.run_id,
            upstream=record.identity.upstream,
            accepted=accepted,
        ),
    )
    if lineage != record.lineage:
        raise _refusal(refuse, Step.LINEAGE, _MISMATCH)
    skill = verified_bytes(bundle, node.module_id, SKILL)
    projections = _step(
        refuse,
        Step.PROJECTIONS,
        lambda: validate_markdown(
            vendor.contract,
            vendor.catalog,
            skill,
            markdown,
            identity=expected,
            gate_expects=gate_expects(route, node),
        ),
    )
    if projections != record.projections:
        raise _refusal(refuse, Step.PROJECTIONS, _MISMATCH)
    citations = None
    if reanchor is not None:
        citations = _reanchored(conn, record, reanchor, refuse)
    return Verified(markdown, stored, record, projections, citations)


def gate_expects(route: ResolvedRoute, node: RouteNode) -> frozenset[str]:
    """The vendor modules CP-0's T8 must name: every pinned node but itself and
    the host's CP-CF, a host extension no vendor readiness row can carry --
    its accepted artifact is proven independently."""
    if node.module_id != GATE_MODULE:
        return frozenset()
    return frozenset(n.module_id for n in route.nodes) - {GATE_MODULE, MODEL_MODULE}


def _reanchored(
    conn: StoreConnection,
    record: CanonicalRecord,
    evidence: PinnedEvidence,
    refuse: Refuse,
) -> tuple[AnchoredCitation, ...]:
    requests = []
    for citation in record.citations:
        source_id = evidence.sources.get(citation.document_sha256)
        if source_id is None:
            raise _refusal(
                refuse,
                Step.SOURCE_NOT_PINNED,
                RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED,
            )
        requests.append(Citation(source_id, citation.page, citation.matched_text))
    anchored = _step(
        refuse,
        Step.CITATION_ANCHOR,
        lambda: verify_citations(
            conn, delivered=evidence.delivered, citations=requests, index=evidence.index
        ),
    )
    # Same quotes, same rectangles, inside the captured blocks.
    if tuple(anchored) != record.citations:
        raise _refusal(refuse, Step.CITATION_MOVED, _MISMATCH)
    return record.citations


_MISMATCH = RefusalCode.ARTIFACT_RECORD_MISMATCH


def _read(blobs: BlobStore, digest: str) -> bytes | None:
    try:
        return blobs.get(digest)
    except (Refusal, OSError):
        return None


def _step[T](refuse: Refuse, step: Step, call: Callable[[], T]) -> T:
    """`call`'s answer, or the refusal `step` maps to -- the caller's code, or
    the call's own -- raised after the handler has closed, so it carries no
    text from the one it replaced."""
    try:
        return call()
    except Refusal as refused:
        own = refused.code
    raise _refusal(refuse, step, own)


def _refusal(refuse: Refuse, step: Step, own: RefusalCode) -> Refusal:
    """The caller's code for `step`, or `own` when it maps to none."""
    code = refuse(step)
    return Refusal(own if code is None else code)
