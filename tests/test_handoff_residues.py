"""Residues of the guided-retry feedback code (N141, N143, N218, F651).

One test module for a batch of small repairs in `handoff.py` and `canonical.py`:
a blob-store outage is not a record mismatch (N141); a register is matched to its
pipe table by the widths the vendor read, not by padded content (N143 a); the
owner lines bound each item and name a module once (N143 b); an answer is parsed
and bounded once per comparison (N218 3, 6); the keep line holds only the bounds
that guard the vendor's slow expressions (N218 5, owner ruling R9); and an answer
the vendor's validator cannot read says so (N218 8).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from canonical_fixtures import BUNDLE, CONTRACT, identity

from caos.methodology import handoff
from caos.methodology.bundle import assemble_authority
from caos.methodology.canonical import _owner_lines, owner_messages
from caos.methodology.executor import SKILL
from caos.methodology.handoff import (
    answer_citations,
    answer_markdown,
    answer_shrank,
    feedback_lines,
    kept_registers_line,
)
from caos.methodology.vendor import catalog
from caos.methodology.verification import CREDIT_SCREEN_SELECTION, OwnerGap
from caos.refusals import Refusal, RefusalCode

CITATION = {"source_id": str(UUID(int=1)), "page": 1, "matched_text": "value 2"}
HEADER6 = ("Factor", "Evidence", "Assessment", "Risk Mechanic", "Credit", "Trace")


def _body(markdown: str) -> str:
    return json.dumps({"canonical_markdown": markdown, "citations": [CITATION]})


def _table(rows: list[str], header: tuple[str, ...] = HEADER6) -> str:
    return (
        "| "
        + " | ".join(header)
        + " |\n"
        + "|---" * len(header)
        + "|\n"
        + "\n".join(rows)
        + "\n"
    )


def _skill(module: str) -> bytes:
    return assemble_authority(BUNDLE, module).files[SKILL]


def _cp3c_feedback(markdown: str) -> tuple[str, ...]:
    ident = replace(identity("CP-0"), module_id="CP-3C")
    return feedback_lines(
        CONTRACT, catalog(BUNDLE), ident, _body(markdown), skill=_skill("CP-3C")
    )


# --- N141 -------------------------------------------------------------------


def _raising(error: BaseException) -> Callable[[], int]:
    def call() -> int:
        raise error

    return call


def test_a_store_outage_inside_or_refuse_stays_store_unavailable() -> None:
    with pytest.raises(Refusal) as caught:
        handoff._or_refuse(
            RefusalCode.ARTIFACT_RECORD_MISMATCH,
            _raising(Refusal(RefusalCode.STORE_UNAVAILABLE)),
        )
    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE


@pytest.mark.parametrize(
    "error",
    [
        ValueError("vendor text"),
        KeyError("k"),
        Refusal(RefusalCode.BLOB_NOT_FOUND),
        Refusal(RefusalCode.HANDOFF_IDENTITY_MISMATCH),
    ],
    ids=["value", "key", "missing-blob", "other-refusal"],
)
def test_every_other_failure_inside_or_refuse_maps_to_the_given_code(
    error: BaseException,
) -> None:
    with pytest.raises(Refusal) as caught:
        handoff._or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, _raising(error))
    assert caught.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    assert caught.value.__context__ is None  # no vendor or document text


def test_or_refuse_returns_what_the_call_returns() -> None:
    assert handoff._or_refuse(RefusalCode.ARTIFACT_RECORD_MISMATCH, lambda: 7) == 7


# --- N143 (a) ---------------------------------------------------------------


def test_two_tables_equal_after_padding_are_told_apart_by_their_widths() -> None:
    """T3D.5's row is one cell short; T3D.7's has a real empty last cell. The
    vendor pads the first to the second, so (header, rows) alone matched
    T3D.7 to T3D.5's table and named a fault T3D.7 does not have."""
    short, real = "| a | b | c | d | e |", "| a | b | c | d | e | |"
    markdown = (
        "---\nmodule_id: CP-3C\n---\n\n### T3D.5 — First\n\n"
        + _table([short])
        + "\n### T3D.7 — Second\n\n"
        + _table([real])
    )
    lines = [
        line for line in _cp3c_feedback(markdown) if line.startswith("host table check")
    ]
    assert len(lines) == 1, lines
    assert lines[0].startswith("host table check: T3D.5 row 1 («a») has 5 cells")


