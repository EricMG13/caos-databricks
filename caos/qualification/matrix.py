"""The qualification set, its answer keys, and the matrix a reviewer reads.

`docs/REBUILD_PLAN.md` Phase 10. A **qualification set** is the immutable cases
and answer keys one verdict is measured against (`CONTEXT.md`); its digest is
one of the six bindings `read_verdict` requires, and this module is where that
digest is computed.

**The matrix reports; it does not conclude.** Comparing a run against an answer
key is mechanical, and the host may do it. Deciding that the comparison is good
enough is a reviewer's signature — `QUALIFIED` is their word, not the host's
(`caos/qualification/__init__.py`). So nothing here carries a verdict, a pass
flag or a score: a row states what the host could prove on its own and which
expected citations the run produced, and a reviewer reads the rows.

That is also why a row survives its own failure. An unprovable case is a row
carrying its refusal code, not an exception that ends the matrix: stopping at
the first one would hand a reviewer less than the host knows, and what the
remaining cases did is the next thing they would ask.

**What an answer key can express, and what it cannot.** A key names citations —
which quote, from which document, under which module. That is the strongest key
the canonical handoff's record can be checked against today, because a record
carries projections and citations and not typed figures. A key saying "net
leverage is 4.2x" has nothing to compare against until the record carries the
figure as a number, which is the known-gaps entry this module ships with.

Beside the citations a key may also ask what a module *concluded*
(`ExpectedProjection`, over the seven fields the host projects) and what it
*wrote in a named register cell* (`ExpectedRegister`, read through the vendor's
own register reader). None of the three is the conclusion's soundness, and a
reviewer still reads the rows.

**A canonical run is scored on its records** (`docs/DECISIONS.md` §42.4), and
only on what the proof proved: the proof returns the citations it re-anchored
under the pinned modules, and those are the run's -- nothing is read again, so
an artifact accepted after the proof is not scored, and a source withdrawn since
refuses the row. An unproven canonical run cites nothing. The matrix reports no
status a record projects, so a SCREENING_ONLY record can never reach a reviewer
through it as committee clearance.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document
from caos.graph.route import MODEL_MODULE, READY, ResolvedRoute, readiness_from
from caos.graph.runtime import accepted_artifacts
from caos.methodology.bundle import Bundle, verified_bytes
from caos.methodology.canonical import accepted_handoff, accepted_projections
from caos.methodology.forecast import forecast_projection
from caos.methodology.handoff import UNCLEARED_READINESS, Projections
from caos.methodology.vendor import VendorContract, load_vendor_contract
from caos.methodology.verification import AcceptedRow
from caos.qualification.proof import OrchestrationProof, assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.routes import resolved_route
from caos.store.run_inputs import RunSubject
from caos.store.runs import run_status
from caos.store.source_sets import pinned_live_sources

# A run that declared its refusal must have *ended on one*. RUNNING is a run
# with more to do and CANCELLED did not answer the question asked, so neither is
# an answer -- and COMPLETE is the run answering it the other way. COMPLETE was
# in this set until the adversarial pass (FP-01) showed what that bought: a
# retried node succeeds, the run finishes, and the first attempt's stale
# `attempt_refusals` row still matched, so a concluded run could be signed as
# the refusal its case declared.
_REFUSED = frozenset({RunStatus.BLOCKED, RunStatus.FAILED})

# A case label is authored and reaches a digest; it is a name, not prose.
_LABEL_LIMIT = 128

# The refusals a case may declare as its expected result. A qualification key
# says what the *methodology* does with the evidence it was given -- a gate that
# refuses a consumer, a handoff that cannot be validated, a quote that cannot be
# anchored. `STORE_UNAVAILABLE`, `PROVIDER_UNAVAILABLE` and the orchestration
# proof's own codes are the host or its infrastructure failing, and a set that
# declared one would be qualifying an outage rather than a reading (FP-01).
DECLARABLE_REFUSALS = frozenset(
    {
        RefusalCode.HANDOFF_BLOCKED,
        RefusalCode.HANDOFF_MALFORMED,
        RefusalCode.HANDOFF_INCOMPLETE,
        RefusalCode.HANDOFF_IDENTITY_MISMATCH,
        RefusalCode.HANDOFF_UNDECLARED_FIELD,
        RefusalCode.ENVELOPE_INVALID,
        RefusalCode.ENVELOPE_UNDECLARED_FIELD,
        RefusalCode.ENVELOPE_UNCITED_CLAIM,
        RefusalCode.READINESS_INVALID,
        RefusalCode.READINESS_INCOMPLETE,
        RefusalCode.CITATION_NOT_LOCATED,
        RefusalCode.CITATION_AMBIGUOUS,
        RefusalCode.CITATION_NOT_DELIVERED,
        RefusalCode.METHODOLOGY_INPUT_INVALID,
        RefusalCode.FORECAST_CHAIN_BROKEN,
        RefusalCode.FORECAST_RESIDUAL_UNRECONCILED,
        RefusalCode.FORECAST_DRIVER_NOT_READY,
    }
)

# The projection fields that carry one value. Two keys naming one of these on
# one module with different values cannot both be met, whatever a run answers
# (AR-23); the remaining fields are lists, where two memberships are ordinary.
SCALAR_PROJECTION_FIELDS = frozenset(
    {"qa_status", "committee_status", "confidence_band", "decision_scope"}
)


@dataclass(frozen=True, slots=True)
class ExpectedCitation:
    """One thing a correct run of this case must have cited.

    The document is named by digest rather than by filename, because a
    qualification set outlives any one case's admission of it and a filename is
    not an identity.
    """

    module_id: str
    document_sha256: str
    matched_text: str


@dataclass(frozen=True, slots=True)
class ForecastValue:
    """One host-recomputed CP-CF value an independent key expects."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class ExpectedForecast:
    """A closed, mechanical credit-conclusion key for an accepted CP-CF run.

    The result is read through ``accepted_handoff`` and recomputed by the host;
    it is never extracted from model-authored narrative text.
    """

    scenario: str
    period_id: str
    values: tuple[ForecastValue, ...]
    currency: str
    scale: str
    perimeter: str
    qa_status: str
    limitation_flags: tuple[str, ...]
    readiness: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ExpectedProjection:
    """One host-projected field of one module's accepted handoff.

    A citation key asks whether a module's handful of length-selected quotes
    happened to include a particular line. This asks what the module concluded:
    the fields the host re-derives from the accepted Markdown and compares
    against the stored record (`accepted_projections`), so the answer is the
    host's reading and not model narrative.

    `value` is compared as a string against a scalar field, and as membership
    against a list one — one rule for both, because "the screen was Restricted"
    and "it flagged the missing audited statements" are the same kind of
    question asked of differently shaped fields. `blockers` is a list of
    `(module, text)` pairs, and membership there is over the texts: a key asks
    which condition the gate stated, and `module_id` already says whose handoff
    is being read (the gate's), so it cannot also say which module the condition
    was about.
    """

    module_id: str
    field: str
    value: str


