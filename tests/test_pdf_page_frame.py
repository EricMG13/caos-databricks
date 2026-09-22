"""`page_frame`: a PDF page's box geometry from the killed, budgeted child.

Boxes and `/Rotate` only, read in the section 47 child rather than in this
process. Split out of `tests/test_evidence_page_read.py` so the operation and
the page read that calls it can land as separate changes; the read's own tests
stay beside `read_page`.
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
import zlib
from dataclasses import replace
from io import BytesIO

import pytest
from test_pdf_extraction import CROP, placed_pdf, raw_pdf

from caos.evidence import pdf
from caos.evidence.extract import DEFAULT_LIMITS
from caos.evidence.pdf import page_frame
from caos.refusals import Refusal, RefusalCode


def _xref_stream_pdf(padding: int) -> bytes:
    """A PDF whose cross-reference table is a Flate stream padded to inflate by
    `padding` bytes: reading page boxes alone decodes it."""
    base = raw_pdf(b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET")
    body = base[: base.index(b"xref\n")]
    offsets = [body.index(f"{n} 0 obj".encode()) for n in range(1, 6)]
    rows = b"\x00" + bytes(4) + (65535).to_bytes(2, "big")
    for offset in [*offsets, len(body)]:
        rows += b"\x01" + offset.to_bytes(4, "big") + bytes(2)
    data = zlib.compress(rows + bytes(padding))
    stream = (
        b"6 0 obj\n<< /Type /XRef /Size 7 /W [1 4 2] /Root 1 0 R"
        b" /Filter /FlateDecode /Length " + str(len(data)).encode() + b" >>\nstream\n"
    )
    trailer = b"\nendstream\nendobj\nstartxref\n" + str(len(body)).encode()
    return body + stream + data + trailer + b"\n%%EOF\n"


def test_page_frame_runs_in_the_killed_budgeted_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boxes and `/Rotate` only, in the §47 child: an empty environment, killed
    at the deadline, and its inflater's budget meets a stream the page tree
    needs decoded."""
    spawned: list[tuple[list[str], object]] = []
    real = subprocess.Popen

    def recorded(args: list[str], **kwargs: object) -> object:
        spawned.append((args, kwargs.get("env")))
        return real(args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "Popen", recorded)
    data = placed_pdf([("Inside", 300, 200)], rotate=90, crop=CROP)

    assert page_frame(data, 1) == pytest.approx((100, 50, 742, 562))
    assert page_frame(_xref_stream_pdf(0), 1) == pytest.approx((0, 0, 612, 792))
    assert spawned and all("-I" in a and env == {} for a, env in spawned)

    budget = replace(DEFAULT_LIMITS, max_decoded_bytes=1024 * 1024)
    refusals = []
    for document, page, limits, deadline in (
        (data, 2, DEFAULT_LIMITS, float("inf")),
        (data, 1, DEFAULT_LIMITS, time.monotonic() - 1),
        (_xref_stream_pdf(64 * 1024 * 1024), 1, budget, float("inf")),
    ):
        with pytest.raises(Refusal) as caught:
            page_frame(document, page, limits=limits, deadline=deadline)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        refusals.append(caught.value.code)

    assert refusals == [
        RefusalCode.PAGE_NOT_AVAILABLE,
        RefusalCode.SOURCE_EXTRACTION_TIMEOUT,
        RefusalCode.SOURCE_TOO_LARGE,
    ]


# `_page_crop`, `_crop_frame` and `_frame_answer` run inside the section 47
# child when `page_frame` drives them, so the parent's coverage never sees the
# lines the test above exercises. They are importable and pure, so they are
# also driven here directly -- which is what states their refusals rather than
# leaving them to a subprocess nothing measures.


def _page(data: bytes, number: int = 1) -> object:
    from pdfminer.pdfpage import PDFPage

    pages = list(PDFPage.get_pages(BytesIO(data), caching=True))
    return pages[number - 1]


def test_a_page_past_the_last_one_is_no_frame_rather_than_a_refusal() -> None:
    data = placed_pdf([("Inside", 300, 200)])
    assert pdf._page_crop(data, 2, deadline=float("inf")) is None


def test_a_document_pdfminer_cannot_parse_is_not_readable() -> None:
    with pytest.raises(Refusal, match=r"^SOURCE_NOT_READABLE$"):
        pdf._page_crop(b"%PDF-1.4\nnot a document at all\n", 1, deadline=float("inf"))


def test_a_deadline_already_past_refuses_before_the_page_is_built() -> None:
    data = placed_pdf([("Inside", 300, 200)])
    with pytest.raises(Refusal, match=r"^SOURCE_EXTRACTION_TIMEOUT$"):
        pdf._page_crop(data, 1, deadline=time.monotonic() - 1)


def test_a_rotation_that_is_not_a_quarter_turn_is_refused() -> None:
    page = _page(placed_pdf([("Inside", 300, 200)]))
    page.rotate = 45  # type: ignore[attr-defined]
    with pytest.raises(Refusal, match=r"^SOURCE_NOT_READABLE$"):
        pdf._crop_frame(page)  # type: ignore[arg-type]


def test_a_page_clipped_to_nothing_is_no_frame() -> None:
    # A cropbox disjoint from the mediabox leaves no visible area, which is not
    # an inverted rectangle to be normalised but an absence of one.
    page = _page(placed_pdf([("Inside", 300, 200)]))
    page.cropbox = (-200.0, -200.0, -100.0, -100.0)  # type: ignore[attr-defined]
    assert pdf._crop_frame(page) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "out,code",
    [
        (b'{"frame": null}', "PAGE_NOT_AVAILABLE"),
        (b'{"refused": "SOURCE_TOO_LARGE"}', "SOURCE_TOO_LARGE"),
        (b'{"refused": "STORE_UNAVAILABLE"}', "SOURCE_NOT_READABLE"),
        (b"not json", "SOURCE_NOT_READABLE"),
        (b"{}", "SOURCE_NOT_READABLE"),
        (b'{"frame": [0, 0, "wide", 1]}', "SOURCE_NOT_READABLE"),
        (b'{"frame": [0, 0, 1e999, 1]}', "SOURCE_NOT_READABLE"),
    ],
)
def test_an_answer_the_child_did_not_promise_is_never_a_frame(
    out: bytes, code: str
) -> None:
    """Only a code the child is allowed to raise crosses back as itself; every
    other answer, malformed or not, is one unreadable document."""
    with pytest.raises(Refusal, match=rf"^{code}$"):
        pdf._frame_answer(out, 0)


def test_a_finite_frame_the_child_named_crosses_back_as_itself() -> None:
    frame = pdf._frame_answer(b'{"frame": [0, 0, 612, 792]}', 0)
    assert frame == (0.0, 0.0, 612.0, 792.0)
