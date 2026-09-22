"""Migration 0008's historical v1 verifier; never substitute a current extractor.

Uses admission's Python digest, preserving raw stored Unicode and binary floats.
Changing this historical format requires a new migration, not a new v1 meaning.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from caos.digest import canonical_digest
from caos.evidence.extract import ExtractorIdentity
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

_TOKEN_FIELDS_V1 = ("text", "page", "region_id", "line_id", "x0", "y0", "x1", "y1")


def _verify_extractions_v1(conn: StoreConnection) -> None:
    """Verify all known output under parent-first locks until migration commit."""
    if conn.execute("SHOW transaction_isolation").fetchone() != ("read committed",):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    conn.execute(
        "LOCK TABLE sources, source_tokens, source_blocks, source_extractions"
        " IN SHARE ROW EXCLUSIVE MODE"
    )
    try:
        with conn.cursor(name="caos_extractions_v1") as candidates:
            candidates.itersize = 1
            candidates.execute(
                "SELECT s.source_id, s.document_sha256, e.format_version,"
                " e.extractor_identity, e.output_sha256, e.extraction_sha256"
                " FROM sources s JOIN source_extractions e USING (source_id)"
                " ORDER BY s.source_id"
            )
            for source, document, version, raw, output, extraction in candidates:
                identity = json.loads(raw)
                if (
                    version != 1
                    or ExtractorIdentity(**identity).canonical() != raw
                    or any(
                        re.fullmatch(r"[0-9a-f]{64}", value) is None
                        for value in (document, output, extraction)
                    )
                    or _stored_output_v1(conn, source) != output
                    or canonical_digest(
                        {
                            "format_version": 1,
                            "document_sha256": document,
                            "extractor_identity": identity,
                            "output_sha256": output,
                        }
                    )
                    != extraction
                ):
                    raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT) from None


def _block_ordinal_v1(block_id: str) -> int:
    ordinal = int(block_id[1:])
    if block_id != f"b{ordinal:06d}" or ordinal < 0:
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    return ordinal


def _stored_output_v1(conn: StoreConnection, source: UUID) -> str:
    # ponytail: largest-source memory, as admission; stream if a fixed bound is needed.
    tokens = conn.execute(
        "SELECT token_id, text, page, region_id, line_id, x0, y0, x1, y1"
        " FROM source_tokens WHERE source_id = %s ORDER BY token_id",
        (source,),
        binary=True,  # Preserve float bits independently of extra_float_digits.
    ).fetchall()
    blocks = sorted(
        conn.execute(
            "SELECT block_id, page, text FROM source_blocks WHERE source_id = %s",
            (source,),
        ).fetchall(),
        key=lambda row: _block_ordinal_v1(row[0]),
    )
    if (
        not tokens
        or not blocks
        or any(row[0] != i for i, row in enumerate(tokens))
        or any(row[0] != f"b{i:06d}" for i, row in enumerate(blocks))
    ):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    return canonical_digest(
        {
            "format_version": 1,
            "tokens": [
                dict(zip(_TOKEN_FIELDS_V1, row[1:], strict=True)) for row in tokens
            ],
            "blocks": blocks,
        }
    )
