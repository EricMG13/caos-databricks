"""The wire contract under `/api/`: the one refusal body and the v1 sections.

Phase 4 Task 4.1, decision 3. Every non-success response carries
`RefusalBody{code, clears}`; `clears` is `CLEARS[code]`, a host constant that
says what would clear the refusal. It is never formatted, so no request or
document text can reach it. `caos/refusals.py` stays code-only.

Decisions 5, 6 and 8: one closed document per enabled section, every key
required, every string and list bounded. Task 4.2, decisions 1, 10 and 11: the
closed command requests and receipts (`V1_COMMANDS`), and the server-computed
`Chrome.actions`. `python -m caos.api.wire` prints their JSON Schema,
committed at `frontend/src/wire/v1/schema.json` (`tests/test_wire_contract.py`
proves the two equal).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
)
from pydantic.json_schema import models_json_schema

from caos.api.identity import GlobalRole
from caos.graph.route import EdgeType, NodeState
from caos.methodology.handoff import (
    MAX_BLOCKER_CHARS,
    MAX_HANDOFF_BYTES,
    MAX_LINE_BYTES,
)
from caos.methodology.tables import (
    CELL_CHARS,
    FIGURE_CHARS,
    TABLE_COLUMNS_MAX,
    TABLE_ID_CHARS,
    TABLE_ROWS_MAX,
    TABLES_MAX,
    TablesUnavailable,
)
from caos.refusals import RefusalCode
from caos.store.gates import Gate, GateState
from caos.store.members import Standing

IO_BUDGET = 0

_CLOSED = ConfigDict(extra="forbid", frozen=True)

# Bounds. A string or list without one is refused by the contract test.
ID_CHARS = 256  # route node, module, profile, selection, build ids
TEXT_CHARS = 4096  # `BoundaryText`'s default limit: titles, filenames, labels
QUOTE_CHARS = MAX_LINE_BYTES  # one quoted line of evidence
MARKDOWN_CHARS = MAX_HANDOFF_BYTES  # a whole accepted handoff is bounded (D45)
CASES_MAX = 200  # beyond it the Directory is partial, `LIST_TRUNCATED`
RUNS_MAX = 200
# A case's members as its administrator sees them in Directory; beyond it the
# document is partial, `LIST_TRUNCATED`.
MEMBERS_MAX = 64
SOURCES_MAX = 1000
SET_VERSIONS_MAX = 1000
ROUTE_NODES_MAX = 256
ATTEMPTS_MAX = 4096
CITATIONS_MAX = 1024
RECTS_MAX = 256
FLAGS_MAX = 256
# A run's revisions Report lists, newest first; older ones stay openable by id.
REVISIONS_MAX = 64
TITLE_CHARS = 256  # a case title a command sets
SOURCE_IDS_MAX = 50  # `AdmissionLimits.max_documents`
ROUTE_CHOICES_MAX = 18
PREVIEW_CHARS = MAX_HANDOFF_BYTES  # a gate preview, bounded as a handoff is
PAGE_LINES_MAX = 2000  # beyond it a page is partial, `LIST_TRUNCATED`
PAGE_MAX = 500  # a page outside 1..PAGE_MAX is `PAGE_NOT_AVAILABLE`
MOMENT_CHARS = 64  # an ISO-8601 instant with its offset, as `read_verdict` reads it
# `caos/deliverable/revisions.py`'s own bounds, restated where the wire is
# what refuses a draft past them.
NARRATIVE_CHARS = 2000
NARRATIVE_SPANS = 64
BOOK_CASES_MAX = 4  # "Two to four credits side by side" (IA_SPEC.md 4.4)
BOOK_COLUMNS_MAX = 16  # the host-declared columns of the CP-CF projection
BOOK_PERIODS_MAX = 8  # beyond it a row is partial, `LIST_TRUNCATED`
BRIEF_QUESTIONS_MAX = 32  # `CP_DR_RESEARCH_BRIEF_V1.md`'s bounded batch

Id = Annotated[str, Field(max_length=ID_CHARS)]
Text = Annotated[str, Field(max_length=TEXT_CHARS)]
Sha256 = Annotated[str, Field(max_length=64, pattern="^[0-9a-f]{64}$")]
Moment = Annotated[str, Field(max_length=MOMENT_CHARS)]
Blocker = Annotated[str, Field(max_length=MAX_BLOCKER_CHARS)]
RunStatus = Literal["RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"]
WorkState = Literal["QUEUED", "CLAIMED", "STOPPED", "DONE"]  # `run_work.state`


class RefusalBody(BaseModel):
    """Everything a declined request says: the code and what clears it."""

    model_config = _CLOSED

    code: RefusalCode
    clears: Text


class QualificationState(StrEnum):
    """What this caller can truthfully say about one exact evidence identity."""

    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    RESTRICTED = "RESTRICTED"
    UNAVAILABLE = "UNAVAILABLE"


class QualificationRead(BaseModel):
    """A global qualification result; it is not a case section document."""

    model_config = _CLOSED

    evidence_sha256: Sha256
    state: QualificationState
    qualification_set_sha256: Sha256 | None
    performed_sha256: Sha256 | None
    build_id: Id | None
    adapter_version: Id | None
    provider: Id | None
    model: Id | None
    reviewer: Text | None
    reviewer_id: UUID | None
    decided_at: AwareDatetime | None
    expires_at: AwareDatetime | None


_C = RefusalCode

# Total over `RefusalCode` (`test_every_refusal_code_has_a_constant_clearance`).
# A code no route answers today still gets its sentence, so the first route to
# raise it cannot ship a body without one.
CLEARS: Mapping[RefusalCode, str] = {
    _C.BOUNDARY_TEXT_INVALID: "Remove control, bidirectional or surrogate characters.",
    _C.BOUNDARY_TEXT_TOO_LONG: "Shorten the text to within its bound.",
    _C.BLOB_DIGEST_MISMATCH: "An operator must restore the stored bytes.",
    _C.BLOB_NOT_FOUND: "An operator must restore the blob store.",
    _C.BLOB_ADDRESS_INVALID: "An operator must repair the stored address.",
    _C.RUN_NOT_FOUND: "Name a run you may read.",
    _C.RUN_NOT_RUNNING: "Act only on a running run.",
    _C.RUN_NOT_BLOCKED: "Name a run of this case that ended BLOCKED.",
    _C.RUN_ALREADY_SUPERSEDED: "Read the successor already recorded for that run.",
    _C.LEASE_NOT_HELD: "Reclaim the lease before acting on the node.",
    _C.RUN_CANCEL_REQUESTED: "Nothing; the run is being cancelled.",
    _C.RUN_NODES_UNACCEPTED: "Accept every pinned node first.",
    _C.RUN_TERMINAL_STALE: "Re-read the run and decide again.",
    _C.ATTEMPT_NOT_FOUND: "An operator must repair the attempt ledger.",
    _C.ATTEMPT_LIMIT_REACHED: "Start a new run.",
    _C.STREAM_LIMIT_REACHED: "Close a tail already open, or retry shortly.",
    _C.CALL_OUTCOME_INVALID: "Record a well-formed call outcome.",
    _C.CALL_OUTCOME_CONFLICT: "Nothing; a different outcome is already recorded.",
    _C.CALL_OUTCOME_LEGACY: "Start a new run.",
    _C.NODE_ALREADY_ACCEPTED: "Nothing; the node is already accepted.",
    _C.MONEY_NOT_DECIMAL: "State the amount as a decimal.",
    _C.MONEY_INVALID: "State a finite, non-negative amount.",
    _C.BUDGET_ALREADY_RESERVED: "Nothing; the reservation already exists.",
    _C.BUDGET_NOT_RESERVED: "Reserve budget before the call.",
    _C.BUDGET_CEILING_REACHED: "Raise the ceiling or start a new run.",
    _C.PROVIDER_NOT_CONFIGURED: "An operator must configure the provider.",
    _C.PROVIDER_CALL_INVALID: "Correct the provider call parameters.",
    _C.CONTEXT_OVER_CEILING: "Deliver less context to the module.",
    _C.UPSTREAM_SECTION_OVER_CEILING: (
        "Start a new run; an accepted handoff is never shortened."
    ),
    _C.RESERVATION_BELOW_REQUEST: (
        "Retry the attempt; a new one reserves for the request it sends. "
        "An operator must investigate if it recurs."
    ),
    _C.PROVIDER_UNAVAILABLE: "Retry when the provider answers.",
    _C.PROVIDER_OUTPUT_TRUNCATED: "Retry the attempt.",
    _C.PROVIDER_REFUSED: "Retry the attempt or revise the evidence.",
    _C.PROVIDER_RESPONSE_INVALID: "Retry the attempt.",
    _C.AUTHORITY_BYTES_MISMATCH: "An operator must restore the pinned bundle.",
    _C.AUTHORITY_MODULE_UNKNOWN: "Name a module the bundle declares.",
    _C.HANDOFF_MALFORMED: (
        "Retry the attempt; an operator must verify a stored handoff refused on read."
    ),
    _C.HANDOFF_BLOCKED: (
        "Supply what the module's stated blocker names, then start a new run."
    ),
    _C.HANDOFF_IDENTITY_MISMATCH: (
        "Retry the attempt; an operator must verify a stored handoff refused on read."
    ),
    _C.HANDOFF_INCOMPLETE: (
        "Retry the attempt; an operator must verify a stored handoff refused on read."
    ),
    _C.HANDOFF_UNDECLARED_FIELD: (
        "Retry the attempt; an operator must verify a stored handoff refused on read."
    ),
    _C.HANDOFF_MODULE_UNSUPPORTED: "Select a route the adapter executes.",
    _C.CALL_OUTCOME_UNEXPLAINED: "An operator must decide whether to pay again.",
    _C.ARTIFACT_RECORD_MISMATCH: "An operator must verify the stored record.",
    _C.NOT_AUTHENTICATED: "Sign in.",
    _C.ENDPOINT_NOT_FOUND: "Use a declared path and method.",
    _C.EDGE_NOT_TRUSTED: "Reach the service through its edge.",
    _C.ORIGIN_REFUSED: "Send the request from the service's own origin.",
    _C.EDGE_CONFIG_INVALID: "An operator must correct the edge configuration.",
    _C.CONCURRENCY_LIMIT_REACHED: "Retry shortly.",
    _C.INTERNAL_FAULT: "Retry; an operator must investigate if it persists.",
    _C.NOT_AUTHORISED: "Obtain the required standing on the case.",
    _C.REQUEST_INVALID: "Send a well-formed request body.",
    _C.IDEMPOTENCY_KEY_REQUIRED: "Send a UUID Idempotency-Key header.",
    _C.IDEMPOTENCY_KEY_REUSED: "Use a new Idempotency-Key for a different request.",
    _C.RUN_INPUT_NOT_PINNED: "Pin the run input first.",
    _C.RUN_ALREADY_STARTED: "Nothing; the run is already started.",
    _C.RUN_NOT_STOPPED: "Retry only a stopped run.",
    _C.QUEUED_RUNS_LIMIT_REACHED: (
        "Wait for one of your queued or running runs to end, or cancel one."
    ),
    _C.ROUTE_NOT_ENABLED: "Select a route the adapter executes.",
    _C.COMMAND_EXPECTATION_STALE: "Re-read the run and act on what it shows.",
    _C.METHODOLOGY_INPUT_INVALID: "Correct the calculation inputs.",
    _C.FORECAST_DRIVER_NOT_READY: "Complete the driver first.",
    _C.DELIVERABLE_PAYLOAD_INVALID: "Correct the deliverable payload.",
    _C.DELIVERABLE_NOT_FOUND: "Name a saved revision of this case.",
    _C.NARRATIVE_FIGURE_UNREFERENCED: (
        "Insert every financial figure through a validated reference."
    ),
    _C.NARRATIVE_REFERENCE_INVALID: (
        "Reference a citation in the accepted revision artifacts."
    ),
    _C.DELIVERABLE_UNCITED_FIGURE: "Cite every figure.",
    _C.DELIVERABLE_MARKDOWN_UNSUPPORTED: (
        "Keep the handoff to the elements the deliverable renders."
    ),
    _C.DELIVERABLE_NOT_SIGNED: "Sign the deliverable first.",
    _C.DELIVERABLE_NOT_FROZEN: "Freeze the deliverable first.",
    _C.DELIVERABLE_MOVED_SINCE_SIGNING: "Review and sign the current revision.",
    _C.DELIVERABLE_ALREADY_FILED: "Nothing; the deliverable is filed.",
    _C.DELIVERABLE_ALREADY_FROZEN: "Nothing; the deliverable is frozen.",
    _C.DELIVERABLE_ALREADY_SIGNED: "Nothing; you have signed this revision.",
    _C.APPROVER_NOT_INDEPENDENT: "Ask an approver who did not author it.",
    _C.CASE_NOT_FOUND: "Name a case you may read.",
    _C.SOURCE_PACK_EMPTY: "Supply at least one document.",
    _C.SOURCE_NOT_READABLE: "Supply a readable document.",
    _C.SOURCE_ENCRYPTED: "Supply the document without encryption.",
    _C.SOURCE_HAS_NO_TEXT: "Supply a document with extractable text.",
    _C.SOURCE_TOO_LARGE: "Supply a smaller document or pack.",
    _C.SOURCE_EXTRACTION_TIMEOUT: "Supply a simpler document.",
    _C.SOURCE_IDENTITY_INVALID: "Readmit the document.",
    _C.EVIDENCE_NOT_AVAILABLE: "Pin a live source for the evidence.",
    _C.EVIDENCE_PACKING_MISMATCH: (
        "An operator must re-admit the source under this build."
    ),
    _C.EVIDENCE_DEMAND_UNRESOLVED: (
        "Run a successor whose CP-0 names each source to attach by its admitted "
        "filename or document digest, or names none."
    ),
    _C.PAGE_NOT_AVAILABLE: "Name a page of a live source pinned to this run.",
    _C.CITATION_NOT_LOCATED: "Quote whole tokens from delivered evidence.",
    _C.CITATION_AMBIGUOUS: "Quote enough text to locate it once.",
    _C.CITATION_NOT_DELIVERED: "Cite only delivered evidence.",
    _C.ROUTE_PROFILE_UNKNOWN: "Name a profile the catalog declares.",
    _C.ROUTE_SELECTION_UNKNOWN: "Name a pathway the profile declares.",
    _C.ROUTE_EXTENSION_OWNER_MISSING: "Include the extension's owning module.",
    _C.ROUTE_HAS_A_CYCLE: "Select a route without a cycle.",
    _C.ROUTE_DUPLICATE_MODULE: "Select a route naming each module once.",
    _C.ROUTE_EDGE_UNSUPPORTED: "Nothing until the engine evaluates this edge type.",
    _C.ROUTE_ALREADY_PINNED: "Nothing; the route is already pinned.",
    _C.ROUTE_IDENTITY_INVALID: "An operator must verify the pinned route.",
    _C.ROUTE_PIN_TOO_LATE: "Start a new run.",
    _C.RUN_INPUT_INVALID: "An operator must verify the run input.",
    _C.RUN_INPUT_ALREADY_PINNED: "Nothing; the input is already pinned.",
    _C.RUN_INPUT_TOO_LATE: "Start a new run.",
    _C.GATE_APPROVAL_MISMATCH: "Approve the content currently shown.",
    _C.QUALIFICATION_SET_EMPTY: "Add at least one case to the set.",
    _C.QUALIFICATION_KEY_UNANSWERABLE: "Key only modules on the case's route.",
    _C.QUALIFICATION_SET_AMBIGUOUS: "Give each case a distinct identity.",
    _C.QUALIFICATION_KEY_AMBIGUOUS: "Name one register row in the answer key.",
    _C.QUALIFICATION_RUN_MISSING: "Perform every case in the set.",
    _C.QUALIFICATION_SET_FILE_INVALID: "Correct the set manifest.",
    _C.QUALIFICATION_SET_PATH_ESCAPES: "Keep documents inside the set directory.",
    _C.QUALIFICATION_SET_OVER_CEILING: "Raise the set ceiling or remove cases.",
    _C.ORCHESTRATION_NOTHING_TO_PROVE: "Accept at least one artifact first.",
    _C.ORCHESTRATION_ROUTE_NOT_PINNED: "Pin the route first.",
    _C.ORCHESTRATION_NODE_NOT_IN_ROUTE: "An operator must verify the run's artifacts.",
    _C.ORCHESTRATION_BUILD_MOVED: "Rerun under the current bundle.",
    _C.ORCHESTRATION_SOURCE_NOT_PINNED: "Rerun against live pinned sources.",
    _C.ORCHESTRATION_CITATION_LOST: "Rerun against live pinned sources.",
    _C.ORCHESTRATION_ARTIFACT_UNREADABLE: "An operator must restore the artifact.",
    _C.VERDICT_INCOMPLETE: "Supply every verdict binding.",
    _C.VERDICT_BINDING_INVALID: "Correct the verdict bindings.",
    _C.VERDICT_UNDECLARED_FIELD: "Remove undeclared verdict fields.",
    _C.VERDICT_EXPIRED: "Obtain a current verdict.",
    _C.VERDICT_ALREADY_RECORDED: "Read the verdict already recorded.",
    _C.QUALIFICATION_EVIDENCE_NOT_FOUND: "Name qualification evidence you may sign.",
    _C.STORE_SCHEMA_DRIFT: "An operator must reconcile the schema.",
    _C.STORE_NOT_TRANSACTIONAL: "An operator must fix the store connection.",
    _C.STORE_NOT_CONFIGURED: "An operator must configure the store.",
    _C.STORE_UNAVAILABLE: "Retry when the store answers.",
    _C.IDENTITY_UNAVAILABLE: "Retry when the workspace answers.",
}


class SectionNote(StrEnum):
    """Why a section document is partial or empty. Closed."""

    LIST_TRUNCATED = "LIST_TRUNCATED"
    ROUTE_NOT_PINNED = "ROUTE_NOT_PINNED"
    HANDOFFS_PENDING = "HANDOFFS_PENDING"


class Subject(BaseModel):
    """The case the section is about."""

    model_config = _CLOSED

    case_id: UUID
    title: Text


class ServedRole(BaseModel):
    """Who the server answered as. Shown, and enables nothing (decision 5)."""

    model_config = _CLOSED

    global_role: GlobalRole
    standing: Standing | None


class ActionName(StrEnum):
    """Every governed command a section can offer. Closed."""

    CREATE_CASE = "CREATE_CASE"
    ADMIT_SOURCES = "ADMIT_SOURCES"
    CREATE_RUN = "CREATE_RUN"
    PIN_RUN_INPUT = "PIN_RUN_INPUT"
    APPROVE_SOURCE_SET = "APPROVE_SOURCE_SET"
    APPROVE_RESEARCH_PLAN = "APPROVE_RESEARCH_PLAN"
    START_RUN = "START_RUN"
    RETRY_RUN = "RETRY_RUN"
    CANCEL_RUN = "CANCEL_RUN"
    # Task 12.1. Membership is judged per case by the Directory read (O21),
    # which is where a case's administrator is shown its members.
    WITHDRAW_SOURCE = "WITHDRAW_SOURCE"
    GRANT_STANDING = "GRANT_STANDING"
    REVOKE_STANDING = "REVOKE_STANDING"
    SAVE_REVISION = "SAVE_REVISION"
    SIGN_OPINION = "SIGN_OPINION"
    FREEZE_DELIVERABLE = "FREEZE_DELIVERABLE"
    FILE_DELIVERABLE = "FILE_DELIVERABLE"


class ActionView(BaseModel):
    """One action as the server judged it: available (`refusal` null) or refused
    with the code the command would answer. Advisory; the command rechecks."""

    model_config = _CLOSED

    action: ActionName
    refusal: RefusalBody | None


class Chrome(BaseModel):
    """The authority facts the client composes its chrome from."""

    model_config = _CLOSED

    subject: Subject | None
    served_role: ServedRole
    actions: Annotated[list[ActionView], Field(max_length=len(ActionName))]


class RunSummary(BaseModel):
    """One run of a case, as a list names it."""

    model_config = _CLOSED

    run_id: UUID
    status: RunStatus
    created_at: AwareDatetime
    profile_id: Id | None
    selection_id: Id | None
    # CF-044: a run parked by its worker (`run_work.state = 'STOPPED'`) still
    # reads `status: RUNNING` here -- the run itself is recoverable, not
    # ended -- so this is the one field that tells a list apart from a run
    # nobody is currently driving. `None` for a run never enqueued or still
    # being worked.
    stop_code: RefusalCode | None


class MemberRow(BaseModel):
    """One live member of a case, as its administrator is shown it."""

    model_config = _CLOSED

    user_id: UUID
    standing: Standing


class CaseRow(BaseModel):
    """One case the actor holds live standing on.

    `members` is served only to the case's ADMIN, who is the one member that
    may change it; `null` says the list was not served, not that it is empty.
    `actions` judges the two membership commands for this case alone."""

    model_config = _CLOSED

    case_id: UUID
    title: Text
    created_at: AwareDatetime
    standing: Standing
    live_sources: int
    latest_run: RunSummary | None
    members: Annotated[list[MemberRow], Field(max_length=MEMBERS_MAX)] | None
    actions: Annotated[list[ActionView], Field(max_length=2)]


class DirectoryBody(BaseModel):
    model_config = _CLOSED

    cases: Annotated[list[CaseRow], Field(max_length=CASES_MAX)]


class SourceRow(BaseModel):
    """One admitted source; withdrawal is read live."""

    model_config = _CLOSED

    source_id: UUID
    filename: Text
    document_sha256: Sha256
    admitted_at: AwareDatetime
    withdrawn_at: AwareDatetime | None
    extractor_identity: Text | None
    set_versions: Annotated[list[int], Field(max_length=SET_VERSIONS_MAX)]


class SetVersion(BaseModel):
    model_config = _CLOSED

    version: int
    fingerprint: Sha256
    member_count: int


class UploadBody(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    sources: Annotated[list[SourceRow], Field(max_length=SOURCES_MAX)]
    set_versions: Annotated[list[SetVersion], Field(max_length=SET_VERSIONS_MAX)]


class RunSubjectView(BaseModel):
    """The pinned run subject."""

    model_config = _CLOSED

    issuer_id: Annotated[str, Field(max_length=128)]
    issuer_name: Text
    reporting_period: Text
    analysis_date: Annotated[str, Field(max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")]


class GateView(BaseModel):
    model_config = _CLOSED

    gate: Gate
    state: GateState


class AttemptView(BaseModel):
    model_config = _CLOSED

    attempt_id: UUID
    route_node_id: Id
    ordinal: int | None
    started_at: AwareDatetime
    accepted: bool


class EdgeView(BaseModel):
    """One dependency a node is still waiting for, with its type."""

    model_config = _CLOSED

    source: Id
    type: EdgeType


class NodeView(BaseModel):
    """A node's state and the reason for it."""

    model_config = _CLOSED

    route_node_id: Id
    module_id: Id
    module_name: Text
    stage: int
    state: NodeState
    waiting_on: Annotated[list[EdgeView], Field(max_length=ROUTE_NODES_MAX)]
    awaiting_gate: bool
    gate_verdict: Id | None
    # What the gate wrote beside a verdict it did not clear: the T8 blocker cell
    # of a CONDITIONAL or BLOCKED readiness row, which is where CP-0 names the
    # source the effective set does not carry (§61). `None` for every node the
    # gate cleared, every node it never ruled on, and every run with no accepted
    # gate artifact -- so the wire says "no condition was stated" by carrying
    # nothing rather than by carrying an empty string. Model-authored prose,
    # bounded by the host at `MAX_BLOCKER_CHARS`; it is the reason a reader may
    # read, never a fact the host asserts.
    gate_reason: Blocker | None


