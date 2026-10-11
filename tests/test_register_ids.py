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

from canonical_fixtures import BUNDLE, CONTRACT, identity

from caos.methodology.bundle import assemble_authority
from caos.methodology.executor import SKILL
from caos.methodology.handoff import feedback_lines
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
