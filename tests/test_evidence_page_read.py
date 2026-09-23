"""The pinned page read and its frame (Phase 4 Task 4.4, slice 4.4c).

`read_page` serves one page of a live source the run pinned: the token index
grouped into lines, beside the frame the stored extractor identity draws those
rectangles in (decisions 7 and 8). Everything unavailable is one
`PAGE_NOT_AVAILABLE` with nothing chained behind it.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import time
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from test_extraction_provenance import Reader
from test_pdf_extraction import (
    CROP,
    FIRST_LINE,
    FROZEN_V1_TOKENS,
    REPORT,
    SECOND_LINE,
    V1_IDENTITY,
    placed_pdf,
    raw_pdf,
)
from test_route_pinning import CATALOG_PATH, PROFILE
from test_run_inputs import SUBJECT

from caos.api.wire import PAGE_LINES_MAX
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import page as page_module
from caos.evidence import pdf as pdf_module
from caos.evidence.citations import anchor_citation
from caos.evidence.extract import (
    DEFAULT_LIMITS,
    AdmissionLimits,
    Extractor,
    ExtractorDispatch,
    ExtractorIdentity,
    Token,
    dispatch_by_content,
)
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.page import read_page
from caos.evidence.pdf import page_frame
from caos.graph.route import resolve_route
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant
from caos.store.routes import pin_route
from caos.store.run_inputs import pin_run_input
from caos.store.runs import create_case, start_run
from caos.store.source_sets import snapshot_source_set


@dataclass(frozen=True, slots=True)
class Pinned:
    conn: StoreConnection
    case_id: UUID
    run_id: UUID
    sources: list[UUID]
    blobs: BlobStore


def pin(
    conn: StoreConnection,
    case_id: UUID,
    blobs: BlobStore,
    documents: list[tuple[str, bytes]],
    reader: object | None = None,
) -> Pinned:
    """Admit `documents`, snapshot the case's set and pin a run's input to it."""
    dispatch: ExtractorDispatch = dispatch_by_content
    if reader is not None:
        dispatch = lambda _: cast(Extractor, reader)  # noqa: E731
    sources = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(BoundaryText.of(n), data) for n, data in documents],
        dispatch=dispatch,
    )
    conn.commit()
    snapshot = snapshot_source_set(conn, case_id)
    run_id = start_run(conn, case_id)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    pin_route(conn, run_id, resolve_route(catalog, PROFILE, "MARKET_DISLOCATION"))
    bundle = Bundle(CATALOG_PATH.parents[3])
    pin_run_input(conn, run_id, snapshot.version, bundle, subject=SUBJECT)
    conn.commit()
    return Pinned(conn, case_id, run_id, sources, blobs)


@pytest.fixture(autouse=True)
def forget_frames() -> Iterator[None]:
    """`page.py` remembers a document's page crops for the life of the process,
    so a test that counts children starts and leaves it empty."""
    page_module._FRAMES.clear()
    yield
    page_module._FRAMES.clear()


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


@pytest.fixture
def report(case: tuple[StoreConnection, UUID], blobs: BlobStore) -> Pinned:
    return pin(*case, blobs, [("report.pdf", REPORT)])


def page_of(pinned: Pinned, source_id: UUID, page: int = 1) -> page_module.PageRead:
    try:
        return read_page(
            pinned.conn,
            pinned.blobs,
            case_id=pinned.case_id,
            run_id=pinned.run_id,
            source_id=source_id,
            page=page,
        )
    finally:
        pinned.conn.rollback()


def refused_with_no_text(pinned: Pinned, source_id: UUID, page: int) -> None:
    with pytest.raises(Refusal) as caught:
        page_of(pinned, source_id, page)
    assert caught.value.code is RefusalCode.PAGE_NOT_AVAILABLE
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert str(caught.value) == "PAGE_NOT_AVAILABLE"


def corrupt_extraction(pinned: Pinned, source_id: UUID, database_url: str) -> None:
    """Privileged corruption, only in this test's disposable database."""
    database = urlsplit(database_url).path.removeprefix("/")
    conn = pinned.conn
    assert conn.execute("SELECT current_database()").fetchone() == (database,)
    conn.rollback()
    with conn.transaction():
        trigger = "TRIGGER extraction_is_immutable"
        conn.execute(f"ALTER TABLE source_extractions DISABLE {trigger}")
        conn.execute(
            "UPDATE source_extractions SET extraction_sha256 = %s WHERE source_id = %s",
            ("0" * 64, source_id),
        )
        conn.execute(f"ALTER TABLE source_extractions ENABLE {trigger}")


