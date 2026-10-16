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
from collections.abc import Callable, Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from canonical_fixtures import BUNDLE, CONTRACT, identity

from caos.graph.route import MODEL_MODULE
from caos.methodology import handoff
from caos.methodology.bundle import assemble_authority
from caos.methodology.canonical import (
    _owner_lines,
    _packed_items,
    _packed_key,
    owner_messages,
)
from caos.methodology.executor import SKILL
from caos.methodology.handoff import (
    MAX_FEEDBACK_CHARS,
    answer_citations,
    answer_markdown,
    answer_shrank,
    feedback_lines,
    kept_registers_line,
)
from caos.methodology.vendor import VendorContract, catalog
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
    decomposed = markdown.replace("Debt", "De\u0301bt")
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


# --- mutation survivors: pins on the lines these repairs moved ---------------


def _scoped_contract(validate_text: Callable[..., object]) -> VendorContract:
    return replace(
        CONTRACT, validate_handoff=SimpleNamespace(validate_text=validate_text)
    )


def test_checked_hands_the_validator_the_text_and_the_catalogs_scope() -> None:
    seen: list[tuple[str, object]] = []

    def validate_text(text: str, *, decision_scope: object) -> object:
        seen.append((text, decision_scope))
        return "RESULT"

    ident = identity("CP-0")
    markdown = b"---\nmodule_id: CP-0\n---\n\n# T\n"
    got = handoff._checked(
        _scoped_contract(validate_text), catalog(BUNDLE), ident, markdown
    )
    assert got == ("RESULT", False)
    scope = handoff._decision_scope(catalog(BUNDLE), ident)
    assert seen == [(markdown.decode(), scope)] and scope is not None


def test_checked_reports_a_raising_validator_and_never_a_bound() -> None:
    def raises(text: str, *, decision_scope: object) -> object:
        raise RecursionError

    def never(text: str, *, decision_scope: object) -> object:
        raise AssertionError  # the validator never reads text past a bound

    ident, markdown = identity("CP-0"), b"---\nmodule_id: CP-0\n---\n\n# T\n"
    assert handoff._checked(
        _scoped_contract(raises), catalog(BUNDLE), ident, markdown
    ) == (None, True)
    assert handoff._checked(
        _scoped_contract(never), catalog(BUNDLE), ident, markdown + b"\r"
    ) == (None, False)


def test_a_body_that_is_not_the_transport_is_told_why_in_the_parsers_words() -> None:
    raw_newline = '{"canonical_markdown": "a\nb", "citations": []}'
    assert handoff._not_transport(raw_newline).endswith(handoff._ESCAPES)
    broken = handoff._not_transport("{bad")
    assert broken.startswith("host transport check: the answer is not one JSON")
    with pytest.raises(json.JSONDecodeError) as bad:
        json.loads("{bad")
    assert broken == handoff._TRANSPORT_JSON.format(bad.value.msg)
    assert handoff._not_transport("[1]") == handoff._TRANSPORT_SHAPE
    assert handoff._not_transport("[" * 100_000) == handoff._TRANSPORT_SHAPE


def _t3d2(extra: str) -> str:
    header = tuple(f"h{n}" for n in range(12))
    row = "| a | b | c | d | e | f | g | h | i | j | k | l |"
    return (
        "---\nmodule_id: CP-3C\n---\n\n### T3D.2 — Debt maturity\n\n"
        + _table([row], header)
        + extra
    )


def _kept(markdown: str) -> str | None:
    return kept_registers_line(CONTRACT, "CP-3C", _body(markdown), _skill("CP-3C"))


def test_the_line_bound_is_on_one_line_and_inclusive_of_the_limit() -> None:
    assert _kept(_t3d2("z" * handoff.MAX_LINE_BYTES + "\n")) is not None
    assert _kept(_t3d2("z" * (handoff.MAX_LINE_BYTES + 1) + "\n")) is None
    # Many short lines make a long text, not a long line.
    assert _kept(_t3d2("word word\n" * 20_000)) is not None
    # A long line of words is one line however it splits on whitespace.
    assert _kept(_t3d2("ab " * 30_000 + "\n")) is None


def test_a_tagged_table_does_not_stop_the_width_lines_of_the_registers_after_it() -> (
    None
):
    tagged = (
        _t3d2("")
        .replace(
            "### T3D.2 — Debt maturity\n\n",
            "### T3D.2 — Debt maturity\n\n<!-- table-id: cp3c.debt -->\n",
        )
        .replace("| l |", "|")
    )
    markdown = tagged + "\n### T3D.5 — Second\n\n" + _table(["| a | b | c | d | e |"])
    lines = [
        line for line in _cp3c_feedback(markdown) if line.startswith("host table check")
    ]
    assert len(lines) == 1 and lines[0].startswith("host table check: T3D.5 row 1")


