"""D30 (N32, the owner's choice): a node whose answer is refused
`HANDOFF_MALFORMED` gets exactly one second attempt, reserved and priced like
any other, carrying what the checks reported on the refused answer. The ledger
decides it, so a crash between the refusal and the second attempt changes
nothing, and a second refusal stops the run as before.

The flawed answer is the one every live model gave (F111): CP-0 tags a finding
MATERIAL and still writes `qa_status: Passed`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

import pytest
from canonical_fixtures import QUOTE, CanonicalCompletions
from conftest import priced
from test_canonical_execution import _node, harness, route
from test_execution_freshness import _Harness
from test_loop_charges import ESTIMATE

from caos.graph import runtime
from caos.graph.runtime import Execution, run_route
from caos.methodology.canonical import second_attempt_due
from caos.methodology.handoff import (
    MAX_FEEDBACK_CHARS,
    MAX_FEEDBACK_MESSAGES,
    retry_feedback,
)
from caos.methodology.runner import ModuleProvider
from caos.methodology.vendor import cached_contract, catalog
from caos.provider import Completion, CompletionProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import connect
from caos.store.outcomes import NodeAttempt, node_attempts

__all__ = ["harness", "route"]

SECOND = "--- SECOND ATTEMPT"
VENDOR_LINE = "validate_handoff: a MATERIAL finding requires qa_status Restricted"


def _module(prompt: str) -> str:
    return prompt.split(maxsplit=6)[5]


def _with_material(body: str) -> str:
    """The same answer with a MATERIAL finding row, `qa_status` left Passed."""
    wire = json.loads(body)
    table = (
        "| ID | Type | Severity | Affected modules | Remediation |\n"
        "|---|---|---|---|---|\n"
        "| G-1 | SOURCE_GAP | MATERIAL | CP-5 | Obtain it |\n\n"
    )
    markdown = wire["canonical_markdown"]
    assert "## Gaps & Conflicts\n\n" in markdown
    wire["canonical_markdown"] = markdown.replace(
        "## Gaps & Conflicts\n\n", "## Gaps & Conflicts\n\n" + table, 1
    )
    return json.dumps(wire)


@dataclass
class _Flawed:
    """CanonicalCompletions whose first `bad` CP-0 answers carry the live miss."""

    delegate: CanonicalCompletions
    bad: int = 1

    @property
    def model(self) -> str:
        return self.delegate.model

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return self.delegate.request_bytes(prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        done = self.delegate.complete(prompt, json_object=json_object)
        if _module(prompt) != "CP-0" or self.bad <= 0:
            return done
        self.bad -= 1
        assert done.content is not None
        return replace(done, content=_with_material(done.content))


def _provider(harness: _Harness, completions: CompletionProvider) -> ModuleProvider:
    return ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        harness.route,
        harness.run_id,
    )


def _run(harness: _Harness, completions: CompletionProvider) -> RefusalCode | None:
    try:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(
                _provider(harness, completions), priced(ESTIMATE), harness.bundle
            ),
        )
    except Refusal as refused:
        assert refused.__cause__ is None and refused.__context__ is None
        return refused.code
    return None


def _cp0_ledger(harness: _Harness) -> tuple[int, int, list[str], int]:
    """CP-0's attempts, reservations, refusal codes and accepted artifacts."""
    node = _node(harness, "CP-0").route_node_id
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(b.attempt_id), count(a.attempt_id)"
            " FROM run_attempts t"
            " LEFT JOIN budget_reservations b USING (attempt_id)"
            " LEFT JOIN artifacts a USING (attempt_id)"
            " WHERE t.run_id=%s AND t.route_node_id=%s",
            (harness.run_id, node),
        ).fetchone()
        codes = observer.execute(
            "SELECT r.code FROM attempt_refusals r JOIN run_attempts t"
            " USING (attempt_id) WHERE t.run_id=%s AND t.route_node_id=%s",
            (harness.run_id, node),
        ).fetchall()
    assert row is not None
    return int(row[0]), int(row[1]), [str(c[0]) for c in codes], int(row[2])


def test_a_refused_answer_gets_one_second_attempt_that_carries_what_failed(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _Flawed(answers)) is None
    called = [_module(prompt) for prompt in answers.prompts]
    assert called == ["CP-0", "CP-0", "CP-L10", "CP-5"]
    first, second = answers.prompts[0], answers.prompts[1]
    assert SECOND not in first
    assert second.index(SECOND) > second.index("--- CP-0 FINAL CHECK")
    assert VENDOR_LINE in second
    # The block is folded into the tag: the refused answer could not have
    # known the markers around the lines that quote it.
    assert (
        first.split("--- HOST-OWNED FRONT MATTER ")[1][:16]
        != (second.split("--- HOST-OWNED FRONT MATTER ")[1][:16])
    )
    # Two attempts, each reserved; one refused, one accepted.
    assert _cp0_ledger(harness) == (2, 2, ["HANDOFF_MALFORMED"], 1)


