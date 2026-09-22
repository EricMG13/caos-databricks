"""Event names and resume markers (brief 4.4, decisions 2 and 3).

The mapping every stored event reaches the browser through, the composite
marker a reconnect resumes from, and the audit read the case stream polls.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

import pytest

from caos.api.events import STREAM_NAMES, Marker, parse_marker
from caos.api.wire import EventName
from caos.store import StoreConnection
from caos.store.audit import GovernedAction, actions_after, governed_write
from caos.store.events import RunEvent
from caos.store.gates import Gate
from caos.store.members import Standing, grant

SERVER = Path(__file__).resolve().parents[1] / "caos"


def _governed_actions() -> set[str]:
    """Every audit action the server can write, read from its source.

    `GovernedAction` takes the action as a string, so the closed set is the
    literal each call site passes; the one built at run time is expanded over
    the enum it formats. Anything else fails, so a new call site cannot slip
    past the mapping by being written differently.
    """
    found: set[str] = set()
    for path in sorted(SERVER.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "GovernedAction"
            ):
                continue
            [value] = [k.value for k in node.keywords if k.arg == "action"] or [
                node.args[2]
            ]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(value.value)
                continue
            assert isinstance(value, ast.JoinedStr), (path, node.lineno)
            prefix = value.values[0]
            assert isinstance(prefix, ast.Constant), (path, node.lineno)
            assert prefix.value == "GATE_RELEASED:", (path, node.lineno)
            found.update(f"GATE_RELEASED:{gate.value}" for gate in Gate)
    return found


def test_every_run_event_and_audit_action_maps_to_one_stream_name_or_is_declared_silent() -> (  # noqa: E501 -- the brief's name
    None
):
    run_events = {event.value for event in RunEvent}
    actions = _governed_actions()
    assert "SOURCE_WITHDRAWN" in actions and "DELIVERABLE_FILED" in actions
    assert run_events.isdisjoint(actions)

    assert set(STREAM_NAMES) == run_events | actions
    assert {name for name in STREAM_NAMES.values() if name is not None} == set(
        get_args(EventName)
    )
    assert {k: v for k, v in STREAM_NAMES.items() if k in run_events} == {
        "ROUTE_PINNED": "run_progress",
        "INPUT_PINNED": "run_progress",
        "ATTEMPT_STARTED": "run_progress",
        "CALL_OUTCOME_RECORDED": "run_progress",
        "ATTEMPT_ACCEPTED": "handoff_accepted",
        "RUN_COMPLETE": "run_terminal",
        "RUN_FAILED": "run_terminal",
        "RUN_BLOCKED": "run_terminal",
        "RUN_CANCELLED": "run_terminal",
    }
    assert STREAM_NAMES["SOURCE_WITHDRAWN"] == "sources_changed"
    assert STREAM_NAMES["GATE_RELEASED:SOURCE_SET"] == "runs_changed"
    assert STREAM_NAMES["SOURCES_ADMITTED"] == "sources_changed"
    for command in ("RUN_CREATED", "RUN_INPUT_PINNED", "RUN_ENQUEUED", "RUN_REQUEUED"):
        assert STREAM_NAMES[command] == "runs_changed"
    assert STREAM_NAMES["RUN_CANCEL_REQUESTED"] == "runs_changed"
    for action in ("OPINION_SIGNED", "DELIVERABLE_FROZEN", "DELIVERABLE_FILED"):
        assert STREAM_NAMES[action] == "filing_changed"
    for silent in (
        "CASE_CREATED",
        "REVISION_SAVED",
        "STANDING_GRANTED",
        "STANDING_REVOKED",
    ):
        assert STREAM_NAMES[silent] is None
    with pytest.raises(TypeError):
        STREAM_NAMES["SOURCE_WITHDRAWN"] = None  # type: ignore[index]


@pytest.mark.parametrize(
    "marker",
    [
        "x",
        "1",
        "1.1.1",
        "-1.0",
        "01.0",
        "1.00",
        " 1.1",
        "1.1 ",
        "¹.1",
        "1.²",
        "\uff11.1",  # a fullwidth digit one
        "1" * 17 + ".0",
        "0." + "1" * 17,
        "3.0",
        "0.2",
        "",
    ],
)
def test_a_malformed_superscript_oversized_or_future_marker_resumes_from_the_heads(
    marker: str,
) -> None:
    heads = Marker(audit_seq=2, run_seq=1)

    assert parse_marker(marker, heads) == heads
    assert parse_marker(None, heads) == heads
    assert parse_marker("1.0", heads) == Marker(1, 0)
    assert parse_marker("9999999999999999.0", Marker(10**16, 0)) == Marker(
        9999999999999999, 0
    )


def test_actions_after_reads_the_case_chain_strictly_after_a_position(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    actor = uuid4()
    grant(conn, case_id=case_id, user_id=actor, standing=Standing.ADMIN)
    conn.commit()
    for action in ("SOURCE_WITHDRAWN", "OPINION_SIGNED"):
        governed_write(
            conn,
            GovernedAction(case_id, actor, action, Standing.READER, {}),
            lambda _conn: None,
        )

    assert actions_after(conn, case_id=case_id, seq=0) == [
        (1, "SOURCE_WITHDRAWN"),
        (2, "OPINION_SIGNED"),
    ]
    assert actions_after(conn, case_id=case_id, seq=1) == [(2, "OPINION_SIGNED")]
    assert actions_after(conn, case_id=case_id, seq=2) == []
    assert actions_after(conn, case_id=uuid4(), seq=0) == []