class WorkView(BaseModel):
    """The run's `run_work` row, when it has been enqueued."""

    model_config = _CLOSED

    state: WorkState
    stop_code: RefusalCode | None
    cancel_requested: bool


class RouteChoice(BaseModel):
    """A (profile, selection) pair the adapter executes (`ADAPTER_ROUTES`).

    `accepts_model_extension` is the create command's own route resolution
    asked in advance: true where the pathway runs every owner CP-CF reads, so
    a `CreateRun` asking for the extension would not be refused
    `ROUTE_EXTENSION_OWNER_MISSING`. Advisory like every availability the
    surface draws -- the command resolves again at commit and is the answer.
    """

    model_config = _CLOSED

    profile_id: Id
    selection_id: Id
    accepts_model_extension: StrictBool


class BlockedByView(BaseModel):
    """The node whose validated Blocked verdict ended the run, and the attempt
    that answered it.

    Recorded by the transition that ended the run, from the verdict the runtime
    had just re-derived (`block_run`, §68) -- never re-derived here. The answer
    is an unaccepted attempt's stored body, and the store refuses to judge it
    again once the run is no longer RUNNING (`check_attempt`), so a reader that
    tried would be refused; and a replay later would rest on evidence and a
    bundle that may since have moved. The node's own `state` stays RUNNABLE,
    because a Blocked verdict accepts nothing: without this a document could
    only say the node did not run, which is the opposite of what happened.
    """

    model_config = _CLOSED

    route_node_id: Id
    module_id: Id
    attempt_id: UUID


