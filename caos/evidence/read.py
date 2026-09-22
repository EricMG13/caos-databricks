"""`read_evidence`: the host boundary a module receives evidence through.

Invariant 2: validated at the boundary, fails closed with a typed code, and **no
text is returned on refusal** -- not in the exception chain, the delivered set,
or the ledger. Every refusal here is raised `from None` for that reason: a
chained `psycopg` error carries the statement, and the statement carries the
identifiers a document was stored under.

One code answers every unavailable read. Distinguishing "no such source" from
"withdrawn" from "no such block" would tell a caller which of the three it
guessed right, and a caller entitled to know already has the delivered set.
Stored text retains historical typed BoundaryText refusals without its contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg

from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

# One read is one row fetch. The predecessor's blocks lived in a JSON column on
# the source row, so every read parsed every block: ~8x, the largest multiple in
# the measurements behind docs/AI_CODE_QUALITY.md. `test_io_budget_read_evidence`
# counts the round trips against this number.
IO_BUDGET = 1

_BLOCK_QUERY = (
    "SELECT blocks.page, blocks.text FROM source_blocks AS blocks"
    " JOIN live_sources USING (source_id)"
    " WHERE blocks.source_id = %s AND blocks.block_id = %s"
)


# Every captured block of one run, in one statement. The run's captured
# membership is the CTE, and the live chain -- pinned version, live source,
# stored extraction identity -- is joined onto it, so what the pin captured and
# what survived come back under one snapshot: a short list is a refusal, never
# a delivery (invariant 2). The totals row is what carries the captured count
# when nothing survived, since LEFT JOIN keeps one row whose block columns are
# NULL rather than returning nothing to read.
_RUN_BLOCKS_QUERY = (
    "WITH captured AS ("
    "SELECT inputs.case_id, inputs.source_version, inputs.source_fingerprint,"
    " members.source_id, members.document_sha256, members.extractor_identity,"
    " members.output_sha256, members.extraction_sha256,"
    " blocks.block_id, blocks.page, blocks.text"
    " FROM runs AS run"
    " JOIN run_inputs AS inputs ON (inputs.run_id,inputs.case_id)"
    " = (run.run_id,run.case_id)"
    " JOIN source_set_members AS members ON (members.case_id,members.version)"
    " = (inputs.case_id,inputs.source_version)"
    " JOIN source_blocks AS blocks ON blocks.source_id = members.source_id"
    " WHERE run.run_id = %s"
    "), live AS ("
    "SELECT captured.source_id, captured.block_id, captured.page, captured.text"
    " FROM captured"
    " JOIN source_set_versions AS versions"
    " ON (versions.case_id,versions.version,versions.fingerprint)"
    " = (captured.case_id,captured.source_version,captured.source_fingerprint)"
    " JOIN live_sources AS sources ON (sources.case_id,sources.source_id)"
    " = (captured.case_id,captured.source_id)"
    " JOIN source_extractions AS extraction"
    " ON extraction.source_id = sources.source_id"
    " WHERE captured.document_sha256 = sources.document_sha256"
    " AND captured.extractor_identity = extraction.extractor_identity"
    " AND captured.output_sha256 = extraction.output_sha256"
    " AND captured.extraction_sha256 = extraction.extraction_sha256"
    ")"
    " SELECT live.source_id, live.block_id, live.page, live.text, totals.captured"
    " FROM (SELECT count(*) AS captured FROM captured) AS totals"
    " LEFT JOIN live ON true"
    " ORDER BY live.source_id, live.block_id"
)


@dataclass(frozen=True, slots=True)
class Block:
    """One block as the host holds it: its text, and the page it sits on.

    The page travels with the text because it is the host's fact and the
    module's obligation. A module cites the page it was told about, so a module
    told the wrong one writes a citation invariant 11 refuses -- for a quote
    that is really there, under a number nobody gave it a way to know.
    """

    page: int
    text: BoundaryText


def read_block(conn: StoreConnection, *, source_id: UUID, block_id: str) -> Block:
    """One block of one live source, or `EVIDENCE_NOT_AVAILABLE`.

    The join to `live_sources` is what makes withdrawal a live check at every use
    rather than a promise made when the source set was pinned (invariant 1).

    Still one row fetch: the page is a column of the row already being read, so
    `IO_BUDGET` is unchanged and there is no second path to a block that could
    forget the join above.
    """
    return _fetch_block(conn, _BLOCK_QUERY, (source_id,), block_id)


def read_run_blocks(
    conn: StoreConnection, *, run_id: UUID
) -> list[tuple[UUID, str, int, BoundaryText]]:
    """Every block the run's pin captured, in `(source_id, block_id)` order.

    One statement where the per-block reader was one statement per block: a pack
    of twenty thousand lines cost twenty thousand round trips under the case
    lock every time a prompt was built. The join proves what the per-block
    reader it replaces proved -- the block belongs to a source this run pinned, at
    the document and extraction identity it was pinned at, and the source is
    live now.

    Fail closed: a count short of what the pin captured is a withdrawn or
    altered source, and refuses `EVIDENCE_NOT_AVAILABLE` rather than delivering
    the blocks that did survive. No text reaches the refusal (invariant 2).
    A run that captured nothing -- no pin, no such run, another case's run --
    refuses too: an empty delivery is still a delivery, and this reader exists
    to refuse deliveries short of the pin.

    A database fault is `STORE_UNAVAILABLE`, not a verdict about the evidence:
    this statement stands where the caller's own unwrapped pins query stood,
    and that is the code a store fault on the delivery path has always carried
    up to `execution_reads`. Typed and `from None` either way, so nothing the
    statement quotes travels with it.
    """
    if not isinstance(run_id, UUID):
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE) from None
    try:
        rows = conn.execute(_RUN_BLOCKS_QUERY, (run_id,)).fetchall()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    # `totals` is one row whatever the run is, so the captured count is always
    # readable -- including the zero a run with no pin captures, which is the
    # shortest short delivery there is. The empty arm is belt and braces rather
    # than a case: zero refuses below either way.
    captured = int(rows[0][4]) if rows else 0
    live = [row for row in rows if row[0] is not None]
    if captured == 0 or len(live) != captured:
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE) from None
    try:
        return [
            (UUID(str(source)), str(block), int(page), BoundaryText.of(text))
            for source, block, page, text, _ in live
        ]
    except Refusal as refused:
        raise Refusal(refused.code) from None


def _fetch_block(
    conn: StoreConnection, query: str, identifiers: tuple[UUID, ...], block_id: str
) -> Block:
    if any(not isinstance(value, UUID) for value in identifiers) or not _is_block_id(
        block_id
    ):
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE) from None
    try:
        row = conn.execute(query, (*identifiers, block_id)).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE) from None
    if row is None:
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE) from None
    try:
        return Block(page=int(row[0]), text=BoundaryText.of(row[1]))
    except Refusal as refused:
        raise Refusal(refused.code) from None


def read_evidence(
    conn: StoreConnection, *, source_id: UUID, block_id: str
) -> BoundaryText:
    """The text of one block of one live source, or `EVIDENCE_NOT_AVAILABLE`.

    The named boundary of invariant 2, and a projection of `read_block` rather
    than a second query -- one statement, one live-source check, one refusal.
    """
    return read_block(conn, source_id=source_id, block_id=block_id).text


def _is_block_id(block_id: str) -> bool:
    # Ingest mints minimum-width-six ASCII ordinals, without alternate padding.
    return (
        isinstance(block_id, str)
        and len(block_id) >= 7
        and block_id[0] == "b"
        and block_id[1:].isascii()
        and block_id[1:].isdigit()
        and (len(block_id) == 7 or block_id[1] != "0")
    )