PROJECTION_FIELDS = frozenset(
    {
        "qa_status",
        "committee_status",
        "confidence_band",
        "decision_scope",
        "limitation_flags",
        "validation_warnings",
        "downstream_consumers",
        # The gate's `(module, why_now_or_blocker)` rows for every module it did
        # not clear (§61): what the run would need before a successor could run.
        "blockers",
    }
)


@dataclass(frozen=True, slots=True)
class ExpectedRegister:
    """One cell of one named register of one module's accepted handoff.

    The third question an answer key can ask, and the first that reaches the
    analysis itself. A citation key asks which quotes a module drew; a
    projection key asks what its seven host-projected scalars said; this asks
    what it *wrote in a named register cell* -- a liquidity bridge's figure, a
    covenant term, a topic's materiality. Those live in the appendix registers
    the vendor's own contract declares, and the vendor ships the reader
    (`completeness_check.find_registers`), so the host locates the table by the
    bundle's rules rather than by a parser of its own (invariant 4).

    `row_key` names the row by its own cells -- `(("topic_id",
    "LIQUIDITY_MATURITIES"),)` -- rather than by position, because row order is
    the module's and a key that counted rows would measure the layout. Exactly
    one row may match: zero and two are both misses, never a guess.

    Authored from the documents, never from a run. A key taken from what a run
    wrote measures the model against itself.
    """

    module_id: str
    register_id: str
    row_key: tuple[tuple[str, str], ...]
    column: str
    expected: str


@dataclass(frozen=True, slots=True)
class QualificationCase:
    """One case of the set: its inputs, its route, and its answer key.

    Both halves in one object, because `CONTEXT.md` defines a qualification set
    as "the immutable cases and answer keys" and they are useless apart. The
    first draft of this module carried the keys alone, which is why
    `build_matrix` had to be handed a `runs` mapping it could not produce: there
    was nothing here to run.

    `expects` is this case's answer key — the citations a correct run must
    produce.
    """

    label: str
    documents: tuple[Document, ...]
    profile_id: str
    selection_id: str
    expects: tuple[ExpectedCitation, ...]
    # Who and when the run is about. A canonical-adapter route requires one
    # (`pin_run_input`); a claims route leaves it None, as every case did before.
    subject: RunSubject | None = None
    # Optional while historical citation-only sets remain reviewable.  New
    # credit-conclusion sets use this deterministic CP-CF answer key.
    forecast: ExpectedForecast | None = None
    expected_refusal: RefusalCode | None = None
    # Module ids CP-0 must find ready. A readiness key, not a citation one: the
    # host already projects `(module_id, readiness_status)` off CP-0's record
    # (`caos/graph/route.py`), so this is read from what the engine gated on
    # rather than from prose. It exists because a gate that wrongly refuses a
    # module is invisible to a citation key -- the module never runs, so it
    # cites nothing, and every key aimed at it reads as a miss by the model.
    expects_ready: tuple[str, ...] = ()
    # Module ids CP-0 must refuse (§99): the readiness key read the other way
    # round, for a corpus on which the honest answer is that a consumer cannot
    # run. Met when CP-0's verdict for every named module is one of the gate's
    # own uncleared words, never by a module the gate did not rule on.
    expects_blocked: tuple[str, ...] = ()
    # What the modules concluded, read from the host's own projections. See
    # `ExpectedProjection`: this is the key that measures the analysis rather
    # than the draw of quotes that happened to support it.
    expects_projection: tuple[ExpectedProjection, ...] = ()
    # CP-CF is a host extension, so a forecast key must bind whether it was
    # present rather than silently qualifying the base route.
    model_extension: bool = False
    # What the modules wrote in their registers. See `ExpectedRegister`: the key
    # that can ask about a cell the host projects no scalar for.
    expects_register: tuple[ExpectedRegister, ...] = ()
    # A CP-DR route's research brief (§96), as the canonical JSON the pin stores
    # (`run_inputs.research_text`). An input like the documents: pinned by the
    # harness, compared at eligibility, and covered by the digest.
    research_brief: str | None = None


@dataclass(frozen=True, slots=True)
class QualificationSet:
    """The immutable cases and answer keys one verdict is measured against."""

    cases: tuple[QualificationCase, ...]


@dataclass(frozen=True, slots=True)
class MatrixRow:
    """One case: what the host proved, and what the run did or did not cite.

    `proven` and `refusal` are the host's own claim about the run (invariant
    terms). `met` and `missed` are the mechanical comparison. Neither is a
    verdict, and there is deliberately no field that combines them into one.
    """

    case_label: str
    proven: bool
    refusal: RefusalCode | None
    met: tuple[ExpectedCitation, ...]
    missed: tuple[ExpectedCitation, ...]
    forecast_met: bool | None
    expected_refusal_met: bool | None
    ready_met: bool | None = None
    blocked_met: bool | None = None
    projections_met: bool | None = None
    registers_met: bool | None = None


@dataclass(frozen=True, slots=True)
class Matrix:
    """Every case of the set, and what the set and build were when it was built."""

    qualification_set_sha256: str
    build_id: str
    rows: tuple[MatrixRow, ...]