class RunView(BaseModel):
    """The displayed run. Node states are recomputed, never stored."""

    model_config = _CLOSED

    run_id: UUID
    status: RunStatus
    created_at: AwareDatetime
    route_digest: Sha256 | None
    build_id: Id | None
    source_set_version: int | None
    # The run's own pinned input, when one is pinned (N48): Start and Retry
    # both take it back, so a client that reloaded without an open preview
    # still has what it needs to send either, rather than only a client that
    # kept a preview's answer in memory.
    input_fingerprint: Sha256 | None
    subject: RunSubjectView | None
    gates: Annotated[list[GateView], Field(max_length=len(Gate))]
    nodes: Annotated[list[NodeView], Field(max_length=ROUTE_NODES_MAX)]
    attempts: Annotated[list[AttemptView], Field(max_length=ATTEMPTS_MAX)]
    work: WorkView | None
    # Why the run ended, when a node's verdict is why. `None` on every run that
    # is not BLOCKED, and on a BLOCKED run no verdict ended: an empty frontier
    # with required work unfinished (§39) is the route's own rule and names no
    # node. Nullable so the wire never claims a blocking node that does not
    # exist -- the two ways a run ends BLOCKED are different things to a reader.
    blocked_by: BlockedByView | None
    # The successor link (§72), both ends. `supersedes` is the BLOCKED run of
    # this case that this run was created to answer, written once by the command
    # that created it; `superseded_by` is the one run created to answer this
    # one. Either is `None` for a run that answers nothing or has not been
    # answered. The link says which run a run answers; whether the successor's
    # source set carries what the verdict asked for is the reader's judgement,
    # not a fact the host asserts.
    supersedes: UUID | None
    superseded_by: UUID | None


