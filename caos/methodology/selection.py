"""Per-node evidence selection from CP-0's T8 `Source files to attach` (§95).

The gate's accepted T8 carries, per consumer module, the vendor's own
`Recommendation.source_files_to_attach` (§92, one reader of one table). The
host maps that cell to the run's pinned source-set members and delivers a
consumer only those members' blocks. Everything here is a pure function of
pinned inputs -- the accepted CP-0 Markdown, the pinned members, the module
id -- so every reader that builds a node's context (the pre-call check, the
attempt, a crash replay) selects the same blocks (invariant 10), and no host
rule invents a demand the gate did not write (invariant 4).

Three outcomes, fail-closed in the direction that matters:

- **named**: every item of the cell maps to exactly one member -- by its
  admitted filename or its document digest -- and the node is handed those
  members and nothing else.
- **whole**: the cell is empty, or names nothing the pin carries. The host
  cannot read it as a selection, so it delivers what every run before §95
  delivered. Narrowing on a guess would turn a truthful quote of an unnamed
  source into `CITATION_NOT_DELIVERED` (§88.2); a whole delivery weakens no
  invariant, and a prompt too wide for the ceiling still refuses
  `CONTEXT_OVER_CEILING` rather than truncating.
- **refused**: the cell is half-readable -- some items map and some do not --
  or an item maps to more than one member. Either narrowing to the readable
  half or widening to the whole would decide something the gate did not say,
  so the node refuses `EVIDENCE_DEMAND_UNRESOLVED` before any attempt,
  reservation or call. The discharge is a successor run whose CP-0 writes a
  cell the host can read.

§98 adds the page grain, in the form the bundle states (REF_CP-0_STEPS.md,
Step I rules 5 and 8). An item may name pages of a member --
`<filename> pages <first>-<last>` or `<filename> page <n>` -- and the node is
then handed those pages of it; a range the member cannot carry refuses as a
half-readable cell does. And the gate, which is always handed the whole pin, is
shown a source past `GATE_SOURCE_BYTES` as its page map (`gate_view`): the
largest uniform number of leading lines of every page that fits the bound, every
line whole, the rest withheld and said to be withheld in the prompt's host
preparation metadata. A page is the stored `page` of a block: a PDF's page, or
the plain-text extractor's declared sixty-line fixed-pitch page.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from caos.methodology.citation_markers import unmarked
from caos.methodology.executor import Delivery
from caos.methodology.invocation import _printable, evidence_sizes
from caos.provider import MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store.source_sets import SourceSetMember

# What the gate may be shown of one source whole, in the evidence section's
# bytes: its lines, and the headers, notes and blank lines the host puts around
# them (`invocation.evidence_sizes`, W3). Three eighths of the request
# ceiling, so two sources at the bound beside CP-0's own delivered authority
# (147,345 bytes at build 91c219fb) still leave the instructions and the
# preparation metadata room under `MAX_REQUEST_BYTES`. Past it a source is
# shown as its page map; nothing in the tree before §98 was that large.
GATE_SOURCE_BYTES = 3 * MAX_REQUEST_BYTES // 8

# The vendor's reading of the cell (`navigation.parse_t8`) is the only reader
# of the table; this module reads its parsed row and never the Markdown.
type VendorNavigation = Any

# A cell lists files; these separate its items. A filename carrying one of them
# is matched whole first, so a single such name still reads.
_SEPARATORS = re.compile(r"[;,\n]|<br\s*/?>", re.IGNORECASE)
# Backtick, the ASCII quotes and the four curly ones, spelled by code point so
# no lookalike character sits in the source.
_WRAPPING = "`'\"" + "".join(map(chr, (0x201C, 0x201D, 0x2018, 0x2019)))
_DIGEST = re.compile(r"[0-9a-f]{64}")
# Step I rule 5's page form, after the filename: `pages 13-31` or `page 7`,
# optionally parenthesised, hyphen or en dash. A number longer than
# `_PAGE_DIGITS` is past any page an admission can carry
# (`AdmissionLimits.max_pages`) and is refused before `int` reads it.
# Possessive quantifiers (F32): with backtracking, one cell of a name, a long
# run of spaces and a word is cubic in the run's length, and a table row may
# carry 65,000 spaces. An item past `_MAX_ITEM_CHARS` names nothing a pin
# carries and is never handed to the expression.
_PAGES = re.compile(
    r"(?P<name>.+?)\s++\(?\s*+pages?\s++(?P<first>\d+)"
    r"(?:\s*+[-" + chr(0x2013) + r"]\s*+(?P<last>\d+))?\s*+\)?",
    re.IGNORECASE | re.ASCII,
)
_PAGE_DIGITS = 6
# Where a page phrase may begin after a name (`_unmapped_fault`, F497).
_PAGE_WORD = re.compile(r"\s++\(?\s*+pages?\b", re.IGNORECASE | re.ASCII)
_MAX_ITEM_CHARS = 512


class Basis(StrEnum):
    """Why a node was handed the members it was handed."""

    # No T8 row names the module, or its cell is empty.
    WHOLE_NO_DEMAND = "WHOLE_NO_DEMAND"
    # The cell names nothing the pin carries: not a selection the host can act on.
    WHOLE_UNMAPPED = "WHOLE_UNMAPPED"
    # Every item mapped to exactly one pinned member.
    NAMED = "NAMED"
    # The gate, handed the whole pin with a source past `GATE_SOURCE_BYTES`
    # shown as its page map (§98).
    PAGE_MAP = "PAGE_MAP"


@dataclass(frozen=True, slots=True)
class Selection:
    """The members one node is handed; `source_ids` is None for the whole pin.

    `pages` narrows a named member to the pages its item named (§98); a member
    absent from it is handed whole. `page_maps` is the gate's: each source it
    was shown as a page map, with what the map shows.
    """

    basis: Basis
    source_ids: frozenset[UUID] | None
    pages: Mapping[UUID, frozenset[int]] = field(default_factory=dict)
    page_maps: Mapping[UUID, Mapping[str, int]] = field(default_factory=dict)

    @property
    def whole(self) -> bool:
        return self.source_ids is None and not self.pages and not self.page_maps

    def delivers(self, source_id: UUID, page: int) -> bool:
        """Whether a block of `source_id` on `page` is handed to the node."""
        if self.source_ids is not None and source_id not in self.source_ids:
            return False
        named = self.pages.get(source_id)
        return named is None or page in named


def gate_view(
    delivered: Sequence[Delivery], budget: int | None = None
) -> tuple[list[Delivery], dict[UUID, dict[str, int]]]:
    """What CP-0 is shown of the whole pin (§98, the bundle's Step I rule 8).

    A source whose share of the evidence section fits `budget`
    (`GATE_SOURCE_BYTES` when None, read at the call) is shown whole, exactly
    as before. The share is every byte the section spends on it
    (`invocation.evidence_sizes`, W3): each block's UTF-8 text and the host's
    text around it -- a header per run, a run's `hidden` note, the blank
    lines. It was the text alone, and a scan, whose every line carried a note,
    passed the bound and then the ceiling. Past it the source is shown as its
    page map: the largest uniform number `k` of leading blocks of every page
    whose total still fits, each block whole, in the delivered order, so every
    page appears. A map that cannot hold one whole block a page refuses
    `CONTEXT_OVER_CEILING` -- the prompt's own refusal, never a trimmed line.
    Pure over the pinned delivery, so every reader of the gate's context shows
    it the same lines. Returns the shown blocks and, per mapped source, what
    its map shows, for the prompt to say.
    """
    bound = GATE_SOURCE_BYTES if budget is None else budget
    by_page = _pages(delivered)
    caps = _caps(by_page, bound)
    if 0 in caps.values():
        raise Refusal(RefusalCode.CONTEXT_OVER_CEILING)
    return _view(delivered, by_page, caps)


def pack_view(
    delivered: Sequence[Delivery],
    measure: Callable[[list[Delivery], dict[UUID, dict[str, int]]], int],
    limit: int,
    *,
    source_bound: int | None = None,
) -> tuple[list[Delivery], dict[UUID, dict[str, int]]]:
    """What a node is shown of its delivery so its whole request fits
    `limit` (D116, N157): `measure` is the request a view would send, in
    bytes, and the view starts as `gate_view` at `source_bound` (the gate's
    per-source bound; None for a consumer, which has none).

    Past `limit`, the largest sources become page maps first: one bound `B`
    on every source's evidence share, each source past it cut to its largest
    uniform leading lines a page within `B` (at least one, so every page
    appears), re-measured and lowered until the request fits. At one line a
    page and still over, it refuses `CONTEXT_OVER_CEILING`. Pure over its
    inputs, so every reader shows the node the same lines.
    """
    by_page = _pages(delivered)
    shares = {s: sum(map(sum, pages.values())) for s, pages in by_page.items()}
    bound = max(shares.values(), default=0) if source_bound is None else source_bound
    caps = _caps(by_page, bound)
    if 0 in caps.values():
        raise Refusal(RefusalCode.CONTEXT_OVER_CEILING)
    while True:
        shown, maps = _view(delivered, by_page, caps)
        over = measure(shown, maps) - limit
        if over <= 0:
            return shown, maps
        if bound == 0:
            raise Refusal(RefusalCode.CONTEXT_OVER_CEILING)
        target = _shown_bytes(by_page, caps) - over
        bound = _largest_bound(by_page, target, bound - 1)
        caps = {s: max(1, k) for s, k in _caps(by_page, bound).items()}


def _pages(delivered: Sequence[Delivery]) -> dict[UUID, dict[int, list[int]]]:
    """Each source's evidence bytes, line by line, by page, in delivered order."""
    by_page: dict[UUID, dict[int, list[int]]] = {}
    for item, size in zip(delivered, evidence_sizes(delivered), strict=True):
        by_page.setdefault(item.source_id, {}).setdefault(item.page, []).append(size)
    return by_page


def _caps(
    by_page: Mapping[UUID, Mapping[int, list[int]]], bound: int
) -> dict[UUID, int]:
    """The leading lines a page of each source past `bound` that fit it."""
    return {
        source_id: _leading(pages.values(), bound)
        for source_id, pages in by_page.items()
        if sum(map(sum, pages.values())) > bound
    }


def _shown_bytes(
    by_page: Mapping[UUID, Mapping[int, list[int]]], caps: Mapping[UUID, int]
) -> int:
    """The evidence bytes a view under `caps` spends on its sources."""
    return sum(
        sum(sum(sizes[: caps.get(source_id, len(sizes))]) for sizes in pages.values())
        for source_id, pages in by_page.items()
    )


def _largest_bound(
    by_page: Mapping[UUID, Mapping[int, list[int]]], target: int, most: int
) -> int:
    """The largest share bound in `[0, most]` whose view spends at most
    `target` evidence bytes (every source past it at one line a page or
    more), or 0 when none does. The view's bytes never fall as the bound
    rises, so the bound is found by bisection."""
    low, high = 0, max(most, 0)
    while low < high:
        middle = (low + high + 1) // 2
        caps = {s: max(1, k) for s, k in _caps(by_page, middle).items()}
        if _shown_bytes(by_page, caps) <= target:
            low = middle
        else:
            high = middle - 1
    return low


def _view(
    delivered: Sequence[Delivery],
    by_page: Mapping[UUID, Mapping[int, list[int]]],
    caps: Mapping[UUID, int],
) -> tuple[list[Delivery], dict[UUID, dict[str, int]]]:
    """The delivery with each capped source cut to its leading lines a page,
    in delivered order, and what each map shows; a cap that keeps every line
    of every page is no map."""
    maps: dict[UUID, dict[str, int]] = {}
    for source_id, k in caps.items():
        pages = by_page[source_id]
        if all(len(sizes) <= k for sizes in pages.values()):
            continue
        maps[source_id] = {
            "leading_lines_per_page": k,
            "pages": len(pages),
            "lines_shown": sum(min(k, len(sizes)) for sizes in pages.values()),
            "lines": sum(map(len, pages.values())),
        }
    shown: list[Delivery] = []
    seen: dict[tuple[UUID, int], int] = {}
    for item in delivered:
        key = (item.source_id, item.page)
        seen[key] = seen.get(key, 0) + 1
        mapped = maps.get(item.source_id)
        if mapped is None or seen[key] <= mapped["leading_lines_per_page"]:
            shown.append(item)
    return shown, maps


def _leading(pages: Iterable[Sequence[int]], bound: int) -> int:
    """The largest k with the first k blocks of every page within `bound`."""
    sizes = [list(page) for page in pages]
    k, total = 0, 0
    while True:
        step = sum(page[k] for page in sizes if k < len(page))
        if (step == 0 and all(k >= len(page) for page in sizes)) or (
            total + step > bound
        ):
            break
        total += step
        k += 1
    return k


def demand_cells(
    navigation: VendorNavigation, catalog: Mapping[str, Any], gate_markdown: bytes
) -> dict[str, str]:
    """Each consumer module's `Source files to attach` cell, from the accepted
    CP-0 Markdown through the vendor's own T8 parser and no other reader.

    The Markdown is one the caller has already verified as the accepted gate
    record's, so the parse cannot fail; if it does, the code is the one the
    gate's own validation gives an unreadable T8, and nothing of the text
    travels with it.
    """
    try:
        rows = navigation.parse_t8(
            gate_markdown.decode("utf-8"), navigation.validate_catalog(catalog)
        )
        return {str(row.module_id): str(row.source_files_to_attach) for row in rows}
    except Exception:  # noqa: BLE001 -- any failure inside is this refusal
        raise Refusal(RefusalCode.HANDOFF_INCOMPLETE) from None


def demand_items(cell: str) -> tuple[str, ...]:
    """The cell's items in written order, each stripped of whitespace and
    wrapping quotation, and the cell read without its citation markers
    (`unmarked`, D107); an empty cell has none."""
    return tuple(
        stripped
        for item in _SEPARATORS.split(unmarked(cell))
        if (stripped := item.strip().strip(_WRAPPING).strip())
    )


class Fault(StrEnum):
    """Why `select_sources` refuses a cell, by its first item at fault."""

    # The item names no pinned member, beside items that do: half-readable.
    UNKNOWN = "UNKNOWN"
    # The item names more than one member.
    AMBIGUOUS = "AMBIGUOUS"
    # The item's page range is one its member cannot carry.
    PAGES = "PAGES"
    # The item begins with a member's name, then a page phrase Step I rule
    # 5's form does not read (two ranges, say): unmapped, as UNKNOWN is.
    PAGE_FORM = "PAGE_FORM"


@dataclass(frozen=True, slots=True)
class DemandFault:
    """The item of a cell `select_sources` refuses, and why (F497). The item
    is the gate's own text: told back to its retry, never a refusal's."""

    item: str
    fault: Fault


def select_sources(
    members: Sequence[SourceSetMember],
    cell: str | None,
    *,
    last_pages: Mapping[UUID, int] | None = None,
) -> Selection:
    """The pure rule: `cell` against the pinned members, as documented above.

    Deterministic in the members' order: the answer is a set. Refuses
    `EVIDENCE_DEMAND_UNRESOLVED` for a half-readable cell, an item naming
    more than one member, or a page range its member cannot carry --
    backwards, below page one, or past `last_pages[member]`, the last page the
    pin captured of it (none known refuses every range); the refusal carries
    no item text. A member named whole and by page is handed whole.
    """
    selection, fault = _resolved(members, cell, last_pages)
    if fault is not None:
        raise Refusal(RefusalCode.EVIDENCE_DEMAND_UNRESOLVED)
    return selection


def demand_fault(
    members: Sequence[SourceSetMember],
    cell: str | None,
    *,
    last_pages: Mapping[UUID, int] | None = None,
) -> DemandFault | None:
    """The item `select_sources` would refuse `cell` for, and why, or None
    when it selects (F497): the same rule, so the gate's own acceptance can
    refuse a cell its consumers would, while a retry can still fix it."""
    return _resolved(members, cell, last_pages)[1]


def _resolved(
    members: Sequence[SourceSetMember],
    cell: str | None,
    last_pages: Mapping[UUID, int] | None,
) -> tuple[Selection, DemandFault | None]:
    """`select_sources`' rule, its refusal returned as the item at fault."""
    if cell is None:
        return Selection(Basis.WHOLE_NO_DEMAND, None), None
    whole = cell.strip().strip(_WRAPPING).strip()
    items = (whole,) if whole and _matching(members, whole) else demand_items(cell)
    if not items:
        return Selection(Basis.WHOLE_NO_DEMAND, None), None
    whole_members: set[UUID] = set()
    ranged: dict[UUID, set[int]] = {}
    unmapped: list[str] = []
    for item in items:
        source_id, named, fault = _placed(members, item, last_pages)
        if fault is not None:
            return Selection(Basis.WHOLE_NO_DEMAND, None), DemandFault(item, fault)
        if source_id is None:
            unmapped.append(item)
        elif named is None:
            whole_members.add(source_id)
        else:
            ranged.setdefault(source_id, set()).update(named)
    mapped = whole_members | set(ranged)
    if not mapped:
        return Selection(Basis.WHOLE_UNMAPPED, None), None
    if unmapped:
        return Selection(Basis.WHOLE_NO_DEMAND, None), DemandFault(
            unmapped[0], _unmapped_fault(members, unmapped[0])
        )
    pages = {
        source_id: frozenset(named)
        for source_id, named in ranged.items()
        if source_id not in whole_members
    }
    return Selection(Basis.NAMED, frozenset(mapped), pages), None


def _placed(
    members: Sequence[SourceSetMember],
    item: str,
    last_pages: Mapping[UUID, int] | None,
) -> tuple[UUID | None, range | None, Fault | None]:
    """One item's member and the pages it names of it (None: the member
    whole), or why the cell is refused for it; no member when it names none."""
    found, span = _named(members, item)
    if len(found) > 1:
        return None, None, Fault.AMBIGUOUS
    if not found:
        return None, None, None
    [source_id] = found
    if span is None:
        return source_id, None, None
    first, last = span
    if not 1 <= first <= last <= (last_pages or {}).get(source_id, 0):
        return None, None, Fault.PAGES
    return source_id, range(first, last + 1), None


def _unmapped_fault(members: Sequence[SourceSetMember], item: str) -> Fault:
    """Why an unmapped item names nothing: `PAGE_FORM` when what precedes one
    of its page words names a member by `_matching`, `_named`'s own test,
    else `UNKNOWN`. Only the retry's wording depends on it, never a verdict."""
    if len(item) <= _MAX_ITEM_CHARS:
        for word in _PAGE_WORD.finditer(item):
            name = item[: word.start()].strip().strip(_WRAPPING).strip()
            if name and _matching(members, name):
                return Fault.PAGE_FORM
    return Fault.UNKNOWN


def _named(
    members: Sequence[SourceSetMember], item: str
) -> tuple[set[UUID], tuple[int, int] | None]:
    """The members `item` names, and the page span it names of them.

    The item as a whole name first, so a filename that ends in a page phrase
    still names its member; otherwise Step I rule 5's page form, whose name
    part is matched exactly as a whole item is. A page number past
    `_PAGE_DIGITS` digits is `(0, 0)`, which every bound refuses.
    """
    found = _matching(members, item)
    if found:
        return found, None
    form = _PAGES.fullmatch(item) if len(item) <= _MAX_ITEM_CHARS else None
    if form is None:
        return found, None
    name = form["name"].strip().strip(_WRAPPING).strip()
    named = _matching(members, name)
    if not named:
        return named, None
    digits = (form["first"], form["last"] or form["first"])
    if any(len(number) > _PAGE_DIGITS for number in digits):
        return named, (0, 0)
    return named, (int(digits[0]), int(digits[1]))


def _matching(members: Sequence[SourceSetMember], item: str) -> set[UUID]:
    """The members `item` names: its admitted filename, exactly or as CP-0 was
    shown it (`_printable`, which drops invisible separators), or its document
    digest (any case). A digest names the document, so two members of one
    document both answer, and that ambiguity is the caller's to refuse."""
    digest = item.lower() if _DIGEST.fullmatch(item.lower()) else None
    return {
        member.source_id
        for member in members
        if item in (member.filename, _printable(member.filename))
        or member.document_sha256 == digest
    }