def qualification_set_digest(qualification: QualificationSet) -> str:
    """The digest a verdict binds. Moves when any case or key moves.

    `read_verdict` takes `qualification_set_sha256` on trust — it checks the
    shape, not the contents. What stops a signature outliving the answer keys it
    was given is this: edit any key and the digest no longer names the set in
    front of the reader.

    Order-independent, because two people assembling the same body of cases must
    bind the same digest; a digest that moved with authorship would make the
    set's identity an accident. Labels cross the boundary here, which is where
    they become pinned state.
    """
    assert_measurable(qualification)
    # Sorted on each entry's own canonical JSON rather than on the list itself.
    # An entry is a list of mixed shapes -- a subject is a list where an
    # expected refusal is a string -- so two cases declaring different optional
    # fields made Python compare a `list` with a `str` and raise a bare
    # `TypeError` out of the digest (FP-08). Every committed set holds one case,
    # where the two orders cannot differ.
    canonical = sorted(
        (_digested(case) for case in qualification.cases), key=_canonical_json
    )
    return sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _canonical_json(entry: list[object]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), allow_nan=False)


def case_label(case: QualificationCase) -> str:
    """One case's label as the digest binds it.

    Public because `assert_unambiguous` has to compare the labels the digest
    will compare: it read the authored strings, so `"A"` and `"A "` were two
    distinct cases there and one entry in the digest (FP-08).
    """
    return BoundaryText.of(case.label.strip(), limit=_LABEL_LIMIT).value


def _digested(case: QualificationCase) -> list[object]:
    """One case's digested form. A subject is appended only when declared, so a
    set of subject-free cases binds exactly the digest it bound before cases
    could carry one."""
    entry: list[Any] = [
        case_label(case),
        [case.profile_id, case.selection_id],
        # The inputs, not only the answers. Two sets with identical keys
        # over different documents are different sets, and a verdict binding
        # one must not read as binding the other.
        sorted(
            [document.filename.value, sha256(document.data).hexdigest()]
            for document in case.documents
        ),
        sorted(
            [expect.module_id, expect.document_sha256, expect.matched_text]
            for expect in case.expects
        ),
    ]
    if case.subject is not None:
        subject = case.subject
        entry.append(
            [
                subject.issuer_id,
                subject.issuer_name,
                subject.reporting_period,
                subject.analysis_date,
            ]
        )
    if case.model_extension:
        entry.append("model_extension")
    if case.forecast is not None:
        entry.append(
            [
                case.forecast.scenario,
                case.forecast.period_id,
                sorted([value.name, value.value] for value in case.forecast.values),
                case.forecast.currency,
                case.forecast.scale,
                case.forecast.perimeter,
                case.forecast.qa_status,
                sorted(case.forecast.limitation_flags),
                sorted(case.forecast.readiness),
            ]
        )
    if case.expected_refusal is not None:
        entry.append(case.expected_refusal.value)
    if case.expects_ready:
        entry.append(sorted(case.expects_ready))
    if case.expects_blocked:
        # Tagged, because the same ids appended bare would digest exactly as an
        # `expects_ready` key does -- two opposite sets, one digest.
        entry.append(["expects_blocked", sorted(case.expects_blocked)])
    if case.expects_projection:
        entry.append(
            sorted(
                [expect.module_id, expect.field, expect.value]
                for expect in case.expects_projection
            )
        )
    if case.research_brief is not None:
        entry.append(["research_brief", case.research_brief])
    if case.expects_register:
        entry.append(
            sorted(
                [
                    expect.module_id,
                    expect.register_id,
                    # The row key is a set of cell conditions, not a sequence:
                    # two authors naming the same row in either order name the
                    # same row, and the digest has to agree with them.
                    sorted([column, value] for column, value in expect.row_key),
                    expect.column,
                    expect.expected,
                ]
                for expect in case.expects_register
            )
        )
    return entry


def build_matrix(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    qualification: QualificationSet,
    runs: Mapping[str, UUID],
) -> Matrix:
    """Every case of the set against the run that covered it.

    Refuses before it reports rather than reporting a matrix nobody can rely on:
    an empty set measures nothing, two keys for one case make "the answer"
    depend on read order, and a case with no run is the vacuous pass in its
    purest form — the row that would have failed is simply not there.
    """
    assert_measurable(qualification)
    assert_unambiguous(qualification)
    labels = [case.label for case in qualification.cases]
    for label in labels:
        if label not in runs:
            raise Refusal(RefusalCode.QUALIFICATION_RUN_MISSING)

    return Matrix(
        qualification_set_sha256=qualification_set_digest(qualification),
        rows=tuple(
            _row(conn, blobs, bundle, case=case, run_id=runs[case.label])
            for case in qualification.cases
        ),
        # Validate the same manifest again after all proofs and citation reads.
        build_id=bundle.build_id,
    )


def _guarded[T](read: Callable[[], T]) -> tuple[T | None, RefusalCode | None]:
    """One reader's answer, or the row's own uncertainty in place of it.

    A row survives its own failure, and `_ROW_REFUSALS` names the three ways a
    reader can fail that are the *row's* uncertainty rather than a reason to end
    the matrix. Only `_cited` and the register reader were guarded, so a pin
    that stopped reading, or vendored bytes that moved, part-way through a set
    raised out of `build_matrix` and `_persist_performed` never ran -- every run
    already paid for, with no snapshot (FP-07). Every reader is guarded here, in
    one place, so the list cannot fall out of step again.

    `None` for a comparison that was not made: scoring it `False` would say the
    module answered wrongly, and a reviewer went hunting the model for a
    vendored-bytes fault.
    """
    try:
        return read(), None
    except Refusal as unreadable:
        if unreadable.code not in _ROW_REFUSALS:
            raise
        return None, unreadable.code


