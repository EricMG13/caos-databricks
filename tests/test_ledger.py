"""The known-gaps ledger's own gate.

`CLAUDE.md` states the rule this enforces: "A ledger entry that describes a gap
the tree has since closed is the same defect as a missing one, read the other
way round." Two ways of getting there are mechanical, and this file is both.

The first is citation rot. An entry earns its keep by naming the test that holds
it open, and a named test that no longer exists turns the entry into an
assurance nobody runs. The second is the half-closed entry: this repository's
convention is that an open entry ends in an `*Upgrade:*` clause, so an entry
with no upgrade path has either been closed without being struck or was written
without saying what would close it.

What this cannot do is read an entry's prose and decide whether the tree still
behaves that way. Two entries were struck by hand in the commit that added this
file -- one claiming there was no `qualification_verdicts` table, one claiming a
proof was held and never stored -- and no rule here would have caught either,
because both were fluent, both cited nothing, and both kept their upgrade
clause while becoming false. Phrase-based rules were tried against the real
file and rejected: the best of them flagged three entries, of which one was the
genuine defect and two were correct entries using the same words. That limit is
recorded in the ledger under Completion Phase 7 rather than papered over with a
gate that looks stronger than it is.
"""

from __future__ import annotations

import re
from pathlib import Path

import ledger_state
import pytest

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "tests"
WORKSPACE_SUITE = REPO / "frontend" / "tests"

# A Python test is a function; a workspace test is a title string. Both are
# cited in the ledger the same way, so both are read.
_PYTHON_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_[a-z0-9_]+)", re.MULTILINE)
_WORKSPACE_TEST = re.compile(r"""\b(?:test|it)\(\s*(["'`])(test_[a-z0-9_]+)\1""")

# The ledger cites a test file as readily as a test function -- "`test_phase_exits.py`
# names it" is a citation of the module. A module stem is therefore a name this
# gate must accept, and `_names_in_the_suite` collects both.

# Names the ledger mentions without claiming the suite defines them. Four, each
# found by running this gate rather than by reading: one test deliberately
# deleted and owed again, one placeholder in a sentence describing a regex, and
# two the feature-status entry names *because* they no longer exist. Each entry
# states why, because an exemption with no reason is how a gate stops gating --
# and `test_no_exempt_name_has_quietly_been_written` refuses one that has since
# become real, so the list cannot outlive its reasons.
NOT_A_CITATION = {
    "test_cp1_produces_canonical_envelope_with_anchored_citations": (
        "deleted with the claims executor (docs/DECISIONS.md 42) and owed again "
        "when Phase 5 extends the canonical adapter to CP-1; the list that owns "
        "it is NOT_YET_REACHED in tests/test_phase_exits.py"
    ),
    "test_a_revision_is_frozen_once": (
        "named by the feature-status entry as an example of a citation that no "
        "longer resolves; written by 9bf20b2 and deleted with the filing code it "
        "covered, so an entry that could cite it would not need the entry"
    ),
    "test_the_receipt_names_the_signer_of_the_frozen_bytes": (
        "the second example in the same entry, deleted with the same code"
    ),
    "test_x": (
        "a placeholder inside the ledger's own description of the phase-exit "
        "gate's title regex, not a citation of anything"
    ),
}


# Every phase heading the ledger carries. Declared rather than derived: the
# point is that a heading cannot appear, vanish or be renamed without a
# deliberate edit here, which is what the count floor alone could not see.
EXPECTED_PHASES = frozenset(
    {
        "Audit remediation (2026-09-17)",
        "Completion Phase 13",
        "Completion Phase 12",
        "Completion Phase 10",
        "Completion Phase 9",
        "Completion Phase 8",
        "Completion Phase 7",
        "Repair Phase 5",
        "Repair Phase 4",
        "Repair Phase 3",
        "Repair Phase 2",
        "Phase 0",
        "Rebuild Phase 10 (historical)",
        "Rebuild Phase 9 (historical)",
        "Rebuild Phase 8 (historical)",
        "Rebuild Phase 7 (historical)",
        "Phase 6",
        "Phase 5",
        "Phase 4",
        "Phase 3",
        "Phase 2",
        "Phase 1",
    }
)


