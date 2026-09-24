"""What a case stream calls each stored event, and where a resume starts.

Brief 4.4 decisions 2 and 3. A frame names which sections to refetch and
nothing else, so every `RunEvent` and every audit action the server writes maps
to one closed `EventName` -- or is declared silent, because the section it
would refresh is not enabled. A test reads the server's `GovernedAction` call
sites and refuses a mapping that misses one.

The cursor is composite, `{audit_seq}.{run_seq}`: the case's audit chain and
the named run's events are numbered separately and have no common order.

No round trip: `IO_BUDGET = 0`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from caos.api.wire import EventName
from caos.store.events import RunEvent

IO_BUDGET = 0

STREAM_NAMES: Mapping[str, EventName | None] = MappingProxyType(
    {
        RunEvent.ROUTE_PINNED.value: "run_progress",
        RunEvent.INPUT_PINNED.value: "run_progress",
        RunEvent.ATTEMPT_STARTED.value: "run_progress",
        RunEvent.CALL_OUTCOME_RECORDED.value: "run_progress",
        RunEvent.ATTEMPT_ACCEPTED.value: "handoff_accepted",
        RunEvent.RUN_COMPLETE.value: "run_terminal",
        RunEvent.RUN_FAILED.value: "run_terminal",
        RunEvent.RUN_BLOCKED.value: "run_terminal",
        RunEvent.RUN_CANCELLED.value: "run_terminal",
        # CF-044: the run itself stays RUNNING (parked, not ended), so this
        # is a refetch like any other in-flight update, not a terminal frame.
        RunEvent.RUN_PARKED.value: "run_progress",
        "SOURCE_WITHDRAWN": "sources_changed",
        "SOURCES_ADMITTED": "sources_changed",
        "GATE_RELEASED:SOURCE_SET": "runs_changed",
        "GATE_RELEASED:RESEARCH_PLAN": "runs_changed",
        "RUN_CREATED": "runs_changed",
        "RUN_INPUT_PINNED": "runs_changed",
        "RUN_ENQUEUED": "runs_changed",
        "RUN_REQUEUED": "runs_changed",
        "RUN_CANCEL_REQUESTED": "runs_changed",
        # Written before any case stream can exist: the Directory is not a stream.
        "CASE_CREATED": None,
        # Saving creates a new exact selection; filing changes the selection on screen.
        "REVISION_SAVED": None,
        "OPINION_SIGNED": "filing_changed",
        "DELIVERABLE_FROZEN": "filing_changed",
        "DELIVERABLE_FILED": "filing_changed",
        # Standing changes what a member may do, not what any section shows:
        # the browser learns its own standing by refetching, and a revoked
        # member's stream closes on the standing check rather than on a frame.
        "STANDING_GRANTED": None,
        "STANDING_REVOKED": None,
    }
)

# Checked as ASCII: `[0-9]`, never `\d`, which also matches superscripts and
# other scripts' digits. Sixteen digits keep either half inside a bigint.
_MARKER = re.compile(r"(0|[1-9][0-9]{0,15})\.(0|[1-9][0-9]{0,15})", re.ASCII)


@dataclass(frozen=True, slots=True)
class Marker:
    """A position in both of a stream's sequences: everything at or before it
    in each has been delivered or was silent."""

    audit_seq: int
    run_seq: int

    def __str__(self) -> str:
        return f"{self.audit_seq}.{self.run_seq}"


def parse_marker(value: str | None, heads: Marker) -> Marker:
    """The client's `Last-Event-ID`, or `heads` when it cannot be used.

    A browser-supplied string: missing, malformed, oversized or ahead of what
    the store holds all resume from the heads rather than refusing, because a
    client can only clear a bad marker by losing its storage, and the browser
    refetches its documents on every `open` anyway.
    """
    matched = None if value is None else _MARKER.fullmatch(value)
    if matched is None:
        return heads
    marker = Marker(int(matched[1]), int(matched[2]))
    if marker.audit_seq > heads.audit_seq or marker.run_seq > heads.run_seq:
        return heads
    return marker