def _row(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
) -> MatrixRow:
    """One case. The proof may fail; the comparison is made either way.

    What a run cited is knowable whether or not the host can vouch for how it
    was produced, and a reviewer looking at an unprovable case still wants to
    see whether it found the right evidence.
    """
    refusal: RefusalCode | None = None
    proof: OrchestrationProof | None = None
    try:
        proof = assert_orchestration_proof(conn, blobs, bundle, run_id=run_id)
    except Refusal as failed:
        refusal = failed.code
    # The proof's own answer, kept apart from the reader refusals below. `refusal`
    # is the row's uncertainty and a later reader may replace it; a declared
    # refusal is a claim about how the *run* ended, and answering it from a
    # register reader's `AUTHORITY_BYTES_MISMATCH` would meet a key with a
    # vendored-bytes fault (FP-01).
    proof_refusal = refusal

    cited, cited_refusal = _guarded(lambda: _cited(conn, run_id, proof=proof))
    registers_met, registers_refusal = _guarded(
        lambda: _registers_met(conn, blobs, bundle, case=case, run_id=run_id)
    )
    forecast_met, forecast_refusal = _guarded(
        lambda: _forecast_met(
            conn, blobs, bundle, case=case, run_id=run_id, proof=proof
        )
    )
    ready_met, ready_refusal = _guarded(
        lambda: _ready_met(conn, blobs, bundle, case=case, run_id=run_id)
    )
    blocked_met, blocked_refusal = _guarded(
        lambda: _blocked_met(conn, blobs, bundle, case=case, run_id=run_id)
    )
    projections_met, projections_refusal = _guarded(
        lambda: _projections_met(conn, blobs, bundle, case=case, run_id=run_id)
    )
    for code in (
        cited_refusal,
        registers_refusal,
        forecast_refusal,
        ready_refusal,
        blocked_refusal,
        projections_refusal,
    ):
        if code is not None:
            refusal = code
    found = cited or set()
    met = tuple(expect for expect in case.expects if _matches(expect, found))
    return MatrixRow(
        case_label=case.label,
        proven=refusal is None,
        refusal=refusal,
        met=met,
        missed=tuple(expect for expect in case.expects if expect not in met),
        forecast_met=forecast_met,
        expected_refusal_met=(
            None
            if case.expected_refusal is None
            else _refusal_met(conn, run_id, case.expected_refusal, proof_refusal)
        ),
        ready_met=ready_met,
        blocked_met=blocked_met,
        projections_met=projections_met,
        registers_met=registers_met,
    )


