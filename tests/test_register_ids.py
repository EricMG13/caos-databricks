"""A register ID is written only where the vendor's locator would read it.

The host's register hint (N52) told a guided retry which register IDs an
answer "never writes" by asking whether the ID was a substring of the text.
`T4.1` is a substring of `T4.10` to `T4.19`, so a CP-1 answer that wrote every
register but T4.1 was told nothing about T4.1, while the vendor's checker,
which reads an ID only whole (`find_registers`' `id_re`), refused it as
missing: loose text standing in for the structural reading, the class of
D103's false positive.
"""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

import pytest
from canonical_fixtures import BUNDLE, CONTRACT, handoff_markdown, identity, skill, wire

from caos.methodology import handoff
from caos.methodology.bundle import assemble_authority
from caos.methodology.executor import SKILL
from caos.methodology.handoff import (
    MAX_FEEDBACK_CHARS,
    feedback_lines,
    kept_registers_line,
)
from caos.methodology.vendor import catalog


def _register_lines(body_markdown: str) -> list[str]:
    """The host register check's lines for a CP-1 answer of this body."""
    markdown = "---\nmodule_id: CP-1\n---\n\n" + body_markdown
    citation = {"source_id": str(UUID(int=1)), "page": 1, "matched_text": "x"}
    body = json.dumps({"canonical_markdown": markdown, "citations": [citation]})
    skill = assemble_authority(BUNDLE, "CP-1").files[SKILL]
    ident = replace(identity("CP-0"), module_id="CP-1")
    lines = feedback_lines(CONTRACT, catalog(BUNDLE), ident, body, skill=skill)
    return [line for line in lines if line.startswith("host register check")]


def _every_register_but(*absent: str) -> str:
    registers = CONTRACT.completeness_check.load_contract(
        assemble_authority(BUNDLE, "CP-1").files[SKILL].decode("utf-8"), "CP-1"
    )["registers"]
    return "".join(
        f"### {register} — Register\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        for register in sorted(registers)
        if register not in absent
    )


def test_an_id_inside_a_longer_id_is_not_written() -> None:
    assert _register_lines(_every_register_but("T4.1")) == [
        "host register check: the register ID `T4.1` appears nowhere in the answer"
    ]


def test_an_id_ending_a_sentence_or_in_emphasis_is_written() -> None:
    # The vendor's boundary: a full stop that ends the sentence, emphasis and
    # punctuation around the ID still write it; only `T4.10` does not.
    text = _every_register_but("T4.1") + "The bridge ties to **T4.1**, see T4.1.\n"
    assert _register_lines(text) == []


def _kept(module_id: str, markdown: bytes) -> str | None:
    """The keep-line a guided retry of `module_id` carries for this answer."""
    body = wire(
        markdown, [{"source_id": str(UUID(int=1)), "page": 1, "matched_text": "x"}]
    )
    return kept_registers_line(CONTRACT, module_id, body, skill(module_id))


def _answer(module_id: str, omit_register: str | None = None) -> bytes:
    """A handoff writing every register of `module_id` but `omit_register`."""
    ident = replace(identity("CP-0"), module_id=module_id)
    fields = {"module_id": module_id}
    return handoff_markdown(ident, fields=fields, omit_register=omit_register)


def test_a_carried_answer_is_told_every_register_it_must_keep() -> None:
    """CP-4 live (F496, qualify run b0b6fd10): each repair fixed the fault it
    was told and dropped whole register blocks it was not told about (14, then
    8 registers). The retry now names the required registers the refused
    answer carried, in the contract's order, and says they all come back."""
    markdown = _answer("CP-1", omit_register="T4.2")
    registers = list(
        CONTRACT.completeness_check.load_contract(skill("CP-1").decode(), "CP-1")[
            "registers"
        ]
    )
    kept = [register for register in registers if register != "T4.2"]
    named = ", ".join(f"`{register}`" for register in kept[:-1])
    assert _kept("CP-1", markdown) == (
        f"host register check: the refused answer holds {len(kept)} of the"
        f" {len(registers)} required registers, {named} and `{kept[-1]}`; keep"
        " every one, with all its rows, unchanged except where another line"
        " names a fault"
    )


def test_the_keep_line_names_every_register_of_the_largest_modules() -> None:
    """R40: CP-4 requires the most registers (31) and CP-1A the longest list
    as written (22 snake_case IDs); a refused answer holding all of them gets
    every one named, within the line limit."""
    for module_id, count in (("CP-4", 31), ("CP-1A", 22)):
        line = _kept(module_id, _answer(module_id))
        assert line is not None
        assert f"holds {count} of the {count} required registers" in line
        assert line.count("`") == 2 * count and " more;" not in line
        assert len(line) <= MAX_FEEDBACK_CHARS


def test_past_the_line_limit_the_rest_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handoff, "MAX_FEEDBACK_CHARS", 300)
    line = _kept("CP-4", _answer("CP-4"))
    assert line is not None and len(line) <= 300
    named = line.count("`") // 2
    assert 0 < named < 31 and f" and {31 - named} more;" in line


def test_an_answer_with_no_register_gets_no_keep_line() -> None:
    markdown = b"---\nmodule_id: CP-1\n---\n\n## Analysis\n\nNo tables.\n"
    assert _kept("CP-1", markdown) is None
