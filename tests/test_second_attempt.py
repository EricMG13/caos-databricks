"""D30 (N32, the owner's choice; widened by N52): a node whose answer is
refused `HANDOFF_MALFORMED` or `HANDOFF_INCOMPLETE` gets exactly one second
attempt, reserved and priced like
any other, carrying what the checks reported on the refused answer. The ledger
decides it, so a crash between the refusal and the second attempt changes
nothing, and a second refusal stops the run as before.

The flawed answer is the one every live model gave (F111): CP-0 tags a finding
MATERIAL and still writes `qa_status: Passed`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
    MAX_FEEDBACK_CITATIONS,
    MAX_FEEDBACK_MESSAGES,
    HostIdentity,
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


def _with_fixture_marker(body: str) -> str:
    """The same answer declaring a fixture marker: the completeness checker's
    refusal (`HANDOFF_INCOMPLETE`), which the validator does not report."""
    wire = json.loads(body)
    markdown = wire["canonical_markdown"]
    assert "validation_warnings: []\n" in markdown
    wire["canonical_markdown"] = markdown.replace(
        "validation_warnings: []\n",
        'validation_warnings: ["PRESENTATION_FIXTURE"]\n',
        1,
    )
    return json.dumps(wire)


@dataclass
class _Flawed:
    """CanonicalCompletions whose first `bad` CP-0 answers carry the live miss."""

    delegate: CanonicalCompletions
    bad: int = 1
    flaw: Callable[[str], str] = _with_material

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
        return replace(done, content=self.flaw(done.content))


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


def test_an_incomplete_answer_gets_the_second_attempt_too(harness: _Harness) -> None:
    """N52: the completeness checker's refusal earns the same one second
    attempt, carrying the checker's own message (its register or marker)."""
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _Flawed(answers, flaw=_with_fixture_marker)) is None
    assert [_module(prompt) for prompt in answers.prompts[:2]] == ["CP-0", "CP-0"]
    assert SECOND not in answers.prompts[0]
    assert (
        "completeness_check: validation_warnings declares the fixture marker"
        in answers.prompts[1]
    )
    assert _cp0_ledger(harness) == (2, 2, ["HANDOFF_INCOMPLETE"], 1)


def test_one_second_attempt_per_node_whichever_code_refused_first(
    harness: _Harness,
) -> None:
    """A node refused incomplete, then malformed, has spent its one."""
    answers = CanonicalCompletions(harness.source_id)
    flaws = iter((_with_fixture_marker, _with_material))
    flawed = _Flawed(answers, bad=2, flaw=lambda body: next(flaws)(body))
    assert _run(harness, flawed) is RefusalCode.HANDOFF_MALFORMED
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-0"]
    count, reserved, codes, accepted = _cp0_ledger(harness)
    assert (count, reserved, accepted) == (2, 2, 0)
    assert sorted(codes) == ["HANDOFF_INCOMPLETE", "HANDOFF_MALFORMED"]


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
    # N51: which ones, by their place in the list, never by their text.
    assert lines[0].startswith("host citation check: citation 2 of 2 quotes text")
    assert QUOTE not in lines[0] and "never said" not in lines[0]
    assert VENDOR_LINE in [line.split(";")[0] for line in lines[1:]]
    assert all(
        len(line) <= len("validate_handoff: ") + MAX_FEEDBACK_CHARS for line in lines
    )
    assert len(lines) <= MAX_FEEDBACK_MESSAGES
    # A conforming answer has nothing to report.
    assert _feedback(harness, answers.bodies[0]) == ()


def test_retry_feedback_says_why_a_body_is_not_the_transport(
    harness: _Harness,
) -> None:
    """N50: an answer that is not the JSON object gets the host's own reason,
    in the parser's fixed words, never the answer's text."""
    [line] = _feedback(harness, "not json")
    assert line.startswith("host transport check: the answer is not one JSON object")
    [raw] = _feedback(harness, '{"canonical_markdown": "---\nmodule_id: X\n"}')
    assert "control character" in raw and "\\n" in raw and "module_id" not in raw
    [shape] = _feedback(harness, json.dumps({"canonical_markdown": "x"}))
    assert shape.startswith("host transport check: the answer is not the JSON object")


def test_retry_feedback_names_at_most_the_first_twenty_failed_citations(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, answers) is None
    wire = json.loads(answers.bodies[0])
    wire["citations"] = [
        {"source_id": str(harness.source_id), "page": 1, "matched_text": f"absent{n}"}
        for n in range(MAX_FEEDBACK_CITATIONS + 10)
    ]
    [line] = _feedback(harness, json.dumps(wire))
    total = MAX_FEEDBACK_CITATIONS + 10
    assert f", {MAX_FEEDBACK_CITATIONS} and 10 more of {total}" in line
    assert "citations 1, 2, 3" in line


def _skill(harness: _Harness) -> bytes:
    from caos.methodology.bundle import assemble_authority
    from caos.methodology.executor import SKILL

    return assemble_authority(harness.bundle, "CP-0").files[SKILL]


def test_retry_feedback_carries_the_completeness_and_t8_checks_too(
    harness: _Harness,
) -> None:
    """A second attempt told only the first check it failed trips over the
    next: the one live answer to clear every earlier check on 23 September
    (GPT-5.6 luna) failed the vendor's completeness checker and its T8 parser.
    Their own messages ride along, labelled by checker, as the validator's do."""
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, answers) is None
    wire = json.loads(answers.bodies[0])
    markdown = wire["canonical_markdown"]
    contract = cached_contract(harness.bundle)
    header = "| " + " | ".join(contract.navigation.NEW_HEADERS) + " |"
    start = markdown.index(header)
    end = markdown.index("\n\n", start)
    doubled = markdown[:end] + "\n\n" + markdown[start:end] + markdown[end:]
    marked = doubled.replace(
        "validation_warnings: []", 'validation_warnings: ["PRESENTATION_FIXTURE"]', 1
    )
    assert marked != doubled
    wire["canonical_markdown"] = marked
    lines = retry_feedback(
        contract,
        catalog(harness.bundle),
        _identity_cp0(),
        json.dumps(wire),
        skill=_skill(harness),
    )
    assert any(line.startswith("navigation: ") for line in lines), lines
    assert any(
        line.startswith("completeness_check: ") and "PRESENTATION_FIXTURE" in line
        for line in lines
    ), lines


def _identity_cp0() -> HostIdentity:
    from canonical_fixtures import identity

    return identity("CP-0")
