"""The first obstacle between the large 10-K texts and admission.

The ledger entry: "a single token past the boundary limit refuses the whole
pack, and that is what stops the large 10-K texts". `ingest._prepare` calls
`BoundaryText.of` on every token before a block is packed, so Boeing's
71,243-character and Ford's 105,966-character single runs refuse
`BOUNDARY_TEXT_TOO_LONG` at the door -- before any line is grouped, and with
nothing the line group can do about it. Its upgrade names the extractor,
"which is where a token's boundaries are decided".

Splitting rather than refusing, for the same reason the line group splits: a
refusal leaves the document unadmissible and every honest word in it
uncitable, where a split costs only the artefact itself. What a 71,243-
character run with no whitespace in it actually is -- a base64 blob, a rule of
dashes, a mangled extraction -- is not something a reader could quote either.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import anchor_citation
from caos.evidence.extract import (
    MAX_TOKEN_CHARS,
    PlainTextExtractor,
    Token,
    nfc_pieces,
)
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection


def _tokens(text: str) -> list[Token]:
    return PlainTextExtractor().extract(text.encode("utf-8"))


def test_a_run_longer_than_the_limit_is_split_rather_than_refused() -> None:
    """The case the two 10-Ks meet. One run, no whitespace, past the bound."""
    run = "x" * (MAX_TOKEN_CHARS * 2 + 7)

    tokens = _tokens(f"before {run} after")

    texts = [token.text for token in tokens]
    assert texts[0] == "before"
    assert texts[-1] == "after"
    assert "".join(texts[1:-1]) == run, "the split must lose nothing"
    assert [len(piece) for piece in texts[1:-1]] == [
        MAX_TOKEN_CHARS,
        MAX_TOKEN_CHARS,
        7,
    ]


def test_a_run_exactly_at_the_limit_is_left_alone() -> None:
    """The boundary itself: at the limit is inside it, so nothing is split and
    no already-admitted document's tokens move."""
    run = "y" * MAX_TOKEN_CHARS

    [token] = _tokens(run)

    assert token.text == run


def test_each_piece_carries_its_own_rectangle_on_the_fixed_pitch_page() -> None:
    """The rectangles stay honest. Plain text is a declared fixed pitch, so a
    piece that starts 4,096 characters into the line starts 4,096 cells along,
    and the pieces abut rather than overlapping or leaving a gap."""
    run = "z" * (MAX_TOKEN_CHARS + 10)

    first, second = _tokens(run)

    assert first.x1 == second.x0
    assert second.x1 > second.x0
    assert first.line_id == second.line_id
    assert first.region_id == second.region_id


def test_the_split_width_is_declared_in_the_extractor_identity() -> None:
    """A reader asking why a token ends where it does has one place to look,
    and a source records the rule it was extracted under."""
    identity = json.loads(PlainTextExtractor().identity.canonical())

    assert identity["config"]["max_token_chars"] == MAX_TOKEN_CHARS
    assert identity["version"] == "3", "a changed tokenisation is a new identity"


def test_a_boeing_sized_run_admits_and_its_neighbours_stay_citable(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The point of the change, driven through real admission rather than
    asserted about the extractor.

    71,243 characters is Boeing's measured single run; Ford's is 105,966. Both
    refused `BOUNDARY_TEXT_TOO_LONG` before this, which refuses the *pack* --
    so not one word of either 10-K could be admitted, let alone cited. The
    assertion that matters is the second one: the ordinary sentences around the
    artefact anchor exactly as they would in any other document.
    """
    conn, case_id = case
    artefact = "b" * 71_243
    lines = (
        "Total debt at 31 December 2026 was USD 1,240.0m",
        artefact,
        "Cash stood at USD 310.5m",
    )
    text = "\n".join(lines) + "\n"

    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("10-k.txt"), data=text.encode())],
    )

    [rect] = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="was USD 1,240.0m"
    )
    assert rect.page == 1
    [second] = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="Cash stood at USD 310.5m"
    )
    assert second.page == 1

    # The artefact itself splits into seventeen identical pieces, so quoting
    # one is `CITATION_AMBIGUOUS` -- the anchoring rule answering correctly,
    # not the admission failing. Highlighting one of seventeen identical runs
    # would assert a precision the host does not have, which is exactly what
    # that refusal is for.
    with pytest.raises(Refusal) as caught:
        anchor_citation(
            conn, source_id=source_id, page=1, matched_text="b" * MAX_TOKEN_CHARS
        )
    assert caught.value.code is RefusalCode.CITATION_AMBIGUOUS


def test_a_split_run_is_still_refused_for_what_the_boundary_actually_guards(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Splitting forgives length and nothing else.

    `BoundaryText` refuses two different things: text that is too long, and
    text it cannot represent -- lone surrogates, Cc controls, bidirectional
    overrides. Only the first is now answered by cutting. The risk in cutting
    at all is that a long run becomes a way to smuggle the second past the
    door, so each piece is checked exactly as the whole run was, and a run far
    past the limit with an override control in it refuses as it always did.

    Written because the claim was made in `test_ingestion.py`'s docstring
    before anything checked it.
    """
    conn, case_id = case
    smuggled = "c" * (MAX_TOKEN_CHARS * 2) + "\N{RIGHT-TO-LEFT OVERRIDE}" + "c" * 50

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path / "blobs"),
            case_id=case_id,
            documents=[
                Document(filename=BoundaryText.of("x.txt"), data=smuggled.encode())
            ],
        )

    assert caught.value.code is RefusalCode.BOUNDARY_TEXT_INVALID


@pytest.mark.parametrize(
    "run",
    [
        pytest.param("x" * (MAX_TOKEN_CHARS * 2 + 7), id="ascii"),
        pytest.param("\u2adc" * 3000, id="grows-under-nfc"),
        pytest.param("e\u0301" * 3000, id="shrinks-under-nfc"),
        # Hangul jamo NFC composes, then marks it cannot: the cut falls inside
        # a combining sequence, which a slice of NFC text keeps as it is.
        pytest.param("\u1100\u1161" * 3000 + "q\u0323\u0302" * 1000, id="mixed"),
    ],
)
def test_the_pdf_cut_is_chosen_on_the_nfc_form(run: str) -> None:
    """CF-073: `BoundaryText` measures a token's NFC, so the PDF extractor's
    cut (`nfc_pieces`) chooses its points there. Every piece fits the limit
    as measured, the pieces are the run's NFC exactly, and their spans tile
    it; a run whose NFC fits is one piece, its own text as drawn."""
    import unicodedata

    normal = unicodedata.normalize("NFC", run)
    pieces = nfc_pieces(run)

    if len(normal) <= MAX_TOKEN_CHARS:
        assert pieces == [(run, 0, len(normal), len(normal))]
        return
    assert "".join(text for text, *_span in pieces) == normal
    assert all(
        len(BoundaryText.of(text).value) <= MAX_TOKEN_CHARS for text, *_ in pieces
    )
    spans = [(start, end) for _text, start, end, _of in pieces]
    assert spans[0][0] == 0 and spans[-1][1] == len(normal)
    assert all(end == start for (_, end), (start, _) in pairwise(spans))