def test_a_second_refusal_stops_the_run_with_no_third_attempt(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _Flawed(answers, bad=2)) is RefusalCode.HANDOFF_MALFORMED
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-0"]
    assert _cp0_ledger(harness) == (
        2,
        2,
        ["HANDOFF_MALFORMED", "HANDOFF_MALFORMED"],
        0,
    )
    # An operator's retry after that is an ordinary attempt: the one second
    # attempt is spent, so nothing is carried and nothing is repeated.
    assert _run(harness, answers) is None
    assert SECOND not in answers.prompts[2]
    assert _cp0_ledger(harness)[0] == 3


class _Crash(BaseException):
    """The process dying between the refusal and the second attempt."""


def test_the_second_attempt_survives_a_crash_after_the_refusal(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    flawed = _Flawed(answers)

    def crash(*_args: object) -> bool:
        raise _Crash

    monkeypatch.setattr(runtime, "_second_due", crash)
    with pytest.raises(_Crash):
        _run(harness, flawed)
    monkeypatch.undo()
    assert _cp0_ledger(harness) == (1, 1, ["HANDOFF_MALFORMED"], 0)
    cp0 = _node(harness, "CP-0").route_node_id
    assert second_attempt_due(harness.conn, run_id=harness.run_id, route_node_id=cp0)
    # Resumed: the ledger, not the dead frame, says the next attempt is the
    # second, so it carries the vendor's message and the route completes.
    assert _run(harness, flawed) is None
    assert VENDOR_LINE in answers.prompts[1]
    assert _cp0_ledger(harness) == (2, 2, ["HANDOFF_MALFORMED"], 1)


def test_any_other_refusal_gets_no_second_attempt(harness: _Harness) -> None:
    def tamper(fields: dict[str, Any]) -> dict[str, Any]:
        return {**fields, "issuer_name": "Someone Else"}

    answers = CanonicalCompletions(harness.source_id, mutate=tamper)
    assert _run(harness, answers) is RefusalCode.HANDOFF_IDENTITY_MISMATCH
    assert len(answers.prompts) == 1
    assert _cp0_ledger(harness) == (1, 1, ["HANDOFF_IDENTITY_MISMATCH"], 0)


def test_the_ledger_read_orders_a_nodes_attempts_oldest_first(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _Flawed(answers)) is None
    with connect(harness.url) as observer:
        found = node_attempts(
            observer, harness.run_id, _node(harness, "CP-0").route_node_id
        )
    assert [a.refusal for a in found] == ["HANDOFF_MALFORMED", None]
    assert all(isinstance(a, NodeAttempt) for a in found)
    assert all(a.diagnostic_sha256 is not None for a in found)
    # Spent: the node's latest attempt is not a refusal, so nothing is due.
    cp0 = _node(harness, "CP-0").route_node_id
    assert not second_attempt_due(
        harness.conn, run_id=harness.run_id, route_node_id=cp0
    )


def _feedback(harness: _Harness, body: str) -> tuple[str, ...]:
    from canonical_fixtures import identity

    return retry_feedback(
        cached_contract(harness.bundle), catalog(harness.bundle), identity("CP-0"), body
    )


def test_retry_feedback_reports_the_vendors_message_and_the_quote_count(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, answers) is None
    wire = json.loads(_with_material(answers.bodies[0]))  # CP-0's, flawed
    wire["citations"].append(
        {"source_id": str(harness.source_id), "page": 1, "matched_text": "never said"}
    )
    lines = _feedback(harness, json.dumps(wire))
    assert lines[0].startswith("host citation check: 1 of 2 citations")
    assert QUOTE not in lines[0]
    assert VENDOR_LINE in [line.split(";")[0] for line in lines[1:]]
    assert all(
        len(line) <= len("validate_handoff: ") + MAX_FEEDBACK_CHARS for line in lines
    )
    assert len(lines) <= MAX_FEEDBACK_MESSAGES
    # A conforming answer has nothing to report.
    assert _feedback(harness, answers.bodies[0]) == ()


def test_retry_feedback_says_nothing_about_a_body_that_is_not_a_transport(
    harness: _Harness,
) -> None:
    assert _feedback(harness, "not json") == ()
    assert _feedback(harness, json.dumps({"canonical_markdown": "x"})) == ()
