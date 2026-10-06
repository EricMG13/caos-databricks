"""CP-0's page-coverage claims held to the pages the host delivered (D112).

CP-0's P5 row records, per source, the pages its delivered evidence covers.
The host knows that extent exactly: a source delivered `WHOLE` is every stored
block of it, so its last page is the highest page delivered. LCR7's CP-0 wrote
"1-59 shown" for a 67-page credit agreement delivered whole, judged it cut,
and held CP-L10 (N156). An answer whose P5 row gives a whole source a shown
range ending below its last delivered page is refused `HANDOFF_MALFORMED` at
acceptance, and its guided retry is told the source, the pages delivered and
the last heading line delivered.

The reading is bounded and conservative. Only the P5 register's table rows are
read, at most `MAX_P5_LINES` of them; a row is read only when its first cell is
a source id, and a claim only when a whole cell, or one `;`- or sentence-
separated part of it, is a range from page 1 (`Pages 1-67`, `1-59 shown`, `page
anchors 1-6 shown`). A claim the parser cannot read is not a fault, and nor is
a range past the last page (an over-claim holds no consumer back).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from caos.methodology.citation_markers import unmarked
from caos.methodology.handoff import MAX_FEEDBACK_CHARS

# Table lines read past the P5 heading; a P5 longer than this is read no
# further (a pack has one row per source, and packs are tens of sources).
MAX_P5_LINES = 512
# The longest cell part read as a claim: a coverage cell, not prose.
MAX_CLAIM_CHARS = 64
# The longest delivered line read as a heading.
MAX_HEADING_CHARS = 160

_P5_HEADING = re.compile(r"#{2,6} *P5\b")
_HEADING = re.compile(r"#{1,6} ")
_PARTS = re.compile(r";|\. |<br */?>")
_CLAIM = re.compile(
    r"(?:(?:evidence|delivered) )?(?:pages?|page anchors|pp\.)? ?"
    r"1 ?[-\u2013\u2014] ?([0-9]{1,5})(?: shown)?\.?",
    re.IGNORECASE,
)
# A numbered heading of a legal or filed document: `SECTION 9.27.`,
# `ARTICLE IX`, `Item 7.`, `PART II` -- then a stop, the line's end or a
# capitalised title, so a cross-reference ("Section 2.01 hereof") is not one;
# the number is atomic, so "2.01" cannot be read as "2" and a stop.
_SECTION = re.compile(
    r"(?:ARTICLE|Article|SECTION|Section|ITEM|Item|PART|Part) +"
    r"(?>[0-9]+(?:\.[0-9]+)*[A-Za-z]?|[IVXLC]+)(?:[.:]|$| +[A-Z])"
)


@dataclass(frozen=True, slots=True)
class CoverageFault:
    """A P5 row giving a wholly delivered source fewer pages than it has."""

    source_id: UUID
    claimed: int
    delivered: int


def _p5_rows(markdown: str) -> Iterable[list[str]]:
    """The P5 register's table rows as stripped cells, at most `MAX_P5_LINES`
    lines past its heading, up to the next heading."""
    lines = iter(markdown.splitlines())
    for line in lines:
        if _P5_HEADING.match(line):
            break
    for _n, line in zip(range(MAX_P5_LINES), lines, strict=False):
        if _HEADING.match(line):
            return
        text = line.strip()
        if text.startswith("|"):
            yield [cell.strip() for cell in text.strip("|").split("|")]


def _source(cell: str) -> UUID | None:
    try:
        return UUID(cell.strip("`* "))
    except ValueError:
        return None


def coverage_claims(markdown: str) -> list[tuple[UUID, int]]:
    """(source, last page claimed) for each range from page 1 a P5 row states,
    in written order; a row whose first cell is not a source id, and a cell
    part that is not a range from page 1 alone, say nothing."""
    claims: list[tuple[UUID, int]] = []
    for cells in _p5_rows(markdown):
        source = _source(cells[0]) if cells else None
        if source is None:
            continue
        claims += [(source, end) for cell in cells[1:] for end in _ends(cell)]
    return claims


def _ends(cell: str) -> Iterable[int]:
    """The last page of each range from page 1 the cell, or one of its parts,
    is alone; a part longer than `MAX_CLAIM_CHARS` is prose, not a claim."""
    for part in _PARTS.split(unmarked(cell)):
        stated = part.strip()
        if len(stated) <= MAX_CLAIM_CHARS and (found := _CLAIM.fullmatch(stated)):
            yield int(found.group(1))


def coverage_faults(
    markdown: str,
    last_pages: Mapping[UUID, int],
    headed: Mapping[UUID, Collection[int]],
) -> list[CoverageFault]:
    """Each source in `last_pages` -- the wholly delivered ones, by their last
    delivered page -- whose P5 row claims a range ending below it, once, at
    its first such claim, and only where a page past the claim holds a
    heading line (`headed`, by `heading_pages`): pages the claim leaves out
    that carry no heading -- signatures, a pricing grid -- are not worth a
    whole CP-0 retry (LRV1's 58 of 59)."""
    faults: dict[UUID, CoverageFault] = {}
    for source, claimed in coverage_claims(markdown):
        last = last_pages.get(source)
        if (
            last is not None
            and claimed < last
            and source not in faults
            and any(page > claimed for page in headed.get(source, ()))
        ):
            faults[source] = CoverageFault(source, claimed, last)
    return list(faults.values())


def _is_heading(line: str) -> bool:
    text = line.strip()
    return len(text) <= MAX_HEADING_CHARS and _SECTION.match(text) is not None


def heading_pages(lines: Iterable[tuple[int, str]]) -> frozenset[int]:
    """The pages among `(page, line)` holding a line `last_heading` reads as
    a numbered heading."""
    return frozenset(page for page, line in lines if _is_heading(line))


def last_heading(lines: Iterable[tuple[int, str]]) -> tuple[int, str] | None:
    """The last numbered heading among `(page, line)` in delivered order, as
    (page, line), or None when no line reads as one."""
    found: tuple[int, str] | None = None
    for page, line in lines:
        if _is_heading(line):
            found = (page, line.strip())
    return found


def coverage_message(
    fault: CoverageFault, filename: str, heading: tuple[int, str] | None
) -> str:
    """What the retry is told of `fault`: the source, the pages delivered and,
    when one reads as such, the last heading line delivered. Within
    `MAX_FEEDBACK_CHARS`, so `_bounded`'s cut never drops the closing
    instruction: past it, the heading goes, then the filename (F522's way)."""
    variants = [(filename, heading), (filename, None), ("", None)]
    for name, shown in variants:
        told = _message(fault, name, shown)
        if len(told) <= MAX_FEEDBACK_CHARS:
            return told
    return told


def _message(
    fault: CoverageFault, filename: str, heading: tuple[int, str] | None
) -> str:
    named = f" ({filename})" if filename else ""
    where = (
        f'; its last heading line delivered, on page {heading[0]}, is "{heading[1]}"'
        if heading is not None
        else ""
    )
    return (
        f"P5 gives source {fault.source_id}{named} pages 1-{fault.claimed},"
        f" but the host delivered it WHOLE, pages 1-{fault.delivered}{where};"
        " correct its P5 row and every finding, gap and T8 status drawn from"
        " the shorter extent"
    )
