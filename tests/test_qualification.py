"""Phase 10's first exit: what a verdict has to bind before it is one.

A verdict is bound to provider identity, qualification-set digest, build,
date, expiry and reviewer. Six bindings, and a
verdict missing any of them is refused rather than read with a hole in it.
N44 adds a seventh, `evidence_sha256`: the six above can agree for two
different snapshots of the same set, build and provider, so the document also
names the one exact evidence identity it was read against.

The seven are not decoration. A reviewer's signature that says the outputs met
the answer keys means nothing unless it also says *whose* outputs, measured
against *which* cases, produced by *which* build, over *which exact evidence*,
signed *when*, current *until when*, and by *whom*. Drop any one and the
signature stops being checkable: the same sentence would cover a different
provider, a different qualification set, a different snapshot, or a build
shipped a year later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from caos.qualification import Assurance
from caos.qualification.verdict import BINDINGS, Verdict, read_verdict
from caos.refusals import Refusal, RefusalCode

DECIDED = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
EXPIRES = datetime(2027, 9, 11, 9, 0, tzinfo=UTC)
NOW = DECIDED + timedelta(days=30)

SET_DIGEST = "b" * 64
EVIDENCE_DIGEST = "e" * 64


def document(**overrides: str) -> dict[str, str]:
    """A complete verdict, with whatever this test wanted changed."""
    complete: dict[str, str] = {
        "provider": "openrouter:anthropic/claude-opus-4.1",
        "qualification_set_sha256": SET_DIGEST,
        "build_id": "a43cb903",
        "decided_at": DECIDED.isoformat(),
        "expires_at": EXPIRES.isoformat(),
        "reviewer": "R. Mehta, credit risk",
        "evidence_sha256": EVIDENCE_DIGEST,
    }
    complete.update(overrides)
    return complete


def test_verdict_binds_provider_qualification_set_build_date_expiry_and_reviewer() -> (
    None
):
    """Phase 10's first exit test.

    Over the whole binding surface rather than one field: each of the seven is
    dropped, then blanked, and the verdict is refused both ways. A test that
    checked one representative field would pass against a reader that validated
    only that one.
    """
    verdict = read_verdict(document(), now=NOW)

    assert verdict.provider.value == "openrouter:anthropic/claude-opus-4.1"
    assert verdict.qualification_set_sha256 == SET_DIGEST
    assert verdict.build_id == "a43cb903"
    assert verdict.decided_at == DECIDED
    assert verdict.expires_at == EXPIRES
    assert verdict.reviewer.value == "R. Mehta, credit risk"
    assert verdict.evidence_sha256 == EVIDENCE_DIGEST
    # The reviewer's word, and the only place in this repository it is spoken.
    assert verdict.assurance is Assurance.QUALIFIED

    # The list the reader validates against is the list the plan names, plus
    # N44's evidence_sha256.
    assert BINDINGS == (
        "provider",
        "qualification_set_sha256",
        "build_id",
        "decided_at",
        "expires_at",
        "reviewer",
        "evidence_sha256",
    )

    for binding in BINDINGS:
        absent = document()
        del absent[binding]
        with pytest.raises(Refusal) as dropped:
            read_verdict(absent, now=NOW)
        assert dropped.value.code is RefusalCode.VERDICT_INCOMPLETE, binding

        with pytest.raises(Refusal) as blank:
            read_verdict(document(**{binding: "   "}), now=NOW)
        assert blank.value.code is RefusalCode.VERDICT_INCOMPLETE, binding

    # And past its expiry, with every binding present and readable.
    with pytest.raises(Refusal) as expired:
        read_verdict(document(), now=EXPIRES + timedelta(seconds=1))
    assert expired.value.code is RefusalCode.VERDICT_EXPIRED


def test_a_verdict_expires_at_its_expiry_not_after_it() -> None:
    """The boundary moment belongs to the expired side.

    A verdict current *at* the instant it expires would be a verdict whose
    expiry is one tick later than it says, and the fail-closed direction is the
    one that costs a re-review rather than the one that admits a stale
    signature.
    """
    last_current = read_verdict(document(), now=EXPIRES - timedelta(seconds=1))
    assert last_current.assurance is Assurance.QUALIFIED

    with pytest.raises(Refusal) as at_expiry:
        read_verdict(document(), now=EXPIRES)
    assert at_expiry.value.code is RefusalCode.VERDICT_EXPIRED


def test_a_verdict_is_not_current_before_its_decision_time() -> None:
    with pytest.raises(Refusal) as future:
        read_verdict(
            document(decided_at=(NOW + timedelta(seconds=1)).isoformat()), now=NOW
        )
    assert future.value.code is RefusalCode.VERDICT_BINDING_INVALID


def test_a_verdict_is_what_it_was_read_as_and_stays_that() -> None:
    """A signature that can be edited after it is read is not a signature.

    `deliverable_opinions` is append-only for the same reason: the seven
    bindings a reader checked and the seven a later caller acts on have to be
    the same seven, or the check was of a different document.
    """
    verdict = read_verdict(document(), now=NOW)
    assert isinstance(verdict, Verdict)

    with pytest.raises(AttributeError):
        verdict.build_id = "b0000000"  # type: ignore[misc]
    # And no instance dictionary, so there is nowhere to hang an eighth
    # binding the reader never checked.
    assert not hasattr(verdict, "__dict__")


def test_a_verdict_refuses_a_binding_it_cannot_read_as_what_it_claims() -> None:
    """Present is not the same as readable.

    A digest that is not a digest and a date that is not a date are bindings in
    name only; a reader that accepted them would bind the verdict to a string
    nobody can check it against.
    """
    unreadable: list[dict[str, str]] = [
        {"qualification_set_sha256": "not-a-digest"},
        {"qualification_set_sha256": "b" * 63},
        {"qualification_set_sha256": "B" * 64},
        {"evidence_sha256": "not-a-digest"},
        {"evidence_sha256": "e" * 63},
        {"decided_at": "the eleventh of September"},
        {"expires_at": "2027-13-01T00:00:00+00:00"},
    ]
    for override in unreadable:
        with pytest.raises(Refusal) as refused:
            read_verdict(document(**override), now=NOW)
        assert refused.value.code is RefusalCode.VERDICT_BINDING_INVALID, override


def test_a_verdict_refuses_a_timestamp_with_no_offset() -> None:
    """An expiry with no offset is an expiry in an unstated zone.

    It also cannot be compared with an aware `now` without raising, so refusing
    it here is what keeps the comparison below a decision rather than a crash.
    """
    for binding in ("decided_at", "expires_at"):
        naive = document(**{binding: "2027-09-11T09:00:00"})
        with pytest.raises(Refusal) as refused:
            read_verdict(naive, now=NOW)
        assert refused.value.code is RefusalCode.VERDICT_BINDING_INVALID, binding


def test_a_verdict_refuses_a_naive_current_time() -> None:
    with pytest.raises(Refusal) as refused:
        read_verdict(document(), now=NOW.replace(tzinfo=None))
    assert refused.value.code is RefusalCode.VERDICT_BINDING_INVALID


def test_a_verdict_refuses_an_expiry_that_does_not_follow_its_date() -> None:
    """A signature that expired before it was signed was never current.

    Refused as an unreadable binding rather than as an expired verdict: nothing
    about it was ever valid, so "it has expired" would be the wrong reason.
    """
    for expires in (DECIDED, DECIDED - timedelta(seconds=1)):
        with pytest.raises(Refusal) as refused:
            read_verdict(document(expires_at=expires.isoformat()), now=NOW)
        assert refused.value.code is RefusalCode.VERDICT_BINDING_INVALID


def test_a_verdict_refuses_a_field_the_seven_do_not_declare() -> None:
    """`extra="forbid"`, for the same reason the canonical envelope has it.

    An eighth key is either a binding nobody agreed to or a note the reader
    would silently drop, and a verdict carrying an unread condition is a
    verdict whose meaning depends on who read it.
    """
    with pytest.raises(Refusal) as refused:
        read_verdict(document(scope="screening only"), now=NOW)
    assert refused.value.code is RefusalCode.VERDICT_UNDECLARED_FIELD


def test_a_verdict_refuses_a_document_that_is_not_one() -> None:
    """The outer shape, before any binding is looked at."""
    bodies: tuple[object, ...] = (None, [], "qualified", 7)
    for body in bodies:
        with pytest.raises(Refusal) as refused:
            read_verdict(body, now=NOW)
        assert refused.value.code is RefusalCode.VERDICT_INCOMPLETE


def test_a_verdict_carries_its_human_text_across_the_boundary() -> None:
    """Reviewer and provider are human-authored and reach a stored record.

    `CLAUDE.md` "Boundary text": a bare `str` on that path is a defect, and the
    bidi override is the reason -- a reviewer's name that renders backwards
    signs something other than what the bytes say.
    """
    with pytest.raises(Refusal) as refused:
        read_verdict(document(reviewer="R. Mehta\u202e, credit risk"), now=NOW)
    assert refused.value.code is RefusalCode.BOUNDARY_TEXT_INVALID
