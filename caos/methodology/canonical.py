"""Running one canonical module: a conforming Markdown handoff and its record (§41).

One pre-call read unit and one post-call read unit around the call. The
attempt, the stored input, the pinned route and node, the pinned adapter and
the host identity are read in one unit before the call and again after it;
the upstream the prompt named must be unchanged. The call is billed before any
analysis, with the exact response body addressed as the call's diagnostic
(§42.3), so a refused or Blocked handoff still says what was said -- and after
a crash the answer is accepted, blocked or explained from it, never paid for
again (`replay_billed`, brief 4.3 D7).
Then the handoff must be the vendor's conforming Markdown for exactly this
invocation. Each citation is anchored in the delivered evidence or kept as
unverified beside it, in a list of its own (D106): a citation's fault refuses
the citation, never the answer, so invariant 11's "coordinate-anchored or
refused" holds of every citation and the record's anchored list holds only
anchored ones.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import psycopg

from caos import methodology
from caos.blobs import BlobStore
from caos.evidence.citations import (
    EXCERPT,
    MIN_EXCERPT_WORDS,
    AnchoredCitation,
    Citation,
    TokenIndex,
    cells_line,
    find_line,
    near_line,
    overrun_kept,
    overrun_line,
    verify_citations,
    whole_line_of,
)
from caos.graph.route import MODEL_MODULE, ResolvedRoute, RouteNode
from caos.methodology.bundle import (
    Bundle,
    DeliveredAuthority,
    assemble_authority,
    authority_digest,
    delivered_authority,
    delivered_authority_digest,
)
from caos.methodology.executor import (
    SKILL,
    Assignment,
    Delivery,
    _delivered,
    _stored_identity,
)
from caos.methodology.handoff import (
    ADVISORY,
    END_WORDS,
    GATE_MODULE,
    HINT_WORDS,
    MAX_FEEDBACK_CHARS,
    MAX_FEEDBACK_CITATIONS,
    MAX_TRANSPORT_CHARS,
    UNVERIFIED_CODES,
    CanonicalRecord,
    HostIdentity,
    LineageRef,
    LineHint,
    Projections,
    UnverifiedCitation,
    UpstreamRef,
    _bounded,
    _numbered,
    anchoring_line,
    answer_citations,
    answer_markdown,
    blocked_citations_bytes,
    capped,
    carried_answer,
    feedback_lines,
    markers,
    parse_response,
    readiness_set_line,
    record_bytes,
    stored_lineage,
    unverified_citation,
    validate_markdown,
)
from caos.methodology.invocation import (
    MAX_UPSTREAM_HANDOFF_BYTES,
    build_handoff_prompt,
    call_time_identity,
    host_identity,
    prospective_identity,
    request_size,
    upstream_markdown,
)
from caos.methodology.selection import (
    Basis,
    DemandFault,
    Fault,
    Selection,
    demand_cells,
    demand_fault,
    demand_items,
    gate_view,
    select_sources,
)
from caos.methodology.vendor import VendorContract, cached_contract, catalog
from caos.methodology.verification import (
    CREDIT_SCREEN_SELECTION,
    OWNER_KEYS,
    AcceptedRow,
    OwnerGap,
    Step,
    VendorAuthority,
    Verified,
    gate_expects,
    owner_restriction_gaps,
    verify_accepted,
    verify_owner_restrictions,
)
from caos.provider import (
    MAX_REQUEST_BYTES,
    CompletionProvider,
    reported_charge,
    resend_checked,
)
from caos.refusals import Refusal, RefusalCode, RunRefusal
from caos.store import StoreConnection, connect
from caos.store.budget import Reservation, remaining, reserved_for
from caos.store.lakebase import store_url
from caos.store.outcomes import (
    CallOutcome,
    NodeAttempt,
    accepted_rows,
    call_hold,
    check_attempt,
    check_call,
    execution_reads,
    node_attempts,
    producer_identifier,
    record_outcome,
    require_idle,
)
from caos.store.run_inputs import load_run_input
from caos.store.runs import attempt_ordinal
from caos.store.source_sets import SourceSet, load_source_set
from caos.store.work import require_resendable

# The bill of an answer already paid for is written this many times at most,
# a pause apart, before the store fault is let through (ST-12): a failover
# between the call and its one write would otherwise lose the only record that
# the call was made, and the next claim would pay for the node again.
BILL_TRIES = 3
BILL_PAUSE_SECONDS = 1.0
_pause = time.sleep


@dataclass(frozen=True, slots=True)
class HandoffOutcome:
    """The accepted Markdown, the host record beside it, and the call's facts."""

    markdown: bytes
    record: bytes
    charge: Decimal
    model: str
    generation_id: str
    # What `record_outcome` stored as the call's diagnostic body address.
    diagnostic_sha256: str | None


def _contract(bundle: Bundle) -> VendorContract:
    return cached_contract(bundle)


def _diagnostic(blobs: BlobStore, content: object) -> tuple[str | None, bool]:
    """The exact response body as a blob address (None when there is none), and
    whether a body that exists could not be stored.

    The whole closed transport, not only its Markdown, so `replay_billed` can
    re-run the complete verdict -- citations included -- from stored facts.
    Lenient on purpose: this is what was said, not what is accepted. A blob
    that cannot be written leaves the address None so the bill still commits,
    and the attempt then refuses as a store fault: a verdict that was never
    stored cannot be honoured on recovery, so it must not be silently lost.
    The bytes are untrusted provider text, never `BoundaryText`: stored as
    said. Two readers alone read them back: `replay_billed`'s full
    re-validation, and a guided retry's prompt (D30, D82), which carries what
    the checks said of them and, since D104, the body itself once it has
    crossed `BoundaryText` (`carried_answer`), into that one request only and
    never a log, refusal or row.
    """
    if not isinstance(content, str) or len(content) > MAX_TRANSPORT_CHARS:
        return None, False
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        return None, False  # a lone surrogate: no body the host could store
    with suppress(Exception):  # the bill commits whatever the blob store did (F42)
        return blobs.put(data), False
    return None, True


def _within_reservation(
    conn: StoreConnection,
    provider: CompletionProvider,
    prompt: str,
    *,
    attempt_id: UUID,
) -> None:
    """Refuse a request this attempt's reservation does not cover (Task 8.2).

    The loop priced the prompt `check_context` built and reserved for it; this
    unit builds its own under the attempt's own identity. A rebuilt prompt that
    is larger -- or a configured price that moved between the two -- would
    otherwise be sent under a reservation too small for it, which is invariant
    8's "no provider call without a reservation" met only in form. So the
    reservation is read back with the price it was taken under and the request
    about to be sent is priced against exactly that price, before the call.

    A missing reservation refuses here as well as in `check_call`: the unit that
    spends checks it, not only the unit that ordered it.
    """
    from caos.pricing import bills_at, priced_request

    measured = request_size(provider, prompt)
    with execution_reads(conn):
        taken = reserved_for(conn, attempt_id)
    if taken is None:
        raise Refusal(RefusalCode.BUDGET_NOT_RESERVED)
    # The whole price, not its model alone: the charge is the provider's, at
    # the provider's own price (CF-089).
    if not bills_at(provider, taken.price):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    if priced_request(taken.price, measured) > taken.amount:
        raise Refusal(RefusalCode.RESERVATION_BELOW_REQUEST)