def _names_in_the_suite() -> frozenset[str]:
    """Every test name the suite defines: functions, titles and module stems."""
    names: set[str] = set()
    for path in sorted(SUITE.rglob("test_*.py")):
        names.add(path.stem)
        names.update(_PYTHON_TEST.findall(path.read_text(encoding="utf-8")))
    if WORKSPACE_SUITE.is_dir():
        for pattern in ("*.ts", "*.tsx"):
            for path in sorted(WORKSPACE_SUITE.rglob(pattern)):
                text = path.read_text(encoding="utf-8")
                names.update(found[1] for found in _WORKSPACE_TEST.findall(text))
    return frozenset(names)


def test_every_test_a_ledger_entry_cites_exists_in_the_suite() -> None:
    """A cited test that nobody runs is a gap recorded as if it were guarded."""
    defined = _names_in_the_suite()
    missing = [
        f"{entry.title!r} cites {name!r}, which the suite does not define"
        for entry in ledger_state.read()
        for name in entry.tests
        if name not in defined and name not in NOT_A_CITATION
    ]
    assert not missing, "\n".join(missing)


def test_no_exempt_name_has_quietly_been_written() -> None:
    """An excuse that has come true is an excuse nobody is reading."""
    defined = _names_in_the_suite()
    stale = sorted(name for name in NOT_A_CITATION if name in defined)
    assert not stale, (
        "these names are exempt from the citation rule but the suite now "
        f"defines them; drop the exemption: {stale}"
    )


def test_every_open_ledger_entry_states_its_upgrade_path() -> None:
    """An open entry with no upgrade path is closed, or was never a gap.

    The convention holds for every open entry in the file today, which is what
    makes it a gate rather than a wish: it fails the day an entry is closed by
    deleting its upgrade clause and left unstruck.
    """
    silent = [
        f"[{entry.phase}] {entry.title!r} is open and states no *Upgrade:*"
        for entry in ledger_state.read()
        if entry.open and not entry.upgrade
    ]
    assert not silent, "\n".join(silent)


def test_the_reader_found_the_whole_ledger() -> None:
    """A reader that matched nothing would make both rules above vacuous.

    A count alone left slack twice over. The confidence review showed a `## `
    inserted mid-ledger would drop twelve entries and still clear a count floor;
    the adversarial audit then showed a deleted blank line relabelling four
    entries with the count unchanged. So the floor names the whole phase set,
    which neither failure can survive.
    """
    found = ledger_state.read()
    assert len(found) > 80, f"read only {len(found)} ledger entries"
    # Every heading, not just the two ends. A count and a bracket both missed the
    # real failure: a deleted blank line stopped `**Phase 2.**` being read as a
    # heading, which moved its four entries under the phase above and left the
    # count identical. Naming the set is what sees that.
    assert {entry.phase for entry in found} == EXPECTED_PHASES, (
        "the ledger's phase headings moved; if a phase was added or renamed, "
        "update EXPECTED_PHASES in the same commit"
    )
    assert any(entry.struck for entry in found), "no closed entry was recognised"
    assert any(entry.open for entry in found), "no open entry was recognised"
    assert all(entry.phase for entry in found), "an entry sits under no phase heading"
    assert all(entry.title for entry in found), "an entry parsed with no title"


def test_a_contract_with_no_ledger_heading_refuses() -> None:
    """The reader fails loudly rather than reporting an empty ledger."""
    with pytest.raises(ValueError):
        ledger_state.entries("# A contract with no ledger\n\nnothing here.\n")


def test_the_reader_separates_struck_entries_from_open_ones() -> None:
    """The one distinction every rule above rests on."""
    found = ledger_state.entries(
        "## Known gaps (honest ledger)\n\n"
        "**Completion Phase 7.**\n\n"
        "- ~~**Closed.**~~ Fixed in `abc1234`, `test_it_works` holds it.\n"
        "- **Open.** Still true. *Upgrade:* do the work.\n\n"
        "## Something else\n\n"
        "- **Not a ledger entry.** Outside the section.\n"
    )
    assert all(isinstance(entry, ledger_state.LedgerEntry) for entry in found)
    assert [(entry.title, entry.struck) for entry in found] == [
        ("Closed", True),
        ("Open", False),
    ]
    assert found[0].tests == ("test_it_works",)
    assert found[0].hex_ids == ("abc1234",)
    assert found[1].upgrade and not found[0].open


