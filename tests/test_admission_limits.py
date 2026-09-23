"""Limits before the expensive step, and a deadline both extractors keep (§44.1/§44.2).

Nothing bounded a pack before this: a document held whole in memory, extracted
whole before any ceiling was consulted. `AdmissionLimits` states the numbers
host policy accepts, `admit_pack` refuses a pack that crosses the cheap ones
(document count, pack bytes, one document's bytes) before any extractor runs,
and each extractor refuses the expensive ones (pages, tokens, time) as it walks
its own document -- cooperatively, so a document already over a ceiling stops
without finishing the rest of the walk that would have proven it.
"""

from __future__ import annotations

import resource
import subprocess
import sys
import time
import zlib
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, cast
from uuid import UUID

import pytest
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from test_pdf_extraction import LEFT_MARGIN, raw_pdf

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import extract as extract_module
from caos.evidence import ingest as ingest_module
from caos.evidence import pdf as pdf_module
from caos.evidence.extract import (
    DEFAULT_LIMITS,
    AdmissionLimits,
    Extractor,
    PlainTextExtractor,
    Token,
)
from caos.evidence.ingest import (
    Document,
    admit_pack,
    admit_prepared,
    prepare_pack,
    put_pack,
)
from caos.evidence.pdf import PdfExtractor, walk_pages
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.cases import lock_case

TEXT = b"alpha beta\ngamma delta\n"


def _document(name: str, data: bytes) -> Document:
    return Document(filename=BoundaryText.of(name), data=data)


def _limits(  # noqa: PLR0913 -- every field of AdmissionLimits, keyword-only
    *,
    max_documents: int = DEFAULT_LIMITS.max_documents,
    max_document_bytes: int = DEFAULT_LIMITS.max_document_bytes,
    max_pack_bytes: int = DEFAULT_LIMITS.max_pack_bytes,
    max_pages: int = DEFAULT_LIMITS.max_pages,
    max_tokens: int = DEFAULT_LIMITS.max_tokens,
    max_seconds: float = DEFAULT_LIMITS.max_seconds,
    max_decoded_bytes: int = DEFAULT_LIMITS.max_decoded_bytes,
    max_pack_tokens: int = DEFAULT_LIMITS.max_pack_tokens,
) -> AdmissionLimits:
    return AdmissionLimits(
        max_documents=max_documents,
        max_document_bytes=max_document_bytes,
        max_pack_bytes=max_pack_bytes,
        max_pages=max_pages,
        max_tokens=max_tokens,
        max_seconds=max_seconds,
        max_decoded_bytes=max_decoded_bytes,
        max_pack_tokens=max_pack_tokens,
    )


def _rows(conn: StoreConnection) -> int:
    total = 0
    for table in ("sources", "source_tokens", "source_blocks", "source_extractions"):
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        total += int(row[0])
    return total


class _Spy:
    """Records whether it was ever asked to extract; never really is."""

    identity = PlainTextExtractor().identity
    called = False

    def extract(
        self, data: bytes, *, limits: AdmissionLimits, deadline: float
    ) -> list[Token]:
        type(self).called = True
        return PlainTextExtractor().extract(data, limits=limits, deadline=deadline)


def test_an_oversized_document_is_refused_before_extraction(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    _Spy.called = False
    tiny = _limits(max_document_bytes=4)

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[_document("memo.txt", TEXT)],
            dispatch=lambda data: cast(Extractor, _Spy()),
            limits=tiny,
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert _Spy.called is False, "the ceiling refused it before any extractor ran"
    assert _rows(conn) == 0


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(_limits(max_documents=1), id="too many documents"),
        pytest.param(_limits(max_pack_bytes=len(TEXT)), id="too many bytes total"),
    ],
)
def test_a_pack_over_the_document_or_byte_ceiling_is_refused(
    case: tuple[StoreConnection, UUID], tmp_path: Path, limits: AdmissionLimits
) -> None:
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[_document("one.txt", TEXT), _document("two.txt", TEXT)],
            limits=limits,
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert _rows(conn) == 0