def _refusal_met(
    conn: StoreConnection,
    run_id: UUID,
    expected: RefusalCode,
    proof_refusal: RefusalCode | None,
) -> bool:
    """Whether the run refused the way its case said it would.

    A case that declares a refusal is declaring how the run ends, and a run
    ends in one of two places: the proof cannot be taken, or execution stopped
    and wrote the reason against an attempt. Reading only the first made this
    key unanswerable by any run the system produces — a deliberately restricted
    case (`docs/REPAIR_PLAN.md` Phase 6) stops with a refusal recorded and a
    sound proof over what it did accept, so the proof says nothing and the
    stored refusal says everything.

    Three rules, all of them from the adversarial pass (FP-01), because
    `PerformedEvidence.complete` waives its COMPLETE requirement for whatever
    this answers -- so this one predicate decides whether an unfinished or
    successful run can be signed as the refusal its case declared.

    - **The run must have ended refused**, before any branch. BLOCKED or FAILED
      and nothing else: COMPLETE is the run answering the other way, RUNNING has
      more to do, CANCELLED was never asked to finish.
    - **A declared `HANDOFF_BLOCKED` needs the verdict that blocked it.** The run
      status alone met it for a run CP-0 blocked on readiness before any handoff
      returned Blocked, which is a different outcome with the same status;
      `run_blocking_verdicts` is the row the transition writes when a validated
      Blocked answer is what ended the run (§68).
    - **A stored code must sit where the run stopped**: on the last attempt of a
      node that never produced an artifact. Any `attempt_refusals` row of any
      attempt matched before, so a node that refused once and succeeded on the
      retry `qualify.py` buys still answered the key.
    """
    if run_status(conn, run_id) not in _REFUSED:
        return False
    if expected is RefusalCode.HANDOFF_BLOCKED:
        # A validated Blocked handoff is the route's own rule applied, so
        # `_settle` writes no `attempt_refusals` row for it -- the recorded
        # verdict is where that outcome is.
        return bool(
            conn.execute(
                "SELECT 1 FROM run_blocking_verdicts WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        )
    if proof_refusal is expected:
        return True
    return bool(
        conn.execute(
            "SELECT 1 FROM attempt_refusals r JOIN run_attempts t"
            " USING (attempt_id) WHERE t.run_id = %s AND r.code = %s"
            " AND NOT EXISTS (SELECT 1 FROM artifacts a JOIN run_attempts n"
            "  ON n.attempt_id = a.attempt_id"
            "  WHERE n.run_id = t.run_id AND n.route_node_id = t.route_node_id)"
            " AND t.attempt_id = (SELECT l.attempt_id FROM run_attempts l"
            "  WHERE l.run_id = t.run_id AND l.route_node_id = t.route_node_id"
            "  ORDER BY l.started_at DESC, l.attempt_id DESC LIMIT 1)",
            (run_id, expected.value),
        ).fetchone()
    )


def _gate_readiness(
    conn: StoreConnection, blobs: BlobStore, bundle: Bundle, run_id: UUID
) -> dict[str, str] | None:
    """CP-0's readiness per module as the engine gated on it, or None when the
    run's route or accepted artifacts cannot be read."""
    route = resolved_route(conn, run_id)
    if route is None:
        return None
    try:
        accepted = accepted_artifacts(conn, blobs, route, run_id, bundle=bundle)
    except Refusal:
        return None
    return dict(readiness_from(route, accepted))


def _blocked_met(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
) -> bool | None:
    """Whether CP-0 refused every module the case names (§99).

    The same projection `_ready_met` reads, over `UNCLEARED_READINESS` -- the
    gate's own two words for "does not run". A module the gate did not rule on
    is not refused: reading "not READY" as "BLOCKED" would meet this key with a
    gate that never ran. `None` when the case names none.
    """
    if not case.expects_blocked:
        return None
    readiness = _gate_readiness(conn, blobs, bundle, run_id)
    if readiness is None:
        return False
    return all(
        readiness.get(module) in UNCLEARED_READINESS for module in case.expects_blocked
    )


def _ready_met(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
) -> bool | None:
    """Whether CP-0 found every module the case names ready to run.

    Read from `readiness_from` — the same projection `node_states` gates on, so
    this asks exactly the question the engine asked and not a re-reading of the
    handoff's prose. `None` when the case names none.

    A gate that refuses a module for the wrong reason is otherwise invisible:
    the module never runs, so it cites nothing, and every citation key aimed at
    it reads as the model failing to find evidence when the truth is that the
    model was never asked.
    """
    if not case.expects_ready:
        return None
    readiness = _gate_readiness(conn, blobs, bundle, run_id)
    if readiness is None:
        return False
    return all(readiness.get(module) in READY for module in case.expects_ready)


def _accepted_rows(
    conn: StoreConnection, run_id: UUID
) -> dict[str, tuple[str, str | None]]:
    """Every accepted node of the run, keyed by route node."""
    return {
        str(row[0]): (str(row[1]), None if row[2] is None else str(row[2]))
        for row in conn.execute(
            "SELECT t.route_node_id, a.artifact_sha256, a.record_sha256"
            " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
            " WHERE a.run_id = %s",
            (run_id,),
        ).fetchall()
    }


def _matches_projection(projections: Projections, expect: ExpectedProjection) -> bool:
    """One expectation against the host's re-derived projections."""
    if expect.field not in PROJECTION_FIELDS:
        return False
    found = getattr(projections, expect.field)
    if isinstance(found, tuple):
        # A pair-shaped field (`blockers`) is matched on the text it carries,
        # never on `str(pair)`: a key must not have to spell a tuple's repr.
        return expect.value in tuple(
            pair[-1] if isinstance(pair, tuple) else pair for pair in found
        )
    return str(found) == expect.value


def _projections_met(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
) -> bool | None:
    """Whether every module concluded what the case says it should have.

    Read through `accepted_projections`, which rebuilds the identity from the
    store, requires the record to bind this Markdown, and re-parses the
    projections from the Markdown to compare against the record (§42.4). A
    module the case names that produced no accepted artifact is a miss, not a
    skip: the question was asked and the run did not answer it.
    """
    if not case.expects_projection:
        return None
    route = resolved_route(conn, run_id)
    if route is None:
        return False
    accepted = _accepted_rows(conn, run_id)
    wanted: dict[str, list[ExpectedProjection]] = {}
    for expect in case.expects_projection:
        wanted.setdefault(expect.module_id, []).append(expect)
    for module_id, expects in wanted.items():
        node = next((item for item in route.nodes if item.module_id == module_id), None)
        if node is None:
            return False
        rows = conn.execute(
            "SELECT a.artifact_sha256, a.record_sha256, a.attempt_id"
            " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
            " WHERE a.run_id = %s AND t.route_node_id = %s",
            (run_id, node.route_node_id),
        ).fetchall()
        if len(rows) != 1 or rows[0][1] is None:
            return False
        artifact_sha256, record_sha256, attempt_id = rows[0]
        try:
            projections = accepted_projections(
                conn,
                blobs,
                bundle,
                route,
                AcceptedRow(
                    run_id=run_id,
                    route_node_id=node.route_node_id,
                    attempt_id=UUID(str(attempt_id)),
                    artifact_sha256=str(artifact_sha256),
                    record_sha256=str(record_sha256),
                ),
                accepted=accepted,
            )
        except Refusal:
            return False
        if not all(_matches_projection(projections, expect) for expect in expects):
            return False
    return True


def _normalised_cell(value: str) -> str:
    """One register cell, column name or expected value, as a key compares them.

    NFC first, because two spellings of the same character are the same cell to
    a reader and a key authored in one must not miss a handoff written in the
    other. Then every run of whitespace collapses to one space and the ends are
    stripped: a Markdown table's cells are padded for alignment and a line may
    be wrapped, neither of which is the module saying anything different.

    **Case is preserved.** `MATERIAL` and `Material` are different values in
    every vendor vocabulary that has one, and a comparison that folded case
    would let a key pass over a cell the bundle's own validators would refuse.
    """
    return " ".join(unicodedata.normalize("NFC", value).split())


def _cell(
    row: Mapping[str, str], column: str, header: Sequence[str] | None = None
) -> str | None:
    """One row's cell under `column`, normalised, or `None` if it is not there.

    The column name is matched under the same rule as the cell, because a header
    is padded and wrapped like any other cell. A register whose header names the
    same column twice answers `None`: the host does not choose between them.

    That last rule needs the header, not the row. The vendor's reader builds a
    row as `dict(zip(header, cells))`, so two identical header names collapse to
    the last cell before the host sees anything -- the row then holds one entry
    and this function used to answer from it, while a person reading the table
    reads the leftmost namesake. The header is where the duplicate is still
    visible. Passing it is optional only so a caller testing one row need not
    build one; every caller that has a register passes it. Found by the
    Completion Phase 8 confidence review, which built the table and watched a
    shipped key answer from the trailing column.
    """
    wanted = _normalised_cell(column)
    if header is not None:
        named = [name for name in header if _normalised_cell(str(name)) == wanted]
        if len(named) != 1:
            return None
    found = [
        value for name, value in row.items() if _normalised_cell(str(name)) == wanted
    ]
    if len(found) != 1:
        return None
    return _normalised_cell(str(found[0]))


def _matches_register(
    registers: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, str]]]],
    expect: ExpectedRegister,
) -> bool:
    """One register expectation against what the vendor's reader found.

    Exactly one row may meet the whole `row_key`. Zero is the register not
    carrying the row the key asks about; two is the key not naming one row, and
    picking the first would make the answer depend on the order the module wrote
    its table in. Both are misses. An empty `row_key` selects nothing here --
    the loader refuses one, and a Python caller's is not silently read as "any
    row".
    """
    found = registers.get(expect.register_id)
    if not expect.row_key or not isinstance(found, tuple) or len(found) != 2:
        # Anything but the reader's `(header, rows)` is not this key's answer:
        # the host reads the vendor's shape and invents no second one.
        return False
    header, rows = found
    matched = [
        row
        for row in rows
        if isinstance(row, Mapping)
        if all(
            _cell(row, column, header) == _normalised_cell(value)
            for column, value in expect.row_key
        )
    ]
    if len(matched) != 1:
        return False
    return _cell(matched[0], expect.column, header) == _normalised_cell(expect.expected)


