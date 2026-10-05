"""D107: the body cites by `[C<n>]` markers and quotes no source text.

The excerpt lives only in `citations` (D105). A marker names the citation at
its 1-based place in the list; `linked` now means a marker names it; a marker
naming no citation refuses the answer as malformed, told by its number; a
citation no marker names is kept, not linked to a statement, and never
refuses. Every citation accepted since D107 keeps its place (`marker`) in the
record, so a downstream reader can resolve a marker it reads in a body.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from canonical_fixtures import CATALOG, CONTRACT, wire
from test_handoff_record import CP0, CP0_MD, SECRET, _citation, _linked
from test_nonblocking_citations import LOST, _edited, _excerpt_record

from caos.methodology import handoff
from caos.methodology.handoff import (
    ADVISORY,
    RECORD_CODEC_VERSION,
    CanonicalRecord,
    _decoded_record,
    markers,
    parse_response,
    record_bytes,
)
from caos.refusals import Refusal, RefusalCode

FRONT = "---\nmodule_id: CP-0\nnote: [C8]\n---\n\n"


def test_markers_reads_the_exact_form_and_its_list_form_only() -> None:
    """Exactly `[C` + ASCII digits + `]`, or several in one bracket; read
    after the front matter, backslash escapes as the marks they write and
    fenced code included. A near miss is text, never a marker."""
    body = (
        FRONT
        + "A [C1] b [C2, C3] c [C4,C5] d \\[C6\\] and [C0001].\n"
        + "```\n[C7]\n```\n"
        + "Near: [c3] [C 3] [C3-C5] [C3\u2013C5] [C3,4] [C] [Cx] [C\u0663]"
        + " [C1,  C2] [C1 , C2] [ C3] C3.\n"
    )
    assert markers(body) == (1, 2, 3, 4, 5, 6, 1, 7)
    assert markers("No front matter [C2], again [C2].") == (2, 2)
    # Past nine digits a marker names no citation, whatever its value.
    assert markers("[C123456789] [C1234567890] [C0000000001]") == (123456789, 0, 0)


def test_linked_means_a_marker_names_the_citation_not_its_quotation() -> None:
    """A body that quotes the excerpt verbatim and writes no marker leaves it
    unlinked; one that writes the marker and no quote links it (D107)."""
    quoted = wire(f"{FRONT}Recorded source p1, as quoted.\n".encode(), [_citation()])
    assert _linked(quoted) == (False,)
    marked = wire(f"{FRONT}The source was recorded [C1].\n".encode(), [_citation()])
    assert _linked(marked) == (True,)
    both = [_citation(), _citation(matched_text="Recorded source p2")]
    assert _linked(wire(f"{FRONT}Both [C2, C1].\n".encode(), both)) == (True, True)


@pytest.mark.parametrize(
    "written", ["[C0]", "[C2]", "[C02]", "[C1, C9]", "\\[C2\\]", "[C0000000001]"]
)
def test_a_marker_that_names_no_citation_refuses_the_answer(written: str) -> None:
    """Which citation `[C9]` beside 8 meant is undecidable: structural,
    `HANDOFF_MALFORMED`, with nothing of the answer in the refusal."""
    body = wire(CP0_MD.replace(b"[C1]", written.encode()), [_citation()])
    with pytest.raises(Refusal) as refused:
        parse_response(body)
    assert refused.value.code is RefusalCode.HANDOFF_MALFORMED
    assert SECRET not in repr(refused.value)


def test_the_dangling_marker_line_names_each_marker_and_the_count() -> None:
    """The retry is told each marker that names nothing, once, as `[C<n>]`
    -- its own number, never its text -- and the places it must stay within.
    It is the refusal's own check, so not advisory."""
    body = wire(CP0_MD + b"\nSee [C0] and [C9], and [C9] again.\n", [_citation()])
    lines = handoff.feedback_lines(CONTRACT, CATALOG, CP0, body)
    [line] = [line for line in lines if line.startswith("host marker check")]
    assert line == (
        "host marker check: the Markdown body writes [C0], [C9], but the answer"
        " has 1 citation, so they name none; a marker [C<n>] names the citation"
        " at place n of the list, from [C1] to [C1]"
    )
    assert SECRET not in "".join(lines)


def test_the_unmarked_line_is_advisory_and_hints_at_near_misses() -> None:
    """A citation no marker names is told by number, as advice; a bracket
    that reads like a marker and is not one is counted, never quoted."""
    two = [_citation(), _citation(matched_text="Recorded source p2")]
    plain = handoff.feedback_lines(CONTRACT, CATALOG, CP0, wire(CP0_MD, two))
    [line] = [line for line in plain if line.startswith("host marker check")]
    assert line == (
        "host marker check: citation 2 of 2 is named by no [C<n>] marker in the"
        " Markdown body (numbered from 1 in the order given)" + ADVISORY
    )
    near = wire(CP0_MD + b"\nAlso [c2] and [C 2].\n", two)
    lines = handoff.feedback_lines(CONTRACT, CATALOG, CP0, near)
    [hinted] = [line for line in lines if line.startswith("host marker check")]
    assert "the body writes 2 bracketed forms the host does not read as a marker" in (
        hinted
    )
    assert "[c2]" not in hinted and hinted.endswith(ADVISORY)
    marked = wire(CP0_MD + b"\nAnd [C2].\n", two)
    assert not [
        line
        for line in handoff.feedback_lines(CONTRACT, CATALOG, CP0, marked)
        if line.startswith("host marker check")
    ]