def execute_handoff(
    conn: StoreConnection,
    bundle: Bundle,
    blobs: BlobStore,
    *,
    assignment: Assignment,
    provider: CompletionProvider,
) -> HandoffOutcome:
    """Run one reserved attempt of a canonical pin from idle entry.

    Refuses `RUN_INPUT_INVALID` for a pin of any other adapter before the call.
    Billing, with the diagnostic address, commits before any analytical
    refusal. A validated `qa_status: Blocked` refuses `HANDOFF_BLOCKED` once
    the host identity has held and its citations were judged (D106).

    From before the call's lease check until its bill commits, the attempt is
    held (`call_hold`), so a worker that claims the run after this one's lease
    lapsed starts nothing at the node while this call may still be billed.
    """
    adapter = methodology.CANONICAL_ADAPTER_VERSION
    attempt, route_node_id = assignment.attempt_id, assignment.node.route_node_id
    with call_hold(conn, attempt):
        with execution_reads(conn):
            check_call(
                conn,
                attempt_id=attempt,
                run_id=assignment.run_id,
                route_node_id=route_node_id,
                lease=assignment.lease,
            )
            _stored_identity(conn, assignment, bundle, adapter=adapter)
            identity = _identity(conn, bundle, assignment)
            context = _prompt_context(conn, blobs, bundle, assignment, identity)
            taken = reserved_for(conn, attempt)
        # The record binds exactly the authority this prompt carries (§45.1).
        carried = delivered_authority(bundle, assignment.module_id)
        # Met before reservation by `check_context`; built again here so the
        # call carries exactly this attempt's identity, and refused again if it
        # moved. Whether it carries the refused answer is what the reservation
        # `check_context` priced says (D104), not a fresh read of the ceiling.
        prompt = _sent_prompt(
            provider,
            context,
            lambda built: _prompt(bundle, assignment, identity, built, carried),
            lambda size: _covered(provider, taken, size),
        )
        _within_reservation(conn, provider, prompt, attempt_id=attempt)

        bundle.verify_manifest()
        model = producer_identifier(provider.model, limit=256)
        if model is None:
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        require_idle(conn)
        # A transport that asks again after a rate limit re-reads the fence
        # first (ST-7): a lost lease or a recorded cancel sends nothing more.
        with resend_checked(lambda: _still_resendable(conn, assignment)):
            completion = provider.complete(prompt, json_object=True)
        charge = reported_charge(
            completion.charge if isinstance(completion.charge, Decimal) else None
        )
        generation = producer_identifier(completion.generation_id, limit=512)
        content = completion.content if completion.refusal is None else None
        diagnostic, unstored = _diagnostic(blobs, content)
        require_idle(conn)
        bill(conn, attempt, CallOutcome(charge, model, generation, diagnostic))
    if unstored:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    if completion.refusal is not None:
        code = completion.refusal
        if not isinstance(code, RefusalCode):
            code = RefusalCode.PROVIDER_RESPONSE_INVALID
        raise Refusal(code) from None
    if not isinstance(content, str) or charge is None or generation is None:
        raise Refusal(RefusalCode.PROVIDER_RESPONSE_INVALID)

    with execution_reads(conn):
        _run_still_holds(conn, assignment, bundle, adapter=adapter)
        judged = _answer(
            conn,
            bundle,
            blobs,
            assignment,
            identity=identity,
            context=context,
            carried=carried,
            content=content,
        )
    # The runtime re-derives a Blocked verdict, its citations with it, from
    # the stored body (`replay_billed`); the live call only says so.
    if isinstance(judged, BlockedAnswer):
        raise Refusal(RefusalCode.HANDOFF_BLOCKED)
    markdown, record = judged
    return HandoffOutcome(
        markdown=markdown,
        record=record,
        charge=charge,
        model=model,
        generation_id=generation,
        diagnostic_sha256=diagnostic,
    )


def _run_still_holds(
    conn: StoreConnection, assignment: Assignment, bundle: Bundle, *, adapter: str
) -> None:
    """The post-call unit's run checks -- the attempt, the pin, live authority
    -- as `replay_billed` makes them. A refusal here is the run's, not the
    answer's (R24-06), and says so by its class."""
    code: RefusalCode | None = None
    try:
        check_attempt(
            conn,
            attempt_id=assignment.attempt_id,
            run_id=assignment.run_id,
            route_node_id=assignment.node.route_node_id,
        )
        _stored_identity(conn, assignment, bundle, adapter=adapter)
    except Refusal as refused:
        code = refused.code
    # Raised outside the handler, so the refusal it replaces does not ride
    # along as context: the code is the whole of what travels.
    if code is not None:
        raise RunRefusal(code)


def _still_resendable(conn: StoreConnection, assignment: Assignment) -> None:
    """Refuse a re-send once the lease is lost or a cancel is recorded, in a
    read unit of its own on the idle connection (ST-7)."""
    with execution_reads(conn):
        require_resendable(conn, assignment.run_id, assignment.lease)


def bill(conn: StoreConnection, attempt_id: UUID, outcome: CallOutcome) -> None:
    """Record a call's outcome, retried a bounded number of times (ST-12).

    `record_outcome` replays an exact outcome as a no-op, so a write whose
    commit landed but whose answer was lost is safe to repeat. A connection the
    fault closed is replaced by a fresh one to the same store for the retry,
    when this environment names one; a store that stays down still refuses
    `STORE_UNAVAILABLE`, and the run is released as before. `BILL_TRIES`
    writes a `BILL_PAUSE_SECONDS` apart sit well inside the lease the call
    was made under.
    """
    for tries_left in range(BILL_TRIES - 1, -1, -1):
        try:
            _billed_once(conn, attempt_id, outcome)
        except Refusal as refused:
            if refused.code is not RefusalCode.STORE_UNAVAILABLE or not tries_left:
                raise
            _pause(BILL_PAUSE_SECONDS)
            continue
        return


def _billed_once(conn: StoreConnection, attempt_id: UUID, outcome: CallOutcome) -> None:
    if not conn.closed:
        record_outcome(conn, attempt_id=attempt_id, outcome=outcome)
        return
    try:
        fresh = connect(store_url())
    except (psycopg.Error, Refusal):
        # No store to retry against: the fault that closed it stands.
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    with fresh:
        record_outcome(fresh, attempt_id=attempt_id, outcome=outcome)


def _answer(  # noqa: PLR0913 -- one recorded answer, keyword-only
    conn: StoreConnection,
    bundle: Bundle,
    blobs: BlobStore,
    assignment: Assignment,
    *,
    identity: HostIdentity,
    context: _Context,
    carried: DeliveredAuthority,
    content: str,
) -> tuple[bytes, bytes] | BlockedAnswer:
    """The one post-call verdict on a recorded answer: its Markdown and record.

    Inside the caller's read unit, after it checked the attempt and the stored
    pin; the live call and `replay_billed` both decide here, so they cannot
    drift. `identity` is what the call was asked under. A validated Blocked
    handoff, anchored or not (D106), is a `BlockedAnswer` carrying its
    citations as judged, for the run's blocking verdict to keep.
    """
    # The identity carries every accepted upstream digest, so this one
    # comparison also catches an upstream rewritten during the call.
    if _identity(conn, bundle, assignment) != identity:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    if context.source_set is not None:
        _assert_originals(blobs, context.source_set)
    # ...and every ancestor's accepted pair, a record rewritten included.
    if _lineage_moved(conn, assignment.run_id, context.lineage):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    # Exactly what the prompt was built from: pins are immutable, so the
    # pre-call reading is this unit's too, without a second query.
    blocks = _by_source(context.delivered)
    markdown, citations, linked = parse_response(content)
    authority = assemble_authority(bundle, assignment.module_id)
    projections = _unless_blocked(
        lambda: validate_markdown(
            _contract(bundle),
            catalog(bundle),
            authority.files[SKILL],
            markdown,
            identity=identity,
            gate_expects=gate_expects(assignment.route, assignment.node),
        )
    )
    # Each quote must be an excerpt of one evidence line, as the final check
    # says (D105); one that is not is kept as unverified, never the answer's
    # refusal (D106).
    anchored, unverified = _partitioned(conn, blocks, citations, linked)
    # A validated Blocked handoff ends the run whatever its quotes anchored
    # (D106, superseding c-5b's guard): a citation fault never refuses an
    # answer, a Blocked one included. Its quotes are judged as any answer's
    # first, so one the host could not keep still refuses it as malformed.
    if projections is None:
        return BlockedAnswer(blocked_citations_bytes(anchored, unverified))
    # F494: every consumer measures these bytes against the upstream bound
    # (`invocation._upstream_section`), so a handoff over it would be accepted
    # here and refused at every next node, where no retry of this one reaches.
    # Refused here instead, as a guided retry told the size (`_size_line`).
    if len(markdown) > MAX_UPSTREAM_HANDOFF_BYTES:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    # F497, the same shape for the gate's T8 demand: a cell a consumer's
    # selection would refuse `EVIDENCE_DEMAND_UNRESOLVED` is refused here, as
    # a guided retry told the item (`_demand_lines`).
    if _demand_faults(bundle, assignment, context, markdown):
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    # D106's one exception, the same producer-guard shape: a citation CP-CF
    # will bind as a calculation input must anchor and be named by a marker
    # in this body (D107), or CP-CF cannot bind it and the run wedges there;
    # refused here, as a guided retry naming it.
    if _calculation_inputs(assignment, _unbindable(anchored, unverified)):
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE)
    _forecast_inputs(bundle, assignment.module_id, markdown, context)
    record = CanonicalRecord(
        artifact_sha256=hashlib.sha256(markdown).hexdigest(),
        adapter_version=methodology.CANONICAL_ADAPTER_VERSION,
        build_id=authority.build_id,
        manifest_sha256=bundle.manifest_sha256,
        authority_bundle_sha256=identity.authority_bundle_sha256,
        authority_digest=authority_digest(authority),
        delivered_authority_digest=delivered_authority_digest(carried),
        identity=identity,
        lineage=context.lineage,
        projections=projections,
        citations=anchored,
        citation_rule=EXCERPT,
        unverified=unverified,
    )
    return markdown, _written(record)