def test_a_table_under_a_retired_register_heading_gets_no_width_line() -> None:
    """The retired IDs reach the vendor's locator here too: a prose line above a
    table headed `#### T4.7 ...` (CP-1 retired it) never binds that table to
    the register the prose mentions, so its short row is no register's fault."""
    markdown = (
        "---\nmodule_id: CP-1\n---\n\nTies to T4.2.\n\n#### T4.7 Normalized\n\n"
        "| Item | Value |\n| --- | --- |\n| a |\n"
    )
    ident = replace(identity("CP-0"), module_id="CP-1")
    lines = feedback_lines(
        CONTRACT, catalog(BUNDLE), ident, _body(markdown), skill=_skill("CP-1")
    )
    assert [line for line in lines if line.startswith("host table check")] == []


def _other(module: str) -> bytes:
    return _front(module).replace(b"LITE_FULL_CREDIT_SCREEN", b"ELSEWHERE")


def _owner_context(*owners: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        upstream=[
            (SimpleNamespace(module_id=f"CP-{n}"), owner)
            for n, owner in enumerate(owners)
        ]
    )


def _owner_answer(markdown: bytes) -> str:
    return json.dumps(
        {"canonical_markdown": markdown.decode(), "citations": [CITATION]}
    )


def _owned(module: str, markdown: bytes, *owners: bytes) -> list[str]:
    assignment: Any = SimpleNamespace(module_id=module)
    context: Any = _owner_context(*owners)
    return _owner_lines(BUNDLE, assignment, context, _owner_answer(markdown))


def test_owner_lines_name_the_module_and_hold_only_the_credit_screen_cp5() -> None:
    owner = _front("CP-1A", flags=("A_FLAG",))
    lines = _owned("CP-5", _front("CP-5"), owner)
    assert lines == [
        "host owner check: CP-5's front matter must carry each upstream owner's"
        " limitation_flags and validation_warnings exactly; missing from"
        " limitation_flags: «A_FLAG» (from CP-1A)"
    ]
    # The selection is the answer's own: outside the credit screen nothing is held.
    assert _owned("CP-5", _other("CP-5"), owner) == []
    assert _owned("CP-1A", _front("CP-1A"), owner) == []


def test_owner_lines_hold_the_model_module_whatever_its_selection() -> None:
    owner = _front("CP-1A", flags=("A_FLAG",))
    lines = _owned(MODEL_MODULE, _other(MODEL_MODULE), owner)
    assert len(lines) == 1 and lines[0].startswith(
        f"host owner check: {MODEL_MODULE}'s front matter"
    )


def test_owner_lines_for_an_answer_the_validator_cannot_read_are_none() -> None:
    assert _owned("CP-5", b"no front matter at all", _front("CP-1A")) == []


def test_restricted_owners_are_listed_with_commas() -> None:
    gaps = [
        OwnerGap("CP-1A", "qa_status", "Restricted"),
        OwnerGap("CP-1C", "qa_status", "Restricted"),
    ]
    assert owner_messages("CP-5", gaps) == [
        "host owner check: CP-5's qa_status must be Restricted while an upstream"
        " owner's is; Restricted: CP-1A, CP-1C"
    ]


def test_packing_cuts_at_the_limit_exactly_and_joins_with_commas() -> None:
    first = "F: "
    room = MAX_FEEDBACK_CHARS - len(first) - 2  # the ", " between two entries
    fits = ["a" * 10, "b" * (room - 10)]
    assert _packed_key(first, "k", fits) == [(first + ", ".join(fits), 2)]
    over = [fits[0], fits[1] + "b"]
    assert _packed_key(first, "k", over) == [
        (first + over[0], 1),
        ("also missing from k: " + over[1], 1),
    ]


def test_packing_keeps_the_rule_head_on_the_first_line_only() -> None:
    gaps = [
        OwnerGap("CP-1A", "qa_status", "Restricted"),
        OwnerGap("CP-1A", "limitation_flags", "FLAG"),
        OwnerGap("CP-1A", "validation_warnings", "WARN"),
    ]
    packed, hidden = _packed_items("CP-5", gaps)
    assert hidden == 0
    assert [text for text, _n in packed] == [
        "CP-5's front matter must carry each upstream owner's limitation_flags"
        " and validation_warnings exactly; missing from limitation_flags:"
        " «FLAG» (from CP-1A)",
        "missing from validation_warnings: «WARN» (from CP-1A)",
    ]


def test_the_text_bounds_are_named_in_their_fixed_words() -> None:
    assert handoff._broken_bound("a\rb") == (
        "a line ends in a carriage return; canonical Markdown ends every line"
        " with a line feed alone"
    )
    assert handoff._broken_bound("a​b") == (
        "the Markdown carries a character no reader can see (a zero-width, tag,"
        " variation-selector or other invisible code point)"
    )


