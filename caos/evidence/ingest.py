"""Admitting a pack: the only way bytes enter a case.

Invariant 1: web discovery is structurally absent -- there is no code path
from here to a network, and that is the point of there being one door.

The whole pack lands or none of it does. A half-admitted pack is a set of
documents nobody agreed to run against, and invariant 1 says a run executes
against the pinned set. This function does not commit: the caller's transaction
is what makes "whole or not at all" true, and a refusal leaves it to roll back.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import inf, isfinite
from uuid import UUID, uuid4

from caos.blobs import BlobStore
from caos.boundary_text import DEFAULT_LIMIT, BoundaryText, hides_text
from caos.digest import canonical_digest
from caos.evidence.extract import (
    DEFAULT_LIMITS,
    HIDDEN_MARKS,
    AdmissionLimits,
    Extractor,
    ExtractorDispatch,
    ExtractorIdentity,
    MarkedToken,
    Token,
    dispatch_by_content,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.cases import lock_case

# pdfminer logs tokens and content-stream operands at DEBUG and WARNING, which is
# document text. Never let it reach this process's handlers.
_PDFMINER = logging.getLogger("pdfminer")
_PDFMINER.addHandler(logging.NullHandler())
_PDFMINER.propagate = False

BLOCK_PREFIX = "b"
# What one block may carry (the group width). Not a free parameter:
# `source_blocks.text` is `BoundaryText`, so a block holds `DEFAULT_LIMIT`
# characters and no more, and any narrower width would re-number documents
# already admitted under this one -- whose rows are immutable and whose
# stored citations name the ids they were given.
GROUP_WIDTH = DEFAULT_LIMIT
# How a line wider than `GROUP_WIDTH` is cut into blocks, recorded per source as
# `source_extractions.format_version` (migration 0032) and carried by its
# output digest. 1: at the width, inside a word if that is where it fell
# (`line_groups`) -- every source admitted before CF-013. 2: between tokens only
# (`token_groups`). Both write a line that fits as one block, byte for byte, so a
# source whose lines all fit is recorded as 1 and keeps the digests every
# earlier admission of it wrote. Format 2 is also the one that carries a line's
# hidden-text mark (N27, migration 0033): a source with a mark is written as 2
# whether or not a line was cut, and packing 2 cuts nothing that fits.
PACKING_BY_WIDTH = 1
PACKING_BY_TOKEN = 2


@dataclass(frozen=True, slots=True)
class Document:
    """One document offered to a case. Its name crossed the boundary already."""

    filename: BoundaryText
    data: bytes


@dataclass(frozen=True, slots=True)
class _Block:
    """One packed block, before it is written: its id, its page, its text.

    The text is `BoundaryText` because that is what the block will be read back
    as. Packing before writing is what lets a line the boundary refuses refuse
    the pack rather than the read.
    """

    block_id: str
    page: int
    text: BoundaryText
    # Why a reader of the rendered page may not see its line (N27), or "".
    hidden: str = ""


@dataclass(frozen=True, slots=True)
class _Packed:
    """One document, extracted and packed, before any of it is written.

    One object rather than three arguments threaded through two functions --
    the shape `Execution` and `Harness` already take here. They are the whole
    of what admitting a document needs, and passing them apart made the
    signature wide enough that the argument ceiling refused it, which is the
    ceiling doing its job.
    """

    document: Document
    tokens: list[Token]
    blocks: list[_Block]
    extractor_identity: str
    output_sha256: str
    extraction_sha256: str
    # `PACKING_BY_WIDTH` or `PACKING_BY_TOKEN`: the row's `format_version`.
    packing: int


@dataclass(frozen=True, slots=True)
class PreparedPack:
    """A whole pack, extracted and packed, before any store access."""

    documents: tuple[_Packed, ...]


def admit_pack(  # noqa: PLR0913 -- one pack's store, blobs and policy, keyword-only
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    case_id: UUID,
    documents: Sequence[Document],
    dispatch: ExtractorDispatch = dispatch_by_content,
    limits: AdmissionLimits = DEFAULT_LIMITS,
) -> list[UUID]:
    """Admit every document or refuse the pack. Returns the new source ids.

    `prepare_pack`, `put_pack`, then `admit_prepared`: extraction and uploads
    before the case lock, and no commit -- the caller's transaction makes the
    pack whole or nothing.
    """
    pack = prepare_pack(documents, dispatch=dispatch, limits=limits)
    return admit_prepared(conn, case_id, pack, put_pack(blobs, pack))


def prepare_pack(
    documents: Sequence[Document],
    *,
    dispatch: ExtractorDispatch = dispatch_by_content,
    limits: AdmissionLimits = DEFAULT_LIMITS,
) -> PreparedPack:
    """Bound, extract and pack every document, touching no store.

    Each document is read by the extractor `dispatch` chooses from its own
    bytes (§44.6), so a mixed pack admits whole and a PDF named `.txt` is still
    a PDF. Text is extracted to tokens carrying page, region, line and
    rectangle, and packed into blocks -- one row each when admitted, never a
    JSON column on the source row, which is the ~8x read defect the N+1 shape
    carries.

    `limits` bounds the pack (document count, pack bytes, and the tokens its
    documents hold together) and each document (document bytes, then -- inside
    its extractor -- pages, tokens and extraction time) before the expensive
    step each ceiling guards (§44.1). Text no reader can see refuses the pack
    here too, in `_prepare`.
    """
    if not documents:
        raise Refusal(RefusalCode.SOURCE_PACK_EMPTY)
    _check_pack_limits(documents, limits)

    # Extract everything first. A document that cannot be read must refuse the
    # pack before any of it is written, not after some of it is.
    pack_deadline = time.monotonic() + limits.max_pack_seconds
    extracted: list[tuple[str, list[Token]]] = []
    packed_tokens = 0
    for document in documents:
        identity, tokens = _extract(dispatch, document, limits, pack_deadline)
        packed_tokens += len(tokens)
        if packed_tokens > limits.max_pack_tokens:
            # The pack's own ceiling, checked as each document arrives rather
            # than after all of them are in memory: fifty documents each
            # inside `max_tokens` are still one request the process cannot
            # hold (Phase 12 adversarial audit).
            raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
        extracted.append((identity, tokens))
    if any(not tokens for _identity, tokens in extracted):
        # Readable bytes, no text: a scanned page. Admitting it would put a
        # source in the pinned set that can never support a citation, and
        # invariant 11 would refuse every quote naming it at artifact time --
        # one run and one provider bill later than here.
        raise Refusal(RefusalCode.SOURCE_HAS_NO_TEXT)

    # And pack the blocks, which is where the text crosses the boundary. Here
    # rather than at the write, for the same reason the check above is here:
    # a line the boundary refuses is a line `read_evidence` refuses, so
    # admitting it would pin a source no run can read.
    #
    # One document at a time, dropping each raw token list as `_prepare`
    # replaces it: `_prepare` builds a second `Token` per token, so holding
    # every raw list would keep two copies of the whole pack rather than two
    # copies of one document.
    prepared: list[_Packed] = []
    for position, document in enumerate(documents):
        identity, tokens = extracted[position]
        prepared.append(_prepare(document, tokens, identity))
        extracted[position] = (identity, [])
    return PreparedPack(tuple(prepared))


def put_pack(blobs: BlobStore, pack: PreparedPack) -> list[str]:
    """Every document of a prepared pack in the blob store, in pack order: the
    digests `admit_prepared` then inserts.

    Called before any unit opens, the way `prepare_pack` extracts before one:
    on Databricks each put is a Files API upload, and fifty of them inside
    the unit held `cases ... FOR UPDATE` -- and so every fenced write of every
    run in the case, which takes the case lock first -- and, behind the
    admission route's governed write, the audit chain head, for as long as
    the uploads took (DL-7, ED-5). The puts are content-addressed, so a
    refused unit leaves harmless orphans and nothing else.
    """
    return [blobs.put(one.document.data) for one in pack.documents]


def admit_prepared(
    conn: StoreConnection, case_id: UUID, pack: PreparedPack, stored: Sequence[str]
) -> list[UUID]:
    """Write a prepared pack's rows under the case lock, in the caller's
    transaction, naming the digests `put_pack` already stored.

    Never commits: a refusal part way leaves rows the caller rolls back, and the
    blobs already put are harmless content-addressed orphans. It takes no
    blob store, so no upload can happen under the lock it takes.
    """
    _require_case(conn, case_id)
    lock_case(conn, case_id)
    return [
        _admit_one(conn, case_id, one, digest)
        for one, digest in zip(pack.documents, stored, strict=True)
    ]


def _check_pack_limits(documents: Sequence[Document], limits: AdmissionLimits) -> None:
    """Document count and byte ceilings, before any dispatch or extraction.

    Checked here rather than per document inside `_extract`, so a pack that
    is simply too big -- too many documents, or too many bytes total -- never
    reaches an extractor at all: not the one document over its own ceiling,
    and not the documents before it, either.
    """
    if len(documents) > limits.max_documents:
        raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
    total_bytes = 0
    for document in documents:
        if len(document.data) > limits.max_document_bytes:
            raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
        total_bytes += len(document.data)
    if total_bytes > limits.max_pack_bytes:
        raise Refusal(RefusalCode.SOURCE_TOO_LARGE)


def _extract(
    dispatch: ExtractorDispatch,
    document: Document,
    limits: AdmissionLimits,
    pack_deadline: float = inf,
) -> tuple[str, list[Token]]:
    """One document's canonical extractor identity and tokens, or a typed code.

    Whatever the dispatch or the extractor raises is reduced to a code and
    raised again outside the handler, so no message, cause or context -- all of
    which can quote the bytes an extractor choked on -- travels with it.
    """
    code: RefusalCode | None = None
    try:
        reader = dispatch(document.data)
        identity = _identity(reader)
        deadline = min(time.monotonic() + limits.max_seconds, pack_deadline)
        tokens = reader.extract(document.data, limits=limits, deadline=deadline)
    except Refusal as refusal:
        code = refusal.code
    except MemoryError:
        raise  # the process, not the document
    except Exception as failure:  # noqa: BLE001 -- untrusted bytes; any failure is a code
        code = _code_for(failure)
    if code is not None:
        raise Refusal(code) from None
    return identity, tokens


def _code_for(failure: Exception) -> RefusalCode:
    # Imported here so plain-text admission never loads pdfminer.
    from pdfminer.pdfdocument import PDFEncryptionError

    if isinstance(failure, PDFEncryptionError):
        return RefusalCode.SOURCE_ENCRYPTED
    return RefusalCode.SOURCE_NOT_READABLE


def _identity(reader: Extractor) -> str:
    try:
        declared = reader.identity
    except (Refusal, AttributeError, TypeError, ValueError, OverflowError):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None
    if not isinstance(declared, ExtractorIdentity):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None
    try:
        return declared.canonical()
    except (Refusal, AttributeError, TypeError, ValueError, OverflowError):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None


def _refuse_hidden_text(blocks: list[_Block]) -> None:
    """Refuse a document carrying text no reader of it can see (AI-2).

    Tag characters, a zero-width space, a word joiner: the approver of the
    source set signs off a preview that does not show them, and every module
    reads them as evidence -- an instruction smuggled past the one human gate
    on what a run is given. Read over the packed blocks, which carry every
    token's text joined line by line, so it is one pass over the document
    rather than one per token.

    `SOURCE_NOT_READABLE` is what it is: a document no reader can read as it
    is written. Refused here, where the pack is still whole and nothing has
    been pinned, rather than at every later read of a source the case is
    already carrying.
    """
    if any(hides_text(block.text.value) for block in blocks):
        raise Refusal(RefusalCode.SOURCE_NOT_READABLE)


def _refuse_unassigned(blocks: list[_Block]) -> None:
    """Refuse a document carrying a code point this Python's Unicode does not
    assign -- general category `Cn`, noncharacters included (N40).

    Why: a line's length is measured on two Unicode tables. Admission cuts it
    by its NFC length in Python, and anchoring re-measures a width-packed
    source's split line in the database (`citations._group_counts` sums
    Postgres's `length(normalize(text, NFC))`; packing 2 reads its numbering
    back without measuring, CF-013). The normalization stability policy fixes
    NFC for every *assigned* character, but a code point unassigned in one
    table can be assigned, with compositions, in the other's newer version --
    Unicode 16 adds compositions -- and the two would then disagree about a
    line nobody changed. Refusing what Python does not assign keeps every
    admitted character inside the table both sides share, whichever side
    moves first.

    What a future Postgres upgrade must check: `SELECT unicode_version()`
    against `unicodedata.unidata_version` (both 15.1 on Postgres 17 and Python
    3.13), and `test_the_store_and_the_host_agree_on_every_nfc_length` rerun.
    A server newer than Python is covered here; one older than Python is not,
    because a code point Python assigns and the server does not passes this
    check and is normalised by one side only -- so neither a Postgres
    downgrade nor a Python upgrade may leave the server's version behind.
    Tokens admitted before this refusal were never asked, and a server version
    that assigns one of their code points re-measures their split lines.

    Read over the distinct characters of the non-ASCII blocks, so a document
    costs one category lookup per character it uses, not per character.
    """
    used: set[str] = set()
    for block in blocks:
        if not block.text.value.isascii():
            used.update(block.text.value)
    if any(unicodedata.category(character) == "Cn" for character in used):
        raise Refusal(RefusalCode.SOURCE_NOT_READABLE)


def _prepare(document: Document, tokens: list[Token], identity: str) -> _Packed:
    try:
        prepared = [_prepared(token) for token in tokens]
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None
    blocks, packing = _blocks(prepared)
    _refuse_hidden_text(blocks)
    _refuse_unassigned(blocks)
    # The output's format is its packing, so the digest a pin captures binds
    # how the blocks were cut. The extraction envelope around it -- document,
    # identity, output digest -- is unchanged and keeps its own version 1,
    # which `source_sets._valid_member` re-derives for every member.
    output = canonical_digest(
        {
            "format_version": packing,
            "tokens": [asdict(token) for token in prepared],
            "blocks": [_block_record(block) for block in blocks],
        }
    )
    extraction = canonical_digest(
        {
            "format_version": 1,
            "document_sha256": sha256(document.data).hexdigest(),
            "extractor_identity": json.loads(identity),
            "output_sha256": output,
        }
    )
    return _Packed(document, prepared, blocks, identity, output, extraction, packing)


def _prepared(token: Token) -> Token:
    """One extracted token, checked field by field and rebuilt, so what is
    written is exactly what was checked -- a `MarkedToken` only when its line
    carries a mark (N27), so an unmarked token's record is the one it always
    was. Raises `TypeError` and friends for `_prepare` to reduce to a code."""
    indices = (token.page, token.region_id, token.line_id)
    coords = (token.x0, token.y0, token.x1, token.y1)
    if any(type(i) is not int or not -(2**31) <= i < 2**31 for i in indices):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    if any(
        type(c) not in (int, float) or not isfinite(c) or float(c) != c for c in coords
    ):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    if type(token.text) is not str:
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    BoundaryText.of(token.text)
    (x0, y0, x1, y1) = map(float, coords)
    hidden = token.hidden if isinstance(token, MarkedToken) else ""
    if hidden == "":
        return Token(token.text, *indices, x0, y0, x1, y1)
    if hidden not in HIDDEN_MARKS:
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return MarkedToken(token.text, *indices, x0, y0, x1, y1, hidden)


def _block_record(block: _Block) -> list[object]:
    """A block as the output digest holds it: its mark only when it has one."""
    record: list[object] = [block.block_id, block.page, block.text.value]
    return [*record, block.hidden] if block.hidden else record


def _require_case(conn: StoreConnection, case_id: UUID) -> None:
    row = conn.execute(
        "SELECT case_id FROM cases WHERE case_id = %s", (case_id,)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.CASE_NOT_FOUND)


def _admit_one(
    conn: StoreConnection, case_id: UUID, packed: _Packed, document_sha256: str
) -> UUID:
    """One source's rows, under the case lock. `document_sha256` is what the
    volume answered when `put_pack` put the bytes, before the lock."""
    source_id = uuid4()
    conn.execute(
        "INSERT INTO sources (source_id, case_id, document_sha256, filename)"
        " VALUES (%s, %s, %s, %s)",
        (
            source_id,
            case_id,
            document_sha256,
            packed.document.filename.value,
        ),
    )
    _store_tokens(conn, source_id, packed.tokens)
    _store_blocks(conn, source_id, packed.blocks)
    conn.execute(
        "INSERT INTO source_extractions"
        " (source_id, format_version, extractor_identity,"
        " output_sha256, extraction_sha256)"
        " VALUES (%s, %s, %s, %s, %s)",
        (
            source_id,
            packed.packing,
            packed.extractor_identity,
            packed.output_sha256,
            packed.extraction_sha256,
        ),
    )
    return source_id


# The column a mark is written to, named in a `COPY` only when there is one.
_MARKED = {False: "", True: ", hidden"}


def _store_tokens(conn: StoreConnection, source_id: UUID, tokens: list[Token]) -> None:
    """One COPY, so one statement carries the document.

    A row at a time cost a round trip and a seal check each: 100,000 tokens took
    13 s of a 14 s admission. `COPY` makes it one of each, which is also what
    the statement-level seal trigger (migration 0027) is counted by.

    `hidden` (migration 0033) is named only for a document with a mark to
    write, so an unmarked one is written with exactly the columns every
    earlier admission wrote (`_MARKED`).
    """
    marked = any(isinstance(token, MarkedToken) for token in tokens)
    with (
        conn.cursor() as cursor,
        cursor.copy(
            "COPY source_tokens (source_id, token_id, page, region_id, line_id,"
            f" text, x0, y0, x1, y1{_MARKED[marked]}) FROM STDIN"
        ) as copy,
    ):
        for token_id, token in enumerate(tokens):
            row = (
                source_id,
                token_id,
                token.page,
                token.region_id,
                token.line_id,
                token.text,
                token.x0,
                token.y0,
                token.x1,
                token.y1,
            )
            mark = token.hidden if isinstance(token, MarkedToken) else None
            copy.write_row((*row, mark) if marked else row)


def _blocks(tokens: list[Token]) -> tuple[list[_Block], int]:
    """One block per line while the line fits, its text across the boundary,
    and the packing that wrote them.

    `source_blocks.text` is pinned state, and CLAUDE.md's rule is that every
    string reaching pinned state carries `BoundaryText`. It was carried on the
    way out instead -- `read_evidence` calls `BoundaryText.of` -- which left
    admission writing a bare `str`, so a line over the limit and a line holding
    the override control the boundary exists to refuse were both admitted and
    then refused at every read. A refusal here costs a pack; there it cost a
    pinned source no run can read.

    A line past `GROUP_WIDTH` is split rather than given a block of its own,
    because a block of its own is a block the boundary refuses -- and refusing
    it refused the whole pack, so one wide table row in a text export meant no
    document of it could be admitted at all. It is split between tokens
    (`token_groups`, CF-013), and a source with such a line is
    `PACKING_BY_TOKEN`.
    """
    lines: dict[int, list[Token]] = {}
    for token in tokens:
        lines.setdefault(token.line_id, []).append(token)
    groups = {
        line_id: token_groups([token.text for token in line])
        for line_id, line in lines.items()
    }
    marks = {line_id: _line_mark(line) for line_id, line in lines.items()}
    block_ids = block_ids_by_line({line_id: len(g) for line_id, g in groups.items()})
    blocks = [
        _Block(
            block_id=block_id,
            page=lines[line_id][0].page,
            text=BoundaryText.of(text),
            hidden=marks[line_id],
        )
        for line_id in sorted(lines)
        for block_id, text in zip(block_ids[line_id], groups[line_id], strict=True)
    ]
    written = any(len(group) > 1 for group in groups.values()) or any(marks.values())
    return blocks, PACKING_BY_TOKEN if written else PACKING_BY_WIDTH


def _line_mark(line: list[Token]) -> str:
    """Why a reader of the rendered page may not see some of `line` (N27):
    its tokens' reasons, sorted and joined by a comma, or ""."""
    reasons = {
        reason
        for token in line
        if isinstance(token, MarkedToken) and token.hidden
        for reason in token.hidden.split(",")
    }
    return ",".join(sorted(reasons))