def _partitioned(
    conn: StoreConnection,
    blocks: dict[UUID, frozenset[str]],
    citations: Sequence[Citation],
    linked: Sequence[bool],
) -> tuple[tuple[AnchoredCitation, ...], tuple[UnverifiedCitation, ...]]:
    """An answer's citations, in order, as anchored -- host-verified under
    `EXCERPT` (D105), flagged not linked to a statement where no marker in
    the body names it -- and unverified: the module's own locator and
    quote with the anchoring refusal that left it so (D106). Each keeps its
    place in the list, which its markers name (`marker`, D107). Each is
    judged alone (`_judged`), so one citation's verdict never moves
    another's. A quote that cannot be kept as unverified
    (`unverified_citation`) refuses `HANDOFF_MALFORMED`, a host text check."""
    anchored: list[AnchoredCitation] = []
    unverified: list[UnverifiedCitation] = []
    judged = _judged(conn, blocks, citations, TokenIndex())
    for place, (citation, held, found) in enumerate(
        zip(citations, linked, judged, strict=True), 1
    ):
        if isinstance(found, AnchoredCitation):
            anchored.append(replace(found, linked=held, marker=place))
        else:
            unverified.append(
                unverified_citation(citation, found, linked=held, marker=place)
            )
    return tuple(anchored), tuple(unverified)


def _written(record: CanonicalRecord) -> bytes:
    """`record_bytes`, or `HANDOFF_MALFORMED` where it refuses the record's
    lines (`_lines_held`, D105): a typed refusal the retry and replay read
    as any other, never a `ValueError` that stops a billed run as a host
    fault (fix round 2)."""
    try:
        return record_bytes(record)
    except ValueError:
        pass
    raise Refusal(RefusalCode.HANDOFF_MALFORMED)


def check_context(  # noqa: PLR0913 -- one node of one run, keyword-only
    conn: StoreConnection,
    bundle: Bundle,
    blobs: BlobStore,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    node: RouteNode,
    provider: CompletionProvider,
) -> int:
    """Build the node's whole prompt before any attempt, reservation or call,
    and return the request size the call will be priced on.

    The pre-call unit `execute_handoff` runs, under `prospective_identity`, so
    every refusal the prompt would raise -- `CONTEXT_OVER_CEILING` on the whole
    request `provider` would send, and a delivered file whose bytes moved -- is
    raised while nothing has been started or set aside (§45.3, invariant 8).
    The prompt itself is not kept: the attempt's own is rebuilt from its own
    read unit, and the reservation this measurement produced is what that
    rebuild is then checked against (Task 8.2).
    """
    assignment = Assignment(node.module_id, run_id, node, route, _NO_ATTEMPT)
    with execution_reads(conn):
        _stored_identity(
            conn, assignment, bundle, adapter=methodology.CANONICAL_ADAPTER_VERSION
        )
        identity = prospective_identity(
            conn, bundle, run_id=run_id, route=route, node=node
        )
        context = _prompt_context(conn, blobs, bundle, assignment, identity)
        left = remaining(conn, run_id) if context.refused_answer else None
    authority = delivered_authority(bundle, node.module_id)
    prompt = _sent_prompt(
        provider,
        context,
        lambda built: _prompt(bundle, assignment, identity, built, authority),
        lambda size: _affordable(provider, left, size),
    )
    return request_size(provider, prompt)


# `check_context` runs before an attempt exists; nothing it reads uses the id.
_NO_ATTEMPT = UUID(int=0)


@dataclass(frozen=True, slots=True)
class _Context:
    """What one prompt is built from, each part read in one pre-call unit."""

    # What the node is handed: the whole pin, or the members its gate row names.
    delivered: list[Delivery]
    upstream: tuple[tuple[UpstreamRef, bytes], ...]
    lineage: tuple[LineageRef, ...]
    # Each direct upstream's anchored citations, from its verified record.
    citations: dict[str, tuple[AnchoredCitation, ...]]
    source_set: SourceSet | None
    # Why `delivered` is what it is (§95); the gate's own is always the whole pin.
    selection: Selection
    # What a node's guided retry carries (D30, D82); empty on every other.
    feedback: tuple[str, ...] = ()
    # The refused answer that retry is asked to correct (D104), or None.
    refused_answer: str | None = None
    # Each direct upstream's unverified citations (D106), whose markers the
    # register names as unlocated (D107).
    unverified: dict[str, tuple[UnverifiedCitation, ...]] = field(default_factory=dict)


def _source_preparation(
    conn: StoreConnection,
    blobs: BlobStore,
    assignment: Assignment,
    delivered: Sequence[Delivery],
) -> SourceSet | None:
    """CP-0 alone receives the verified source snapshot it must prepare."""
    if assignment.module_id != GATE_MODULE:
        return None
    source_set = _pinned_source_set(conn, assignment.run_id)
    if {member.source_id for member in source_set.members} != {
        item.source_id for item in delivered
    }:
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)
    _assert_originals(blobs, source_set)
    return source_set


def _pinned_source_set(conn: StoreConnection, run_id: UUID) -> SourceSet:
    """The run's pinned source-set version, verified against its pin."""
    pin = load_run_input(conn, run_id)
    if pin is None:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    source_set = load_source_set(conn, pin.case_id, pin.source_version)
    if source_set is None or source_set.fingerprint != pin.source_fingerprint:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    return source_set


def _selected(
    conn: StoreConnection,
    bundle: Bundle,
    assignment: Assignment,
    upstream: Sequence[tuple[UpstreamRef, bytes]],
    delivered: list[Delivery],
) -> tuple[list[Delivery], Selection]:
    """The deliveries a consumer is handed: the pin narrowed to the members
    its gate row names (§95), read from the accepted CP-0 Markdown the unit
    has just verified, through the vendor's own T8 parser.

    Pure over pinned inputs, so the pre-call check, the attempt and a crash
    replay select alike. The whole pin was already read and counted against
    the pin by `read_run_blocks`, so a withdrawn member still refuses before
    anything is narrowed (invariant 1). The pinned members are read only when
    the cell has items to map, so a node without a demand -- the gate itself,
    the host's CP-CF, a row whose source-files cell is empty -- costs no extra
    round trip. (The vendor's parser reads the legacy header's column too.)
    """
    if assignment.module_id == GATE_MODULE:
        # §98: the whole pin, a source past the gate bound as its page map.
        shown, maps = gate_view(delivered)
        basis = Basis.PAGE_MAP if maps else Basis.WHOLE_NO_DEMAND
        return shown, Selection(basis, None, page_maps=maps)
    gate = next(data for ref, data in upstream if ref.module_id == GATE_MODULE)
    cell = demand_cells(_contract(bundle).navigation, catalog(bundle), gate).get(
        assignment.module_id
    )
    if cell is None or not demand_items(cell):
        return delivered, Selection(Basis.WHOLE_NO_DEMAND, None)
    last_pages: dict[UUID, int] = {}
    for item in delivered:
        last_pages[item.source_id] = max(item.page, last_pages.get(item.source_id, 0))
    selection = select_sources(
        _pinned_source_set(conn, assignment.run_id).members,
        cell,
        last_pages=last_pages,
    )
    if selection.whole:
        return delivered, selection
    return [d for d in delivered if selection.delivers(d.source_id, d.page)], selection


def _assert_originals(blobs: BlobStore, source_set: SourceSet) -> None:
    """Keep original-blob failures typed and free of filesystem context."""
    refusal: RefusalCode | None = None
    for member in source_set.members:
        try:
            blobs.get(member.document_sha256)
        except OSError:
            refusal = RefusalCode.STORE_UNAVAILABLE
            break
        except Refusal as caught:
            refusal = caught.code
            break
    if refusal is not None:
        raise Refusal(refusal)


def _context(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    assignment: Assignment,
    identity: HostIdentity,
) -> _Context:
    """The delivered evidence, the verified upstream, its whole accepted lineage
    and its citation register, read inside the caller's unit after it checked
    the stored pin. Only accepted rows reach any part: a Blocked or refused
    attempt's diagnostic body is never read here (a guided retry's lines are
    read beside it, by the two prompt builders alone: `_prompt_context`)."""
    delivered = _delivered(conn, assignment.run_id)
    source_set = _source_preparation(conn, blobs, assignment, delivered)
    # Records first: what binds and re-validates is then read as context.
    records, lineage = _upstream_records(
        conn, blobs, bundle, assignment, identity.upstream
    )
    upstream = upstream_markdown(blobs, identity.upstream)
    # The gate's verified record is what the selection is read from (§95).
    delivered, selection = _selected(conn, bundle, assignment, upstream, delivered)
    return _Context(
        delivered=delivered,
        upstream=upstream,
        lineage=lineage,
        citations={node: record.citations for node, record in records.items()},
        source_set=source_set,
        selection=selection,
        unverified={node: record.unverified for node, record in records.items()},
    )


