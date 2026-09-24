"""The journey's mixed pack: one plain-text report and one small PDF.

Both carry the quote the deterministic provider cites (`QUOTE`, whole words,
exactly once), so either document anchors it; the journey worker cites the PDF,
which is what puts a rectangle over rendered words in the evidence drawer. The
PDF is written out by hand, as `tests/test_pdf_extraction.py` writes its
fixtures, so it needs no library.

`insufficient_pack` is the deliberately insufficient-evidence case: one
earnings note and no covenant certificate. It carries the same quote once,
so CP-0 and CP-L10 still anchor
what they cite; what it lacks is what CP-5 blocks on, and the journey worker
keys its `Blocked` verdict on this document being the evidence pinned.
"""

from __future__ import annotations

from canonical_fixtures import QUOTE

TEXT_NAME = "journey-earnings-update.txt"
PDF_NAME = "journey-covenant-certificate.pdf"
INSUFFICIENT_NAME = "journey-earnings-note.txt"

TEXT_LINES = (
    "Journey Holdings quarterly earnings update",
    f"{QUOTE} was 1,240 million",
    "Reported leverage conflicts across the covenant certificate and the "
    "earnings release",
)
PDF_LINES = (
    "Journey Holdings covenant compliance certificate",
    f"{QUOTE} stood at 1,240 million",
    "Net leverage was within the covenant level",
)
INSUFFICIENT_LINES = (
    "Journey Holdings earnings note",
    f"{QUOTE} was 1,240 million",
    "No covenant compliance certificate was delivered for the period",
)


def _pdf(lines: tuple[str, ...]) -> bytes:
    """A one-page Helvetica PDF drawing one line per `Tj`, 24 pt apart."""
    text = "BT\n/F1 12 Tf\n"
    for index, line in enumerate(lines):
        text += f"1 0 0 1 72 {700 - 24 * index} Tm\n({line}) Tj\n"
    content = (text + "ET\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def journey_pack() -> list[tuple[str, bytes]]:
    """(filename, bytes) for each document, in upload order."""
    return [
        (TEXT_NAME, ("\n".join(TEXT_LINES) + "\n").encode("utf-8")),
        (PDF_NAME, _pdf(PDF_LINES)),
    ]


def insufficient_pack() -> list[tuple[str, bytes]]:
    """The one-note pack whose evidence does not support the work."""
    return [(INSUFFICIENT_NAME, ("\n".join(INSUFFICIENT_LINES) + "\n").encode("utf-8"))]
