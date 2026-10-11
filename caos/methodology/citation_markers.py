"""D107's citation marker, `[C<n>]`, as every host reader spells it.

A marker is exactly `[C` + ASCII digits + `]`, or several in one bracket,
`[C2, C5]` (a comma and at most one space between): the place, 1-based, of
the citation it names in the answer's own list. It is read in the body as a
reader sees it (`body`): after the front matter, with Markdown's backslash
escapes read as the marks they write. One pattern and one reading serve the
answer's reader (`handoff.markers`), the prompt's rendering of an upstream
body (`qualified`, which rewrites exactly the spans `body` reads as markers)
and the cell cleaner a host figure reader uses (`unmarked`), so no two of
them can disagree on what a marker is.
"""

from __future__ import annotations

import re

MARKER = re.compile(r"\[(C[0-9]+(?:, ?C[0-9]+)*)\]")
# CommonMark's backslash escape: a backslash before ASCII punctuation is how
# Markdown writes that mark, so `\"` reads `"` (F149).
# ponytail: code spans keep their backslashes literally; unescaped here too.
ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# A run of markers in a cell, escapes and all, and the spaces before each;
# from the first space of a run only, so a long run of spaces is one scan.
_IN_CELL = re.compile(r"(?<! )(?: *\\?\[C[0-9]+(?:\\?, ?C[0-9]+)*\\?\])+")
# What a figure is written with on either side of a marker that splits it.
_FIGURE_EDGE = frozenset("0123456789.,")
# What stands for such a marker: no figure reader takes it (`4 | 5`).
_SPLIT = " | "


def _body_start(text: str) -> int:
    """Where the body begins: after the line that closes the front matter,
    when the text opens with `---` and closes it; else at the start."""
    lines = text.split("\n")
    if lines[:1] != ["---"] or "---" not in lines[1:]:
        return 0
    closing = lines.index("---", 1)
    return min(len(text), sum(len(line) + 1 for line in lines[: closing + 1]))


def body(text: str) -> str:
    """The Markdown after its front matter, with its backslash escapes read
    as the marks they write: `\\[C3\\]` is `[C3]`, as a reader sees it. The
    front matter is host identity, not analysis, so no marker stands in it."""
    return ESCAPE.sub(r"\1", text[_body_start(text) :])


def unmarked(cell: str) -> str:
    """`cell` as a host reader parses it for a figure, status or other value:
    each run of markers in it removed with the spaces before it, so that
    `(45) [C1]` reads as `(45)`, or, where it splits a figure -- figure marks
    on both sides, as in `4[C1]5` or `1,2[C1]50` -- replaced by ` | `, which
    no figure reader takes, so the two halves are never joined into another
    figure. Pure; a cell with no marker is returned as it is."""

    def replaced(found: re.Match[str]) -> str:
        before = cell[found.start() - 1 : found.start()]
        after = cell[found.end() : found.end() + 1]
        # `before` and `after` are "" at an edge, which no figure mark is.
        split = before in _FIGURE_EDGE and after in _FIGURE_EDGE
        return _SPLIT if split and not found.group().startswith(" ") else ""

    return _IN_CELL.sub(replaced, cell)


def qualified(text: str, module_id: str) -> str:
    """An upstream handoff's text as a downstream prompt shows it: each
    marker `body` reads qualified by the module that wrote it, `[C3]` in
    CP-1's body shown as `[CP-1 C3]` and `[C2, C5]` as `[CP-1 C2, C5]`,
    which is not a marker, so a model that copies one neither links nor
    dangles a citation of its own. Exactly the spans `body` reads as
    markers are rewritten, escapes included (`\\[C1\\, C2\\]`); the front
    matter and every other byte stay as stored. Pure over the text."""
    start = _body_start(text)
    rest = text[start:]
    if MARKER.search(ESCAPE.sub(r"\1", rest)) is None:
        return text
    # Each read character, and the span of `rest` it was read from.
    read: list[str] = []
    spans: list[tuple[int, int]] = []
    at = 0
    for escape in ESCAPE.finditer(rest):
        read += rest[at : escape.start()]
        spans += [(i, i + 1) for i in range(at, escape.start())]
        read.append(escape.group(1))
        spans.append((escape.start(), escape.end()))
        at = escape.end()
    read += rest[at:]
    spans += [(i, i + 1) for i in range(at, len(rest))]
    pieces: list[str] = []
    kept = 0
    for found in MARKER.finditer("".join(read)):
        begin, end = spans[found.start()][0], spans[found.end() - 1][1]
        pieces += [rest[kept:begin], f"[{module_id} {found.group(1)}]"]
        kept = end
    return text[:start] + "".join(pieces) + rest[kept:]