def _prompt_context(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    assignment: Assignment,
    identity: HostIdentity,
) -> _Context:
    """`_context` for a prompt about to be priced or sent: with the lines a
    node's guided retry carries (D30, D82). Replay and the readers never
    build a prompt, so they never pay for the ledger read this adds."""
    context = _context(conn, blobs, bundle, assignment, identity)
    fed = _feedback_body(conn, blobs, assignment)
    if fed is None:
        return context
    body, refused = fed
    skill = assemble_authority(bundle, assignment.module_id).files[SKILL]
    contract, pathways = _contract(bundle), catalog(bundle)
    host = (
        *_demand_lines(bundle, assignment, context, body),
        *_owner_lines(bundle, assignment, context, body),
        _anchoring_line(conn, context.delivered, answer_citations(body)),
        readiness_set_line(
            contract,
            pathways,
            body,
            gate_expects(assignment.route, assignment.node),
        ),
        _driver_line(contract, assignment, context, body),
        _size_line(answer_markdown(body)),
        _calculation_line(conn, assignment, context.delivered, body),
    )
    # Judged under the identity the refused answer was asked under: its
    # ordinal, not this attempt's, fixes the attempt id and invocation digest
    # it had to copy, so only a field it really copied wrong is named.
    with suppress(Refusal):  # an attempt from before ordinals: this identity
        identity = replace(identity, ordinal=attempt_ordinal(conn, refused))
    lines = feedback_lines(contract, pathways, identity, body, skill=skill)
    feedback = capped([line for line in host if line] + list(lines))
    # The answer rides only beside its checks (D104): with none, no block.
    answer = carried_answer(body) if feedback else None
    return replace(context, feedback=feedback, refused_answer=answer)


def _demand_faults(
    bundle: Bundle, assignment: Assignment, context: _Context, markdown: bytes
) -> list[tuple[str, DemandFault]]:
    """Each route consumer's T8 cell in the gate's answer that its selection
    would refuse (F497), by module and the item at fault: `demand_fault`,
    `select_sources`' own rule, over the pinned members and the last page of
    each the consumer will see. Empty for every other module. Pure over the
    pin and the answer, so the live call and `replay_billed` agree. The
    gate's view shows every page of every member (`gate_view` keeps at least
    one line a page), so its last pages are the consumer's."""
    if assignment.module_id != GATE_MODULE or context.source_set is None:
        return []
    consumers = {n.module_id for n in assignment.route.nodes} - {GATE_MODULE}
    cells = demand_cells(_contract(bundle).navigation, catalog(bundle), markdown)
    last_pages: dict[UUID, int] = {}
    for item in context.delivered:
        last_pages[item.source_id] = max(item.page, last_pages.get(item.source_id, 0))
    members = context.source_set.members
    return [
        (module, fault)
        for module, cell in cells.items()
        if module in consumers
        and (fault := demand_fault(members, cell, last_pages=last_pages)) is not None
    ]


# What a retry is told of each T8 item at fault (F497), after the row and the
# item the gate wrote.
_DEMAND_FIX = {
    Fault.UNKNOWN: (
        "which is no source of this run; write each source by its exact filename"
        " as listed in the host source preparation metadata"
    ),
    Fault.AMBIGUOUS: (
        "which names more than one source of this run; write each source by its"
        " exact filename as listed in the host source preparation metadata"
    ),
    Fault.PAGES: (
        "whose pages that source does not carry; name pages from 1 to its last"
        " page, or the source whole"
    ),
    Fault.PAGE_FORM: (
        "whose page form the host cannot read; write one range per item, as"
        " `<filename> pages <first>-<last>` or `<filename> page <n>`, separated"
        ' by ";"'
    ),
}


def _demand_lines(
    bundle: Bundle, assignment: Assignment, context: _Context, body: str
) -> list[str]:
    """The gate retry's lines for its refused answer's T8 cells at fault
    (F497): the row and the item, the model's own text told back (D30),
    across the boundary and bounded like a vendor message (`_bounded`)."""
    markdown = answer_markdown(body)
    if markdown is None:
        return []
    try:
        faults = _demand_faults(bundle, assignment, context, markdown)
    except Refusal:  # a T8 the vendor cannot read: its own checks say so
        return []
    return [
        line
        for module, found in faults
        if (
            line := _bounded(
                "host demand check",
                f'T8 row {module} names "{found.item}", {_DEMAND_FIX[found.fault]}',
            )
        )
    ]


# How many lines a retry is told the owner restrictions it dropped on (F510);
# the items past them are counted on one more line.
MAX_OWNER_LINES = 6


def _owner_lines(
    bundle: Bundle, assignment: Assignment, context: _Context, body: str
) -> list[str]:
    """CP-5's and CP-CF's retry lines for the owner restrictions its refused
    answer dropped (F510): `owner_restriction_gaps`, the comparison
    `_forecast_inputs` refuses `HANDOFF_INCOMPLETE` on, which told the retry
    nothing (LFCS1 CP-5, three times). The items are the upstream owners' own
    front matter, already in this prompt's upstream handoffs (D30)."""
    module, markdown = assignment.module_id, answer_markdown(body)
    if module not in {MODEL_MODULE, "CP-5"} or markdown is None:
        return []
    with suppress(Exception):  # an answer the validator cannot read says so itself
        gaps = owner_restriction_gaps(
            _contract(bundle),
            markdown,
            [data for _ref, data in context.upstream],
            selection=(CREDIT_SCREEN_SELECTION if module == "CP-5" else None),
        )
        return owner_messages(module, gaps)
    return []


def owner_messages(module: str, gaps: Sequence[OwnerGap]) -> list[str]:
    """The lines for `gaps`: the qa_status rule naming the Restricted owners,
    then each dropped item quoted once with every owner that carries it,
    packed up to `MAX_FEEDBACK_CHARS` a line, at most `MAX_OWNER_LINES` lines
    and one more counting the items not shown."""
    lines: list[str] = []
    restricted = list(dict.fromkeys(g.owner for g in gaps if g.key == "qa_status"))
    if restricted:
        lines.append(
            f"host owner check: {module}'s qa_status must be Restricted while an"
            f" upstream owner's is; Restricted: {', '.join(restricted)}"
        )
    packed = _packed_items(module, gaps)
    lines += [
        line
        for text, _n in packed[:MAX_OWNER_LINES]
        if (line := _bounded("host owner check", text))
    ]
    if rest := sum(n for _text, n in packed[MAX_OWNER_LINES:]):
        lines.append(f"host owner check: {rest} more missing items not shown")
    return lines


def _packed_items(module: str, gaps: Sequence[OwnerGap]) -> list[tuple[str, int]]:
    """(line text, items on it) for the dropped items, by front matter list."""
    owners: dict[tuple[str, str], list[str]] = {}
    for gap in gaps:
        if gap.key != "qa_status":
            owners.setdefault((gap.key, gap.item), []).append(gap.owner)
    head = (
        f"{module}'s front matter must carry each upstream owner's"
        " limitation_flags and validation_warnings exactly; "
    )
    packed: list[tuple[str, int]] = []
    for key in OWNER_KEYS:
        text, count = f"{head}missing from {key}: ", 0
        for (listed, item), named in owners.items():
            if listed != key:
                continue
            entry = f"«{item}» (from {', '.join(dict.fromkeys(named))})"
            if count and len(text) + 2 + len(entry) > MAX_FEEDBACK_CHARS:
                packed.append((text, count))
                text, count = f"also missing from {key}: ", 0
            text, count = text + (", " if count else "") + entry, count + 1
        if count:
            packed.append((text, count))
            head = ""
    return packed


def _calculation_inputs(assignment: Assignment, quotes: Sequence[str]) -> list[int]:
    """Which of `quotes` CP-CF will bind as calculation inputs owned by this
    node's module (`forecast.binds_input`), by index: none unless the pinned
    route runs CP-CF and this module owns one of its sections. Pure over the
    pin and the answer, so the live call and `replay_billed` agree."""
    from caos.methodology.forecast import FORECAST_OWNERS, binds_input

    module = assignment.module_id
    if module not in FORECAST_OWNERS or MODEL_MODULE not in {
        node.module_id for node in assignment.route.nodes
    }:
        return []
    return [n for n, quote in enumerate(quotes) if binds_input(module, quote)]


