"""D107's citation marker, `[C<n>]`, as every host reader spells it.

A marker is exactly `[C` + ASCII digits + `]`, or several in one bracket,
`[C2, C5]` (a comma and at most one space between): the place, 1-based, of
the citation it names in the answer's own list. One pattern serves the
answer's reader (`handoff.markers`), the cell cleaner a host figure reader
uses (`unmarked`) and the prompt's rendering of an upstream body
(`qualified`), so no two of them can disagree on what a marker is.
"""

from __future__ import annotations

import re

MARKER = re.compile(r"\[(C[0-9]+(?:, ?C[0-9]+)*)\]")
# A marker as written in a table cell or an upstream body: its brackets
# possibly Markdown escapes (`\[C1\]`), which a reader sees as the marker.
_WRITTEN = re.compile(r"\\?\[(C[0-9]+(?:, ?C[0-9]+)*)\\?\]")
# The same, with the spaces before it, which go with it out of a cell: from
# the first space of a run only, so a long run of spaces is one scan.
_IN_CELL = re.compile(r"(?<! ) *" + _WRITTEN.pattern)


def unmarked(cell: str) -> str:
    """`cell` with every marker in it removed, and the spaces before each:
    what a host reader parses as a figure, status or other value, so that
    `(45) [C1]` reads as `(45)`. Pure, and nothing else in the cell moves:
    a cell with no marker is returned as it is."""
    return _IN_CELL.sub("", cell)


def qualified(text: str, module_id: str) -> str:
    """An upstream handoff's text as a downstream prompt shows it: each of
    its markers qualified by the module that wrote it, `[C3]` in CP-1's body
    shown as `[CP-1 C3]` and `[C2, C5]` as `[CP-1 C2, C5]`, which is not a
    marker, so a model that copies one neither links nor dangles a citation
    of its own. Pure over the text; the stored bytes never change."""
    return _WRITTEN.sub(lambda found: f"[{module_id} {found.group(1)}]", text)