def test_a_source_outside_the_runs_pinned_version_is_evidence_not_available(
    report: Pinned,
) -> None:
    """A source admitted after the pin belongs to a later version only: the
    later run reads it, the pinned run does not -- nor another case's source."""
    later = pin(report.conn, report.case_id, report.blobs, [("l.txt", b"later")])
    other = create_case(report.conn, BoundaryText.of("Other"))
    foreign = pin(report.conn, other, report.blobs, [("x.txt", b"foreign")])

    assert [line.text for line in page_of(later, later.sources[0]).body.lines] == [
        "later"
    ]
    for source in (later.sources[0], foreign.sources[0]):
        refused_with_no_text(report, source, 1)


def test_a_withdrawn_source_page_refuses_with_no_text_in_body_or_chain(
    report: Pinned,
) -> None:
    [source] = report.sources
    assert [line.text for line in page_of(report, source).body.lines] == [
        FIRST_LINE,
        SECOND_LINE,
    ]
    writer = uuid4()
    grant(report.conn, case_id=report.case_id, user_id=writer, standing=Standing.WRITER)
    withdraw_source(
        report.conn, case_id=report.case_id, source_id=source, actor_id=writer
    )
    report.conn.commit()

    refused_with_no_text(report, source, 1)


def test_unknown_page_and_extraction_mismatch_are_the_same_private_404(
    report: Pinned, empty_database: str
) -> None:
    [source] = report.sources
    for unknown, page in ((source, 2), (source, 0), (source, 501), (uuid4(), 1)):
        refused_with_no_text(report, unknown, page)

    corrupt_extraction(report, source, empty_database)

    refused_with_no_text(report, source, 1)


def test_a_blob_whose_digest_differs_from_the_pin_refuses(report: Pinned) -> None:
    [source] = report.sources
    document = page_of(report, source).body.document_sha256
    report.blobs.path_of(document).write_bytes(REPORT.replace(b"Total", b"Fraud"))

    refused_with_no_text(report, source, 1)


@pytest.mark.parametrize(
    ("rotate", "crop", "size"),
    [
        (0, "", (612, 792)),
        (90, "", (792, 612)),
        (0, CROP, (512, 642)),
        # Rotated, the crop displays as x 100..742 and y-up 50..562.
        (90, CROP, (642, 512)),
        (180, CROP, (512, 642)),
        (270, CROP, (642, 512)),
    ],
)
def test_a_v2_frame_matches_the_crop_for_rotated_and_cropped_pdfs(
    case: tuple[StoreConnection, UUID],
    blobs: BlobStore,
    rotate: int,
    crop: str,
    size: tuple[int, int],
) -> None:
    placed = {0: (72, 700), 90: (300, 200), 180: (300, 400), 270: (300, 400)}[rotate]
    data = placed_pdf([("Inside", *placed)], rotate=rotate, crop=crop)
    pinned = pin(*case, blobs, [("placed.pdf", data)])

    read = page_of(pinned, pinned.sources[0])

    frame = read.body.frame
    assert (frame.x0, frame.y0, frame.y_axis) == (0, 0, "down")
    assert (frame.x1, frame.y1) == pytest.approx(size)
    [line] = read.body.lines
    assert line.text == "Inside"
    assert 0 <= line.x0 < line.x1 <= frame.x1 and 0 <= line.y0 < line.y1 <= frame.y1


