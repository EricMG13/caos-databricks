"""Why a glyph a PDF lays out may not be seen on the rendered page (N27).

pdfminer lays out every glyph a content stream shows, however it is painted,
so four kinds of text a reader of the rendered page does not see arrive as
ordinary words: text in render mode 3, painted neither filled nor stroked --
which is also the text layer every OCR'd scan carries over its image -- text
painted in the colour already behind it, glyphs too small to read, and text
inside optional content the document switches off. They stay evidence,
because a scan's only text is its invisible layer, and the extractor marks
each line that carries one with why (`pdf._line_tokens`), so the approver and
the model can weigh it.

`MarkingAggregator` is pdfminer's page aggregator watching the paint in
drawing order: each string's render mode and em on the page, the colours it is
painted in, what the page's filled paths had painted under each glyph when it
was drawn, and the marked-content sequences it is drawn in. Behind a glyph no
filled path covers is paper, white; an image's colours are not read, so what
is behind a glyph drawn on one is not compared. `MarkingInterpreter` is
pdfminer's interpreter deciding what that device cannot see: whether an `/OC`
sequence is optional content the document's default configuration switches
off (`OptionalContent`), read against the resources in force.

It is a reading of the paint, not a rendering: a clip, a transparency group
and a shape painted over the glyph later are not read here, where a viewer
could differ nothing is marked, and a mark is a note to weigh, never a refusal.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdevice import PDFDevice, PDFTextSeq
from pdfminer.pdfinterp import (
    PDFGraphicState,
    PDFPageInterpreter,
    PDFResourceManager,
    PDFStackT,
    PDFTextState,
)
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import PDFObjRef, PDFStream
from pdfminer.psexceptions import PSException
from pdfminer.psparser import PSLiteral, literal_name
from pdfminer.utils import Matrix, PathSegment, Rect, apply_matrix_pt, mult_matrix

from caos.evidence.extract import (
    NEAR_BACKGROUND,
    OPTIONAL_CONTENT_OFF,
    RENDER_MODE_3,
    UNDER_2PT,
)
from caos.evidence.pdf import (
    CLIP_ONLY_RENDER_MODE,
    INVISIBLE_RENDER_MODE,
    MARKED_CONTENT_DEPTH,
    NEAR_BACKGROUND_DISTANCE,
    OPTIONAL_CONTENT_GROUPS,
    OPTIONAL_CONTENT_TERMS,
    SMALLEST_READABLE_PT,
)

# Neither fills nor strokes (ISO 32000-1, 9.3.6): the same nothing-is-drawn
# glyph as `INVISIBLE_RENDER_MODE`, so the same reason marks it.
_INVISIBLE_RENDER_MODES = frozenset({INVISIBLE_RENDER_MODE, CLIP_ONLY_RENDER_MODE})

# The backdrop's grid: a page is cut into this many cells a side, and a filled
# path is noted in each cell it overlaps, so a glyph is compared with the paths
# of its own cell rather than with every path the page painted.
BACKDROP_CELLS = 8

type Rgb = tuple[float, float, float]
type Box = tuple[float, float, float, float]

PAPER: Rgb = (1.0, 1.0, 1.0)
# The render modes that fill a glyph, and those that stroke it.
_FILLED = frozenset({0, 2, 4, 6})
_STROKED = frozenset({1, 2, 5, 6})
# The colour spaces whose values are read as gray, RGB or CMYK by their count.
_READ_SPACES = frozenset(
    {"DeviceGray", "CalGray", "DeviceRGB", "CalRGB", "DeviceCMYK", "ICCBased"}
)
# The intent a group or a configuration has when it names none, and the base
# states of a default configuration this reading decides (ISO 32000-1, 8.11.4).
_VIEW = frozenset({"View"})
_BASE_STATES = frozenset({"ON", "OFF"})
# What an object pdfminer cannot read raises as it is resolved: pdfminer's own
# errors and the builtins a broken object store surfaces as -- never the
# decoded-bytes budget or memory, which the extraction child answers itself.
_UNREADABLE = (
    PSException,
    ArithmeticError,
    AssertionError,
    AttributeError,
    EOFError,
    IndexError,
    KeyError,
    RecursionError,
    TypeError,
    ValueError,
    zlib.error,
)


@dataclass(frozen=True, slots=True)
class OptionalContent:
    """A document's default optional content configuration (`/OCProperties
    /D`, ISO 32000-1, 8.11.4), read only as far as every conforming viewer
    agrees on it.

    A group is OFF when `/D /OFF` lists it, or when `/BaseState` is `/OFF`
    and `/D /ON` does not; content in a marked-content sequence under an OFF
    group -- or under a membership dictionary whose policy its groups' states
    fail -- is drawn by no viewer. Group numbers are object numbers: a group
    is an indirect object, and the configuration lists it by reference.
    """

    declared: frozenset[int]
    on: frozenset[int]
    off: frozenset[int]
    base_off: bool
    intents: frozenset[str]
    unsettled: frozenset[int]

    @classmethod
    def of(cls, catalog: object) -> OptionalContent | None:
        """The configuration `catalog` declares, or `None` for a document
        with none, or with one this reading does not decide: a list past
        `OPTIONAL_CONTENT_GROUPS`, a base state other than ON or OFF, or an
        `/Intent` or `/AS` it cannot read."""
        properties = _dict(_entry(catalog, "OCProperties"))
        config = _dict(_entry(properties, "D"))
        if properties is None or config is None:
            return None
        declared = _numbers(properties.get("OCGs"), OPTIONAL_CONTENT_GROUPS)
        on = _numbers(config.get("ON", []), OPTIONAL_CONTENT_GROUPS)
        off = _numbers(config.get("OFF", []), OPTIONAL_CONTENT_GROUPS)
        base = _name(config["BaseState"]) if "BaseState" in config else "ON"
        intents = _names(config.get("Intent"), _VIEW)
        unsettled = _unsettled(config.get("AS"))
        if (
            declared is None
            or on is None
            or off is None
            or intents is None
            or unsettled is None
            or base not in _BASE_STATES
        ):
            return None
        return cls(declared, on, off, base == "OFF", intents, unsettled)

    def state(self, number: int, group: dict[str, object]) -> bool | None:
        """Whether group `number` is ON (`True`) or OFF (`False`); `None`
        where conforming viewers could differ: a group the configuration
        does not declare, one it lists both ON and OFF, and one it switches
        off that a viewer may still draw -- by an intent the configuration
        does not consider, by its own `/View` usage, or by an automatic
        `/AS` event."""
        if number not in self.declared or (number in self.on and number in self.off):
            return None
        if number not in self.off and (number in self.on or not self.base_off):
            return True
        if number in self.unsettled or _viewed(group) or not self._considers(group):
            return None
        return False

    def drawn(self, resources: object, operand: object) -> bool | None:
        """Whether what an `/OC` marked-content sequence encloses is drawn,
        `operand` its property list or the name of one in `resources`'
        `/Properties`: a group, or a membership dictionary (`/OCMD`) whose
        `/P` policy reads its groups' states. `None` where viewers could
        differ, and for a visibility expression (`/VE`), which is not read."""
        if isinstance(operand, PSLiteral):
            operand = _entry(_entry(resources, "Properties"), literal_name(operand))
        listed = _dict(operand)
        kind = _name(_entry(listed, "Type"))
        if kind == "OCG":
            return self._group(operand)
        if kind == "OCMD" and listed is not None and "VE" not in listed:
            return self._membership(listed)
        return None

    def _group(self, value: object) -> bool | None:
        """The state of the group `value` refers to; `None` for anything but
        a reference to a group dictionary."""
        group = _dict(value)
        if (
            not isinstance(value, PDFObjRef)
            or group is None
            or _name(group.get("Type")) != "OCG"
        ):
            return None
        return self.state(value.objid, group)

    def _membership(self, membership: dict[str, object]) -> bool | None:
        """A membership dictionary's visibility by its `/P` policy (`AnyOn`
        when it names none) over its groups' states: one group or a list of
        `OPTIONAL_CONTENT_TERMS` at most. `None` when it names none, or when
        any group's state is undecided -- viewers differ on which of them
        they read first."""
        members = membership.get("OCGs")
        single = _name(_entry(members, "Type")) == "OCG"
        groups = [members] if single else _list(members, OPTIONAL_CONTENT_TERMS)
        states = [self._group(group) for group in groups or ()]
        decided = [state for state in states if state is not None]
        if not states or len(decided) < len(states):
            return None
        policy = _name(membership["P"]) if "P" in membership else "AnyOn"
        return _policy(policy, decided)

    def _considers(self, group: dict[str, object]) -> bool:
        """Whether the configuration reads the group's state at all: they
        share an intent, or the configuration's is `All`."""
        intents = _names(group.get("Intent"), _VIEW)
        return intents is not None and bool(
            "All" in self.intents or intents & self.intents
        )


class MarkedContent:
    """The marked-content sequences open where the page draws, each drawn
    (`True`), switched off (`False`) or undecided (`None`), to
    `MARKED_CONTENT_DEPTH` deep; one opened past that is counted, undecided.

    What a form XObject opens is closed when the form ends. A form that
    closes a sequence it did not open leaves the rest of the page undecided
    (`tangled`): viewers differ on whether a form's sequences reach past it.
    """

    def __init__(self) -> None:
        self.levels: list[bool | None] = []
        self.deeper = 0
        self.floors: list[int] = []
        self.off = 0
        self.tangled = False

    @property
    def depth(self) -> int:
        """How many sequences are open."""
        return len(self.levels) + self.deeper

    @property
    def hides(self) -> bool:
        """Whether an open sequence is switched off: nothing drawn now is seen."""
        return self.off > 0 and not self.tangled

    def begin(self, drawn: bool | None) -> None:
        """A sequence opens (`BMC`, `BDC`)."""
        if len(self.levels) == MARKED_CONTENT_DEPTH:
            self.deeper += 1
            return
        self.levels.append(drawn)
        self.off += drawn is False

    def end(self) -> None:
        """The innermost open sequence closes (`EMC`); one with nothing open
        since the page or its form began closes nothing."""
        if self.depth > (self.floors[-1] if self.floors else 0):
            self._close(1)
        elif self.floors:
            self.tangled = True

    def enter(self) -> None:
        """A form XObject (or an image) begins drawing."""
        self.floors.append(self.depth)

    def leave(self) -> None:
        """It ends: whatever it left open closes with it."""
        floor = self.floors.pop() if self.floors else 0
        self._close(self.depth - floor)

    def _close(self, count: int) -> None:
        deeper = min(max(count, 0), self.deeper)
        self.deeper -= deeper
        for _ in range(max(count, 0) - deeper):
            self.off -= self.levels.pop() is False


class Backdrop:
    """What the filled paths of one page had painted where, in drawing order.

    Each path is noted in the grid cells its box overlaps, and a later path
    that covers a whole cell leaves only itself there: nothing painted before
    it can be seen through it at a point it covers. `None` is a colour this
    reading does not know (an image, a pattern, a spot colour).
    """

    def __init__(self, page: Box) -> None:
        (x0, y0, x1, y1) = page
        self.page = page
        self.cell = (
            max((x1 - x0) / BACKDROP_CELLS, 1.0),
            max((y1 - y0) / BACKDROP_CELLS, 1.0),
        )
        self.cells: dict[tuple[int, int], list[tuple[Box, Rgb | None]]] = {}

    def paint(self, box: Box, colour: Rgb | None) -> None:
        """Note one filled path, or an image, over the cells it overlaps."""
        clipped = _clip(box, self.page)
        if clipped is None:
            return
        (left, bottom) = self._index(clipped[0], clipped[1])
        (right, top) = self._index(clipped[2], clipped[3])
        for column in range(left, right + 1):
            for row in range(bottom, top + 1):
                self._note((column, row), clipped, colour)

    def under(self, x: float, y: float) -> Rgb | None:
        """The colour last painted under the point, paper if nothing was."""
        for (x0, y0, x1, y1), colour in reversed(self.cells.get(self._index(x, y), [])):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return colour
        return PAPER

    def _index(self, x: float, y: float) -> tuple[int, int]:
        (width, height) = self.cell
        column = int((x - self.page[0]) // width)
        row = int((y - self.page[1]) // height)
        return (
            min(max(column, 0), BACKDROP_CELLS - 1),
            min(max(row, 0), BACKDROP_CELLS - 1),
        )

    def _note(self, key: tuple[int, int], box: Box, colour: Rgb | None) -> None:
        (column, row) = key
        (width, height) = self.cell
        cell = (
            self.page[0] + column * width,
            self.page[1] + row * height,
            self.page[0] + (column + 1) * width,
            self.page[1] + (row + 1) * height,
        )
        if _covers(box, cell):
            self.cells[key] = [(box, colour)]
        else:
            self.cells.setdefault(key, []).append((box, colour))


class MarkingAggregator(PDFPageAggregator):
    """pdfminer's page aggregator, noting for each glyph it lays out why a
    reader of the rendered page may not see it: `hidden[glyph]`, the reasons
    sorted and joined by a comma, for the glyphs that have one. A new page
    begins a new record, so the one a page's layout is walked with is its own.
    """

    def __init__(self, resources: PDFResourceManager, laparams: LAParams) -> None:
        super().__init__(resources, laparams=laparams)
        self.hidden: dict[LTChar, str] = {}
        self.backdrop = Backdrop((0.0, 0.0, 0.0, 0.0))
        self.marked = MarkedContent()

    @override
    def begin_page(self, page: PDFPage, ctm: Matrix) -> None:
        super().begin_page(page, ctm)
        self.hidden = {}
        self.backdrop = Backdrop(self.cur_item.bbox)
        self.marked = MarkedContent()

    @override
    def begin_tag(self, tag: PSLiteral, props: PDFStackT | None = None) -> None:
        """A marked-content sequence as pdfminer's own interpreter hands it
        on: an `/OC` property list is a name this device cannot look up, so
        what it encloses is undecided (`MarkingInterpreter` decides it)."""
        super().begin_tag(tag, props)
        optional = props is not None and literal_name(tag) == "OC"
        self.begin_sequence(None if optional else True)

    def begin_sequence(self, drawn: bool | None) -> None:
        """A marked-content sequence opens, what it encloses drawn, switched
        off or undecided."""
        self.marked.begin(drawn)

    @override
    def end_tag(self) -> None:
        super().end_tag()
        self.marked.end()

    @override
    def begin_figure(self, name: str, bbox: Rect, matrix: Matrix) -> None:
        super().begin_figure(name, bbox, matrix)
        self.marked.enter()

    @override
    def end_figure(self, _: str) -> None:
        super().end_figure(_)
        self.marked.leave()

    @override
    def paint_path(
        self,
        gstate: PDFGraphicState,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> None:
        super().paint_path(gstate, stroke, fill, evenodd, path)
        box = _path_box(self.ctm, path)
        if fill and box is not None:
            self.backdrop.paint(box, _rgb(gstate.ncs, gstate.ncolor))

    @override
    def render_image(self, name: str, stream: PDFStream) -> None:
        super().render_image(name, stream)
        # The image is its figure's box; its colours are not read.
        self.backdrop.paint(self.cur_item.bbox, None)

    @override
    def render_string(
        self,
        textstate: PDFTextState,
        seq: PDFTextSeq,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> None:
        """The string laid out as pdfminer lays it out, then each glyph it
        added noted: one render mode and one em hold for the whole string, and
        no path is painted between its glyphs."""
        before = len(self.cur_item)
        super().render_string(textstate, seq, ncs, graphicstate)
        (_a, _b, c, d, _e, _f) = mult_matrix(textstate.matrix, self.ctm)
        em = textstate.fontsize * math.hypot(c, d)
        switched_off = self.marked.hides
        # pdfminer's `render_char` appends each glyph it makes to the container
        # being laid out and hands back only its advance, so this string's
        # glyphs are that container's objects past `before`.
        for glyph in self.cur_item._objs[before:]:
            if isinstance(glyph, LTChar):
                reasons = self._reasons(glyph, textstate.render, em, switched_off)
                if reasons:
                    self.hidden[glyph] = reasons

    def _reasons(
        self, glyph: LTChar, render: int, em: float, switched_off: bool
    ) -> str:
        """Why `glyph` may not be seen, sorted and joined by a comma."""
        reasons = [OPTIONAL_CONTENT_OFF] if switched_off else []
        if render in _INVISIBLE_RENDER_MODES:
            reasons.append(RENDER_MODE_3)
        elif _near(_paints(render, glyph.graphicstate), self._behind(glyph)):
            reasons.append(NEAR_BACKGROUND)
        if em < SMALLEST_READABLE_PT:
            reasons.append(UNDER_2PT)
        return ",".join(sorted(reasons))

    def _behind(self, glyph: LTChar) -> Rgb | None:
        return self.backdrop.under((glyph.x0 + glyph.x1) / 2, (glyph.y0 + glyph.y1) / 2)


class MarkingInterpreter(PDFPageInterpreter):
    """pdfminer's page interpreter, deciding for its `MarkingAggregator` what
    that device cannot: whether an `/OC` marked-content sequence encloses
    optional content the document switches off, read against the document's
    default configuration and the `/Properties` of the resources in force --
    the page's, or a form XObject's own."""

    def __init__(self, rsrcmgr: PDFResourceManager, device: PDFDevice) -> None:
        super().__init__(rsrcmgr, device)
        self.document: object = None
        self.layers: OptionalContent | None = None

    @override
    def dup(self) -> MarkingInterpreter:
        """A form XObject's interpreter, reading the same configuration."""
        twin = MarkingInterpreter(self.rsrcmgr, self.device)
        (twin.document, twin.layers) = (self.document, self.layers)
        return twin

    @override
    def process_page(self, page: PDFPage) -> None:
        if page.doc is not self.document:
            self.document = page.doc
            self.layers = OptionalContent.of(page.doc.catalog)
        super().process_page(page)

    @override
    def do_BDC(self, tag: PDFStackT, props: PDFStackT) -> None:
        device = self.device
        if not isinstance(tag, PSLiteral) or not isinstance(device, MarkingAggregator):
            super().do_BDC(tag, props)
            return
        drawn: bool | None = True
        if literal_name(tag) == "OC":
            layers = self.layers
            drawn = None if layers is None else layers.drawn(self.resources, props)
        device.begin_sequence(drawn)


def _paints(render: int, graphicstate: PDFGraphicState) -> list[Rgb | None]:
    """The colours a glyph in render mode `render` is painted in."""
    paints: list[Rgb | None] = []
    if render in _FILLED:
        paints.append(_rgb(graphicstate.ncs, graphicstate.ncolor))
    if render in _STROKED:
        paints.append(_rgb(graphicstate.scs, graphicstate.scolor))
    return paints


def _near(paints: list[Rgb | None], behind: Rgb | None) -> bool:
    """Whether every colour a glyph is painted in is the colour behind it."""
    if behind is None or not paints:
        return False
    return all(
        paint is not None
        and max(abs(mine - theirs) for mine, theirs in zip(paint, behind, strict=True))
        <= NEAR_BACKGROUND_DISTANCE
        for paint in paints
    )


def _rgb(space: PDFColorSpace, value: object) -> Rgb | None:
    """A gray, RGB or CMYK colour as RGB on 0..1; `None` for any other."""
    components = _components(value)
    if components is None or space.name not in _READ_SPACES:
        return None
    if len(components) == 1:
        return (components[0], components[0], components[0])
    if len(components) == 3:
        return (components[0], components[1], components[2])
    if len(components) == 4:
        (cyan, magenta, yellow, black) = components
        return (
            1.0 - min(1.0, cyan + black),
            1.0 - min(1.0, magenta + black),
            1.0 - min(1.0, yellow + black),
        )
    return None


def _components(value: object) -> tuple[float, ...] | None:
    """A colour's numeric components on 0..1, or `None` when it has others."""
    values = value if isinstance(value, tuple | list) else (value,)
    if not all(
        isinstance(one, int | float) and not isinstance(one, bool) for one in values
    ):
        return None
    numbers = [float(one) for one in values]
    if not all(math.isfinite(one) for one in numbers):
        return None
    return tuple(min(max(one, 0.0), 1.0) for one in numbers)


def _path_box(ctm: Matrix, path: Sequence[PathSegment]) -> Box | None:
    """One subpath's box on the page, or `None` for a path with several.

    pdfminer paints a path of several subpaths one subpath at a time through
    this same method, so each is noted by itself; the box of the whole would
    cover the space between them.
    """
    if sum(1 for segment in path if segment[0] == "m") != 1:
        return None
    points = [
        apply_matrix_pt(ctm, (float(coords[at]), float(coords[at + 1])))
        for segment in path
        for coords in (segment[1:],)
        for at in range(0, len(coords) - 1, 2)
    ]
    if not points:
        return None
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _clip(box: Box, page: Box) -> Box | None:
    """`box` within the page, or `None` when it misses it."""
    clipped = (
        max(box[0], page[0]),
        max(box[1], page[1]),
        min(box[2], page[2]),
        min(box[3], page[3]),
    )
    if clipped[0] > clipped[2] or clipped[1] > clipped[3]:
        return None
    return clipped


def _covers(box: Box, cell: Box) -> bool:
    return (
        box[0] <= cell[0]
        and box[1] <= cell[1]
        and cell[2] <= box[2]
        and cell[3] <= box[3]
    )


def _resolved(value: object) -> object:
    """`value`, or the object it refers to: one indirect reference is
    followed and never a chain -- a reference to a reference is no PDF
    object -- and one pdfminer cannot read is `None`."""
    if not isinstance(value, PDFObjRef):
        return value
    try:
        target = value.resolve()
    except _UNREADABLE:
        return None
    return None if isinstance(target, PDFObjRef) else target


def _dict(value: object) -> dict[str, object] | None:
    target = _resolved(value)
    return target if isinstance(target, dict) else None


def _entry(container: object, key: str) -> object:
    """`container[key]` for a dictionary `container`, `None` otherwise."""
    found = _dict(container)
    return None if found is None else found.get(key)


def _list(value: object, limit: int) -> list[object] | None:
    """An array of `limit` entries at most, `None` for anything else."""
    target = _resolved(value)
    if isinstance(target, list | tuple) and len(target) <= limit:
        return list(target)
    return None


def _name(value: object) -> str | None:
    target = _resolved(value)
    return literal_name(target) if isinstance(target, PSLiteral) else None


def _names(value: object, default: frozenset[str]) -> frozenset[str] | None:
    """A name or an array of names, `default` for none, `None` otherwise."""
    if value is None:
        return default
    single = _name(value)
    if single is not None:
        return frozenset({single})
    entries = _list(value, OPTIONAL_CONTENT_TERMS)
    names = {_name(entry) for entry in entries} if entries else {None}
    return None if None in names else frozenset(n for n in names if n is not None)


def _numbers(value: object, limit: int) -> frozenset[int] | None:
    """The object numbers of the references an array of `limit` entries at
    most holds; an entry that is no reference names no group, as viewers
    read it."""
    entries = _list(value, limit)
    if entries is None:
        return None
    return frozenset(entry.objid for entry in entries if isinstance(entry, PDFObjRef))


def _unsettled(value: object) -> frozenset[int] | None:
    """The groups a configuration's automatic `/AS` View events re-state by
    anything but the group's own `/View` usage (zoom, language, user): a
    viewer that applies them may draw a group the configuration switches off.
    `None` for an `/AS` this reading cannot read."""
    if value is None:
        return frozenset()
    entries = _list(value, OPTIONAL_CONTENT_TERMS)
    if entries is None:
        return None
    unsettled: set[int] = set()
    for entry in entries:
        usage = _dict(entry)
        groups = _numbers(_entry(usage, "OCGs"), OPTIONAL_CONTENT_GROUPS)
        if usage is None or groups is None:
            return None
        viewing = _name(usage.get("Event")) not in ("Print", "Export")
        if viewing and _names(usage.get("Category"), frozenset()) != _VIEW:
            unsettled |= groups
    return frozenset(unsettled)


def _viewed(group: dict[str, object]) -> bool:
    """Whether a group's own `/Usage /View /ViewState` is ON: a viewer that
    reads it draws the group whatever the configuration says."""
    view = _entry(_entry(group, "Usage"), "View")
    return _name(_entry(view, "ViewState")) == "ON"


def _policy(policy: str | None, states: list[bool]) -> bool | None:
    """Whether a membership dictionary's content is drawn under its `/P`
    policy, given its groups' states; `None` for a policy that is none of the
    four."""
    if policy == "AnyOn":
        return any(states)
    if policy == "AllOn":
        return all(states)
    if policy == "AnyOff":
        return not all(states)
    if policy == "AllOff":
        return not any(states)
    return None
