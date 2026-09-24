"""Each document is read by the extractor its bytes call for (§44.6).

One extractor per pack, defaulting to plain text, meant a PDF admitted without
the caller remembering to say so was tokenised as UTF-8 -- or refused as
unreadable -- and a mixed pack could not be admitted at all. The choice is now
made per document, from its content, never its filename; and anything an
extractor raises reaches the caller as a typed code with nothing behind it.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from test_pdf_extraction import minimal_pdf

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.extract import (
    Extractor,
    ExtractorDispatch,
    PlainTextExtractor,
    Token,
    dispatch_by_content,
    text_fallback,
)
from caos.evidence.ingest import Document, admit_pack, prepare_pack
from caos.evidence.pdf import PdfExtractor
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

SECRET = "Confidential covenant headroom 4.2x"
PDF = minimal_pdf([SECRET])
TEXT = b"Credit memo\nLeverage is 3.4x on a net basis.\n"
ENCRYPTED = minimal_pdf(
    [SECRET],
    trailer=b"/Encrypt << /Filter /Standard /V 1 /R 2 /O <00> /U <00> /P -1 >>"
    b" /ID [<00> <00>] ",
)
# Cut through the cross-reference table: pdfminer raises an end-of-file error
# its `_pages` guard never caught.
CORRUPT = PDF[: len(PDF) // 2]
SCANNED = minimal_pdf([])


def _document(name: str, data: bytes) -> Document:
    return Document(filename=BoundaryText.of(name), data=data)


def _identities(conn: StoreConnection, sources: list[UUID]) -> list[str]:
    names = []
    for source in sources:
        row = conn.execute(
            "SELECT extractor_identity FROM source_extractions WHERE source_id = %s",
            (source,),
        ).fetchone()
        assert row is not None
        names.append(json.loads(str(row[0]))["name"])
    return names


def _rows(conn: StoreConnection) -> int:
    total = 0
    for table in ("sources", "source_tokens", "source_blocks", "source_extractions"):
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        total += int(row[0])
    return total


def test_dispatch_reads_the_bytes_not_the_name() -> None:
    assert isinstance(dispatch_by_content(PDF), PdfExtractor)
    assert isinstance(dispatch_by_content(TEXT), PlainTextExtractor)
    # A header after some leading junk is still a PDF, as readers accept it.
    assert isinstance(dispatch_by_content(b"\n" * 1000 + PDF), PdfExtractor)
    assert isinstance(dispatch_by_content(b" " * 1024 + PDF), PlainTextExtractor)
    extractor: Extractor = dispatch_by_content(b"")
    assert isinstance(extractor, PlainTextExtractor)


def test_a_mixed_text_and_pdf_pack_admits_each_through_its_own_extractor(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("memo.txt", TEXT), _document("report.pdf", PDF)],
    )
    assert _identities(conn, sources) == ["caos.plain-text", "caos.pdfminer"]
    first = conn.execute(
        "SELECT text FROM source_tokens WHERE source_id = %s ORDER BY token_id LIMIT 1",
        (sources[1],),
    ).fetchone()
    assert first == ("Confidential",)


def test_a_pdf_named_txt_is_still_read_as_pdf(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("report.txt", PDF), _document("memo.pdf", TEXT)],
    )
    assert _identities(conn, sources) == ["caos.pdfminer", "caos.plain-text"]


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        pytest.param(CORRUPT, RefusalCode.SOURCE_NOT_READABLE, id="corrupt"),
        pytest.param(ENCRYPTED, RefusalCode.SOURCE_ENCRYPTED, id="encrypted"),
        pytest.param(SCANNED, RefusalCode.SOURCE_HAS_NO_TEXT, id="scanned"),
    ],
)
def test_a_mixed_pack_with_one_bad_pdf_leaves_no_rows(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    bad: bytes,
    code: RefusalCode,
) -> None:
    conn, case_id = case
    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[
                _document("memo.txt", TEXT),
                _document("good.pdf", PDF),
                _document("bad.pdf", bad),
            ],
        )
    assert caught.value.code is code
    assert _rows(conn) == 0


def test_an_encrypted_pdf_is_refused_as_encrypted(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[_document("locked.pdf", ENCRYPTED)],
        )
    assert caught.value.code is RefusalCode.SOURCE_ENCRYPTED
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert _rows(conn) == 0


class _Explodes:
    """An extractor whose failure message quotes the document, as pdfminer's do."""

    identity = PlainTextExtractor().identity

    def extract(self, data: bytes) -> list[Token]:
        raise RuntimeError(data.decode("latin-1"))