class RunBody(BaseModel):
    """Latest and displayed run are separate identities (item 1)."""

    model_config = _CLOSED

    case_id: UUID
    latest_run_id: UUID | None
    displayed_run_id: UUID | None
    runs: Annotated[list[RunSummary], Field(max_length=RUNS_MAX)]
    run: RunView | None
    route_choices: Annotated[list[RouteChoice], Field(max_length=ROUTE_CHOICES_MAX)]


class RectView(BaseModel):
    """A rectangle in page coordinates, from the record."""

    model_config = _CLOSED

    x0: float
    y0: float
    x1: float
    y1: float


class CitationView(BaseModel):
    """A host-verified citation; withdrawal is read live. `source_id` is the
    pinned source the document resolves to, which addresses its page (4.4)."""

    model_config = _CLOSED

    document_sha256: Sha256
    source_id: UUID
    filename: Text
    page: int
    matched_text: Annotated[str, Field(max_length=QUOTE_CHARS)]
    rects: Annotated[list[RectView], Field(max_length=RECTS_MAX)]
    withdrawn_at: AwareDatetime | None


# A handoff's tagged tables (`caos.methodology.tables`), whose bounds these are.
CellText = Annotated[str, Field(max_length=CELL_CHARS)]
DecimalText = Annotated[
    str, Field(max_length=FIGURE_CHARS, pattern=r"^-?[0-9]+(\.[0-9]+)?$")
]


