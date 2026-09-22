"""The plan's own standing rule, made executable.

`docs/REBUILD_PLAN.md`: "A phase is exited by its named tests, and
`test_every_exit_test_of_an_exited_phase_exists` refuses a later phase starting
before they are written."

That test was named in the seed and never written, which is the sort of thing
this repository is otherwise careful about: a rule enforced by intention rather
than by a tool is not enforced. It reads the plan, collects every test the plan
names, and checks the suite defines it.

*Which* suite is the part that took a second pass. The plan names tests across
both halves of this repository: Phases 1-8 are Python, and Phase 9 is the
workspace, whose passport and snapshot binding are TypeScript and whose tests
are therefore TypeScript too. A gate that read `tests/` alone would have to
excuse every one of them permanently, which is indistinguishable from not
gating them -- so it reads `frontend/tests/` as well, and Phase 9's two names
left the excuse list the day it did.

What it cannot do is decide which phase is current -- so the phases not yet
reached are listed below, explicitly, with the reason each is absent. That list
is the whole point: adding code for a phase without its named test fails this,
and so does quietly deleting a test that already exists.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "docs" / "REBUILD_PLAN.md"
SUITE = REPO / "tests"
WORKSPACE_SUITE = REPO / "frontend" / "tests"

# `test("test_x", ...)` or `it("test_x", ...)`, in any of the three quotes
# TypeScript allows. A workspace test is named by its title rather than by a
# symbol, so the title is what this matches -- and only a title written as a
# literal. One assembled at run time (the chrome suite builds a title per
# section from a template) is invisible here, which is the known gap this
# carries and the reason the floor below names two titles it must find.
_WORKSPACE_TEST = re.compile(r"""\b(?:test|it)\(\s*(["'`])(test_[a-z0-9_]+)\1""")

# Named in the plan, and legitimately not written yet. Every entry states why,
# because "not yet" with no reason is how a list like this becomes a list of
# tests nobody intends to write.
#
# Phase 11's eight names left this list one at a time, as each test was
# written, which is the direction it should move in. Phase 12's nine are named
# by the plan before the work that satisfies them exists, and leave the same
# way. What the plan still owes is work it never named a test for -- the
# qualification-set harness, its answer keys and the matrix -- and this gate
# cannot see that, which is why a phase is not closed on the strength of it
# alone.
NOT_YET_REACHED: set[str] = {
    # Phase 5's own exit test ran the retired claims executor on CP-1 of the
    # FULL route (`docs/superpowers/plans/2026-09-13-phase-3-task-3.1-brief.md`,
    # f-1c note); f-1c already refuses that executor `HANDOFF_MODULE_UNSUPPORTED`
    # before any call, and f-2b deletes the executor itself, so nothing can pass
    # this test as written. It is owed again the day Phase 5 extends the
    # canonical adapter to CP-1 (`docs/DECISIONS.md` §42; `CLAUDE.md` Repair
    # Phase 3 ledger).
    "test_cp1_produces_canonical_envelope_with_anchored_citations",
    # Phase 12, the handoff: no module payload exists yet, so a register, a
    # critical column and a cited figure are all things no artifact carries.
    "test_the_declared_register_schema_matches_the_bundles_own_contract",
    "test_a_handoff_carries_every_register_its_module_declares",
    "test_a_row_missing_a_critical_column_is_refused",
    "test_a_figure_is_cited_or_null_with_a_gap",
    "test_the_host_computes_the_confidence_the_module_reports_counts",
    "test_the_prompt_carries_the_companions_the_skill_calls_mandatory",
    "test_cp1_produces_its_declared_registers_from_real_documents",
    # Phase 12, the display: nothing serves a section document, and the
    # workspace's Analysis body is the widget set this phase replaces.
    "test_the_analysis_document_is_built_from_accepted_handoffs",
    "test_the_analysis_section_renders_a_handoffs_narrative_and_tables",
}


def named_in_the_plan() -> set[str]:
    """Every `test_*` the plan names in backticks."""
    return set(re.findall(r"`(test_[a-z0-9_]+)`", PLAN.read_text(encoding="utf-8")))


def defined_in_the_python_suite() -> set[str]:
    """Every test `tests/` defines, by name."""
    defined: set[str] = set()
    for path in SUITE.rglob("test_*.py"):
        defined.update(
            re.findall(
                r"^def (test_[a-z0-9_]+)\(", path.read_text(encoding="utf-8"), re.M
            )
        )
    return defined


def defined_in_the_workspace_suite() -> set[str]:
    """Every plan-shaped test `frontend/tests/` defines, by title.

    Both halves of the workspace suite count: the unit tests the plan's two
    Phase 9 names live in, and the workbench specs its exit line names in the
    same breath.
    """
    defined: set[str] = set()
    for pattern in ("*.test.ts", "*.test.tsx", "*.spec.ts"):
        for path in WORKSPACE_SUITE.rglob(pattern):
            source = path.read_text(encoding="utf-8")
            defined.update(name for _, name in _WORKSPACE_TEST.findall(source))
    return defined


def defined_in_the_suite() -> set[str]:
    """Every test either suite defines. The plan does not distinguish them."""
    return defined_in_the_python_suite() | defined_in_the_workspace_suite()


def test_every_exit_test_of_an_exited_phase_exists() -> None:
    """The named test the plan's standing rules call for.

    Fails two ways, both of which matter: a phase whose code arrived without its
    named test, and a named test that used to exist and was removed.
    """
    named = named_in_the_plan()
    missing = named - defined_in_the_suite()

    assert missing == NOT_YET_REACHED, (
        "the plan names tests the suite does not define, or the not-yet-reached "
        f"list is stale. Unexpectedly missing: {sorted(missing - NOT_YET_REACHED)}; "
        f"listed but now present: {sorted(NOT_YET_REACHED - missing)}"
    )


def test_the_plan_still_names_the_tests_this_list_excuses() -> None:
    """The excuse list cannot outlive the plan that justifies it.

    A name dropped from the plan but left here would silently excuse a test
    nobody is waiting for.
    """
    assert NOT_YET_REACHED <= named_in_the_plan()


def test_the_plan_names_the_tests_this_file_reads() -> None:
    """A guard against the parser silently matching nothing -- which would make
    every assertion above vacuously true."""
    named = named_in_the_plan()

    assert len(named) > 30, "the plan names far more tests than this found"
    assert "test_terminal_event_is_exactly_once" in named


def test_the_gate_reads_the_workspace_suite_as_well_as_this_one() -> None:
    """A scanner that scanned nothing is a failure, not a pass (`CLAUDE.md`).

    Were the workspace reader to stop matching -- a moved directory, a different
    call form -- every TypeScript test would read as unwritten. The assertion
    above would go red, and the cheapest way to green it would be to re-excuse
    the names in `NOT_YET_REACHED`: a gate turned off to make a gate pass. This
    fails first and says why instead.
    """
    workspace = defined_in_the_workspace_suite()

    assert len(workspace) > 20, "the workspace suite names far more tests than this"
    # Phase 9's two, by name: what the plan's exit line asks for, where it lives.
    assert {
        "test_passport_contract",
        "test_book_binds_one_snapshot_per_compared_case",
    } <= workspace
    # The two readers are separate, and neither quietly stands in for the other:
    # a Python test title has no business appearing in this half.
    assert "test_terminal_event_is_exactly_once" not in workspace
    assert "test_passport_contract" not in defined_in_the_python_suite()
