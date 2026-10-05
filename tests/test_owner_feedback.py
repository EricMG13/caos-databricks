"""CP-5's guided retry is told which owner restrictions it dropped (F510).

Live run LFCS1: CP-5 was refused `HANDOFF_INCOMPLETE` three times by
`verify_owner_restrictions` and every retry was told nothing; each answer
left out 23 or 24 distinct flags and warnings of eight upstream owners.
"""

from __future__ import annotations

import json

import pytest
from canonical_fixtures import CONTRACT

from caos.methodology.canonical import MAX_OWNER_LINES, owner_messages
from caos.methodology.handoff import MAX_FEEDBACK_CHARS
from caos.methodology.verification import (
    CREDIT_SCREEN_SELECTION,
    OWNER_KEYS,
    OwnerGap,
    owner_restriction_gaps,
    verify_owner_restrictions,
)
from caos.refusals import Refusal, RefusalCode

RULE = (
    "host owner check: CP-5's front matter must carry each upstream owner's"
    " limitation_flags and validation_warnings exactly; "
)


def _front(
    module: str,
    qa: str = "Passed",
    flags: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    selection: tuple[str, str] = CREDIT_SCREEN_SELECTION,
) -> bytes:
    profile, chosen = selection
    return (
        f"---\nmodule_id: {module}\nqa_status: {qa}\n"
        f"limitation_flags: {json.dumps(list(flags))}\n"
        f"validation_warnings: {json.dumps(list(warnings))}\n"
        f"credit_os_profile_id: {profile}\ncredit_os_selection_id: {chosen}\n"
        "---\n\n# Body\n"
    ).encode()


def _gaps(answer: bytes, *owners: bytes) -> list[OwnerGap]:
    return owner_restriction_gaps(
        CONTRACT, answer, owners, selection=CREDIT_SCREEN_SELECTION
    )


def test_a_missing_warning_is_named_with_its_owner() -> None:
    owners = (
        _front("CP-1A", warnings=("LITE_FULL_UPGRADE_REQUIRED", "KEPT")),
        _front("CP-2H", warnings=("LITE_FULL_UPGRADE_REQUIRED",), flags=("F1",)),
    )
    answer = _front("CP-5", warnings=("KEPT",), flags=("F1",))
    gaps = _gaps(answer, *owners)
    assert gaps == [
        OwnerGap("CP-1A", "validation_warnings", "LITE_FULL_UPGRADE_REQUIRED"),
        OwnerGap("CP-2H", "validation_warnings", "LITE_FULL_UPGRADE_REQUIRED"),
    ]
    assert owner_messages("CP-5", gaps) == [
        RULE + "missing from validation_warnings: «LITE_FULL_UPGRADE_REQUIRED»"
        " (from CP-1A, CP-2H)"
    ]


def test_the_qa_status_rule_is_named() -> None:
    gaps = _gaps(_front("CP-5"), _front("CP-1C", qa="Restricted", flags=("F",)))
    assert gaps[0] == OwnerGap("CP-1C", "qa_status", "Restricted")
    assert owner_messages("CP-5", gaps) == [
        "host owner check: CP-5's qa_status must be Restricted while an upstream"
        " owner's is; Restricted: CP-1C",
        RULE + "missing from limitation_flags: «F» (from CP-1C)",
    ]


def test_the_owner_lines_are_packed_and_capped_with_a_count() -> None:
    flags = tuple(f"FLAG_{n:03d}_" + "X" * 30 for n in range(120))
    gaps = _gaps(_front("CP-5"), _front("CP-1A", flags=flags))
    lines = owner_messages("CP-5", gaps)
    assert len(lines) == MAX_OWNER_LINES + 1
    assert lines[0].startswith(RULE + "missing from limitation_flags: ")
    assert lines[1].startswith("host owner check: also missing from limitation_flags")
    prefix = len("host owner check: ")
    assert all(len(line) <= prefix + MAX_FEEDBACK_CHARS for line in lines)
    shown = sum(line.count("«") for line in lines[:-1])
    assert lines[-1] == f"host owner check: {120 - shown} more missing items not shown"


def test_nothing_is_named_when_nothing_is_dropped() -> None:
    owner = _front("CP-1A", qa="Restricted", flags=("F",), warnings=("W",))
    answer = _front("CP-5", qa="Restricted", flags=("F", "OWN"), warnings=("W",))
    assert _gaps(answer, owner) == []
    assert owner_messages("CP-5", []) == []
    # Outside the credit screen selection CP-5 is held to nothing.
    other = _front("CP-5", selection=("LITE_CREDIT_22", "OTHER"))
    assert _gaps(other, owner) == []
    assert set(OWNER_KEYS) == {"limitation_flags", "validation_warnings"}


def test_acceptance_is_still_exact_set_inclusion() -> None:
    owner = _front("CP-1A", flags=("LITE_FULL_UPGRADE_REQUIRED",))
    near = _front("CP-5", flags=("LITE_FULL_UPGRADE_REQUIRE",))
    with pytest.raises(Refusal) as refused:
        verify_owner_restrictions(
            CONTRACT,
            near,
            [owner],
            refuse=RefusalCode.HANDOFF_INCOMPLETE,
            selection=CREDIT_SCREEN_SELECTION,
        )
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE
    exact = _front("CP-5", flags=("LITE_FULL_UPGRADE_REQUIRED",))
    verify_owner_restrictions(
        CONTRACT,
        exact,
        [owner],
        refuse=RefusalCode.HANDOFF_INCOMPLETE,
        selection=CREDIT_SCREEN_SELECTION,
    )