def test_every_document_reaches_the_volume_before_the_case_lock(
    case: tuple[StoreConnection, UUID], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DL-7: each put is a Files API upload on Databricks, and fifty of them
    ran inside the transaction holding `cases ... FOR UPDATE` -- so every
    fenced write of every run in the case waited behind an admission, because
    `lock_run` takes the case lock first. The uploads are content-addressed
    and an orphan is harmless, so they happen before the lock is taken."""
    conn, case_id = case
    order: list[str] = []
    real_lock = lock_case

    def watched_lock(connection: StoreConnection, identifier: UUID) -> None:
        order.append("lock")
        real_lock(connection, identifier)

    class _Watched(BlobStore):
        def put(self, data: bytes) -> str:
            order.append("put")
            return super().put(data)

    monkeypatch.setattr(ingest_module, "lock_case", watched_lock)
    pack = prepare_pack([_document("one.txt", TEXT), _document("two.txt", b"gamma\n")])

    stored = put_pack(_Watched(tmp_path), pack)
    admitted = admit_prepared(conn, case_id, pack, stored)

    assert len(admitted) == 2
    assert order == ["put", "put", "lock"]
    digests = conn.execute(
        "SELECT document_sha256 FROM sources WHERE case_id = %s ORDER BY filename",
        (case_id,),
    ).fetchall()
    assert [row[0] for row in digests] == [
        BlobStore(tmp_path).put(one.document.data) for one in pack.documents
    ]
    conn.rollback()


def test_a_pack_over_the_token_ceiling_stops_at_the_document_that_crosses_it() -> None:
    """AS-2: `max_tokens` bounds one document, so fifty documents each inside
    it were 25M token objects -- and briefly two copies of them -- in the one
    App process. The pack's own ceiling is checked as each document is
    extracted, so the pack that crosses it never reaches the one after."""
    extracted: list[str] = []

    class _Counted:
        identity = PlainTextExtractor().identity

        def extract(
            self, data: bytes, *, limits: AdmissionLimits, deadline: float
        ) -> list[Token]:
            extracted.append(data.decode())
            return PlainTextExtractor().extract(data, limits=limits, deadline=deadline)

    documents = [_document(f"{n}.txt", b"alpha beta gamma\n") for n in range(3)]

    with pytest.raises(Refusal) as caught:
        prepare_pack(
            documents,
            dispatch=lambda data: cast(Extractor, _Counted()),
            limits=_limits(max_pack_tokens=5),
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert len(extracted) == 2, "the third document was never extracted"
    # Under the ceiling the same pack prepares whole.
    pack = prepare_pack(documents, limits=_limits(max_pack_tokens=9))
    assert len(pack.documents) == 3


def _run_length(content: bytes) -> bytes:
    """`content` as a PDF RunLengthDecode stream, run by run.

    A length byte of 257 - n repeats the next byte n times, so two encoded
    bytes become up to 128 decoded ones: the expansion pdfminer's `rldecode`
    performs into a Python list with no bound of its own.
    """
    out = bytearray()
    position = 0
    while position < len(content):
        run = content[position : position + 1]
        length = 1
        while (
            length < 128
            and position + length < len(content)
            and content[position + length : position + length + 1] == run
        ):
            length += 1
        if length > 1:
            out += bytes([257 - length]) + run
        else:
            out += b"\x00" + run
        position += length
    return bytes(out + b"\x80")


def multi_page_pdf(
    contents: list[bytes], *, flate: bool = False, run_length: bool = False
) -> bytes:
    """A PDF of `len(contents)` pages, each page's stream exactly one entry.

    Written the way `raw_pdf` is, object by object, so the fixture stays a
    plain byte string with no dependency of its own -- extended here to more
    than the one page `raw_pdf` builds. `flate` compresses each page's stream,
    which is how a few kilobytes become megabytes once pdfminer decodes them,
    and `run_length` does the same through a filter pdfminer decodes with its
    own function rather than through `zlib`.
    """
    if flate:
        contents = [zlib.compress(content, 9) for content in contents]
    if run_length:
        contents = [_run_length(content) for content in contents]
    decode = b""
    if flate:
        decode = b" /Filter /FlateDecode"
    if run_length:
        decode = b" /Filter /RunLengthDecode"
    count = len(contents)
    font_object = 3 + 2 * count
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + i} 0 R".encode() for i in range(count))
        + b"] /Count "
        + str(count).encode()
        + b" >>",
    ]
    for i in range(count):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 "
            + str(font_object).encode()
            + b" 0 R >> >> /Contents "
            + str(3 + count + i).encode()
            + b" 0 R >>"
        )
    for content in contents:
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + decode
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    start_xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(start_xref).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def _page(line: str) -> bytes:
    return (
        f"BT\n/F1 12 Tf\n1 0 0 1 {LEFT_MARGIN:.0f} 700 Tm\n({line}) Tj\nET\n"
    ).encode("ascii")


def test_pages_over_the_ceiling_refuse_without_parsing_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page ceiling of one still has to learn a second page exists -- pulling
    it from pdfminer's own generator is unavoidable -- but must never pull a
    third. `process_page` is spied on to count exactly how many pages the
    walk actually asked pdfminer to lay out."""
    real = PDFPageInterpreter.process_page
    seen: list[PDFPage] = []

    def spy(self: PDFPageInterpreter, page: PDFPage) -> None:
        seen.append(page)
        real(self, page)

    monkeypatch.setattr(PDFPageInterpreter, "process_page", spy)
    data = multi_page_pdf([_page("Page one"), _page("Page two"), _page("Page three")])
    limits = _limits(max_pages=1)

    # The walk itself, in this process: `PdfExtractor` runs it in a child.
    with pytest.raises(Refusal) as caught:
        walk_pages(data, limits=limits, deadline=float("inf"))

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert len(seen) == 2, "the page that crossed the ceiling, never the one after it"


def test_tokens_over_the_ceiling_refuse() -> None:
    limits = _limits(max_tokens=2)

    with pytest.raises(Refusal) as caught:
        PlainTextExtractor().extract(
            b"alpha beta gamma delta\n", limits=limits, deadline=float("inf")
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE


def test_tokens_over_the_ceiling_refuse_in_a_pdf_too() -> None:
    limits = _limits(max_tokens=1)
    data = raw_pdf(b"BT\n/F1 12 Tf\n1 0 0 1 72 700 Tm\n(Alpha Beta Gamma) Tj\nET\n")

    with pytest.raises(Refusal) as caught:
        PdfExtractor().extract(data, limits=limits, deadline=float("inf"))

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE


@pytest.mark.parametrize(
    "extractor",
    [
        pytest.param(PlainTextExtractor(), id="plain text"),
        pytest.param(PdfExtractor(), id="pdf"),
    ],
)
def test_extraction_past_the_deadline_refuses(
    extractor: Extractor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deadline already past refuses on the first cooperative check -- no
    real sleep, since the deadline itself is what is manipulated."""
    import time

    past = time.monotonic() - 1
    if isinstance(extractor, PdfExtractor):
        data = raw_pdf(b"BT\n/F1 12 Tf\n1 0 0 1 72 700 Tm\n(Alpha) Tj\nET\n")
    else:
        data = TEXT

    with pytest.raises(Refusal) as caught:
        extractor.extract(data, limits=DEFAULT_LIMITS, deadline=past)

    assert caught.value.code is RefusalCode.SOURCE_EXTRACTION_TIMEOUT


def test_a_document_under_every_limit_still_admits(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Guard: the ceilings above must not narrow an ordinary admission."""
    conn, case_id = case

    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("memo.txt", TEXT)],
        limits=DEFAULT_LIMITS,
    )

    assert len(sources) == 1
    assert _rows(conn) > 0


# Phase 3 adversarial audit: a 16,926-byte page of operators took 23.2 s against
# a 2 s deadline, and a 261,529-byte page of spaces held 806 MiB, while the
# deadline was checked only between pages and pdfminer inflated without bound.
OPERATORS = b"1 w " * (16 * 1024 * 256)


def test_one_page_cannot_outrun_the_deadline() -> None:
    data = multi_page_pdf([OPERATORS], flate=True)
    limits = _limits(max_seconds=1.0)
    start = time.monotonic()

    with pytest.raises(Refusal) as caught:
        PdfExtractor().extract(data, limits=limits, deadline=start + limits.max_seconds)

    assert caught.value.code is RefusalCode.SOURCE_EXTRACTION_TIMEOUT
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert time.monotonic() - start < 10.0, (
        "stopped at the deadline, not after the page"
    )


@pytest.mark.parametrize("corrupt", [False, True], ids=["intact", "corrupt checksum"])
def test_a_stream_that_inflates_past_the_ceiling_refuses(corrupt: bool) -> None:
    """A corrupt checksum sends pdfminer to its byte-by-byte fallback inflater,
    which must meet the same budget."""
    data = multi_page_pdf([b" " * (64 * 1024 * 1024)], flate=True)
    if corrupt:
        tail = data.index(b"\nendstream")
        data = data[: tail - 4] + b"\x00\x00\x00\x00" + data[tail:]
    limits = _limits(max_decoded_bytes=1024 * 1024)

    with pytest.raises(Refusal) as caught:
        PdfExtractor().extract(data, limits=limits, deadline=float("inf"))

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_a_non_flate_stream_past_the_ceiling_refuses() -> None:
    """AS-1: the budget replaced `zlib` and nothing else, so a document whose
    streams use `LZWDecode`, `RunLengthDecode` or either ASCII filter grew
    past `max_decoded_bytes` with only the 60 s wall clock to stop it -- in
    the App process that also runs the worker, up to 32 admissions at a time.
    Every filter pdfminer decodes now draws on the one budget."""
    data = multi_page_pdf([b" " * (16 * 1024 * 1024)], run_length=True)
    limits = _limits(max_decoded_bytes=1024 * 1024)

    with pytest.raises(Refusal) as caught:
        PdfExtractor().extract(data, limits=limits, deadline=float("inf"))

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_every_filter_pdfminer_decodes_is_budgeted() -> None:
    """The names the child rebinds are the ones `PDFStream.decode` looks up."""
    import pdfminer.pdftypes

    assert all(
        callable(getattr(pdfminer.pdftypes, name))
        for name in pdf_module.BUDGETED_FILTERS
    )
    inflater = pdf_module._Inflater(4)
    bounded = pdf_module._budgeted(lambda data: data * 4, inflater)
    assert bounded(b"x") == b"xxxx"
    with pytest.raises(pdf_module._Inflated):
        bounded(b"x")
    assert inflater.exceeded is True


def test_the_child_bounds_its_address_space_where_the_platform_has_one() -> None:
    """`RLIMIT_AS` is the backstop under the budget, for a decoder still
    inside its own loop. Run in a process of its own, because that is where
    the limit belongs and macOS refuses it outright -- which the child
    tolerates, keeping its deadline and its decoded-bytes budget."""
    source = (
        "import resource, sys;"
        " sys.path.insert(0, sys.argv[1]);"
        " from caos.evidence.pdf import _Inflater, _limit_address_space;"
        " _limit_address_space(_Inflater(1024 * 1024));"
        " print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    )
    root = str(Path(__file__).resolve().parents[1])
    done = subprocess.run(
        [sys.executable, "-I", "-c", source, root],
        capture_output=True,
        check=True,
        timeout=60,
    )
    reported = int(done.stdout.split()[-1])
    ceiling = 1024 * 1024 + pdf_module.ADDRESS_SPACE_HEADROOM
    assert reported in (ceiling, resource.RLIM_INFINITY)


def test_an_ordinary_flate_page_still_extracts_in_the_child() -> None:
    """`child_main` answers the tokens `walk_pages` reads, through the budgeted
    inflater, and a child that names a code it may not answer is unreadable."""
    data = multi_page_pdf([_page("Inflated line")], flate=True)

    tokens = PdfExtractor().extract(data, limits=DEFAULT_LIMITS)

    assert [token.text for token in tokens] == ["Inflated", "line"]
    with pytest.raises(Refusal) as caught:
        pdf_module._answer(b'{"refused": "STORE_UNAVAILABLE"}', 0)
    assert caught.value.code is RefusalCode.SOURCE_NOT_READABLE


def test_a_malformed_child_answer_is_not_readable() -> None:
    with pytest.raises(Refusal) as caught:
        pdf_module._answer(b"not json", 0)

    assert caught.value.code is RefusalCode.SOURCE_NOT_READABLE


def test_walk_pages_can_return_tokens_in_process() -> None:
    tokens = walk_pages(
        raw_pdf(_page("Direct walk")), limits=DEFAULT_LIMITS, deadline=float("inf")
    )

    assert [token.text for token in tokens] == ["Direct", "walk"]


def test_walk_pages_refuses_a_past_deadline_in_process() -> None:
    with pytest.raises(Refusal) as caught:
        walk_pages(raw_pdf(_page("Late")), limits=DEFAULT_LIMITS, deadline=0.0)

    assert caught.value.code is RefusalCode.SOURCE_EXTRACTION_TIMEOUT


def test_walk_pages_skips_a_page_with_no_visible_crop() -> None:
    tokens = walk_pages(
        raw_pdf(_page("Hidden"), page=b"/CropBox [700 0 900 792]"),
        limits=DEFAULT_LIMITS,
        deadline=float("inf"),
    )

    assert tokens == []


def test_walk_pages_refuses_tokens_past_the_ceiling_in_process() -> None:
    with pytest.raises(Refusal) as caught:
        walk_pages(
            raw_pdf(_page("Alpha Beta Gamma")),
            limits=_limits(max_tokens=1),
            deadline=float("inf"),
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE


def test_the_child_entrypoint_writes_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = Token("Alpha", 1, 2, 3, 4.0, 5.0, 6.0, 7.0)

    def walked(data: bytes, *, limits: AdmissionLimits, deadline: float) -> list[Token]:
        assert data == b"pdf bytes"
        assert limits == DEFAULT_LIMITS
        assert deadline == float("inf")
        return [token]

    monkeypatch.setattr(pdf_module, "walk_pages", walked)

    assert _child_answer(monkeypatch, b"pdf bytes") == {
        "tokens": [["Alpha", 1, 2, 3, 4.0, 5.0, 6.0, 7.0]]
    }


def _encryption_error() -> BaseException:
    from pdfminer.pdfdocument import PDFEncryptionError

    return PDFEncryptionError("encrypted")


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        pytest.param(
            Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT),
            RefusalCode.SOURCE_EXTRACTION_TIMEOUT,
            id="refusal",
        ),
        pytest.param(
            pdf_module._Inflated(), RefusalCode.SOURCE_TOO_LARGE, id="inflated"
        ),
        pytest.param(MemoryError(), RefusalCode.SOURCE_TOO_LARGE, id="memory"),
        pytest.param(_encryption_error(), RefusalCode.SOURCE_ENCRYPTED, id="encrypted"),
        pytest.param(
            RuntimeError("private bytes"), RefusalCode.SOURCE_NOT_READABLE, id="other"
        ),
    ],
)
def test_the_child_entrypoint_writes_only_public_refusal_codes(
    monkeypatch: pytest.MonkeyPatch, raised: BaseException, code: RefusalCode
) -> None:
    def walked(data: bytes, *, limits: AdmissionLimits, deadline: float) -> list[Token]:
        raise raised

    monkeypatch.setattr(pdf_module, "walk_pages", walked)

    assert _child_answer(monkeypatch, b"pdf bytes") == {"refused": code}