def _unbindable(
    anchored: Sequence[AnchoredCitation], unverified: Sequence[UnverifiedCitation]
) -> list[str]:
    """The quotes CP-CF could not bind from this answer, judged by quote as
    the binder judges them (`forecast.validate_forecast_bindings`, D107): a
    quote binds when some anchored citation of it is one a marker in the
    body names (`linked`), so an unverified or unmarked citation of a quote
    another citation binds is no fault."""
    bound = {c.matched_text for c in anchored if c.linked}
    quotes = [c.matched_text for c in anchored] + [e.matched_text for e in unverified]
    return [quote for quote in quotes if quote not in bound]


def _calculation_line(
    conn: StoreConnection,
    assignment: Assignment,
    delivered: Sequence[Delivery],
    body: str,
) -> str | None:
    """The owner retry's line for its citations CP-CF binds but could not
    (D106, `_unbindable`), by number: unlike every other citation they
    refuse the answer until each anchors and a marker names it (D107).
    The anchoring and marker lines beside it say what is wrong with each.
    None for every other module and route."""
    citations = answer_citations(body)
    markdown = answer_markdown(body) or b""
    if not _calculation_inputs(assignment, [c.matched_text for c in citations]):
        return None
    verdicts = _anchoring(conn, _by_source(delivered), citations, TokenIndex())
    named = frozenset(markers(markdown.decode("utf-8")))
    # By quote, as `_unbindable` and the binder judge: a quote some anchored,
    # marked citation carries binds, and stands as "", which binds nothing.
    bound = {
        c.matched_text
        for place, (c, v) in enumerate(zip(citations, verdicts, strict=True), 1)
        if v is None and place in named
    }
    lost = ["" if c.matched_text in bound else c.matched_text for c in citations]
    failed = [n + 1 for n in _calculation_inputs(assignment, lost)]
    if not failed:
        return None
    many = len(failed) > 1
    return (
        f"host calculation-input check: {_numbered(failed)} of {len(citations)}"
        f" {'feed' if many else 'feeds'} the forecast calculator (CP-CF) and must"
        " be an exact excerpt of one evidence line that anchors, named by its"
        " [C<n>] marker in the Markdown body; unlike other citations,"
        f" {'they refuse' if many else 'it refuses'} this answer until then (the"
        " host anchoring and marker checks say what is wrong with each;"
        " numbered from 1 in the order given)"
    )


def _size_line(markdown: bytes | None) -> str | None:
    """The retry line for a handoff over the upstream bound `_answer` refuses
    (F494), its size and the bound in figures and never its text; None within
    the bound or when the answer is not the transport."""
    if markdown is None or len(markdown) <= MAX_UPSTREAM_HANDOFF_BYTES:
        return None
    return (
        f"host size check: your handoff is {len(markdown):,} bytes; the host's"
        f" bound is {MAX_UPSTREAM_HANDOFF_BYTES:,}; shorten it (for example quote"
        " fewer or shorter evidence lines) and keep every register"
    )


def _driver_line(
    contract: VendorContract, assignment: Assignment, context: _Context, body: str
) -> str | None:
    """CP-CF's second attempt told which of CP-2G's driver rows its refused
    request cannot map, by row (G3-9); None for every other module."""
    if assignment.module_id != MODEL_MODULE:
        return None
    owner = next(
        (data for ref, data in context.upstream if ref.module_id == "CP-2G"), None
    )
    markdown = answer_markdown(body)
    if owner is None or markdown is None:
        return None
    from caos.methodology.forecast import driver_line

    return driver_line(contract, markdown, owner)


# The refusals whose checks a guided retry can be told of (D30, N52, D82): the
# validator's and the host's own (`HANDOFF_MALFORMED`), the completeness
# checker's (`HANDOFF_INCOMPLETE`), and -- owner-approved on 2026-09-23
# (G1-16) -- a host-owned field copied wrong or a field no handoff may carry,
# each told by field name (`handoff._front_matter_lines`). Anchoring's own
# codes left it with D106: a citation that does not anchor no longer refuses
# an accepted answer, and its lines ride a retry another check earned only as
# advice (`handoff.ADVISORY`).
SECOND_ATTEMPT_CODES = frozenset(
    {
        RefusalCode.HANDOFF_MALFORMED,
        RefusalCode.HANDOFF_INCOMPLETE,
        RefusalCode.HANDOFF_IDENTITY_MISMATCH,
        RefusalCode.HANDOFF_UNDECLARED_FIELD,
    }
)
# How many guided retries one node gets (D82 and its amendment of 4 October
# 2026; D30 gave one): its 2nd, 3rd and 4th attempts, each told what the
# attempt just before it was refused for.
GUIDED_RETRIES = 3


def _feedback_source(attempts: Sequence[NodeAttempt]) -> NodeAttempt | None:
    """The refused attempt a node's next attempt answers, when that next one is
    a guided retry (D30, D82): the latest attempt, refused with one of
    `SECOND_ATTEMPT_CODES`, while the node holds at most `GUIDED_RETRIES` such
    refusals -- so its 2nd, 3rd and 4th attempts are told of the 1st, 2nd and 3rd, and
    every later attempt is an ordinary one. Read from the ledger, so a crash
    between a refusal and its retry changes nothing."""
    refused = [a for a in attempts if a.refusal in SECOND_ATTEMPT_CODES]
    if not refused or len(refused) > GUIDED_RETRIES or attempts[-1] != refused[-1]:
        return None
    return refused[-1]


def second_attempt_due(
    conn: StoreConnection, *, run_id: UUID, route_node_id: str
) -> bool:
    """Whether this node's next attempt is a guided retry (D30, D82)."""
    with execution_reads(conn):
        return _feedback_source(node_attempts(conn, run_id, route_node_id)) is not None


def _feedback_body(
    conn: StoreConnection, blobs: BlobStore, assignment: Assignment
) -> tuple[str, UUID] | None:
    """The refused answer this attempt answers and the attempt that gave it,
    when this is a guided retry (D30, D82), else None.

    Counted from the attempts before this one, so the prospective prompt that
    is priced and the attempt's own rebuilt prompt carry the same lines. A body
    that is lost or corrupt leaves the retry a plain one: the lines are
    help, not a verdict, and parking the run over them would cost the attempt.
    """
    attempts = node_attempts(conn, assignment.run_id, assignment.node.route_node_id)
    ids = [attempt.attempt_id for attempt in attempts]
    before = ids.index(assignment.attempt_id) if assignment.attempt_id in ids else None
    source = _feedback_source(attempts[:before])
    if source is None or source.diagnostic_sha256 is None:
        return None
    body: str | None = None
    try:
        body = _stored_body(blobs, source.diagnostic_sha256)
    except Refusal as lost:
        if lost.code not in _BLOB_LOST:
            raise
    return None if body is None else (body, source.attempt_id)


def _anchoring_line(
    conn: StoreConnection, delivered: Sequence[Delivery], citations: Sequence[Citation]
) -> str | None:
    """The host anchoring line a retry carries (`anchoring_line`): each
    citation's verdict, and where the host's own search places each refused
    `CITATION_NOT_LOCATED` among what the node was given (D82), marked
    advisory (`ADVISORY`, D106)."""
    index = TokenIndex()
    blocks = _by_source(delivered)
    verdicts = _anchoring(conn, blocks, citations, index)
    # Only the citations the line can place are searched (`anchoring_line`).
    lost = [
        n
        for n, verdict in enumerate(verdicts)
        if verdict is RefusalCode.CITATION_NOT_LOCATED
    ][:MAX_FEEDBACK_CITATIONS]
    hints: list[LineHint | None] = [None] * len(verdicts)
    for n in lost:
        hints[n] = _line_hint(conn, delivered, blocks, citations[n], index)
    # An ambiguous quote that is a whole line cannot be lengthened within it
    # (fix round 1): told so, read from the delivered text alone.
    twice = [
        n
        for n, verdict in enumerate(verdicts)
        if verdict is RefusalCode.CITATION_AMBIGUOUS
    ][:MAX_FEEDBACK_CITATIONS]
    for n in twice:
        if _whole_on_its_page(delivered, citations[n]):
            hints[n] = LineHint(repeated=True)
    # A source_id the request never offered (F495): told so, not "a page or
    # line this node was not given", which names nothing to fix.
    holders: dict[tuple[int, str], set[UUID]] | None = None
    for n, verdict in enumerate(verdicts):
        source = citations[n].source_id
        if verdict is RefusalCode.CITATION_NOT_DELIVERED and source not in blocks:
            holders = _holders(delivered) if holders is None else holders
            held = holders.get(_quoted_at(citations[n]), set())
            hints[n] = LineHint(
                unknown_source=str(source),
                held_by=str(next(iter(held))) if len(held) == 1 else "",
            )
    line = anchoring_line(verdicts, hints)
    # Advice beside a retry another check earned, never its reason (D106).
    return None if line is None else line + ADVISORY


