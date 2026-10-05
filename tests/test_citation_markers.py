"""D107: every citation accepted since D107 keeps its place in the answer's
list (`marker`), which the body's `[C<n>]` markers name, so a downstream
reader can resolve a marker it reads in a body; a record from before holds
none and is the bytes it was.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from test_nonblocking_citations import LOST, _edited, _excerpt_record

from caos.methodology.handoff import (
    RECORD_CODEC_VERSION,
    CanonicalRecord,
    _decoded_record,
    record_bytes,
)


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