def test_the_child_entrypoint_honours_the_inflater_overrun_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def walked(data: bytes, *, limits: AdmissionLimits, deadline: float) -> list[Token]:
        import pdfminer.pdftypes

        pdfminer.pdftypes.zlib.exceeded = True  # type: ignore[attr-defined]
        return [Token("Ignored", 1, 0, 0, 0.0, 0.0, 1.0, 1.0)]

    monkeypatch.setattr(pdf_module, "walk_pages", walked)

    assert _child_answer(monkeypatch, b"pdf bytes") == {
        "refused": RefusalCode.SOURCE_TOO_LARGE
    }


def test_the_child_inflater_keeps_one_decoded_byte_budget() -> None:
    inflater = pdf_module._Inflater(16)

    assert inflater.decompress(zlib.compress(b"small")) == b"small"
    stream = inflater.decompressobj()
    assert stream.decompress(zlib.compress(b" bytes")) == b" bytes"

    stream = inflater.decompressobj()
    with pytest.raises(pdf_module._Inflated):
        stream.decompress(zlib.compress(b"too much data"))
    assert inflater.exceeded is True


def test_the_child_inflater_preserves_zlib_incomplete_stream_errors() -> None:
    inflater = pdf_module._Inflater(16)

    with pytest.raises(zlib.error):
        inflater.decompress(zlib.compress(b"small")[:3])
    assert inflater.exceeded is False