def module_registers(
    contract: VendorContract, bundle: Bundle, module_id: str, text: str
) -> dict[str, Any]:
    """One module's registers, located exactly as the vendor's `check()` does.

    The locator is `completeness_check.find_registers`, asked with the module's
    whole contract register list from its verified `SKILL.md` -- the call
    `check()` makes, and the check this handoff already passed at acceptance
    (`handoff.validate_markdown`). So the scorer reads the table the bundle
    verified, never a second reading of one.

    Neither narrower nor wider. Narrowed to a key's own ids, the locator walks
    past a sibling's heading to prose naming the key and binds the wrong table
    (CP-L10 writes twenty registers in families of identical columns): the
    Completion Phase 8 adversarial audit built a handoff passing `check()` whose
    shipped key was met from a sibling. Unnarrowed, the locator falls back to
    its default pattern, which cannot match `TDR.3` or CP-1A's named registers,
    so every CP-DR key read as a miss over a dossier carrying exactly the
    answers it named (run `de27f93c`, 18 September 2026).
    """
    skill = verified_bytes(bundle, module_id, "SKILL.md").decode("utf-8")
    checker = contract.completeness_check
    declared = checker.load_contract(skill, module_id)["registers"]
    found = checker.find_registers(text, declared)
    return found if isinstance(found, dict) else {}


def unlocatable_register_keys(
    bundle: Bundle, qualification: QualificationSet
) -> tuple[ExpectedRegister, ...]:
    """Every register key no run could ever meet, in the order the set lists them.

    A key is locatable when its module declares a register contract, the
    register is one of it, its keyed columns are among any columns the contract
    declares, and `module_registers` -- the scorer's own reader -- finds the
    register when it is written as the vendor's suite writes it: its id in a
    heading above the table. Anything else reads
    `registers_met: false` whatever the model answers, which is a question the
    set asked of nobody.
    """
    contract = load_vendor_contract(bundle)
    return tuple(
        expect
        for case in qualification.cases
        for expect in case.expects_register
        if not _locatable(contract, bundle, expect)
    )


def _register_values_representable(expect: ExpectedRegister) -> bool:
    """Whether the vendor's pipe-table reader can return the keyed values."""
    return not any(
        "|" in _normalised_cell(part) for pair in expect.row_key for part in pair
    ) and not any(
        "|" in _normalised_cell(part) for part in (expect.column, expect.expected)
    )


def _probe_columns(
    declared: Sequence[object], expect: ExpectedRegister
) -> tuple[list[str], dict[str, str]] | None:
    """Safe synthetic headers under the register's declared column policy."""
    declared_columns = [str(column) for column in declared]
    candidates = declared_columns or [column for column, _ in expect.row_key] + [
        expect.column
    ]
    names: dict[str, str] = {}
    for column in candidates:
        normalised = _normalised_cell(column)
        if normalised in names:
            if declared_columns:
                return None
            continue
        names[normalised] = column if declared_columns else normalised
    if not declared_columns:
        sentinel = "__caos_probe__"
        while sentinel in names:
            sentinel += "_"
        names[sentinel] = sentinel
    return list(names.values()), names


def _locatable(
    contract: VendorContract, bundle: Bundle, expect: ExpectedRegister
) -> bool:
    """One key against its module's declared register contract and reader."""
    if not _register_values_representable(expect):
        return False
    try:
        skill = verified_bytes(bundle, expect.module_id, "SKILL.md").decode("utf-8")
        declared = contract.completeness_check.load_contract(skill, expect.module_id)
    except (Refusal, ValueError, UnicodeDecodeError):
        return False
    spec = declared["registers"].get(expect.register_id)
    if spec is None:
        return False
    probe_columns = _probe_columns(spec["columns"], expect)
    if probe_columns is None:
        return False
    columns, declared_names = probe_columns
    try:
        row_key = tuple(
            (
                declared_names[_normalised_cell(column)],
                sha256(_normalised_cell(value).encode()).hexdigest(),
            )
            for column, value in expect.row_key
        )
        expected_column = declared_names[_normalised_cell(expect.column)]
    except KeyError:
        return False
    cells = dict.fromkeys(columns, "x")
    for column, value in row_key:
        cells[column] = value
    expected = sha256(_normalised_cell(expect.expected).encode()).hexdigest()
    cells[expected_column] = expected
    table = (
        f"#### {expect.register_id}\n\n| {' | '.join(columns)} |\n"
        f"|{'---|' * len(columns)}\n"
        f"| {' | '.join(cells[column] for column in columns)} |\n"
    )
    registers = module_registers(contract, bundle, expect.module_id, table)
    probe = ExpectedRegister(
        module_id=expect.module_id,
        register_id=expect.register_id,
        row_key=row_key,
        column=expected_column,
        expected=expected,
    )
    return _matches_register(registers, probe)


def _registers_met(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
) -> bool | None:
    """Whether every module wrote what the case says it should have written.

    The Markdown is read through `accepted_handoff`, which binds the record to
    it, and the registers are located by `module_registers` -- the vendor's own
    locator, asked exactly as the vendor's `check()` asks it at acceptance: the
    host adds no table parser of its own (invariant 4). `None` when the case
    names none; a module the case names that produced no single accepted
    artifact, or an artifact that will not read, is a miss and not an exception
    -- a row survives its own failure.
    """
    if not case.expects_register:
        return None
    route = resolved_route(conn, run_id)
    if route is None:
        return False
    accepted = _accepted_rows(conn, run_id)
    # One load for the whole row, not one per module: `load_vendor_contract` has
    # no cache (`canonical._contract` is the cached reader, and this is not it),
    # so asking per module recompiled and re-hashed twelve vendor files each
    # time -- measured at 33 ms and 148 KB per call. And its own refusal is
    # raised here rather than inside the per-module guard below, because an
    # `AUTHORITY_BYTES_MISMATCH` is the bundle failing its integrity check, not
    # the module writing the wrong cell: swallowing it as a miss pointed a
    # reviewer at the model for a vendored-bytes fault. `build_matrix` turns it
    # into the row's own refusal. Both found by the Completion Phase 8
    # adversarial audit, which measured the cache claim and found it false.
    contract = load_vendor_contract(bundle)
    wanted: dict[str, list[ExpectedRegister]] = {}
    for expect in case.expects_register:
        wanted.setdefault(expect.module_id, []).append(expect)
    for module_id, expects in wanted.items():
        node = next((item for item in route.nodes if item.module_id == module_id), None)
        if node is None:
            return False
        rows = conn.execute(
            "SELECT a.artifact_sha256, a.record_sha256, a.attempt_id"
            " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
            " WHERE a.run_id = %s AND t.route_node_id = %s",
            (run_id, node.route_node_id),
        ).fetchall()
        if len(rows) != 1 or rows[0][1] is None:
            return False
        artifact_sha256, record_sha256, attempt_id = rows[0]
        try:
            markdown, _record = accepted_handoff(
                conn,
                blobs,
                bundle,
                route,
                AcceptedRow(
                    run_id=run_id,
                    route_node_id=node.route_node_id,
                    attempt_id=UUID(str(attempt_id)),
                    artifact_sha256=str(artifact_sha256),
                    record_sha256=str(record_sha256),
                ),
                accepted=accepted,
            )
            registers = module_registers(
                contract, bundle, module_id, markdown.decode("utf-8")
            )
            if not isinstance(registers, dict):
                return False
            met = all(_matches_register(registers, expect) for expect in expects)
        except (Refusal, ValueError, TypeError, UnicodeDecodeError):
            # The reader's own faults included: an artifact the host cannot read
            # is a case it cannot score, never a case that concluded correctly.
            return False
        if not met:
            return False
    return True