def _dispatch_raises(data: bytes) -> Extractor:
    raise KeyError(data)


_FAILURES: dict[str, tuple[ExtractorDispatch, bytes, RefusalCode]] = {
    "corrupt": (dispatch_by_content, CORRUPT, RefusalCode.SOURCE_NOT_READABLE),
    "encrypted": (dispatch_by_content, ENCRYPTED, RefusalCode.SOURCE_ENCRYPTED),
    "extractor raises": (
        lambda data: cast(Extractor, _Explodes()),
        SECRET.encode(),
        RefusalCode.SOURCE_NOT_READABLE,
    ),
    "dispatch raises": (
        _dispatch_raises,
        SECRET.encode(),
        RefusalCode.SOURCE_NOT_READABLE,
    ),
}


@pytest.mark.parametrize("failure", _FAILURES)
def test_a_refusal_and_its_logs_carry_no_document_text(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """pdfminer's messages quote the bytes it choked on; so may any extractor.
    The refusal, its chain and every log line carry the code alone."""
    dispatch, data, code = _FAILURES[failure]
    conn, case_id = case
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[_document("memo.txt", TEXT), _document("secret.pdf", data)],
            dispatch=dispatch,
        )
    assert caught.value.code is code
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    rendered = "".join(traceback.format_exception(caught.value))
    for word in ("Confidential", "covenant", "Leverage"):
        assert word not in rendered
        assert word not in caplog.text
    assert _rows(conn) == 0


def test_pdfminer_never_logs_document_text_through_this_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """pdfminer logs content-stream tokens at DEBUG; none may reach a handler."""
    import caos.evidence.ingest  # noqa: F401 -- installs the guard

    with caplog.at_level(logging.DEBUG):
        PdfExtractor().extract(PDF)
    assert SECRET not in caplog.text
    assert not [r for r in caplog.records if r.name.startswith("pdfminer")]


def test_plain_text_beginning_with_a_pdf_header_is_read_as_pdf_and_refused() -> None:
    """Deliberate (§44.6): bytes that begin by declaring a PDF are parsed as
    one; a memo whose first bytes are a PDF header is refused, never re-read
    as text, so a corrupt PDF cannot be admitted as garbage tokens."""
    memo = b"%PDF-1.7 is the version our template uses.\n" + SECRET.encode()
    assert isinstance(dispatch_by_content(memo), PdfExtractor)


def test_a_text_that_mentions_a_pdf_header_near_its_top_is_read_as_text(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """CF-074: a memo naming the format its issuer files in, in its first
    kilobyte, is a memo. It was sent to the PDF extractor and refused, so a
    readable document could not be admitted for one phrase in it. A header
    past the first byte is a PDF's only when the document also ends as one."""
    memo = TEXT + b"The issuer files its reports as %PDF-1.7 documents.\n"
    assert isinstance(dispatch_by_content(memo), PlainTextExtractor)
    conn, case_id = case
    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("memo.txt", memo)],
    )
    assert _identities(conn, sources) == ["caos.plain-text"]


