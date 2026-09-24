"""Typed refusals. The code travels; the offending text never does.

Error handling is ~2x worse in agent-written code (docs/AI_CODE_QUALITY.md
section 1) and the failure is always the same shape: an exception string
carrying a document's contents, a vendor's name or a filesystem path into a log
line or an HTTP body. A Refusal carries a code from a closed set and nothing
else, so there is no string to leak.
"""

from __future__ import annotations

from enum import StrEnum


class RefusalCode(StrEnum):
    """Every reason the host declines. Public-safe by construction."""

    BOUNDARY_TEXT_INVALID = "BOUNDARY_TEXT_INVALID"
    BOUNDARY_TEXT_TOO_LONG = "BOUNDARY_TEXT_TOO_LONG"
    BLOB_DIGEST_MISMATCH = "BLOB_DIGEST_MISMATCH"
    BLOB_NOT_FOUND = "BLOB_NOT_FOUND"
    BLOB_ADDRESS_INVALID = "BLOB_ADDRESS_INVALID"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUN_NOT_RUNNING = "RUN_NOT_RUNNING"
    # The successor link (§72): only a BLOCKED run of the same case can be
    # answered, and by one run.
    RUN_NOT_BLOCKED = "RUN_NOT_BLOCKED"
    RUN_ALREADY_SUPERSEDED = "RUN_ALREADY_SUPERSEDED"
    # Phase 4 Task 4.3 (worker lease and terminal decision).
    LEASE_NOT_HELD = "LEASE_NOT_HELD"
    RUN_CANCEL_REQUESTED = "RUN_CANCEL_REQUESTED"
    RUN_NODES_UNACCEPTED = "RUN_NODES_UNACCEPTED"
    RUN_TERMINAL_STALE = "RUN_TERMINAL_STALE"
    ATTEMPT_NOT_FOUND = "ATTEMPT_NOT_FOUND"
    ATTEMPT_LIMIT_REACHED = "ATTEMPT_LIMIT_REACHED"
    CALL_OUTCOME_INVALID = "CALL_OUTCOME_INVALID"
    CALL_OUTCOME_CONFLICT = "CALL_OUTCOME_CONFLICT"
    CALL_OUTCOME_LEGACY = "CALL_OUTCOME_LEGACY"
    # A charge with no stored body: the answer was paid for and cannot be read.
    CALL_OUTCOME_UNEXPLAINED = "CALL_OUTCOME_UNEXPLAINED"
    NODE_ALREADY_ACCEPTED = "NODE_ALREADY_ACCEPTED"
    MONEY_NOT_DECIMAL = "MONEY_NOT_DECIMAL"
    MONEY_INVALID = "MONEY_INVALID"
    BUDGET_ALREADY_RESERVED = "BUDGET_ALREADY_RESERVED"
    BUDGET_NOT_RESERVED = "BUDGET_NOT_RESERVED"
    BUDGET_CEILING_REACHED = "BUDGET_CEILING_REACHED"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_CALL_INVALID = "PROVIDER_CALL_INVALID"
    # A module's whole context exceeds the request bound; nothing is cut (§45.3).
    CONTEXT_OVER_CEILING = "CONTEXT_OVER_CEILING"
    # One upstream handoff exceeds its own declared section bound; nothing is cut.
    UPSTREAM_SECTION_OVER_CEILING = "UPSTREAM_SECTION_OVER_CEILING"
    # The request an attempt is about to send prices above what that attempt
    # reserved: the context is unchanged, the reservation no longer covers it.
    RESERVATION_BELOW_REQUEST = "RESERVATION_BELOW_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_OUTPUT_TRUNCATED = "PROVIDER_OUTPUT_TRUNCATED"
    PROVIDER_REFUSED = "PROVIDER_REFUSED"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    AUTHORITY_BYTES_MISMATCH = "AUTHORITY_BYTES_MISMATCH"
    AUTHORITY_MODULE_UNKNOWN = "AUTHORITY_MODULE_UNKNOWN"
    HANDOFF_MALFORMED = "HANDOFF_MALFORMED"
    HANDOFF_BLOCKED = "HANDOFF_BLOCKED"
    HANDOFF_IDENTITY_MISMATCH = "HANDOFF_IDENTITY_MISMATCH"
    HANDOFF_INCOMPLETE = "HANDOFF_INCOMPLETE"
    HANDOFF_UNDECLARED_FIELD = "HANDOFF_UNDECLARED_FIELD"
    HANDOFF_MODULE_UNSUPPORTED = "HANDOFF_MODULE_UNSUPPORTED"
    ARTIFACT_RECORD_MISMATCH = "ARTIFACT_RECORD_MISMATCH"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    # Phase 4 Task 4.1: an undeclared path or method under /api/.
    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    # Phase 4 Task 4.5: the edge guard (decisions 3 and 5); the last is boot-only.
    EDGE_NOT_TRUSTED = "EDGE_NOT_TRUSTED"
    ORIGIN_REFUSED = "ORIGIN_REFUSED"
    EDGE_CONFIG_INVALID = "EDGE_CONFIG_INVALID"
    # CF-051: every in-flight request slot is held; waiting is what repairs it.
    CONCURRENCY_LIMIT_REACHED = "CONCURRENCY_LIMIT_REACHED"
    # An unhandled exception, answered by the guard in the constant body.
    INTERNAL_FAULT = "INTERNAL_FAULT"
    NOT_AUTHORISED = "NOT_AUTHORISED"
    # Phase 4 Task 4.2: governed commands (decisions 5 to 8).
    REQUEST_INVALID = "REQUEST_INVALID"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    RUN_INPUT_NOT_PINNED = "RUN_INPUT_NOT_PINNED"
    RUN_ALREADY_STARTED = "RUN_ALREADY_STARTED"
    RUN_NOT_STOPPED = "RUN_NOT_STOPPED"
    ROUTE_NOT_ENABLED = "ROUTE_NOT_ENABLED"
    COMMAND_EXPECTATION_STALE = "COMMAND_EXPECTATION_STALE"
    METHODOLOGY_INPUT_INVALID = "METHODOLOGY_INPUT_INVALID"
    FORECAST_DRIVER_NOT_READY = "FORECAST_DRIVER_NOT_READY"
    DELIVERABLE_PAYLOAD_INVALID = "DELIVERABLE_PAYLOAD_INVALID"
    DELIVERABLE_NOT_FOUND = "DELIVERABLE_NOT_FOUND"
    NARRATIVE_FIGURE_UNREFERENCED = "NARRATIVE_FIGURE_UNREFERENCED"
    NARRATIVE_REFERENCE_INVALID = "NARRATIVE_REFERENCE_INVALID"
    DELIVERABLE_UNCITED_FIGURE = "DELIVERABLE_UNCITED_FIGURE"
    DELIVERABLE_MARKDOWN_UNSUPPORTED = "DELIVERABLE_MARKDOWN_UNSUPPORTED"
    DELIVERABLE_NOT_SIGNED = "DELIVERABLE_NOT_SIGNED"
    DELIVERABLE_NOT_FROZEN = "DELIVERABLE_NOT_FROZEN"
    DELIVERABLE_MOVED_SINCE_SIGNING = "DELIVERABLE_MOVED_SINCE_SIGNING"
    DELIVERABLE_ALREADY_FILED = "DELIVERABLE_ALREADY_FILED"
    DELIVERABLE_ALREADY_FROZEN = "DELIVERABLE_ALREADY_FROZEN"
    # `0029_one_opinion_per_signer`: this approver has already signed this
    # revision. Its own code so a second press is not read as a wrong binding.
    DELIVERABLE_ALREADY_SIGNED = "DELIVERABLE_ALREADY_SIGNED"
    APPROVER_NOT_INDEPENDENT = "APPROVER_NOT_INDEPENDENT"
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    SOURCE_PACK_EMPTY = "SOURCE_PACK_EMPTY"
    SOURCE_NOT_READABLE = "SOURCE_NOT_READABLE"
    SOURCE_ENCRYPTED = "SOURCE_ENCRYPTED"
    SOURCE_HAS_NO_TEXT = "SOURCE_HAS_NO_TEXT"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_EXTRACTION_TIMEOUT = "SOURCE_EXTRACTION_TIMEOUT"
    SOURCE_IDENTITY_INVALID = "SOURCE_IDENTITY_INVALID"
    EVIDENCE_NOT_AVAILABLE = "EVIDENCE_NOT_AVAILABLE"
    # A live source whose stored block count this build's `GROUP_WIDTH` no
    # longer reproduces, or whose token-packed blocks no longer tile its lines
    # (CF-013): the host's own rows do not read as its packing wrote them.
    # Distinct from EVIDENCE_NOT_AVAILABLE because pinning a live source cannot
    # clear it -- the source is live -- and re-admitting it under this build can.
    EVIDENCE_PACKING_MISMATCH = "EVIDENCE_PACKING_MISMATCH"
    # §95: CP-0's `Source files to attach` cell for a consumer names some
    # pinned members and something the pin does not carry, or one name that two
    # members answer to. Neither the readable half nor the whole pin is what
    # the gate said, so the node is refused before any attempt. Distinct from
    # EVIDENCE_NOT_AVAILABLE because every pinned source is live; what clears
    # it is a successor run whose gate writes a cell the host can read.
    EVIDENCE_DEMAND_UNRESOLVED = "EVIDENCE_DEMAND_UNRESOLVED"
    # Phase 4 Task 4.4c: an evidence page the caller may not or cannot read.
    PAGE_NOT_AVAILABLE = "PAGE_NOT_AVAILABLE"
    CITATION_NOT_LOCATED = "CITATION_NOT_LOCATED"
    CITATION_AMBIGUOUS = "CITATION_AMBIGUOUS"
    CITATION_NOT_DELIVERED = "CITATION_NOT_DELIVERED"
    ROUTE_PROFILE_UNKNOWN = "ROUTE_PROFILE_UNKNOWN"
    ROUTE_SELECTION_UNKNOWN = "ROUTE_SELECTION_UNKNOWN"
    ROUTE_EXTENSION_OWNER_MISSING = "ROUTE_EXTENSION_OWNER_MISSING"
    ROUTE_HAS_A_CYCLE = "ROUTE_HAS_A_CYCLE"
    ROUTE_DUPLICATE_MODULE = "ROUTE_DUPLICATE_MODULE"
    ROUTE_EDGE_UNSUPPORTED = "ROUTE_EDGE_UNSUPPORTED"
    ROUTE_ALREADY_PINNED = "ROUTE_ALREADY_PINNED"
    ROUTE_IDENTITY_INVALID = "ROUTE_IDENTITY_INVALID"
    ROUTE_PIN_TOO_LATE = "ROUTE_PIN_TOO_LATE"
    RUN_INPUT_INVALID = "RUN_INPUT_INVALID"
    RUN_INPUT_ALREADY_PINNED = "RUN_INPUT_ALREADY_PINNED"
    RUN_INPUT_TOO_LATE = "RUN_INPUT_TOO_LATE"
    GATE_APPROVAL_MISMATCH = "GATE_APPROVAL_MISMATCH"
    QUALIFICATION_SET_EMPTY = "QUALIFICATION_SET_EMPTY"
    QUALIFICATION_KEY_UNANSWERABLE = "QUALIFICATION_KEY_UNANSWERABLE"
    QUALIFICATION_SET_AMBIGUOUS = "QUALIFICATION_SET_AMBIGUOUS"
    # A key that cannot name one answer: a register key whose row key selects
    # rows rather than a row. Apart from a malformed manifest because the remedy
    # is different -- name the row, do not fix the file's shape.
    QUALIFICATION_KEY_AMBIGUOUS = "QUALIFICATION_KEY_AMBIGUOUS"
    QUALIFICATION_RUN_MISSING = "QUALIFICATION_RUN_MISSING"
    QUALIFICATION_SET_FILE_INVALID = "QUALIFICATION_SET_FILE_INVALID"
    QUALIFICATION_SET_PATH_ESCAPES = "QUALIFICATION_SET_PATH_ESCAPES"
    QUALIFICATION_SET_OVER_CEILING = "QUALIFICATION_SET_OVER_CEILING"
    ORCHESTRATION_NOTHING_TO_PROVE = "ORCHESTRATION_NOTHING_TO_PROVE"
    ORCHESTRATION_ROUTE_NOT_PINNED = "ORCHESTRATION_ROUTE_NOT_PINNED"
    ORCHESTRATION_NODE_NOT_IN_ROUTE = "ORCHESTRATION_NODE_NOT_IN_ROUTE"
    ORCHESTRATION_BUILD_MOVED = "ORCHESTRATION_BUILD_MOVED"
    ORCHESTRATION_SOURCE_NOT_PINNED = "ORCHESTRATION_SOURCE_NOT_PINNED"
    ORCHESTRATION_CITATION_LOST = "ORCHESTRATION_CITATION_LOST"
    ORCHESTRATION_ARTIFACT_UNREADABLE = "ORCHESTRATION_ARTIFACT_UNREADABLE"
    VERDICT_INCOMPLETE = "VERDICT_INCOMPLETE"
    VERDICT_BINDING_INVALID = "VERDICT_BINDING_INVALID"
    VERDICT_UNDECLARED_FIELD = "VERDICT_UNDECLARED_FIELD"
    VERDICT_EXPIRED = "VERDICT_EXPIRED"
    # The one-verdict constraint, distinguished from a wrong binding so a
    # retrying client is not told to correct a document that was right.
    VERDICT_ALREADY_RECORDED = "VERDICT_ALREADY_RECORDED"
    # F17's producer: qualification evidence the caller may not sign, or
    # that the store does not hold. One answer for both, as CASE_NOT_FOUND is.
    QUALIFICATION_EVIDENCE_NOT_FOUND = "QUALIFICATION_EVIDENCE_NOT_FOUND"
    STORE_SCHEMA_DRIFT = "STORE_SCHEMA_DRIFT"
    STORE_NOT_TRANSACTIONAL = "STORE_NOT_TRANSACTIONAL"
    STORE_NOT_CONFIGURED = "STORE_NOT_CONFIGURED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    # The workspace that names the caller did not answer (F43); the caller is
    # not refused, the process could not ask.
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
    # Every stream slot is taken. Transient by the D3 question -- the identical
    # request later, with nobody doing anything in between, plausibly succeeds,
    # because a watcher only has to close a tab.
    STREAM_LIMIT_REACHED = "STREAM_LIMIT_REACHED"


class Refusal(Exception):
    """A declined operation. Its only payload is the code."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code.value)
        self.code = code

    def __repr__(self) -> str:
        return f"Refusal({self.code.value})"