def _child_answer(monkeypatch: pytest.MonkeyPatch, data: bytes) -> dict[str, object]:
    import json
    import sys
    from dataclasses import asdict
    from io import BytesIO
    from types import SimpleNamespace

    import pdfminer.pdftypes

    payload = json.dumps(
        {"limits": asdict(DEFAULT_LIMITS), "deadline": float("inf")}
    ).encode()
    stdin = SimpleNamespace(buffer=BytesIO(payload + b"\n" + data))
    out = BytesIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=out))
    # The child's entry point, run in *this* process: everything it rebinds in
    # pdfminer is put back, and the address-space ceiling belongs to a real
    # child (it would otherwise be set on the test runner for good).
    monkeypatch.setattr(pdf_module, "_limit_address_space", lambda inflater: None)
    zlib_module = pdfminer.pdftypes.zlib  # type: ignore[attr-defined]
    decoders = {
        name: getattr(pdfminer.pdftypes, name) for name in pdf_module.BUDGETED_FILTERS
    }
    try:
        pdf_module.child_main()
    finally:
        pdfminer.pdftypes.zlib = zlib_module  # type: ignore[attr-defined]
        for name, decoder in decoders.items():
            setattr(pdfminer.pdftypes, name, decoder)
    loaded = json.loads(out.getvalue())
    assert isinstance(loaded, dict)
    return cast(dict[str, object], loaded)