@pytest.mark.parametrize(
    "junk",
    [
        pytest.param(b"\n" * 1000, id="blank-lines"),
        pytest.param(b"\x00\x05\x16junk\xff\xfe" * 10, id="binary"),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n\r\n", id="http"
        ),
    ],
)
def test_a_pdf_with_leading_junk_before_its_header_is_still_read_as_pdf(
    case: tuple[StoreConnection, UUID], tmp_path: Path, junk: bytes
) -> None:
    """Readers accept a header anywhere in the first kilobyte of a file whose
    end-of-file marker is in its last one, and pdfminer reads through the
    junk to the document's own objects."""
    data = junk + PDF
    assert isinstance(dispatch_by_content(data), PdfExtractor)
    conn, case_id = case
    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("report.pdf", data)],
    )
    assert _identities(conn, sources) == ["caos.pdfminer"]
    first = conn.execute(
        "SELECT text FROM source_tokens WHERE source_id = %s ORDER BY token_id LIMIT 1",
        (sources[0],),
    ).fetchone()
    assert first == ("Confidential",)


# N8: a short note that names both markers, the header past its first byte.
MARKERS_NOTE = (
    b"IT note: every PDF file starts with %PDF-1.7 and ends with %%EOF.\n"
    b"No action needed.\n"
)


def test_a_text_naming_both_pdf_markers_is_read_as_text_when_no_pdf_parses(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """N8: a note under a kilobyte that names `%PDF-` and `%%EOF` meets both
    of CF-074's tests, so it went to the PDF reader and was refused
    `SOURCE_NOT_READABLE`: a readable document no one could admit. Its
    header is past its first byte, so when no PDF parses it is read as the
    text it is, under the plain-text identity."""
    assert isinstance(dispatch_by_content(MARKERS_NOTE), PdfExtractor)
    assert text_fallback(MARKERS_NOTE)
    conn, case_id = case

    sources = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[_document("it-note.txt", MARKERS_NOTE)],
    )

    assert _identities(conn, sources) == ["caos.plain-text"]
    blocks = conn.execute(
        "SELECT text FROM source_blocks WHERE source_id = %s ORDER BY block_id",
        (sources[0],),
    ).fetchall()
    assert [row[0] for row in blocks] == MARKERS_NOTE.decode().splitlines()


def test_only_a_header_past_the_first_byte_falls_back_to_text() -> None:
    """Bytes that begin as a PDF are refused when they are not one (§44.6),
    never admitted as garbage tokens; bytes that are neither a PDF nor UTF-8
    are refused by both readers; and a caller's own dispatch is its own
    answer, with no fallback behind it."""
    assert not text_fallback(b"%PDF-1.7 as our template says. %%EOF")
    assert not text_fallback(TEXT) and not text_fallback(PDF)
    unreadable = b"\xff\xfe junk %PDF-1.4 \x00\x81 trailer %%EOF"
    assert text_fallback(unreadable)
    forced = cast(ExtractorDispatch, lambda data: PdfExtractor())
    for data, dispatch in (
        (CORRUPT, dispatch_by_content),
        (unreadable, dispatch_by_content),
        (MARKERS_NOTE, forced),
    ):
        with pytest.raises(Refusal) as refused:
            prepare_pack([_document("x", data)], dispatch=dispatch)
        assert refused.value.code is RefusalCode.SOURCE_NOT_READABLE
        assert refused.value.__context__ is None and refused.value.__cause__ is None


def test_the_pre_spend_check_reads_a_document_as_admission_does() -> None:
    """The qualification harness's key check reads each document to judge
    whether a key could anchor in it, and raises what admission would refuse:
    a note naming both markers is text to both now, and a corrupt PDF is
    refused by both."""
    from caos.qualification.harness import _extracted

    tokens = _extracted(MARKERS_NOTE)
    assert tokens == PlainTextExtractor().extract(MARKERS_NOTE)
    with pytest.raises(Refusal) as refused:
        _extracted(CORRUPT)
    assert refused.value.code is RefusalCode.SOURCE_NOT_READABLE