def test_a_v1_frame_is_the_bottom_left_layout_crop(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """§44.4: a v1 row keeps its y-up rectangles, so its frame is the visible
    crop in pdfminer's layout space, y up -- not the v2 crop-relative frame."""
    data = placed_pdf([("Total", 72, 700)], crop=CROP)
    identity = ExtractorIdentity("caos.pdfminer", "1", V1_IDENTITY)
    pinned = pin(
        *case, blobs, [("v1.pdf", data)], Reader(identity, list(FROZEN_V1_TOKENS))
    )

    read = page_of(pinned, pinned.sources[0])

    frame = read.body.frame
    assert (frame.x0, frame.y0, frame.x1, frame.y1) == pytest.approx(
        (50, 100, 562, 742)
    )
    assert frame.y_axis == "up"
    [line] = read.body.lines
    (first, second) = FROZEN_V1_TOKENS
    assert (line.text, line.x0, line.y0, line.x1, line.y1) == (
        "Total debt",
        first.x0,
        first.y0,
        second.x1,
        second.y1,
    )


PLAIN: dict[str, str | int | float | bool | None] = {
    "encoding": "utf-8",
    "coordinates": "cell-top-left-pt",
    "cell_width": 4.0,
    "cell_height": 10.0,
    "margin": 5.0,
    "lines_per_page": 2,
}


def plain_reader(text: str, config: Mapping[str, Any]) -> Reader:
    """A fixed-pitch extractor recording `config`, placing one token per word."""
    tokens = []
    (width, height, margin) = (
        config[k] for k in ("cell_width", "cell_height", "margin")
    )
    for number, line in enumerate(text.splitlines()):
        page, row = divmod(number, int(config["lines_per_page"]))
        top, column = margin + row * height, 0
        for word in line.split(" "):  # the fixtures' words are single-spaced
            left = margin + column * width
            right = left + len(word) * width
            tokens.append(
                Token(word, page + 1, 0, number, left, top, right, top + height)
            )
            column += len(word) + 1
    return Reader(ExtractorIdentity("caos.plain-text", "2", dict(config)), tokens)


def test_a_plain_text_frame_comes_from_its_recorded_identity(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """The stored configuration, not today's constants, sizes the page: its
    height is the recorded rows and margins, its width the widest line."""
    text = "alpha beta\ngamma\ndelta epsilon zeta\n"
    pinned = pin(*case, blobs, [("memo.txt", text.encode())], plain_reader(text, PLAIN))
    default = pin(*case, blobs, [("default.txt", b"one two\nthree")])
    [source] = pinned.sources

    first, second = page_of(pinned, source, 1), page_of(pinned, source, 2)

    for read, width in ((first, 5 + 5 + 4 * 10), (second, 5 + 5 + 4 * 18)):
        frame = read.body.frame
        assert (frame.x0, frame.y0, frame.x1, frame.y1, frame.y_axis) == (
            0,
            0,
            width,
            5 + 5 + 10 * 2,
            "down",
        )
    assert [line.text for line in first.body.lines] == ["alpha beta", "gamma"]
    refused_with_no_text(pinned, source, 3)
    constants = page_of(default, default.sources[0]).body.frame
    assert (constants.x1, constants.y1) == (72.0 * 2 + 7.2 * 7, 72.0 * 2 + 12.0 * 60)


def test_a_cited_quote_normalizes_inside_its_page_lines(report: Pinned) -> None:
    """The rectangles a citation anchored sit wholly inside the served frame and
    each inside one served line, so one conversion places both."""
    [source] = report.sources
    rects = anchor_citation(
        report.conn, source_id=source, page=1, matched_text="USD 1,240.0m Cash and"
    )
    read = page_of(report, source)
    frame = read.body.frame
    width, height = frame.x1 - frame.x0, frame.y1 - frame.y0

    assert len(rects) == 2
    for rect, line in zip(rects, read.body.lines, strict=True):
        xs = ((rect.x0 - frame.x0) / width, (rect.x1 - frame.x0) / width)
        ys = ((rect.y0 - frame.y0) / height, (rect.y1 - frame.y0) / height)
        assert all(0 <= value <= 1 for value in (*xs, *ys))
        assert line.x0 <= rect.x0 < rect.x1 <= line.x1
        assert line.y0 <= rect.y0 < rect.y1 <= line.y1


def long_page(case: tuple[StoreConnection, UUID], blobs: BlobStore) -> Pinned:
    """One page of `PAGE_LINES_MAX + 1` lines."""
    config = {**PLAIN, "lines_per_page": PAGE_LINES_MAX + 1}
    text = "w\n" * (PAGE_LINES_MAX + 1)
    return pin(*case, blobs, [("long.txt", text.encode())], plain_reader(text, config))


def test_a_page_over_its_line_bound_is_cut_at_its_bound(
    report: Pinned, case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    pinned = long_page(case, blobs)

    read = page_of(pinned, pinned.sources[0])

    assert read.truncated and len(read.body.lines) == PAGE_LINES_MAX
    assert not page_of(report, report.sources[0]).truncated


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
    assert page_module.IO_BUDGET == 1


def test_the_page_read_declares_one_round_trip() -> None:
    """`page_frame` and its budgeted child are covered in
    `tests/test_pdf_page_frame.py`; what belongs here is the read's own budget."""
    assert page_module.IO_BUDGET == 1


def test_a_pdf_page_frame_is_read_from_the_child_once_per_document_and_page(
    report: Pinned, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS-5: every read of an evidence page started an interpreter with a 60 s
    budget, at READER standing, for a crop that is a pure function of a
    digest-addressed document and a page number. Paging through a document, or
    reopening it, re-read it every time."""
    asked: list[int] = []
    real = page_frame

    def counted(
        data: bytes, page: int, *, limits: AdmissionLimits, deadline: float
    ) -> pdf_module.Frame:
        asked.append(page)
        return real(data, page, limits=limits, deadline=deadline)

    monkeypatch.setattr(pdf_module, "page_frame", counted)
    first = page_of(report, report.sources[0])
    again = page_of(report, report.sources[0])

    assert asked == [1]
    assert again.body.frame == first.body.frame
    assert again.body.lines == first.body.lines


def test_the_remembered_frames_are_bounded_and_a_refusal_is_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache is an LRU of `FRAME_CACHE_SIZE`, and only of what the child
    answered: a deadline the load made is not a fact about a document."""
    monkeypatch.setattr(
        pdf_module, "page_frame", lambda data, page, **bounds: (0.0, 0.0, 1.0, 2.0)
    )
    for ordinal in range(page_module.FRAME_CACHE_SIZE + 5):
        crop = page_module._Crop(f"{ordinal:064x}", b"", DEFAULT_LIMITS, float("inf"))
        assert page_module._page_crop(crop, 1) == (0.0, 0.0, 1.0, 2.0)
    assert len(page_module._FRAMES) == page_module.FRAME_CACHE_SIZE
    assert ("0" * 64, 1) not in page_module._FRAMES, "the oldest was dropped"

    refused: list[int] = []

    def timed_out(data: bytes, page: int, **bounds: object) -> pdf_module.Frame:
        refused.append(page)
        raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)

    monkeypatch.setattr(pdf_module, "page_frame", timed_out)
    crop = page_module._Crop("f" * 64, b"", DEFAULT_LIMITS, float("inf"))
    assert page_module._page_crop(crop, 3) is None
    assert page_module._page_crop(crop, 3) is None
    assert refused == [3, 3]


def test_a_page_the_document_does_not_have_is_asked_of_the_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EV-7: a missing page was refused and never remembered, so every read of
    page 500 of a one-page PDF started an interpreter. The child's `null` is a
    fact of the bytes -- the page is not there, or clips to nothing -- and is
    remembered like a crop; a deadline or a budget still is not."""
    asked: list[int] = []

    def missing(data: bytes, page: int, **bounds: object) -> pdf_module.Frame:
        asked.append(page)
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)

    monkeypatch.setattr(pdf_module, "page_frame", missing)
    crop = page_module._Crop("e" * 64, b"", DEFAULT_LIMITS, float("inf"))
    for _read in range(5):
        assert page_module._page_crop(crop, 500) is None
    assert asked == [500]
    assert page_module._FRAMES[("e" * 64, 500)] is None


def test_frame_children_never_run_past_their_process_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EV-7: nothing bounded how many interpreters concurrent page reads
    started -- twelve reads of twelve missing pages ran twelve at once, each
    ~250 MiB for a large PDF, at READER standing. They queue for
    `FRAME_CHILDREN` slots now, each within its own read's deadline."""
    import threading
    import time

    running = 0
    peak = 0
    lock = threading.Lock()

    def slow(data: bytes, page: int, **bounds: object) -> pdf_module.Frame:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return (0.0, 0.0, 1.0, float(page))

    monkeypatch.setattr(pdf_module, "page_frame", slow)
    deadline = time.monotonic() + 30.0
    crop = page_module._Crop("d" * 64, b"", DEFAULT_LIMITS, deadline)
    answers: dict[int, object] = {}

    def read(page: int) -> None:
        answers[page] = page_module._page_crop(crop, page)

    threads = [threading.Thread(target=read, args=(page,)) for page in range(1, 13)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak <= page_module.FRAME_CHILDREN
    assert answers == {page: (0.0, 0.0, 1.0, float(page)) for page in range(1, 13)}


def test_one_actor_cannot_hold_both_frame_children_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N38. `FRAME_CHILDREN` bounds the whole process, not one reader: nothing
    kept a single READER's own concurrent page requests from racing for every
    slot, so a different reader's read waited out its own deadline for a
    resource one actor was hoarding. Each actor now holds at most
    `ACTOR_FRAME_CHILDREN` of the global slots at once, the way
    `ACTOR_STREAM_LIMIT` shares `caos/api/stream.py`'s `STREAM_LIMIT`: the
    hog's own second read now waits on its own share instead of ever
    contending for the slot a different actor needs.
    """
    import threading

    first_entered, release = threading.Event(), threading.Event()

    def slow(data: bytes, page: int, **bounds: object) -> pdf_module.Frame:
        first_entered.set()
        release.wait(5)
        return (0.0, 0.0, 1.0, float(page))

    monkeypatch.setattr(pdf_module, "page_frame", slow)
    hog = uuid4()
    deadline = time.monotonic() + 30.0

    def hog_read(page: int) -> None:
        crop = page_module._Crop("h" * 64, b"", DEFAULT_LIMITS, deadline, hog)
        page_module._page_crop(crop, page)

    # Two concurrent reads from the same actor: the first takes a global slot,
    # and the second -- free before this fix to race for the other one -- is
    # given time here to have done exactly that.
    threads = [threading.Thread(target=hog_read, args=(page,)) for page in (1, 2)]
    for thread in threads:
        thread.start()
    try:
        assert first_entered.wait(5), "the hog's own read never started"
        time.sleep(0.2)

        other = uuid4()
        crop = page_module._Crop(
            "o" * 64, b"", DEFAULT_LIMITS, time.monotonic() + 1.0, other
        )
        answer = page_module._page_crop(crop, 1)

        assert answer == (0.0, 0.0, 1.0, 1.0), "a different actor was starved"
    finally:
        release.set()
        for thread in threads:
            thread.join(5)


def test_a_read_whose_deadline_passes_waiting_for_a_slot_starts_no_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiting for a slot spends the read's own deadline, and a read that runs
    out of it is refused like one whose child ran out -- and not remembered."""
    import time

    asked: list[int] = []

    def answered(data: bytes, page: int, **bounds: object) -> pdf_module.Frame:
        asked.append(page)
        return (0.0, 0.0, 1.0, 1.0)

    monkeypatch.setattr(pdf_module, "page_frame", answered)
    held = [
        page_module._CHILDREN.acquire(blocking=False)
        for _slot in range(page_module.FRAME_CHILDREN)
    ]
    try:
        assert all(held)
        crop = page_module._Crop("c" * 64, b"", DEFAULT_LIMITS, time.monotonic() + 0.1)
        assert page_module._page_crop(crop, 1) is None
    finally:
        for _slot in held:
            page_module._CHILDREN.release()
    assert asked == []
    assert ("c" * 64, 1) not in page_module._FRAMES


# The identity and frame helpers refuse before any store or extractor is
# reached, so they are driven directly: every one is a fail-closed path whose
# only observable is the typed code it raises (invariant 2).

_TEXT_CONFIG: dict[str, Any] = {
    "cell_width": 6.0,
    "cell_height": 12.0,
    "margin": 18.0,
    "lines_per_page": 2,
    "coordinates": page_module.TEXT_COORDINATES,
}


@pytest.mark.parametrize(
    "stored",
    [
        "not json at all",
        "[]",
        '{"version": "1", "config": {}}',
        '{"name": 1, "version": "1", "config": {}}',
        '{"name": "caos.pdfminer", "version": "1", "config": []}',
    ],
)
def test_a_stored_identity_that_is_not_the_declared_shape_is_refused(
    stored: str,
) -> None:
    with pytest.raises(Refusal, match=r"^SOURCE_IDENTITY_INVALID$"):
        page_module._identity(stored)


@pytest.mark.parametrize("value", [None, "1", float("nan"), -1, 0])
def test_a_cell_size_that_is_not_a_positive_finite_number_is_refused(
    value: object,
) -> None:
    with pytest.raises(Refusal, match=r"^SOURCE_IDENTITY_INVALID$"):
        page_module._positive(value)
    # Zero is a margin and never a cell size, which is the whole of `zero`.
    assert value != 0 or page_module._positive(value, zero=True) == 0.0


@pytest.mark.parametrize(
    "over",
    [{"lines_per_page": 0}, {"lines_per_page": "2"}, {"coordinates": "elsewhere"}],
)
def test_a_text_frame_refuses_a_configuration_it_cannot_draw_in(
    over: dict[str, Any],
) -> None:
    with pytest.raises(Refusal, match=r"^SOURCE_IDENTITY_INVALID$"):
        page_module._text_frame({**_TEXT_CONFIG, **over}, b"one\ntwo\n", 1)


@pytest.mark.parametrize("data,page", [(b"\xff\xfe not utf-8", 1), (b"one\n", 9)])
def test_a_text_page_with_no_lines_is_unavailable_rather_than_empty(
    data: bytes, page: int
) -> None:
    with pytest.raises(Refusal, match=r"^PAGE_NOT_AVAILABLE$"):
        page_module._text_frame(_TEXT_CONFIG, data, page)


def test_a_text_frame_is_as_wide_as_its_widest_line_and_as_tall_as_its_rows() -> None:
    frame = page_module._text_frame(_TEXT_CONFIG, b"ab\nabcd\nignored\n", 1)
    # 2 margins + 4 cells wide, 2 margins + 2 rows tall, origin at the top left;
    # the third line belongs to page 2 rather than to this frame's width.
    assert (frame.x0, frame.y0, frame.x1, frame.y1, frame.y_axis) == (
        0.0,
        0.0,
        2 * 18.0 + 4 * 6.0,
        2 * 18.0 + 2 * 12.0,
        "down",
    )