def token_groups(words: Sequence[str]) -> list[str]:
    """One line's blocks under `PACKING_BY_TOKEN`: its tokens, NFC, joined by
    one space while they fit `GROUP_WIDTH`, and a new block begun at the token
    that would not.

    A block ends where the token index can break a quote (CF-013). Cut at the
    width instead (`line_groups`), a block began and ended inside words, and a
    module shown it as a line of its own and quoting it whole was refused
    `CITATION_NOT_LOCATED`. A token is never wider than a block -- the
    extractor cuts at `MAX_TOKEN_CHARS`, which is this width, and `_prepare`
    holds every token to `BoundaryText` -- so every block is at most the
    width. A line that fits is the one group `line_groups` makes of it, byte
    for byte: nothing composes across the space between two tokens, so the
    tokens' NFC joined is the joined line's NFC.
    """
    groups: list[list[str]] = []
    width = 0
    for word in words:
        normal = unicodedata.normalize("NFC", word)
        if groups and width + 1 + len(normal) <= GROUP_WIDTH:
            groups[-1].append(normal)
            width += 1 + len(normal)
        else:
            groups.append([normal])
            width = len(normal)
    return [" ".join(group) for group in groups]


def line_groups(text: str) -> list[str]:
    """One line's blocks under `PACKING_BY_WIDTH`: the whole line while it
    fits `GROUP_WIDTH`, chunks of that width once it does not.

    Normalised before it is measured and cut, because the width is
    `BoundaryText`'s and `BoundaryText` measures what it has normalised. A line
    that fits is therefore the one group it has always been, byte for byte.

    A chunk cuts wherever the width falls, inside a word if that is where it
    falls. No longer how admission packs (`token_groups`, CF-013): it is the
    rule every source recorded as packing 1 was written under, which
    `citations._group_counts` re-derives in the database when it numbers one
    of their split lines.
    """
    normalised = unicodedata.normalize("NFC", text)
    if len(normalised) <= GROUP_WIDTH:
        return [normalised]
    return [
        normalised[at : at + GROUP_WIDTH]
        for at in range(0, len(normalised), GROUP_WIDTH)
    ]