def _forecast_met(  # noqa: PLR0913 -- one qualification case's bound readers
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case: QualificationCase,
    run_id: UUID,
    proof: OrchestrationProof | None,
) -> bool | None:
    """Compare a CP-CF answer key only after the complete run proof exists."""
    expected = case.forecast
    if expected is None:
        return None
    if proof is None:
        return False
    route = resolved_route(conn, run_id)
    if route is None:
        return False
    node = next((item for item in route.nodes if item.module_id == MODEL_MODULE), None)
    if node is None:
        return False
    rows = conn.execute(
        "SELECT a.artifact_sha256, a.record_sha256, a.attempt_id"
        " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
        " WHERE a.run_id = %s AND t.route_node_id = %s",
        (run_id, node.route_node_id),
    ).fetchall()
    if len(rows) != 1 or rows[0][1] is None:
        return False
    accepted = {
        str(row[0]): (str(row[1]), None if row[2] is None else str(row[2]))
        for row in conn.execute(
            "SELECT t.route_node_id, a.artifact_sha256, a.record_sha256"
            " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
            " WHERE a.run_id = %s",
            (run_id,),
        ).fetchall()
    }
    artifact_sha256, record_sha256, attempt_id = rows[0]
    try:
        markdown, record = accepted_handoff(
            conn,
            blobs,
            bundle,
            route,
            AcceptedRow(
                run_id=run_id,
                route_node_id=node.route_node_id,
                attempt_id=UUID(str(attempt_id)),
                artifact_sha256=str(artifact_sha256),
                record_sha256=str(record_sha256),
            ),
            accepted=accepted,
        )
        result = forecast_projection(markdown)
    except (Refusal, ValueError, TypeError):
        return False
    row = next(
        (
            item
            for item in result["rows"]
            if item["case"] == expected.scenario
            and item["period_id"] == expected.period_id
        ),
        None,
    )
    return (
        row is not None
        and all(
            _forecast_values(row).get(value.name) == value.value
            for value in expected.values
        )
        and result["units"] == {"currency": expected.currency, "scale": expected.scale}
        and result["perimeter"] == expected.perimeter
        and record.projections.qa_status == expected.qa_status
        and sorted(record.projections.limitation_flags)
        == sorted(expected.limitation_flags)
        and sorted(_readiness(conn, blobs, bundle, route, run_id))
        == sorted(expected.readiness)
    )


def _forecast_values(row: Mapping[str, object]) -> dict[str, str]:
    values: dict[str, str] = {}
    for group, item in row.items():
        if group in {"case", "period_id", "fiscal_year", "days", "unavailable_reason"}:
            continue
        if isinstance(item, dict):
            for name, value in item.items():
                if isinstance(value, dict) and isinstance(value.get("value"), str):
                    values[f"{group}.{name}"] = value["value"]
                elif isinstance(value, str):
                    values[f"{group}.{name}"] = value
        elif isinstance(item, str):
            values[group] = item
    return values


def _readiness(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    route: ResolvedRoute,
    run_id: UUID,
) -> tuple[tuple[str, str], ...]:
    """The gate's revalidated readiness projection, or an empty non-match."""
    gate = next((item for item in route.nodes if item.module_id == "CP-0"), None)
    if gate is None:
        return ()
    row = conn.execute(
        "SELECT a.artifact_sha256, a.record_sha256, a.attempt_id"
        " FROM artifacts a JOIN run_attempts t ON t.attempt_id = a.attempt_id"
        " WHERE a.run_id = %s AND t.route_node_id = %s",
        (run_id, gate.route_node_id),
    ).fetchone()
    if row is None or row[1] is None:
        return ()
    try:
        _markdown, record = accepted_handoff(
            conn,
            blobs,
            bundle,
            route,
            AcceptedRow(
                run_id=run_id,
                route_node_id=gate.route_node_id,
                attempt_id=UUID(str(row[2])),
                artifact_sha256=str(row[0]),
                record_sha256=str(row[1]),
            ),
        )
    except (Refusal, ValueError, TypeError):
        return ()
    return record.projections.readiness


def _matches(expect: ExpectedCitation, cited: set[tuple[str, str, str]]) -> bool:
    """An expectation is met by the same quote, from the same document, under the
    same module. The right quote under the wrong module answers a different
    question and is not this key's answer."""
    return (expect.module_id, expect.document_sha256, expect.matched_text) in cited


# A row's own uncertainty, not a reason to end the matrix: a pin that no longer
# reads, a proven source withdrawn before its quotes were scored, or vendored
# bytes that no longer match the manifest. The last one is here because the
# register reader verifies the bundle where the cached validator does not, so it
# is the one place a tampered vendor script surfaces during scoring -- and it
# belongs in the row's refusal rather than in its comparison.
_ROW_REFUSALS = frozenset(
    {
        RefusalCode.ROUTE_IDENTITY_INVALID,
        RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED,
        RefusalCode.AUTHORITY_BYTES_MISMATCH,
    }
)