def test_one_line_past_the_token_ceiling_stops_building_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4 MiB line built two million tokens before the per-line check refused."""
    built: list[Token] = []
    real = extract_module.Token

    def counted(**fields: object) -> Token:
        token = real(**fields)  # type: ignore[arg-type]
        built.append(token)
        return token

    monkeypatch.setattr(extract_module, "Token", counted)
    limits = _limits(max_tokens=10)

    with pytest.raises(Refusal) as caught:
        PlainTextExtractor().extract(
            b"a " * 10_000, limits=limits, deadline=float("inf")
        )

    assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE
    assert len(built) <= limits.max_tokens + 1


class _Deadlines:
    """Records the deadline each document's extraction was handed."""

    identity = PlainTextExtractor().identity
    seen: ClassVar[list[float]] = []

    def extract(
        self, data: bytes, *, limits: AdmissionLimits, deadline: float
    ) -> list[Token]:
        type(self).seen.append(deadline)
        time.sleep(0.05)
        return PlainTextExtractor().extract(data, limits=limits, deadline=deadline)


def test_one_deadline_bounds_the_whole_pack_not_each_document() -> None:
    """A per-document deadline alone let fifty documents take fifty times it in
    one request (the Phase 4 audit): every document's deadline is capped by the
    pack's, so the whole extraction ends by `max_pack_seconds`."""
    _Deadlines.seen = []
    limits = replace(DEFAULT_LIMITS, max_seconds=60.0, max_pack_seconds=0.12)
    documents = [_document(f"{n}.txt", TEXT) for n in range(3)]
    started = time.monotonic()

    with pytest.raises(Refusal) as caught:
        prepare_pack(
            documents,
            dispatch=lambda data: cast(Extractor, _Deadlines()),
            limits=limits,
        )

    assert caught.value.code is RefusalCode.SOURCE_EXTRACTION_TIMEOUT
    assert _Deadlines.seen, "extraction ran"
    assert max(_Deadlines.seen) <= started + limits.max_pack_seconds + 0.01