class CellView(BaseModel):
    """One cell: its exact text and, where the bundle's `parse_figure` reads a
    figure, that figure's exact value -- `Decimal` in plain notation, never a
    float (invariant 7). `None` is no figure, which is never zero."""

    model_config = _CLOSED

    text: CellText
    value: DecimalText | None


class TableView(BaseModel):
    """One `<!-- table-id: -->`-tagged table, as the bundle's reader reads it:
    the header, then every row in header order."""

    model_config = _CLOSED

    table_id: Annotated[
        str, Field(max_length=TABLE_ID_CHARS, pattern=r"^[A-Za-z0-9_.]+$")
    ]
    columns: Annotated[list[CellText], Field(max_length=TABLE_COLUMNS_MAX)]
    rows: Annotated[
        list[Annotated[list[CellView], Field(max_length=TABLE_COLUMNS_MAX)]],
        Field(max_length=TABLE_ROWS_MAX),
    ]


class HandoffView(BaseModel):
    """One accepted handoff, labelled per §46.3."""

    model_config = _CLOSED

    route_node_id: Id
    module_id: Id
    # The bundle catalog's own name for `module_id` (N61), so a reader is
    # never the one mirroring `icm/stages` slugs into prose.
    module_name: Text
    artifact_sha256: Sha256
    record_sha256: Sha256
    accepted_at: AwareDatetime
    qa_status: Id
    committee_status: Id
    confidence_score: int
    confidence_band: Id
    limitation_flags: Annotated[list[Text], Field(max_length=FLAGS_MAX)]
    validation_warnings: Annotated[list[Text], Field(max_length=FLAGS_MAX)]
    decision_scope: Id
    screening_only: bool
    source_facts: Annotated[list[CitationView], Field(max_length=CITATIONS_MAX)]
    model_analysis: Annotated[str, Field(max_length=MARKDOWN_CHARS)]
    host_calculation: Literal["NONE", "CP_CF_FORECAST"]
    # The tagged tables `model_analysis` carries, derived from it at read time;
    # model-authored as it is, and it stays the authority. Empty with a reason
    # when the bundle's reader refused them or they are past a bound.
    tables: Annotated[list[TableView], Field(max_length=TABLES_MAX)]
    tables_unavailable_reason: TablesUnavailable | None


class PendingNode(BaseModel):
    model_config = _CLOSED

    route_node_id: Id
    module_id: Id
    module_name: Text
    state: NodeState