def _whole_on_its_page(delivered: Sequence[Delivery], citation: Citation) -> bool:
    """Whether the quote is all of a delivered line of its cited page
    (`whole_line_of`), from the delivered blocks' own text only."""
    return any(
        whole_line_of(citation.matched_text, d.text.value)
        for d in delivered
        if d.source_id == citation.source_id and d.page == citation.page
    )


def _quoted_at(citation: Citation) -> tuple[int, str]:
    """A citation's cited page and its quote's words joined by one space."""
    return citation.page, " ".join(citation.matched_text.split())


def _holders(delivered: Sequence[Delivery]) -> dict[tuple[int, str], set[UUID]]:
    """The sources holding each delivered line, by page and the line's words
    joined by one space (F495): read from the delivered blocks' own text
    only, so nothing the node was not given is read or shown (D82's M2)."""
    holders: dict[tuple[int, str], set[UUID]] = {}
    for d in delivered:
        key = (d.page, " ".join(d.text.value.split()))
        holders.setdefault(key, set()).add(d.source_id)
    return holders


def _anchoring(
    conn: StoreConnection,
    blocks: dict[UUID, frozenset[str]],
    citations: Sequence[Citation],
    index: TokenIndex,
) -> list[RefusalCode | None]:
    """Each citation's own anchoring refusal (`_judged`), None for one that
    anchored."""
    return [
        None if isinstance(found, AnchoredCitation) else found
        for found in _judged(conn, blocks, citations, index)
    ]


def _judged(
    conn: StoreConnection,
    blocks: dict[UUID, frozenset[str]],
    citations: Sequence[Citation],
    index: TokenIndex,
) -> list[AnchoredCitation | RefusalCode]:
    """Each citation anchored by the rule an answer is judged by
    (`verify_citations` under `EXCERPT`), or its own anchoring refusal
    (`UNVERIFIED_CODES`), one at a time so every one is named. Any other
    refusal -- the store, a source whose blocks no longer read -- is raised:
    it is not the citation's fault."""
    verdicts: list[AnchoredCitation | RefusalCode] = []
    for citation in citations:
        try:
            [found] = verify_citations(
                conn,
                delivered=blocks,
                citations=(citation,),
                index=index,
                rule=EXCERPT,
            )
        except Refusal as refused:
            if refused.code not in UNVERIFIED_CODES:
                raise
            verdicts.append(refused.code)
        else:
            verdicts.append(found)
    return verdicts


def _line_hint(
    conn: StoreConnection,
    delivered: Sequence[Delivery],
    blocks: dict[UUID, frozenset[str]],
    citation: Citation,
    index: TokenIndex,
) -> LineHint:
    """Where `find_line` places a citation refused `CITATION_NOT_LOCATED`
    (D82): the other delivered pages it is an excerpt of a line of, that no
    delivered line holds it, or -- found nowhere as one excerpt -- the line
    it runs past the end of, nearly matches or left cells out of
    (`_near_hint`), or that it runs from one delivered line onto the next
    (`across`). A quote of fewer than `MIN_EXCERPT_WORDS` words that is
    none of those is told it is too short (D105): it is part of a longer
    line, or no whole line, and only more words make it an excerpt. The
    search is help, not a verdict: a refusal from it (a source whose blocks
    no longer read as written, say) leaves the citation unplaced rather than
    costing the retry."""
    source = citation.source_id
    try:
        found = find_line(
            conn,
            blocks=blocks.get(source, frozenset()),
            pages={d.page for d in delivered if d.source_id == source},
            citation=citation,
            index=index,
        )
    except Refusal:
        return LineHint()
    if found.block_id is None and not found.pages:
        near = (
            _near_hint(delivered, citation, overrun_line, overrun=True)
            or _near_hint(delivered, citation, near_line)
            or _near_hint(delivered, citation, cells_line, cells=True)
        )
        if near is not None:
            return near
    short = len(citation.matched_text.split()) < MIN_EXCERPT_WORDS
    return LineHint(
        pages=found.pages,
        absent=found.absent,
        across=found.across,
        short=short and not (found.pages or found.absent or found.across),
    )


def _near_hint(
    delivered: Sequence[Delivery],
    citation: Citation,
    search: Callable[[str, Sequence[str]], int | None],
    *,
    cells: bool = False,
    overrun: bool = False,
) -> LineHint | None:
    """The near-miss hint (F493) for a citation `find_line` could neither
    find part of a line nor whole on another page: the one delivered line of
    its source `search` names -- the line it runs past the end of
    (`overrun_line`, F496, `overrun`: shown by its last `END_WORDS` words,
    and `short` when fewer than `MIN_EXCERPT_WORDS` quoted words lie in it),
    the line it nearly matches (`near_line`), or the row it left cells out
    of (`cells_line`, F495, `cells`) -- by page and first `HINT_WORDS`
    words. Only the delivered blocks' own text is compared, so nothing the
    node was not given is read or shown."""
    lines = list(
        {d.block_id: d for d in delivered if d.source_id == citation.source_id}.values()
    )
    found = search(citation.matched_text, [d.text.value for d in lines])
    if found is None:
        return None
    line = lines[found]
    words = line.text.value.split()
    kept = overrun_kept(citation.matched_text, line.text.value) if overrun else 0
    return LineHint(
        begins="" if overrun else " ".join(words[:HINT_WORDS]),
        near=line.page,
        moved=line.page != citation.page,
        cells=cells,
        ends=" ".join(words[-END_WORDS:]) if overrun else "",
        short=0 < kept < MIN_EXCERPT_WORDS,
    )


def _lineage_moved(
    conn: StoreConnection, run_id: UUID, lineage: tuple[LineageRef, ...]
) -> bool:
    """Whether any ancestor's accepted (artifact, record) pair is no longer the
    one the prompt's lineage named. One query, none without lineage."""
    if not lineage:
        return False
    accepted = {row[0]: (row[2], row[3]) for row in accepted_rows(conn, run_id)}
    return any(
        accepted.get(link.route_node_id) != (link.artifact_sha256, link.record_sha256)
        for link in lineage
    )


def _prompt(
    bundle: Bundle,
    assignment: Assignment,
    identity: HostIdentity,
    context: _Context,
    authority: DeliveredAuthority,
) -> str:
    """The prompt over exactly the delivered authority (§45.1): names from the
    manifest and the verified SKILL.md, never from evidence or upstream text."""
    return build_handoff_prompt(
        _contract(bundle),
        identity=identity,
        authority=authority,
        catalog=catalog(bundle),
        delivered=context.delivered,
        upstream=context.upstream,
        upstream_citations=context.citations,
        upstream_unverified=context.unverified,
        route=assignment.route,
        source_set=context.source_set,
        page_maps=context.selection.page_maps,
        retry_feedback=context.feedback,
        refused_answer=context.refused_answer,
    )


def _sent_prompt(
    provider: CompletionProvider,
    context: _Context,
    prompt_of: Callable[[_Context], str],
    affords: Callable[[int], bool],
) -> str:
    """The prompt `prompt_of` builds, less the refused answer a guided retry
    would carry when carrying it puts the request `provider` sends past
    `MAX_REQUEST_BYTES`, the transport ceiling a reservation is priced under,
    or past what `affords` says the run can pay for that many bytes (D104):
    that retry asks for the whole answer again instead, which the ceiling may
    still cover, rather than being lost to `BUDGET_CEILING_REACHED`. The
    prompt priced before the reservation (`check_context`, against the run's
    remaining ceiling) and the one sent (`execute_handoff`, against the
    reservation that pricing produced) both come from here, so they choose
    alike; were they ever to differ, `_within_reservation` refuses the
    larger."""
    prompt = prompt_of(context)
    if context.refused_answer is None:
        return prompt
    size = len(provider.request_bytes(prompt, json_object=True))
    if size <= MAX_REQUEST_BYTES and affords(size):
        return prompt
    return prompt_of(replace(context, refused_answer=None))


def _affordable(provider: CompletionProvider, left: Decimal | None, size: int) -> bool:
    """Whether a request of `size` bytes, priced at the price `provider`
    bills at, fits the run's remaining ceiling `left` (D104). A provider that
    states no price cannot be priced here; its reservation is refused anyway
    (`bills_at`), so the answer stays as it was."""
    from caos.pricing import ModelPrice, priced_request

    price = getattr(provider, "price", None)
    if left is None or not isinstance(price, ModelPrice):
        return True
    return priced_request(price, size) <= left