def _placed(
    anchored: tuple[int | None, ...], kept: tuple[int | None, ...]
) -> CanonicalRecord:
    """An excerpt record whose anchored and unverified citations hold these
    places (`marker`)."""
    [one] = _excerpt_record().citations
    return _excerpt_record(
        citations=tuple(dataclasses.replace(one, marker=n) for n in anchored),
        unverified=tuple(dataclasses.replace(LOST, marker=n) for n in kept),
    )


def test_every_citation_keeps_its_place_in_the_record() -> None:
    """Since D107 each citation holds its `marker`, together the places 1 to
    n, so a marker names one citation, anchored or not; a record from before
    holds none and is the bytes it was. The codec moved (rollback check)."""
    assert RECORD_CODEC_VERSION == 2
    record = _placed((1, 3), (2,))
    data = record_bytes(record)
    document = json.loads(data)
    assert [c["marker"] for c in document["citations"]] == [1, 3]
    assert document["unverified"][0]["marker"] == 2
    assert _decoded_record(data) == record
    before = _placed((None,), (None,))
    assert "marker" not in record_bytes(before).decode()
    assert _decoded_record(record_bytes(before)) == before


@pytest.mark.parametrize(
    ("anchored", "kept"),
    [((1, 2), (2,)), ((1, None), (2,)), ((2, 1), (3,)), ((1, 2), (4,)), ((0,), ())],
)
def test_places_that_are_not_one_to_n_in_order_are_not_written(
    anchored: tuple[int | None, ...], kept: tuple[int | None, ...]
) -> None:
    """A repeat, a gap, a missing place, a list out of order or a place 0."""
    with pytest.raises(ValueError):
        record_bytes(_placed(anchored, kept))


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["citations"][0].__setitem__("marker", 0),
        lambda d: d["citations"][0].__setitem__("marker", True),
        lambda d: d["citations"][0].__setitem__("marker", "1"),
        lambda d: d["unverified"][0].__setitem__("marker", 1),
        lambda d: d["unverified"][0].pop("marker"),
    ],
)
def test_a_marker_this_host_did_not_write_does_not_read(
    edit: Callable[[Any], object],
) -> None:
    with pytest.raises((ValueError, TypeError)):
        _decoded_record(_edited(edit, _placed((1,), (2,))))


def test_the_dangling_line_shows_each_marker_as_written() -> None:
    """`[C02]` is told as `[C02]`, a ten-digit `[C0000000001]` (which names
    nothing, value aside) as written, and a longer one cut to 12 digits."""
    long = "9" * 40
    body = wire(CP0_MD + f"\n[C02] [C0000000001] [C{long}]\n".encode(), [_citation()])
    [line] = [
        line
        for line in handoff.feedback_lines(CONTRACT, CATALOG, CP0, body)
        if line.startswith("host marker check")
    ]
    assert line.startswith(
        "host marker check: the Markdown body writes [C02], [C0000000001],"
        " [C999999999999...], but the answer has 1 citation"
    )


def test_unmarked_reads_a_cell_without_its_markers_and_moves_nothing_else() -> None:
    """MK1 fix round 1: CP-2G wrote `(45) [C1]` in a driver cell and CP-CF
    could never map it. A host reader parses a cell `unmarked`."""
    from decimal import Decimal

    from caos.methodology.citation_markers import unmarked
    from caos.methodology.forecast import driver_value
    from caos.methodology.selection import demand_items
    from caos.methodology.tables import figure_value
    from caos.qualification.matrix import _normalised_cell

    assert unmarked("(45) [C1]") == "(45)"
    assert driver_value(unmarked("(45) [C1]")) == Decimal(-45)
    assert unmarked("1,250.0 \\[C2, C3\\]") == "1,250.0"
    assert unmarked("(45[C1])") == "(45)"
    for cell in ("(45)", "1,250.0", " 0 ", "READY", "[c1]", "[C1,  C2]", "CF-1"):
        assert unmarked(cell) == cell
    assert figure_value(CONTRACT, "(45) [C1]") == figure_value(CONTRACT, "(45)")
    assert figure_value(CONTRACT, "2993 [C3]") == "2993"
    assert _normalised_cell("READY [C1]") == "READY"
    assert demand_items("a.txt [C1]; b.txt pages 2-3 [C2, C3]") == (
        "a.txt",
        "b.txt pages 2-3",
    )


def test_an_upstream_body_is_shown_with_its_markers_qualified() -> None:
    """`[C3]` in CP-1's body reads `[CP-1 C3]` downstream: not a marker, so
    a model that copies it neither links nor dangles a citation of its own,
    and its unmarked line gives no near-miss hint. Pure over the text."""
    from caos.methodology.citation_markers import qualified

    text = "A [C3] and \\[C2, C5\\]; [c1] [C1,  C2] stay."
    shown = qualified(text, "CP-1")
    assert shown == "A [CP-1 C3] and [CP-1 C2, C5]; [c1] [C1,  C2] stay."
    assert qualified(text, "CP-1") == shown and markers(shown) == ()
    copied = wire(f"{FRONT}As CP-1 found [CP-1 C3].\n".encode(), [_citation()])
    assert _linked(copied) == (False,)
    [line] = [
        line
        for line in handoff.feedback_lines(CONTRACT, CATALOG, CP0, copied)
        if line.startswith("host marker check")
    ]
    assert "bracketed" not in line


def test_markers_belong_only_to_an_excerpt_record() -> None:
    """A record under an earlier rule holding a marker is not this host's."""
    from test_handoff_record import _record

    from caos.evidence.citations import WHOLE_LINE

    [one] = _record(citation_rule=WHOLE_LINE).citations
    with pytest.raises(ValueError):
        record_bytes(
            _record(
                citation_rule=WHOLE_LINE,
                citations=(dataclasses.replace(one, marker=1),),
            )
        )