class AnalysisBody(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    latest_run_id: UUID | None
    displayed_run_id: UUID | None
    subject: RunSubjectView | None
    # The displayed run's own status. Without it this page cannot tell a run
    # that stopped from one still working: `pending` is recomputed from accepted
    # artifacts, so a node the run never reached looks exactly like a node whose
    # turn has not come. `None` when no run is displayed.
    displayed_run_status: RunStatus | None
    # The node whose validated Blocked verdict ended the run, read exactly as
    # `RunView.blocked_by` is and `None` on the same runs. This page's `pending`
    # list holds that node, because a Blocked verdict accepts nothing, and
    # without the name a reader cannot tell the node that answered from the
    # nodes that never started.
    blocked_by: BlockedByView | None
    handoffs: Annotated[list[HandoffView], Field(max_length=ROUTE_NODES_MAX)]
    pending: Annotated[list[PendingNode], Field(max_length=ROUTE_NODES_MAX)]


class ModelUnit(StrEnum):
    """A projected value's own dimension (R24-12): the calculator's `_amount`
    values are money, in the forecast's stated currency and scale; its
    `_ratio` values are dimensionless -- a multiple for the leverage/coverage
    family (`metrics.*`), an explicit ratio for the one margin (never a
    percentage relabelled without the scaling that would take, since a Model
    reader performs no arithmetic on the server's decimal strings). Closed."""

    MONEY = "MONEY"
    MULTIPLE = "MULTIPLE"
    RATIO = "RATIO"


class ModelValue(BaseModel):
    model_config = _CLOSED

    name: Id
    unit: ModelUnit
    value: Annotated[str, Field(max_length=64, pattern=r"^-?[0-9]+(\.[0-9]+)?$")] | None
    unavailable_reason: Literal["ZERO_OR_NEGATIVE_DENOMINATOR"] | None


class ModelPeriod(BaseModel):
    model_config = _CLOSED

    case: Text
    period_id: Text
    fiscal_year: Text
    days: Annotated[str, Field(max_length=3, pattern=r"^[0-9]+$")]
    values: Annotated[list[ModelValue], Field(max_length=40)]
    unavailable_reason: Text | None


class ModelForecast(BaseModel):
    model_config = _CLOSED

    route_node_id: Id
    artifact_sha256: Sha256
    record_sha256: Sha256
    accepted_at: AwareDatetime
    qa_status: Id
    limitation_flags: Annotated[list[Text], Field(max_length=FLAGS_MAX)]
    validation_warnings: Annotated[list[Text], Field(max_length=FLAGS_MAX)]
    currency: Annotated[str, Field(max_length=3, pattern="^[A-Z]{3}$")]
    scale: Literal["units", "thousands", "millions", "billions"]
    perimeter: Text
    periods: Annotated[list[ModelPeriod], Field(max_length=240)]


class ModelBody(BaseModel):
    """The accepted forecast, or why there is none.

    `unavailable_reason` says there is no accepted forecast; the two fields
    beside it say whether one is still coming. A body that carried neither
    answered "not yet" to a run that had ended, which is the same blindness
    Analysis carried until `blocked_by` joined it.
    """

    model_config = _CLOSED

    case_id: UUID
    latest_run_id: UUID | None
    displayed_run_id: UUID | None
    subject: RunSubjectView | None
    displayed_run_status: RunStatus | None
    blocked_by: BlockedByView | None
    forecast: ModelForecast | None
    unavailable_reason: Literal["NO_ACCEPTED_FORECAST"] | None


class BookColumn(BaseModel):
    """One column of the book: a value the accepted projection already
    carries. `unit` is what the cell's own figure is (N60): a plain
    `Decimal` states a fraction (`0.20`) and a count identically, so the
    cell has to be told which -- the calculator names its own margins and
    coverage ratios, and the column declares that naming, never a guess
    from the figure's magnitude."""

    model_config = _CLOSED

    key: Id
    label: Text
    unit: Literal["percent", "currency", "multiple", "count", "none"]


class BookResearch(BaseModel):
    """An accepted module artifact of the row's displayed run."""

    model_config = _CLOSED

    route_node_id: Id
    module_id: Id
    qa_status: Id


class BookPassport(BaseModel):
    """The ten fields IA_SPEC.md 4.4 says a passport always carries, in its
    order. Every one is read from the accepted record, the pinned run subject
    or the host's declaration of its own calculator; none is a judgement about
    the run. `scenario` is the accepted projection's own `case` -- the name
    `caos-forecast-v1` gives a scenario, and the one
    `caos/qualification/matrix.py` already reads as `ExpectedForecast.scenario`
    -- so a base case and a downside are told apart in the field whose only job
    is to tell them apart. IA_SPEC's "evidence date" is served as
    `reporting_period`, the analyst's declared period from the pinned subject,
    because the host derives no date from any admitted document."""

    model_config = _CLOSED

    definition: Text
    period: Text
    scenario: Text
    reporting_period: Text
    computed_at: AwareDatetime
    snapshot: Sha256
    method: Text
    derivation: Text
    citations: Annotated[list[CitationView], Field(max_length=CITATIONS_MAX)]
    supporting_research: Annotated[
        list[BookResearch], Field(max_length=ROUTE_NODES_MAX)
    ]


class BookCell(BaseModel):
    model_config = _CLOSED

    column: Id
    value: Annotated[str, Field(max_length=64, pattern=r"^-?[0-9]+(\.[0-9]+)?$")] | None
    unavailable_reason: Literal["ZERO_OR_NEGATIVE_DENOMINATOR"] | None
    passport: BookPassport


class BookPeriod(BaseModel):
    model_config = _CLOSED

    case: Text
    period_id: Text
    fiscal_year: Text
    days: Annotated[str, Field(max_length=3, pattern=r"^[0-9]+$")]
    unavailable_reason: Text | None
    cells: Annotated[list[BookCell], Field(max_length=BOOK_COLUMNS_MAX)]


class BookRow(BaseModel):
    """One credit, and why it carries no cells when it carries none.

    `unavailable_reason` says no forecast is accepted; `refusal` is the typed
    refusal this credit's own projection read raised. A refusal on one credit
    never decides the others, so the book states it here rather than declining
    the whole portfolio.
    """

    model_config = _CLOSED

    case_id: UUID
    title: Text
    standing: Standing
    subject: RunSubjectView | None
    displayed_run_id: UUID | None
    displayed_run_status: RunStatus | None
    snapshot: Sha256 | None
    # The projection's own units. A portfolio that compared credits without
    # them would put two currencies in one column and say nothing.
    currency: Annotated[str, Field(max_length=3, pattern="^[A-Z]{3}$")] | None
    scale: Literal["units", "thousands", "millions", "billions"] | None
    periods: Annotated[list[BookPeriod], Field(max_length=BOOK_PERIODS_MAX)]
    unavailable_reason: Literal["NO_ACCEPTED_FORECAST"] | None
    refusal: RefusalBody | None


class BookBasis(BaseModel):
    """The one basis the comparison is stated on (IA_SPEC.md 4.4)."""

    model_config = _CLOSED

    period: Literal["EVERY_ACCEPTED_PERIOD"]
    scenario: Literal["EVERY_ACCEPTED_CASE"]
    accepted_only: Literal[True]


class BookBody(BaseModel):
    model_config = _CLOSED

    basis: BookBasis
    columns: Annotated[list[BookColumn], Field(max_length=BOOK_COLUMNS_MAX)]
    rows: Annotated[list[BookRow], Field(max_length=BOOK_CASES_MAX)]


class NarrativeFigure(BaseModel):
    """A bracketed figure the narrative cites, self-contained the way
    `CitationView` is: the evidence drawer opens it without cross-referencing
    `ReportBody.artifacts` for the record or the run's pinned members for the
    source. `record_sha256` is the accepted record `route_node_id` bound at
    save time; `source_id` is the pinned source `document_sha256` resolves
    to, live preferred (N59)."""

    model_config = _CLOSED

    route_node_id: Id
    record_sha256: Sha256
    citation_index: Annotated[int, Field(ge=0)]
    document_sha256: Sha256
    source_id: UUID
    page: Annotated[int, Field(ge=1)]
    matched_text: Annotated[str, Field(max_length=QUOTE_CHARS)]


class NarrativeSpan(BaseModel):
    model_config = _CLOSED

    text: Annotated[str, Field(max_length=NARRATIVE_CHARS)] | None
    figure: NarrativeFigure | None


class NarrativeFigureRef(BaseModel):
    """What a draft may say about a figure: which citation of which node. The
    quote and its coordinates are the host's, read from the accepted record."""

    model_config = _CLOSED

    route_node_id: Id
    citation_index: Annotated[int, Field(ge=0)]


class ReportArtifact(BaseModel):
    model_config = _CLOSED

    route_node_id: Id
    artifact_sha256: Sha256
    record_sha256: Sha256
    markdown: Annotated[str, Field(max_length=MARKDOWN_CHARS)]
    record: Annotated[str, Field(max_length=MARKDOWN_CHARS)]
    qa_status: Id
    committee_status: Id
    decision_scope: Id
    limitation_flags: Annotated[list[Text], Field(max_length=FLAGS_MAX)]
    validation_warnings: Annotated[list[Text], Field(max_length=FLAGS_MAX)]


class RevisionSummary(BaseModel):
    """One revision of the displayed run and how far it has gone.

    What Report lists and Committee's front door links to. It proves nothing:
    opening a revision runs that section's own proofs.
    """

    model_config = _CLOSED

    revision_id: UUID
    payload_sha256: Sha256
    saved_at: AwareDatetime
    state: Literal["saved", "frozen", "filed"]


class ReportBody(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    displayed_run_id: UUID
    # Both null on the one Report with no revision: a run nothing has been
    # saved from, served with the artifacts a first save would carry. Committee
    # serves only a frozen revision and redeclares both required.
    revision_id: UUID | None
    payload_sha256: Sha256 | None
    case_title: Text
    artifacts: Annotated[list[ReportArtifact], Field(max_length=ROUTE_NODES_MAX)]
    narrative: Annotated[
        list[Annotated[list[NarrativeSpan], Field(max_length=64)]], Field(max_length=64)
    ]
    # The run's revisions, newest first: empty on the Report with none.
    revisions: Annotated[list[RevisionSummary], Field(max_length=REVISIONS_MAX)]


class FiledReceipt(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    run_id: UUID
    revision_id: UUID
    payload_sha256: Sha256
    signed_by: UUID
    frozen_by: UUID
    filed_by: UUID
    renderer_sha256: Sha256
    filed_event_sha256: Sha256


class CommitteeBody(ReportBody):
    revision_id: UUID
    payload_sha256: Sha256
    state: Literal["frozen", "filed"]
    signed_by: Annotated[list[UUID], Field(max_length=1000)]
    frozen_by: UUID
    filed_by: UUID | None
    receipt: FiledReceipt | None
    # Committee never serves a revision `caos/api/reads/deliverable.py` would
    # refuse `DELIVERABLE_NOT_FROZEN` (N4): every revision it names is already
    # proven frozen, so `render_url` is never a dead link. `package_url` names
    # the same revision's audit package once `state` is "filed", and is null
    # until then -- there is no receipt for `read_deliverable_package` to prove.
    render_url: Text
    package_url: Text | None


SectionStatus = Literal["complete", "partial"]
Notes = Annotated[list[SectionNote], Field(max_length=len(SectionNote))]


class DirectoryDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: DirectoryBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class UploadDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: UploadBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class RunSectionDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: RunBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class AnalysisDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: AnalysisBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class ModelDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: ModelBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class BookDocument(BaseModel):
    """Portfolio-scoped: no case in its path, so `chrome.subject` is null."""

    model_config = _CLOSED

    chrome: Chrome
    body: BookBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class ReportDocument(BaseModel):
    model_config = _CLOSED

    chrome: Chrome
    body: ReportBody
    observed_at: AwareDatetime
    observed_empty: bool
    status: SectionStatus
    notes: Notes


class CommitteeDocument(ReportDocument):
    body: CommitteeBody


V1_DOCUMENTS: tuple[type[BaseModel], ...] = (
    DirectoryDocument,
    UploadDocument,
    RunSectionDocument,
    AnalysisDocument,
    ModelDocument,
    BookDocument,
    ReportDocument,
    CommitteeDocument,
)


# Events and evidence pages (Task 4.4, decisions 2, 7 and 8).

# The closed event names a case stream carries. A frame has no payload: a name
# only says which sections to refetch. Printed as its own `$defs` entry.
EventName = Literal[
    "run_progress",
    "handoff_accepted",
    "run_terminal",
    "sources_changed",
    "runs_changed",
    "filing_changed",
]


class FrameView(BaseModel):
    """A page's frame in the coordinates its rectangles are stored in."""

    model_config = _CLOSED

    x0: float
    y0: float
    x1: float
    y1: float
    y_axis: Literal["down", "up"]


# Why a reader of the rendered page may not see a line's text (N27): drawn in
# text render mode 3 (a scan's OCR layer), painted near the colour behind it,
# or in glyphs under 2 pt. `caos.evidence.extract.HIDDEN_REASONS`, as the wire
# names them; a line with nothing to note -- every line of a source extracted
# before there were marks -- carries none.
HiddenReason = Literal["near_background", "render_mode_3", "under_2pt"]


class PageLine(BaseModel):
    """One line of the token index: joined text, union rectangle, hidden marks."""

    model_config = _CLOSED

    text: Annotated[str, Field(max_length=QUOTE_CHARS)]
    x0: float
    y0: float
    x1: float
    y1: float
    hidden: Annotated[list[HiddenReason], Field(max_length=3)]


class PageBody(BaseModel):
    """The text layer of one page of a pinned live source of a run."""

    model_config = _CLOSED

    case_id: UUID
    run_id: UUID
    source_id: UUID
    document_sha256: Sha256
    page: Annotated[int, Field(ge=1, le=PAGE_MAX)]
    frame: FrameView
    lines: Annotated[list[PageLine], Field(max_length=PAGE_LINES_MAX)]


class PageDocument(BaseModel):
    """An evidence page. Not a section document, so it carries no chrome."""

    model_config = _CLOSED

    body: PageBody
    observed_at: AwareDatetime
    status: SectionStatus
    notes: Notes


# Commands (Task 4.2, decision 1). A request carries no actor, case, run or
# approver: the actor is the caller and the ids come from the path (decision 2).
# Digests in a request are expectations the command re-derives, never authority.


class CreateCase(BaseModel):
    model_config = _CLOSED

    title: Annotated[str, Field(max_length=TITLE_CHARS)]


class CaseCreated(BaseModel):
    model_config = _CLOSED

    case_id: UUID


class SourcesAdmitted(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    source_ids: Annotated[list[UUID], Field(max_length=SOURCE_IDS_MAX)]


class CreateRun(BaseModel):
    model_config = _CLOSED

    profile_id: Id
    selection_id: Id
    # The BLOCKED run of the path's case this run answers (§72), or null for an
    # ordinary run. Stated on every request, as every request field is: an
    # absent key is a malformed body, not a default.
    supersedes: UUID | None
    # Whether the route carries the host's model extension, CP-CF (§6). A
    # route-selection input like the pair above: it changes the resolved node
    # list, so it is inside the route digest the pin carries (invariant 10).
    # Refused `ROUTE_EXTENSION_OWNER_MISSING` on a pathway that does not run
    # every artifact owner CP-CF reads. Strict: `"true"` or `1` is a malformed
    # body, not a coerced yes, because the answer changes what the run pays for.
    model_extension: StrictBool


class RunCreated(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    run_id: UUID
    route_digest: Sha256


class ResearchBriefQuestion(BaseModel):
    """One row of a CP-DR brief's bounded question batch
    (`CP_DR_RESEARCH_BRIEF_V1.md`'s `questions`)."""

    model_config = _CLOSED

    question_id: Id
    question: Text
    decision_relevance: Text
    consumer_module_id: Id
    after_module_id: Id
    evidence_needed: Text
    completion_test: Text


class ResearchBrief(BaseModel):
    """The caller-authored fields of a run-linked CP-DR brief
    (`CP_DR_RESEARCH_BRIEF_V1.md`). The host supplies the rest -- `schema`,
    `mode: linked`, the CP-0 `scope_type`/`scope_key`/`subject_name` identity
    (from the pinned subject) and `source_mode: supplied_only` (invariant 1)
    -- before `bound_research_brief` judges the whole against the pinned
    route and subject; this model states only what the vendor schema leaves
    to the caller. A route that does not carry CP-DR, or one that requires a
    brief this pin omits, still refuses in the store (invariant 4)."""

    model_config = _CLOSED

    decision_context: Text
    as_of_date: Annotated[str, Field(max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")]
    time_horizon: Text
    budget: Literal["standard", "extended"]
    authorization_basis: Text
    exclusions: Text
    questions: Annotated[
        list[ResearchBriefQuestion], Field(max_length=BRIEF_QUESTIONS_MAX)
    ]


class PinRunInput(BaseModel):
    model_config = _CLOSED

    subject: RunSubjectView
    # Required on every advertised research route (`DEEP_RESEARCH`,
    # `LITE_DEEP_RESEARCH`); null elsewhere. Stated on every request, as every
    # request field is: an absent key is a malformed body, not a default.
    research: ResearchBrief | None


class RunInputPinned(BaseModel):
    model_config = _CLOSED

    run_id: UUID
    source_set_version: int
    input_fingerprint: Sha256


class GatePreviewDocument(BaseModel):
    """The exact content an approver is shown, and the digests to submit."""

    model_config = _CLOSED

    run_id: UUID
    gate: Gate
    content: Annotated[str, Field(max_length=PREVIEW_CHARS)]
    preview_sha256: Sha256
    input_fingerprint: Sha256
    observed_at: AwareDatetime


class ApproveGate(BaseModel):
    model_config = _CLOSED

    preview_sha256: Sha256
    input_fingerprint: Sha256


class GateApproved(BaseModel):
    model_config = _CLOSED

    run_id: UUID
    gate: Gate
    preview_sha256: Sha256
    input_fingerprint: Sha256


class StartRun(BaseModel):
    model_config = _CLOSED

    input_fingerprint: Sha256


class RetryRun(BaseModel):
    model_config = _CLOSED

    input_fingerprint: Sha256


class CancelRun(BaseModel):
    # An empty object still states `required`, as the browser DSL emits it.
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra={"required": []}
    )


class RunWork(BaseModel):
    model_config = _CLOSED

    run_id: UUID
    run_status: RunStatus
    work: WorkView


class SignVerdict(BaseModel):
    """A reviewer's verdict document: the seven bindings `read_verdict`
    declares, and nothing else. The shape is closed here; what the document
    *means* -- a naive or future `decided_at`, a passed expiry -- is the
    reader's to decide, so the moments travel as text and are parsed once,
    there. The reviewer's identity is not a field: the host derives it from
    the actor. `evidence_sha256` names the exact evidence identity the
    document was read against (N44): the other six can agree for two
    different snapshots of the same set, build and provider.
    """

    model_config = _CLOSED

    provider: Id
    qualification_set_sha256: Sha256
    build_id: Id
    decided_at: Moment
    expires_at: Moment
    reviewer: Id
    evidence_sha256: Sha256


class VerdictRecorded(BaseModel):
    """The receipt for a recorded verdict: which evidence, who the host bound
    it to, and the currency the reviewer declared."""

    model_config = _CLOSED

    evidence_sha256: Sha256
    reviewer_id: UUID
    decided_at: AwareDatetime
    expires_at: AwareDatetime


class GrantStanding(BaseModel):
    """Give or replace one member's standing. The member is named; the actor
    granting it is derived, and holds ADMIN on the case."""

    model_config = _CLOSED

    user_id: UUID
    standing: Standing


class StandingGranted(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    user_id: UUID
    standing: Standing


class RevokeStanding(BaseModel):
    """The member is in the path; there is nothing else to say."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra={"required": []}
    )


class StandingRevoked(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    user_id: UUID


class WithdrawSource(BaseModel):
    """Invariant 1's second half. The source is in the path."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra={"required": []}
    )


class SourceWithdrawn(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    source_id: UUID


class NarrativeDraft(BaseModel):
    """One span a draft offers: prose, or a reference to a citation the host
    resolves. Exactly one of the two, and a figure names only which citation --
    the document, page and quote are the host's to fill from the record."""

    model_config = _CLOSED

    text: Annotated[str, Field(max_length=NARRATIVE_CHARS)] | None
    figure: NarrativeFigureRef | None


class SaveRevision(BaseModel):
    """A draft over one run's accepted artifacts.

    `expected_revision_id` is the latest revision of that run the client had
    when it composed this draft, null when it saw none: a save that raced
    another save is refused rather than quietly making a second head.
    """

    model_config = _CLOSED

    expected_revision_id: UUID | None
    narrative: Annotated[
        list[Annotated[list[NarrativeDraft], Field(max_length=NARRATIVE_SPANS)]],
        Field(max_length=NARRATIVE_SPANS),
    ]


class RevisionSaved(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    run_id: UUID
    revision_id: UUID
    payload_sha256: Sha256


class SignOpinion(BaseModel):
    """Invariant 5: the signature binds the exact bytes the signer reviewed."""

    model_config = _CLOSED

    payload_sha256: Sha256


class OpinionSigned(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    revision_id: UUID
    payload_sha256: Sha256
    signed_by: UUID


class FreezeDeliverable(BaseModel):
    model_config = _CLOSED

    payload_sha256: Sha256


class DeliverableFrozen(BaseModel):
    model_config = _CLOSED

    case_id: UUID
    revision_id: UUID
    payload_sha256: Sha256
    frozen_by: UUID


class FileDeliverable(BaseModel):
    model_config = _CLOSED

    payload_sha256: Sha256


class DeliverableFiled(BaseModel):
    """The filing's own receipt. The detached one -- renderer and filing link --
    is derived from the audit event this unit writes, so it is read from the
    Committee section rather than answered here."""

    model_config = _CLOSED

    case_id: UUID
    run_id: UUID
    revision_id: UUID
    payload_sha256: Sha256
    filed_by: UUID


V1_COMMANDS: tuple[type[BaseModel], ...] = (
    CreateCase,
    CaseCreated,
    SourcesAdmitted,
    CreateRun,
    RunCreated,
    PinRunInput,
    RunInputPinned,
    GatePreviewDocument,
    ApproveGate,
    GateApproved,
    StartRun,
    RetryRun,
    CancelRun,
    RunWork,
    SignVerdict,
    VerdictRecorded,
    GrantStanding,
    StandingGranted,
    RevokeStanding,
    StandingRevoked,
    WithdrawSource,
    SourceWithdrawn,
    SaveRevision,
    RevisionSaved,
    SignOpinion,
    OpinionSigned,
    FreezeDeliverable,
    DeliverableFrozen,
    FileDeliverable,
    DeliverableFiled,
)


def wire_schema() -> str:
    """The four documents, the page document, `EventName`, the commands and
    `RefusalBody` under `$defs`, keys
    sorted, one definition per line and one trailing newline -- byte for byte
    the committed schema, and a diff that names the model that moved."""
    models: tuple[type[BaseModel], ...] = (
        *V1_DOCUMENTS,
        PageDocument,
        QualificationRead,
        *V1_COMMANDS,
        RefusalBody,
    )
    _, schema = models_json_schema(
        [(model, "validation") for model in models],
        ref_template="#/$defs/{model}",
    )
    definitions = schema.get("$defs", {})
    if set(schema) != {"$defs"} or "EventName" in definitions:
        raise ValueError  # everything is a definition; nothing else is printed
    definitions["EventName"] = TypeAdapter(EventName).json_schema()
    lines = [
        f"  {json.dumps(name)}: "
        + json.dumps(definitions[name], sort_keys=True, ensure_ascii=False)
        for name in sorted(definitions)
    ]
    return '{"$defs": {\n' + ",\n".join(lines) + "\n}}\n"


if __name__ == "__main__":
    sys.stdout.write(wire_schema())