def _covered(
    provider: CompletionProvider, taken: Reservation | None, size: int
) -> bool:
    """Whether this attempt's own reservation covers a request of `size`
    bytes at the price it was taken under (D104): the record of what
    `check_context` chose, since it reserved exactly the request it priced.
    None, or another price, is refused by `_within_reservation` whichever
    prompt is built."""
    from caos.pricing import bills_at, priced_request

    if taken is None or not bills_at(provider, taken.price):
        return False
    return priced_request(taken.price, size) <= taken.amount


def _by_source(delivered: Sequence[Delivery]) -> dict[UUID, frozenset[str]]:
    """Source to the block ids a node was handed, from its deliveries."""
    blocks: dict[UUID, set[str]] = {}
    for delivery in delivered:
        blocks.setdefault(delivery.source_id, set()).add(delivery.block_id)
    return {source: frozenset(ids) for source, ids in blocks.items()}


def _unless_blocked(validate: Callable[[], Projections]) -> Projections | None:
    """The projections, or None for a validated Blocked handoff."""
    try:
        return validate()
    except Refusal as refusal:
        if refusal.code is not RefusalCode.HANDOFF_BLOCKED:
            raise
    return None


# Refusals that say the store, not the answer, failed: never read as a verdict.
_STORE_FAULTS = frozenset(
    {
        RefusalCode.BLOB_ADDRESS_INVALID,
        RefusalCode.BLOB_DIGEST_MISMATCH,
        RefusalCode.BLOB_NOT_FOUND,
        RefusalCode.STORE_UNAVAILABLE,
        RefusalCode.STORE_NOT_TRANSACTIONAL,
    }
)


class Verdict(StrEnum):
    """What a billed answer's stored body re-derives to (brief 4.3 D7)."""

    ANSWERED = "ANSWERED"
    BLOCKED = "BLOCKED"
    REFUSED = "REFUSED"


@dataclass(frozen=True, slots=True)
class Replayed:
    """One billed, unaccepted, unexplained attempt and its re-derived verdict:
    the outcome to accept when ANSWERED, the refusal's code when REFUSED, the
    Blocked answer's citations as judged when BLOCKED (D106)."""

    attempt_id: UUID
    verdict: Verdict
    outcome: HandoffOutcome | None = None
    code: RefusalCode | None = None
    citations: bytes | None = None


@dataclass(frozen=True, slots=True)
class BlockedAnswer:
    """A validated Blocked handoff's verdict (D106): no record is written, so
    its citations, judged as any answer's, are what it keeps --
    `handoff.blocked_citations_bytes`, stored beside the run's blocking
    verdict for the blocked view."""

    citations: bytes


def unexplained_charge(
    conn: StoreConnection,
    *,
    run_id: UUID,
    route_node_ids: Sequence[str],
) -> str | None:
    """A ready node already paid for whose answer was never stored.

    `_diagnostic` can fail to write its body after `record_outcome` has already
    committed the charge: the bytes are gone, and `replay_billed` cannot settle
    the attempt because it requires a diagnostic to read. Left alone the next
    pass starts a fresh attempt, reserves again and calls the provider again,
    so one node is billed twice with nobody deciding that it should be. The
    run ceiling bounds it; nothing else does.

    Returns the first such node, for a caller that refuses rather than spends.
    Paying again may well be the right answer -- but it is an operator's to
    give, which is what parking the run with a code asks for.
    """
    row = conn.execute(
        "SELECT t.route_node_id FROM call_outcomes o JOIN run_attempts t"
        " USING (attempt_id) JOIN budget_ledger l"
        " ON (l.run_id, l.attempt_id) = (o.run_id, o.charged_attempt_id)"
        " WHERE t.run_id = %s AND t.route_node_id = ANY(%s)"
        " AND o.diagnostic_sha256 IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.attempt_id = o.attempt_id)"
        " AND NOT EXISTS"
        " (SELECT 1 FROM attempt_refusals r WHERE r.attempt_id = o.attempt_id)"
        " ORDER BY t.ordinal, t.route_node_id LIMIT 1",
        (run_id, list(route_node_ids)),
    ).fetchone()
    return None if row is None else str(row[0])


def replay_billed(  # noqa: PLR0913 -- one run's nodes, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    route_node_ids: Collection[str],
) -> Replayed | None:
    """The first billed answer of these nodes still owed a verdict, re-derived.

    Inside the caller's read unit, so the live path and crash recovery decide
    alike and a recorded answer is never paid for twice: an attempt with a known
    charge, generation and stored body, no artifact and no `attempt_refusals`
    row, in ordinal order. Its attempt and stored pin are checked as the live
    post-call unit checks them, and those refusals -- about the run, not the
    answer -- raise. The answer is then judged by `_answer` under the identity
    its call could have named (`call_time_identity`), which must still be
    `host_identity` now: a soft input accepted after the attempt started makes
    it REFUSED `ROUTE_IDENTITY_INVALID`. A store fault always raises, never a
    verdict. One query when nothing is owed.
    """
    rows = conn.execute(
        "SELECT t.route_node_id, o.attempt_id, o.diagnostic_sha256, l.amount,"
        " o.model, o.generation_id"
        " FROM call_outcomes o JOIN run_attempts t USING (attempt_id)"
        " JOIN budget_ledger l"
        " ON (l.run_id, l.attempt_id) = (o.run_id, o.charged_attempt_id)"
        " WHERE t.run_id = %s AND t.route_node_id = ANY(%s)"
        " AND o.generation_id IS NOT NULL AND o.model IS NOT NULL"
        " AND o.diagnostic_sha256 IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.attempt_id = o.attempt_id)"
        " AND NOT EXISTS"
        " (SELECT 1 FROM attempt_refusals r WHERE r.attempt_id = o.attempt_id)"
        " ORDER BY t.ordinal, t.route_node_id",
        (run_id, list(route_node_ids)),
    ).fetchall()
    nodes = {node.route_node_id: node for node in route.nodes}
    for route_node_id, attempt, diagnostic, charge, model, generation in rows:
        node = nodes.get(str(route_node_id))
        if node is None:
            continue
        attempt_id = UUID(str(attempt))
        body = _stored_body(blobs, str(diagnostic))
        assignment = Assignment(node.module_id, run_id, node, route, attempt_id)
        check_attempt(
            conn,
            attempt_id=attempt_id,
            run_id=run_id,
            route_node_id=node.route_node_id,
        )
        _stored_identity(
            conn, assignment, bundle, adapter=methodology.CANONICAL_ADAPTER_VERSION
        )
        try:
            judged = _replayed_answer(conn, blobs, bundle, assignment, body)
        except Refusal as refusal:
            if refusal.code in _STORE_FAULTS:
                raise
            code = refusal.code
        else:
            if isinstance(judged, BlockedAnswer):
                return Replayed(attempt_id, Verdict.BLOCKED, citations=judged.citations)
            markdown, record = judged
            outcome = HandoffOutcome(
                markdown, record, charge, str(model), str(generation), str(diagnostic)
            )
            return Replayed(attempt_id, Verdict.ANSWERED, outcome=outcome)
        return Replayed(attempt_id, Verdict.REFUSED, code=code)
    return None


def blocked_verdict(  # noqa: PLR0913 -- one run's nodes, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    route_node_ids: Collection[str],
) -> UUID | None:
    """The attempt whose answer, the first `replay_billed` owes a verdict on,
    re-derives to Blocked; None when that answer is anything else, or there is
    none. The attempt rather than a bool, because the transition that acts on
    the verdict records which answer it was (`block_run`, §68)."""
    replayed = replay_billed(
        conn, blobs, bundle, run_id=run_id, route=route, route_node_ids=route_node_ids
    )
    if replayed is None or replayed.verdict is not Verdict.BLOCKED:
        return None
    return replayed.attempt_id


_BLOB_LOST = frozenset({RefusalCode.BLOB_NOT_FOUND, RefusalCode.BLOB_DIGEST_MISMATCH})