# --- N143 (b) ---------------------------------------------------------------


def _front(module: str, flags: tuple[str, ...] = ()) -> bytes:
    profile, chosen = CREDIT_SCREEN_SELECTION
    return (
        f"---\nmodule_id: {module}\nqa_status: Passed\n"
        f"limitation_flags: {json.dumps(list(flags))}\n"
        "validation_warnings: []\n"
        f"credit_os_profile_id: {profile}\ncredit_os_selection_id: {chosen}\n"
        "---\n\n# Body\n"
    ).encode()


def test_an_item_that_hides_text_drops_only_itself_from_its_line() -> None:
    gaps = [
        OwnerGap("CP-1A", "limitation_flags", "SEEN_ONE"),
        OwnerGap("CP-1A", "limitation_flags", "HID​DEN"),
        OwnerGap("CP-2H", "limitation_flags", "SEEN_TWO"),
    ]
    lines = owner_messages("CP-5", gaps)
    assert len(lines) == 2, lines
    assert "«SEEN_ONE» (from CP-1A)" in lines[0]
    assert "«SEEN_TWO» (from CP-2H)" in lines[0]
    assert "HID" not in "".join(lines)
    assert lines[1] == "host owner check: 1 more missing items not shown"


def test_a_module_with_two_upstream_refs_is_read_as_acceptance_reads_it() -> None:
    """Acceptance keys upstream by module (`_forecast_inputs`: the later ref
    wins), so a retry is told of the later ref's flags only, once."""
    context = SimpleNamespace(
        upstream=[
            (SimpleNamespace(module_id="CP-1A"), _front("CP-1A", ("OLD_FLAG",))),
            (SimpleNamespace(module_id="CP-1A"), _front("CP-1A", ("ONLY_FLAG",))),
        ]
    )
    answer = json.dumps(
        {"canonical_markdown": _front("CP-5").decode(), "citations": [CITATION]}
    )
    assignment: Any = SimpleNamespace(module_id="CP-5")
    ctx: Any = context
    lines = _owner_lines(BUNDLE, assignment, ctx, answer)
    assert len(lines) == 1, lines
    assert lines[0].endswith("missing from limitation_flags: «ONLY_FLAG» (from CP-1A)")


# --- N218 (3), (6), F651 ----------------------------------------------------


class _Count:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        self.calls = 0
        real = getattr(handoff, name)

        def spy(*args: object, **kwargs: object) -> object:
            self.calls += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(handoff, name, spy)


def _answer(rows: list[str], extra: str = "") -> str:
    return (
        "---\nmodule_id: CP-3C\n---\n\n### T3D.2 — Debt maturity\n\n"
        + _table(rows, HEADER6)
        + extra
    )