def test_the_front_matter_bound_is_inclusive_and_only_for_a_front_matter() -> None:
    limit = handoff.MAX_FRONTMATTER_BYTES
    line = "k: " + "v" * 1000  # 1,003 bytes with its line feed
    body = "\n".join([line] * ((limit // 1004) - 1))
    assert handoff._broken_bound(f"---\n{body}\n---\n") == ""
    pad = limit - len(f"---\n{body}\n---".encode()) - 1
    exact = f"---\n{body}\n" + "p" * pad + "\n---\n"
    assert handoff._broken_bound(exact) == ""
    over = exact.replace("p" * pad, "p" * (pad + 1))
    assert handoff._broken_bound(over).startswith("the front matter is longer than")
    # Text that does not open with `---` has no front matter to bound.
    long_body = "\n".join([line] * (limit // 1004 + 5))
    assert handoff._broken_bound(f"# T\n{long_body}\n---\nend\n") == ""
    assert handoff._broken_bound("---\n---\nbody\n") == ""


def test_an_answer_whose_front_matter_the_parser_cannot_nest_is_not_a_shrink() -> None:
    nested = "x: " + "[" * 3000 + "]" * 3000
    body = _body(f"---\nmodule_id: CP-0\n{nested}\n---\n\n# T\n")
    assert not answer_shrank(CONTRACT, "CP-0", body, body, b"")


def test_the_run_bounds_are_named_and_inclusive_of_their_limits() -> None:
    assert handoff._run_bound("a b\tc") == ""
    run = "x" + " " * (handoff.MAX_WHITESPACE_RUN + 1)
    assert handoff._run_bound(run).startswith("a line carries a run of more than")
    assert handoff._run_bound("x" + "\t" * (handoff.MAX_WHITESPACE_RUN + 1)) != ""
    assert handoff._run_bound("x" + " " * handoff.MAX_WHITESPACE_RUN) == ""
    title = "## t" + " " * (handoff.MAX_HEADING_RUN + 1) + "u"
    assert handoff._run_bound(title).startswith("a heading's title carries a run")
    assert handoff._run_bound("## t" + " " * handoff.MAX_HEADING_RUN + "u") == ""


# --- fix round 1 ---------------------------------------------------------------


def _slow_heading(char: str, count: int = 16_000) -> str:
    return _t3d2("").replace(
        "### T3D.2 — Debt maturity",
        "#" + char * count + "x\n\n### T3D.2 — Debt maturity",
    )


def _vendor_reads() -> tuple[VendorContract, list[str]]:
    """A contract whose register locator records its calls and delegates, so a
    test can tell that a host bound refused a text before the vendor's
    quadratic expressions met it: deterministic, where a wall-clock limit
    flakes on a loaded runner (N197)."""
    reads: list[str] = []
    real = CONTRACT.completeness_check

    def find_registers(
        text: str, registers: Sequence[str], retired: Sequence[str]
    ) -> object:
        reads.append("find_registers")
        return real.find_registers(text, registers, retired)

    checker = SimpleNamespace(
        load_contract=real.load_contract, find_registers=find_registers
    )
    return replace(CONTRACT, completeness_check=checker), reads


def test_a_control_run_heading_gets_no_keep_line_and_never_meets_the_vendor() -> None:
    markdown = _slow_heading("\x1f")
    contract, reads = _vendor_reads()
    skill = _skill("CP-3C")
    assert kept_registers_line(contract, "CP-3C", _body(markdown), skill) is None
    assert handoff._readable(_body(markdown)) is None
    assert reads == []
    # The spy is live: a sound text does reach the vendor's locator.
    assert kept_registers_line(contract, "CP-3C", _body(_t3d2("plain\n")), skill)
    assert reads == ["find_registers"]


def test_a_control_character_alone_withholds_the_keep_line() -> None:
    assert _kept(_t3d2("a\x01b\n")) is None
    assert _kept(_t3d2("plain\n")) is not None


def test_a_carriage_return_or_non_nfc_alone_keeps_the_keep_line() -> None:
    assert _kept(_t3d2("a\rb\n")) is not None
    assert _kept(_t3d2("e\u0301\n")) is not None


@pytest.mark.parametrize("char", ["\u3000", "\u00a0", "\x1f", "\u2003"])
def test_a_run_of_any_whitespace_is_a_host_bound(char: str) -> None:
    markdown = _slow_heading(char)
    contract, reads = _vendor_reads()
    assert handoff._readable(_body(markdown)) is None
    assert (
        kept_registers_line(contract, "CP-3C", _body(markdown), _skill("CP-3C")) is None
    )
    with pytest.raises(Refusal) as refused:
        handoff._text(markdown.encode())
    assert refused.value.code is RefusalCode.HANDOFF_MALFORMED
    assert reads == []  # refused by a host bound before the vendor's expressions
    run = handoff.MAX_WHITESPACE_RUN
    assert handoff._run_bound("x" + char * (run + 1)).startswith("a line carries")
    assert handoff._run_bound("x" + char * run) == ""


def test_single_no_break_spaces_and_blank_lines_still_pass() -> None:
    text = _t3d2("a\u00a0b \u3000 c\n" + "\n" * 400 + "end\n")
    assert handoff._run_bound(text) == ""
    assert handoff._readable(_body(text)) == text


def test_a_non_transport_body_is_parsed_once_and_not_diagnosed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads = _Count(monkeypatch, "_not_transport")
    assert answer_markdown("{bad") is None
    assert answer_citations("{bad") == ()
    assert loads.calls == 0
    assert feedback_lines(CONTRACT, catalog(BUNDLE), identity("CP-0"), "{bad")
    assert loads.calls == 1


def test_the_unused_shaped_helper_is_gone() -> None:
    assert not hasattr(handoff, "_shaped")