def _stored_body(blobs: BlobStore, diagnostic_sha256: str) -> str | None:
    """A billed attempt's stored body. A blob store that will not answer is a
    store fault, never a verdict: reading it as a refusal would pay again. A
    blob that is gone or corrupt (`BLOB_NOT_FOUND`, `BLOB_DIGEST_MISMATCH`)
    is neither: it parks the run with that code (DL-5), where a store fault
    would release it to the head of the queue and block every other run."""
    lost: RefusalCode | None = None
    data: bytes | None = None
    try:
        data = blobs.get(diagnostic_sha256)
    except Refusal as refused:
        lost = refused.code if refused.code in _BLOB_LOST else None
    except OSError:
        pass
    # Raised outside the handler, so no driver or filesystem error rides
    # along as context: the code is the whole of what travels.
    if lost is not None:
        raise Refusal(lost)
    if data is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _replayed_answer(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    assignment: Assignment,
    body: str | None,
) -> tuple[bytes, bytes] | BlockedAnswer:
    """`_answer` over a stored body, with the context its call was built from."""
    if body is None:
        raise Refusal(RefusalCode.PROVIDER_RESPONSE_INVALID)
    # An unaccepted attempt has no record, so its call named its blocking
    # inputs and the soft ones accepted before it started; `_answer` refuses
    # the attempt when that is no longer every input accepted now.
    identity = call_time_identity(
        conn,
        assignment.route,
        _identity(conn, bundle, assignment),
        attempt_id=assignment.attempt_id,
        record=None,
    )
    return _answer(
        conn,
        bundle,
        blobs,
        assignment,
        identity=identity,
        context=_context(conn, blobs, bundle, assignment, identity),
        carried=delivered_authority(bundle, assignment.module_id),
        content=body,
    )


def accepted_projections(  # noqa: PLR0913 -- the unit's handles, its row, its pairs
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    row: AcceptedRow,
    *,
    accepted: Mapping[str, tuple[str, str | None]] | None = None,
) -> Projections:
    """An accepted canonical artifact's projections, re-derived and compared.

    Inside the caller's read unit: the host identity is rebuilt from the stored
    facts, the record must bind this Markdown and that identity, and the
    projections re-parsed from the Markdown must equal the record's (§42.4).
    Citations are not re-anchored here; the proof and freezing do that.
    `accepted` is the unit's accepted pairs when the caller holds them.

    The identity is `call_time_identity`, the one rule the proof and the
    deliverable use too, so a soft input accepted after its target never makes
    the runtime refuse a record the other readers accept.
    """
    return _verified_accepted(
        conn,
        blobs,
        bundle,
        route,
        row,
        accepted=accepted,
    ).projections


def accepted_handoff(  # noqa: PLR0913 -- the unit's handles, its row, its pairs
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    row: AcceptedRow,
    *,
    accepted: Mapping[str, tuple[str, str | None]] | None = None,
) -> tuple[bytes, CanonicalRecord]:
    """An accepted canonical artifact's exact Markdown and its verified record.

    The checks `accepted_projections` makes, inside the caller's read unit:
    the record binds this Markdown, the identity rebuilt from the store, this
    build and the accepted lineage, and the projections re-derived from the
    Markdown equal the record's (§42.4). Citations are not re-anchored; the
    rectangles are the ones recorded at acceptance.
    """
    verified = _verified_accepted(
        conn,
        blobs,
        bundle,
        route,
        row,
        accepted=accepted,
    )
    return verified.markdown, verified.record


def _refuse(step: Step) -> RefusalCode | None:
    """The runtime's codes: `ROUTE_IDENTITY_INVALID` for a row naming no
    pinned node, `ARTIFACT_RECORD_MISMATCH` for bytes that will not read,
    `ORCHESTRATION_BUILD_MOVED` as the proof maps it; every other step's own."""
    return {
        Step.NODE_NOT_IN_ROUTE: RefusalCode.ROUTE_IDENTITY_INVALID,
        Step.UNREADABLE: RefusalCode.ARTIFACT_RECORD_MISMATCH,
        Step.AUTHORITY_MOVED: RefusalCode.ORCHESTRATION_BUILD_MOVED,
    }.get(step)


def _verified_accepted(  # noqa: PLR0913 -- the unit's handles, its row, its pairs
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    row: AcceptedRow,
    *,
    accepted: Mapping[str, tuple[str, str | None]] | None,
) -> Verified:
    """`accepted_projections` with the verified record and bytes it read.

    `ARTIFACT_RECORD_MISMATCH` when the record does not bind (`read_record`)
    or its lineage is not the accepted chain the store holds now (§45.4);
    `ORCHESTRATION_BUILD_MOVED` when it was written under another adapter,
    build, manifest or authority, as the proof maps it; `validate_markdown`'s
    own code for a stored handoff that no longer validates;
    `AUTHORITY_BYTES_MISMATCH` for any file of the module's authority moved on
    disk. Citations are not re-anchored (§42.4). The frontier keeps the
    per-manifest authority digest cache. Caller owns the read.
    """
    verified = verify_accepted(
        conn,
        blobs,
        bundle,
        route,
        row,
        vendor=VendorAuthority(_contract(bundle), catalog(bundle)),
        accepted=accepted,
        verify_authority=False,
        reanchor=None,
        refuse=_refuse,
    )
    node = next(n for n in route.nodes if n.route_node_id == row.route_node_id)
    # Every file of the module's authority, verified on disk now: the shared
    # steps read SKILL.md and compare cached digests, so this is what refuses
    # a sibling reference file tampered under an unchanged manifest on the
    # read that serves the frontier, the Run and Analysis documents and the
    # matrix (§45.1). It is what the parent read paid; the cache costs nothing.
    assemble_authority(bundle, node.module_id)
    identity = verified.record.identity
    if node.module_id == MODEL_MODULE or (
        node.module_id == "CP-5"
        and (identity.profile_id, identity.selection_id) == CREDIT_SCREEN_SELECTION
    ):
        assignment = Assignment(node.module_id, row.run_id, node, route, row.attempt_id)
        _forecast_inputs(
            bundle,
            node.module_id,
            verified.markdown,
            _context(conn, blobs, bundle, assignment, verified.record.identity),
        )
    return verified


def _forecast_inputs(
    bundle: Bundle, module: str, markdown: bytes, context: _Context
) -> None:
    """Owner restrictions bind acceptance, replay and every accepted read."""
    if module not in {MODEL_MODULE, "CP-5"}:
        return
    upstream = {ref.module_id: data for ref, data in context.upstream}
    if module == MODEL_MODULE:
        from caos.methodology.forecast import (
            validate_driver_mapping,
            validate_forecast_bindings,
        )

        citations = {
            ref.module_id: context.citations[ref.route_node_id]
            for ref, _data in context.upstream
        }
        validate_forecast_bindings(markdown, upstream, citations)
        validate_driver_mapping(_contract(bundle), markdown, upstream["CP-2G"])
    verify_owner_restrictions(
        _contract(bundle),
        markdown,
        upstream.values(),
        refuse=RefusalCode.HANDOFF_INCOMPLETE,
        selection=(CREDIT_SCREEN_SELECTION if module == "CP-5" else None),
    )


def _upstream_records(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    assignment: Assignment,
    refs: tuple[UpstreamRef, ...],
) -> tuple[dict[str, CanonicalRecord], tuple[LineageRef, ...]]:
    """Every upstream the prompt will carry is an accepted record of this build
    whose projections re-derive from its Markdown and whose own lineage is the
    accepted chain; returns those records by route node and the whole lineage
    behind them, read from those records.

    Inside the pre-call read unit, so nothing another build wrote, and no record
    that disagrees with its own Markdown, reaches the prompt (invariant 4; the
    same checks the frontier and the proof apply). A row whose digest is not the
    ref's is `ROUTE_IDENTITY_INVALID`; a row without a record, or whose Markdown
    will not read, `ARTIFACT_RECORD_MISMATCH`.
    One `accepted_rows` query for the whole unit, none when there is no
    upstream; each upstream record is read once, by its own verification, and
    that verified record is what the lineage is read from.
    """
    if not refs:
        return {}, ()
    rows = {row[0]: row for row in accepted_rows(conn, assignment.run_id)}
    accepted = {row[0]: (row[2], row[3]) for row in rows.values()}
    nodes = {n.route_node_id: n for n in assignment.route.nodes}
    verified: dict[str, CanonicalRecord] = {}
    by_node: dict[str, CanonicalRecord] = {}
    for ref in refs:
        row = rows.get(ref.route_node_id)
        if row is None or row[2] != ref.sha256 or ref.route_node_id not in nodes:
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        _, attempt, digest, record_sha256 = row
        if record_sha256 is None:
            raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
        record = _verified_accepted(
            conn,
            blobs,
            bundle,
            assignment.route,
            AcceptedRow(
                run_id=assignment.run_id,
                route_node_id=ref.route_node_id,
                attempt_id=attempt,
                artifact_sha256=digest,
                record_sha256=record_sha256,
            ),
            accepted=accepted,
        ).record
        verified[record_sha256] = by_node[ref.route_node_id] = record
    return by_node, stored_lineage(blobs, refs, accepted, verified=verified)


def _identity(
    conn: StoreConnection, bundle: Bundle, assignment: Assignment
) -> HostIdentity:
    return host_identity(
        conn,
        bundle,
        run_id=assignment.run_id,
        route=assignment.route,
        node=assignment.node,
        attempt_id=assignment.attempt_id,
    )