def block_ids_by_line(groups: Mapping[int, int]) -> dict[int, tuple[str, ...]]:
    """Line id to the block ids admission writes for it: the one numbering.

    `groups` is how many blocks each line needs -- one while it fits
    `GROUP_WIDTH`, more once it does not. Ordinals ascend over the lines in
    line order and over the blocks within a line, zero-padded to six digits
    (wider past 999,999 blocks). Admission packs with it and citation anchoring
    reads it back from the token index, so the two cannot disagree about which
    blocks a quoted line belongs to.
    """
    numbering: dict[int, tuple[str, ...]] = {}
    ordinal = 0
    for line_id in sorted(groups):
        count = groups[line_id]
        numbering[line_id] = tuple(
            f"{BLOCK_PREFIX}{at:06d}" for at in range(ordinal, ordinal + count)
        )
        ordinal += count
    return numbering


def _store_blocks(conn: StoreConnection, source_id: UUID, blocks: list[_Block]) -> None:
    """By `COPY` for the same reason `_store_tokens` is: one statement, one seal
    check. A block per line means a tenth of the rows, not a different shape,
    and `hidden` is named only when a block has a mark to write."""
    marked = any(block.hidden for block in blocks)
    with (
        conn.cursor() as cursor,
        cursor.copy(
            f"COPY source_blocks (source_id, block_id, page, text{_MARKED[marked]})"
            " FROM STDIN"
        ) as copy,
    ):
        for block in blocks:
            row = (source_id, block.block_id, block.page, block.text.value)
            copy.write_row((*row, block.hidden or None) if marked else row)
