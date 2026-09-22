"""Unit rules behind the vocabulary gate.

CONTEXT.md is the only glossary. These assert that the gate reads it rather than
carrying a second copy, that it refuses to run when the two have drifted, and
that it looks at identifiers rather than at prose.
"""

from __future__ import annotations

import ast
import re
import runpy
import sys
from pathlib import Path

import check_vocabulary
import pytest

REPO = Path(__file__).resolve().parents[1]
CONTEXT_MD = (REPO / "CONTEXT.md").read_text(encoding="utf-8")


def test_banned_terms_reads_the_domain_table() -> None:
    banned = check_vocabulary.banned_terms(CONTEXT_MD)
    assert banned["deal"] == "case"
    assert banned["chunk"] == "block"
    assert banned["ready_set"] == "frontier"
    # Node-state and edge-type prose is not a table and must not be harvested.
    assert "restricted" not in banned


def test_every_context_synonym_is_classified() -> None:
    missing, stale = check_vocabulary.unclassified(
        check_vocabulary.banned_terms(CONTEXT_MD)
    )
    assert missing == set(), f"CONTEXT.md synonyms nothing classifies: {missing}"
    assert stale == set(), f"classified synonyms CONTEXT.md no longer lists: {stale}"


def test_the_qualification_set_keeps_its_own_synonyms_and_remaps_nothing(
    tmp_path: Path,
) -> None:
    """Phase 10's term, and the one it is careful not to take over.

    `docs/DECISIONS.md` §23: the body a verdict is measured against is a
    *qualification set*, not a source set and not a corpus. It gets a term
    because it is a concept CONTEXT.md did not have -- cases and their answer
    keys, spanning runs -- rather than an exemption for the word the plan
    reached for first.

    `corpus` stays where it was. Listing it again under the new term would
    remap it silently, because `banned_terms` is last-wins by token, and a
    reader of the gate's message would then be told to spell a source set as a
    qualification set.
    """
    banned = check_vocabulary.banned_terms(CONTEXT_MD)
    assert banned["benchmark"] == "qualification set"
    assert banned["golden_set"] == "qualification set"
    assert banned["corpus"] == "source set"

    module = tmp_path / "m.py"
    module.write_text("def load_benchmark_cases() -> None: ...\n", encoding="utf-8")
    reported = list(check_vocabulary.violations(module, banned))
    assert len(reported) == 1
    assert "'qualification set'" in reported[0]


def test_a_new_context_synonym_is_unclassified_until_someone_decides() -> None:
    doctored = CONTEXT_MD + "\n| **case** | one engagement | matter |\n"
    missing, _ = check_vocabulary.unclassified(check_vocabulary.banned_terms(doctored))
    assert missing == {"matter"}


def test_identifiers_ignores_prose_and_string_literals() -> None:
    tree = ast.parse('DOC = "the deal chunk"\n')
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert found == {"DOC"}


def test_violations_reads_camel_case_as_words(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text("def loadDealChunks() -> None: ...\n", encoding="utf-8")
    reported = list(
        check_vocabulary.violations(module, check_vocabulary.banned_terms(CONTEXT_MD))
    )
    # Two wrong words in one name, each reported against the term it displaces.
    assert {line.rsplit("use ", 1)[1] for line in reported} == {"'case'", "'block'"}


def test_violations_reads_the_file_name_too(tmp_path: Path) -> None:
    module = tmp_path / "deal_store.py"
    module.write_text("x = 1\n", encoding="utf-8")
    reported = list(
        check_vocabulary.violations(module, check_vocabulary.banned_terms(CONTEXT_MD))
    )
    assert len(reported) == 1
    assert "'case'" in reported[0]


def test_identifiers_includes_imported_names() -> None:
    tree = ast.parse("import chunker\nfrom x import y as fragment_reader\n")
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert found == {"chunker", "fragment_reader"}


def test_violations_catches_a_plural_synonym(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text("def read_chunks() -> None: ...\n", encoding="utf-8")
    reported = list(
        check_vocabulary.violations(module, check_vocabulary.banned_terms(CONTEXT_MD))
    )
    assert len(reported) == 1
    assert "'block'" in reported[0]


def test_identifiers_includes_function_arguments() -> None:
    tree = ast.parse("def f(chunk_size): ...\n")
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert "chunk_size" in found


def test_identifiers_includes_attribute_assignment_targets() -> None:
    tree = ast.parse("self.chunk_count = 1\n")
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert "chunk_count" in found


def test_identifiers_includes_except_handler_names() -> None:
    tree = ast.parse("try:\n    pass\nexcept ValueError as fragment_error:\n    pass\n")
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert "fragment_error" in found


def test_identifiers_includes_match_capture_names() -> None:
    tree = ast.parse("match x:\n    case chunk_capture:\n        pass\n")
    found = {name for _, name in check_vocabulary.identifiers(tree)}
    assert "chunk_capture" in found


def test_banned_terms_skips_an_empty_synonym_cell() -> None:
    """A trailing comma in the Domain table's synonym cell is an empty phrase,
    which normalises to no token and bans nothing."""
    doctored = "| **case** | one engagement | deal, |\n"
    assert check_vocabulary.banned_terms(doctored) == {"deal": "case"}


def test_check_vocabulary_main_refuses_when_context_and_gate_disagree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doctored = tmp_path / "CONTEXT.md"
    doctored.write_text("| **case** | d | mismatched_synonym |\n", encoding="utf-8")
    monkeypatch.setattr(check_vocabulary, "CONTEXT_MD", doctored)

    assert check_vocabulary.main([]) == 2
    assert "disagree" in capsys.readouterr().err


def test_check_vocabulary_main_refuses_when_nothing_is_scanned(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_vocabulary, "tracked_python", lambda _repo: [])

    assert check_vocabulary.main([]) == 2
    assert "scanned no files" in capsys.readouterr().err


def test_check_vocabulary_main_reports_violations_and_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "m.py"
    module.write_text("def read_chunk() -> None: ...\n", encoding="utf-8")

    assert check_vocabulary.main([str(module)]) == 1
    assert "'chunk'" in capsys.readouterr().out


def test_check_vocabulary_main_passes_when_clean(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text("def read_block() -> None: ...\n", encoding="utf-8")

    assert check_vocabulary.main([str(module)]) == 0


def test_check_vocabulary_module_guard_exits_with_mains_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole repo's own tree: `make lint` already guarantees this passes.
    script = REPO / "scripts" / "check_vocabulary.py"
    monkeypatch.setattr(sys, "argv", ["check_vocabulary.py"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(script), run_name="__main__")
    assert caught.value.code == 0


def test_ts_gate_enforces_the_same_tokens() -> None:
    """The TypeScript gate carries the same ENFORCED set, read from its source.

    One glossary, two halves: if either side adds or drops a synonym the other
    must follow, or a wrong word becomes legal in one language.
    """
    gate = (REPO / "frontend" / "scripts" / "check-vocabulary.mjs").read_text(
        encoding="utf-8"
    )
    literal = re.search(r"export const ENFORCED = \[(.*?)\];", gate, re.DOTALL)
    assert literal, "the TypeScript gate no longer declares ENFORCED as a literal"
    tokens = set(re.findall(r'"([a-z_]+)"', literal.group(1)))
    assert tokens == set(check_vocabulary.ENFORCED)