def _cited(
    conn: StoreConnection, run_id: UUID, *, proof: OrchestrationProof | None
) -> set[tuple[str, str, str]]:
    """Every (module, document, quote) this run's proof re-anchored.

    The module is taken from the route pin, as `proof.py` takes it (invariant
    3: the host owns identity). A run with no pin cites nothing, which is a row
    that misses every key; an invalid pin refuses so `_row` records uncertainty.
    A run cites exactly what its `proof` re-anchored, and nothing without one:
    no artifact is read as a claims envelope (§42.1).
    """
    if resolved_route(conn, run_id) is None:
        return set()
    return _proven(conn, run_id, proof)


def _proven(
    conn: StoreConnection, run_id: UUID, proof: OrchestrationProof | None
) -> set[tuple[str, str, str]]:
    """A proven canonical run's anchored quotes, each document still live now.

    Scoring is a use, so a source withdrawn since the proof refuses the row
    `ORCHESTRATION_SOURCE_NOT_PINNED`, as the proof itself would (invariant 1).
    """
    if proof is None:
        return set()
    live = pinned_live_sources(conn, run_id)
    if any(document not in live for _module, document, _quote in proof.anchored):
        raise Refusal(RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED)
    return set(proof.anchored)


def assert_measurable(qualification: QualificationSet) -> None:
    """A set with no cases, a case expecting nothing, or a case with no
    documents: each measures nothing.

    Public because the harness has to apply it *before* it performs a single
    case, and a copy of the rule there would be a second place to keep in step
    with this one.

    It would also match everything, which is the shape of a qualification that
    reads as a pass because it asked no question.
    """
    if not qualification.cases:
        raise Refusal(RefusalCode.QUALIFICATION_SET_EMPTY)
    if any(
        not case.documents
        or (
            not case.expects
            and case.forecast is None
            and case.expected_refusal is None
            and not case.expects_ready
            and not case.expects_blocked
            and not case.expects_projection
            and not case.expects_register
        )
        or (case.forecast is not None and not case.forecast.values)
        for case in qualification.cases
    ):
        # A case with no declared comparison, or an empty forecast key, measures
        # nothing; a case with no documents cannot be run.  All are the same
        # pre-spend hole.
        raise Refusal(RefusalCode.QUALIFICATION_SET_EMPTY)


def _register_cell(
    expect: ExpectedRegister,
) -> tuple[str, str, frozenset[tuple[str, str]], str]:
    """The cell a register key names, without the answer it expects.

    Two keys sharing this and disagreeing on `expected` cannot both be met.
    """
    return (
        expect.module_id,
        expect.register_id,
        frozenset(
            (_normalised_cell(column), _normalised_cell(value))
            for column, value in expect.row_key
        ),
        _normalised_cell(expect.column),
    )


def _witnesses_contradict(
    witnesses: list[tuple[frozenset[tuple[str, str]], dict[str, str]]],
) -> bool:
    """Whether exact-one selectors force incompatible keys onto one row."""
    selectors = [selector for selector, _requirements in witnesses]
    requirements = [required for _selector, required in witnesses]
    parents = list(range(len(witnesses)))
    pending = list(parents)

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    while pending:
        left = root(pending.pop())
        for key_index, selector in enumerate(selectors):
            right = root(key_index)
            if left == right or not all(
                requirements[left].get(column) == value for column, value in selector
            ):
                continue
            if any(
                column in requirements[right] and requirements[right][column] != value
                for column, value in requirements[left].items()
            ):
                return True
            parents[right] = left
            requirements[left].update(requirements[right])
            pending.append(left)
            break
    return False


def _registers_ambiguous(expects: tuple[ExpectedRegister, ...]) -> bool:
    """Whether one case carries register keys no run can satisfy together."""
    cells = [_register_cell(expect) for expect in expects]
    if len(set(cells)) != len(cells):
        return True

    groups: dict[
        tuple[str, str],
        list[tuple[frozenset[tuple[str, str]], dict[str, str]]],
    ] = {}
    for expect, (module_id, register_id, selectors, column) in zip(
        expects, cells, strict=True
    ):
        expected = _normalised_cell(expect.expected)
        requirements = dict(selectors)
        if (
            not selectors
            or len(requirements) != len(selectors)
            or (column in requirements and requirements[column] != expected)
            or not _register_values_representable(expect)
        ):
            continue
        requirements[column] = expected
        groups.setdefault((module_id, register_id), []).append(
            (selectors, requirements)
        )

    # ponytail: quadratic witness closure; add an index only if qualification
    # key counts grow enough for this bounded preflight to matter.
    return any(_witnesses_contradict(witnesses) for witnesses in groups.values())


def _projections_ambiguous(expects: tuple[ExpectedProjection, ...]) -> bool:
    """Whether one case expects two values of one module's single-valued field.

    `qa_status` is one word per handoff, so "CP-0 said Passed" and "CP-0 said
    Restricted" are a pair no run can satisfy -- and the ambiguity check covered
    register and readiness conflicts while letting this one through to
    execution, where it consumed a route's model work before reading as a miss
    (AR-23). A list-shaped field is left alone: two memberships of
    `limitation_flags` are two ordinary questions about one handoff.
    """
    seen: dict[tuple[str, str], str] = {}
    for expect in expects:
        if expect.field not in SCALAR_PROJECTION_FIELDS:
            continue
        key = (expect.module_id, expect.field)
        if seen.setdefault(key, expect.value) != expect.value:
            return True
    return False


def assert_unambiguous(qualification: QualificationSet) -> None:
    """Refuse duplicate case labels or answer keys before either can be scored."""
    labels = [case_label(case) for case in qualification.cases]
    if len(set(labels)) != len(labels) or any(
        len(set(case.expects)) != len(case.expects)
        or len(set(case.expects_register)) != len(case.expects_register)
        or _registers_ambiguous(case.expects_register)
        or _projections_ambiguous(case.expects_projection)
        or (
            case.forecast is not None
            and len({value.name for value in case.forecast.values})
            != len(case.forecast.values)
        )
        # A module expected both cleared and refused is a key no run can meet.
        or bool(set(case.expects_ready) & set(case.expects_blocked))
        for case in qualification.cases
    ):
        raise Refusal(RefusalCode.QUALIFICATION_SET_AMBIGUOUS)
