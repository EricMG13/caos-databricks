"""Why a glyph a PDF lays out may not be seen on the rendered page (N27).

pdfminer lays out every glyph a content stream shows, however it is painted,
so three kinds of text a reader of the rendered page does not see arrive as
ordinary words: text in render mode 3, painted neither filled nor stroked --
which is also the text layer every OCR'd scan carries over its image -- text
painted in the colour already behind it, and glyphs too small to read. They
stay evidence, because a scan's only text is its invisible layer, and the
extractor marks each line that carries one with why (`pdf._line_tokens`), so
the approver and the model can weigh it.

`MarkingAggregator` is pdfminer's page aggregator watching the paint in
drawing order: each string's render mode and em on the page, the colours it is
painted in, and what the page's filled paths had painted under each glyph when
it was drawn. Behind a glyph no filled path covers is paper, white; an image's
colours are not read, so what is behind a glyph drawn on one is not compared.
It is a reading of the paint, not a rendering: a clip, a transparency group, an
optional-content layer that is off and a shape painted over the glyph later are
not read here, and a mark is a note to weigh, never a refusal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import override

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdevice import PDFTextSeq
from pdfminer.pdfinterp import PDFGraphicState, PDFResourceManager, PDFTextState
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import PDFStream
from pdfminer.utils import Matrix, PathSegment, apply_matrix_pt, mult_matrix

from caos.evidence.extract import NEAR_BACKGROUND, RENDER_MODE_3, UNDER_2PT
from caos.evidence.pdf import (
    INVISIBLE_RENDER_MODE,
    NEAR_BACKGROUND_DISTANCE,
    SMALLEST_READABLE_PT,
)

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

    @override
    def begin_page(self, page: PDFPage, ctm: Matrix) -> None:
        super().begin_page(page, ctm)
        self.hidden = {}
        self.backdrop = Backdrop(self.cur_item.bbox)

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
        # pdfminer's `render_char` appends each glyph it makes to the container
        # being laid out and hands back only its advance, so this string's
        # glyphs are that container's objects past `before`.
        for glyph in self.cur_item._objs[before:]:
            if isinstance(glyph, LTChar):
                reasons = self._reasons(glyph, textstate.render, em)
                if reasons:
                    self.hidden[glyph] = reasons

    def _reasons(self, glyph: LTChar, render: int, em: float) -> str:
        """Why `glyph` may not be seen, sorted and joined by a comma."""
        reasons = []
        if render == INVISIBLE_RENDER_MODE:
            reasons.append(RENDER_MODE_3)
        elif _near(_paints(render, glyph.graphicstate), self._behind(glyph)):
            reasons.append(NEAR_BACKGROUND)
        if em < SMALLEST_READABLE_PT:
            reasons.append(UNDER_2PT)
        return ",".join(reasons)

    def _behind(self, glyph: LTChar) -> Rgb | None:
        return self.backdrop.under((glyph.x0 + glyph.x1) / 2, (glyph.y0 + glyph.y1) / 2)


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