def test_feedback_lines_parses_the_answer_once(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _Count(monkeypatch, "_wire")
    _cp3c_feedback(_answer(["| a | b | c | d | e | f |"]))
    assert wire.calls == 1


def test_the_answer_readers_parse_the_answer_once_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _body(_answer(["| a | b | c | d | e | f |"]))
    wire = _Count(monkeypatch, "_wire")
    assert answer_markdown(body) is not None
    assert wire.calls == 1
    assert len(answer_citations(body)) == 1
    assert wire.calls == 2


def test_a_comparison_parses_and_bounds_each_body_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    earlier = _body(_answer(["| a | b | c | d | e | f |"]))
    later = _body(_answer(["| a | b | c | d | e | f |"], "\n## Extra\n"))
    wire = _Count(monkeypatch, "_wire")
    bound = _Count(monkeypatch, "_text_bound")
    answer_shrank(CONTRACT, "CP-3C", earlier, later, _skill("CP-3C"))
    assert (wire.calls, bound.calls) == (2, 2)


def test_each_reading_is_of_its_own_body_with_nothing_kept_between() -> None:
    first = _body("---\nmodule_id: A\n---\n\n# One\n")
    second = _body("---\nmodule_id: B\n---\n\n# Two\n")
    for _ in range(2):
        assert answer_markdown(first) == b"---\nmodule_id: A\n---\n\n# One\n"
        assert answer_markdown(second) == b"---\nmodule_id: B\n---\n\n# Two\n"
        assert answer_markdown("not json") is None
    assert answer_citations("not json") == ()
    assert answer_citations(first) == answer_citations(second)


# --- N218 (5), owner ruling R9 ---------------------------------------------

HELD = "`T3D.2`"


def test_a_carried_answer_refused_only_on_a_carriage_return_gets_the_keep_line() -> (
    None
):
    row = "| a | b | c | d | e | f | g | h | i | j | k | l |"
    header = tuple(f"h{n}" for n in range(12))
    markdown = "---\nmodule_id: CP-3C\n---\n\n### T3D.2 — Debt maturity\n\n" + _table(
        [row], header
    )
    skill = _skill("CP-3C")
    plain = kept_registers_line(CONTRACT, "CP-3C", _body(markdown), skill)
    assert plain is not None and HELD in plain
    with_cr = kept_registers_line(
        CONTRACT, "CP-3C", _body(markdown.replace("Debt", "Debt\r")), skill
    )
    assert with_cr == plain
    decomposed = markdown.replace("Debt", "Débt")
    assert kept_registers_line(CONTRACT, "CP-3C", _body(decomposed), skill) == plain


def test_the_keep_line_still_refuses_the_bounds_that_guard_the_vendor() -> None:
    header = tuple(f"h{n}" for n in range(12))
    row = "| a | b | c | d | e | f | g | h | i | j | k | l |"
    base = "---\nmodule_id: CP-3C\n---\n\n### T3D.2 — Debt maturity\n\n" + _table(
        [row], header
    )
    skill = _skill("CP-3C")
    run = base + "x" + " " * (handoff.MAX_WHITESPACE_RUN + 1) + "y\n"
    heading = base + "## t" + " " * (handoff.MAX_HEADING_RUN + 1) + "u\n"
    long_line = base + "z" * (handoff.MAX_LINE_BYTES + 1) + "\n"
    for broken in (run, heading, long_line):
        assert kept_registers_line(CONTRACT, "CP-3C", _body(broken), skill) is None


# --- N218 (8) ---------------------------------------------------------------

VENDOR_RAISED = "host vendor check:"


def _check_lines(markdown: str) -> list[str]:
    lines = feedback_lines(CONTRACT, catalog(BUNDLE), identity("CP-0"), _body(markdown))
    return [line for line in lines if line.startswith(VENDOR_RAISED)]


def test_an_answer_the_vendors_validator_raises_on_says_so() -> None:
    nested = "x: " + "[" * 3000 + "]" * 3000
    lines = _check_lines(f"---\nmodule_id: CP-0\n{nested}\n---\n\n# T\n")
    assert len(lines) == 1, lines
    assert "validator raised" in lines[0]
    assert "x:" not in lines[0] and "[[" not in lines[0]  # never the text


def test_a_host_bound_refusal_or_a_sound_answer_gets_no_vendor_raised_line() -> None:
    assert _check_lines("---\nmodule_id: CP-0\r\n---\n\n# T\n") == []
    assert _check_lines("---\nmodule_id: CP-0\n---\n\n# T\n") == []