def test_a_heading_without_a_blank_line_before_it_is_refused() -> None:
    """The failure this gate was written after, made into a rule.

    `8b1fac6` deleted the blank line before `**Phase 2.**` while rewriting the
    entry above it, and `fa6bbfe` then required headings to follow a blank line.
    Together they stopped that heading being read, moved its four entries under
    the phase above, and left the entry count identical -- so the check the
    remediation relied on could not see it. Absorbing such a line silently is
    the defect; refusing is the fix.
    """
    unseparated = (
        "## Known gaps (honest ledger)\n\n"
        "**Phase 9.**\n\n"
        "- **An entry.** Its text. *Upgrade:* do the work.\n"
        "**Phase 8.**\n\n"
        "- **Another.** Text. *Upgrade:* later.\n"
    )
    with pytest.raises(ValueError, match="blank line"):
        ledger_state.entries(unseparated)

    separated = unseparated.replace(
        "*Upgrade:* do the work.\n**Phase 8.**",
        "*Upgrade:* do the work.\n\n**Phase 8.**",
    )
    assert [entry.phase for entry in ledger_state.entries(separated)] == [
        "Phase 9",
        "Phase 8",
    ]


def test_a_fenced_example_is_not_read_as_a_real_entry() -> None:
    """A struck bullet inside a fenced block illustrates the convention;
    it does not describe a gap this ledger actually has."""
    found = ledger_state.entries(
        "## Known gaps (honest ledger)\n\n"
        "**Phase 9.**\n\n"
        "```\n"
        "- ~~**An example.**~~ Not a real entry.\n"
        "```\n\n"
        "- **A real one.** Text. *Upgrade:* do the work.\n"
    )
    assert [entry.title for entry in found] == ["A real one"]


def _write_contract(path: Path, body: str = "") -> Path:
    contract = path / "CLAUDE.md"
    contract.write_text(
        body
        or (
            "## Known gaps (honest ledger)\n\n"
            "**Phase 9.**\n\n"
            "- ~~**Closed.**~~ Fixed in `abc1234`.\n"
            "- **Open.** Still true. *Upgrade:* do the work.\n"
        ),
        encoding="utf-8",
    )
    return contract


def test_main_reports_one_line_per_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--report` is how a person checks the parser itself."""
    contract = _write_contract(tmp_path)

    code = ledger_state.main(["--contract", str(contract), "--report"])

    out = capsys.readouterr().out
    assert code == 0
    assert "closed [Phase 9] Closed" in out
    assert "open   [Phase 9] Open" in out
    assert "2 entries, 1 closed, 1 open" in out


def test_main_without_report_prints_only_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default is the summary a script can grep for; `--report` is opt-in."""
    contract = _write_contract(tmp_path)

    code = ledger_state.main(["--contract", str(contract)])

    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "2 entries, 1 closed, 1 open"


def test_main_refuses_a_contract_that_does_not_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing file is refused with its own message, not an unhandled trace."""
    code = ledger_state.main(["--contract", str(tmp_path / "nowhere.md")])

    assert code == 2
    assert "ledger unreadable" in capsys.readouterr().err


def test_main_refuses_a_contract_with_no_ledger_heading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`entries`'s own refusal, surfaced by `main` as its own exit code."""
    contract = _write_contract(tmp_path, "# No ledger heading here\n")

    code = ledger_state.main(["--contract", str(contract)])

    assert code == 2
    assert "ledger unreadable" in capsys.readouterr().err


def test_main_refuses_a_contract_with_no_ledger_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A scan of nothing is a failure, not a quiet pass."""
    contract = _write_contract(
        tmp_path, "## Known gaps (honest ledger)\n\nNothing under the heading.\n"
    )

    code = ledger_state.main(["--contract", str(contract)])

    assert code == 2
    assert "read no ledger entries" in capsys.readouterr().err
