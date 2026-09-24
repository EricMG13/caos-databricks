"""Admission binds the host adapter and its actual prepared evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import ingest
from caos.evidence.extract import (
    Extractor,
    ExtractorIdentity,
    PlainTextExtractor,
    Token,
)
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.pdf import PdfExtractor
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection


class Reader:
    def __init__(self, identity: object, tokens: list[Token] | None = None) -> None:
        self.identity = identity
        self.tokens = tokens

    def extract(self, data: bytes, **_kwargs: object) -> list[Token]:
        return (
            self.tokens
            if self.tokens is not None
            else PlainTextExtractor().extract(data)
        )


def _admit(
    case: tuple[StoreConnection, UUID], tmp_path: Path, reader: object
) -> tuple[object, ...]:
    conn, case_id = case
    [source] = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[Document(BoundaryText.of("report.pdf"), b"one two")],
        dispatch=lambda data: cast(Extractor, reader),
    )
    row = conn.execute(
        "SELECT format_version, extractor_identity, output_sha256, extraction_sha256"
        " FROM source_extractions WHERE source_id = %s",
        (source,),
    ).fetchone()
    assert row is not None
    return row


def test_known_identity_is_versioned_bounded_and_stable(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    first = _admit(case, tmp_path, PlainTextExtractor())
    assert _admit(case, tmp_path, PlainTextExtractor()) == first
    assert first[0] == 1
    adapter = json.loads(str(first[1]))
    assert adapter["name"] == "caos.plain-text"
    assert adapter["version"] == "4"
    assert adapter["config"]["encoding"] == "utf-8-sig"
    assert adapter["config"]["cell_width"] == 7.2
    assert len(str(first[1])) <= 4096
    assert PdfExtractor().identity.name == "caos.pdfminer"
    assert "pdfminer_version" in PdfExtractor().identity.config
    conn, _ = case
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM source_extractions").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)


@pytest.mark.parametrize(
    "field,value",
    [("name", "other"), ("version", "5"), ("config", {"cell_width": 8.0})],
)
def test_host_identity_changes_extraction_digest(
    case: tuple[StoreConnection, UUID], tmp_path: Path, field: str, value: object
) -> None:
    original = PlainTextExtractor().identity
    first = _admit(case, tmp_path, Reader(original))
    changed = replace(original, **{field: cast(Any, value)})
    second = _admit(case, tmp_path, Reader(changed))
    assert first[2] == second[2]
    assert first[3] != second[3]


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "different"),
        ("page", 2),
        ("region_id", 2),
        ("line_id", 2),
        ("x0", 71.0),
        ("y0", 71.0),
        ("x1", 123.0),
        ("y1", 123.0),
    ],
)
def test_every_token_field_binds_actual_output(
    case: tuple[StoreConnection, UUID], tmp_path: Path, field: str, value: object
) -> None:
    tokens = PlainTextExtractor().extract(b"one two")
    first = _admit(case, tmp_path, Reader(PlainTextExtractor().identity, tokens))
    changed = [replace(tokens[0], **{field: cast(Any, value)}), tokens[1]]
    second = _admit(case, tmp_path, Reader(PlainTextExtractor().identity, changed))
    assert first[2:] != second[2:]


def test_order_block_identity_and_document_bytes_are_bound(
    case: tuple[StoreConnection, UUID], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = PlainTextExtractor().extract(b"one two")
    reader = Reader(PlainTextExtractor().identity, tokens)
    first = _admit(case, tmp_path, reader)
    reversed_tokens = Reader(reader.identity, list(reversed(tokens)))
    assert _admit(case, tmp_path, reversed_tokens)[2:] != first[2:]
    monkeypatch.setattr(ingest, "BLOCK_PREFIX", "changed")
    assert _admit(case, tmp_path, reader)[2:] != first[2:]
    monkeypatch.undo()
    conn, case_id = case
    [source] = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[Document(BoundaryText.of("different.txt"), b"different bytes")],
        dispatch=lambda data: cast(Extractor, reader),
    )
    row = conn.execute(
        "SELECT output_sha256, extraction_sha256 FROM source_extractions"
        " WHERE source_id = %s",
        (source,),
    ).fetchone()
    assert row is not None and row[0] == first[2] and row[1] != first[3]


@pytest.mark.parametrize(
    "identity",
    [
        None,
        "guessed-class",
        ExtractorIdentity("", "1", {}),
        ExtractorIdentity("test", "", {}),
        ExtractorIdentity("test", "1", {"x": float("nan")}),
        ExtractorIdentity("test", "1", {"x": float("inf")}),
        ExtractorIdentity("test", "1", {"x": "secret" * 1000}),
        ExtractorIdentity("test", "1", {"x": "secret\u202e"}),
        ExtractorIdentity(
            "test", "1", cast(dict[str, str | int | float | bool | None], {1: "secret"})
        ),
        ExtractorIdentity(
            "test", "1", cast(dict[str, str | int | float | bool | None], {"x": [1]})
        ),
    ],
)
def test_bad_host_identity_refuses_before_lock_or_writes(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    identity: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lock(*args: object) -> None:
        pytest.fail("identity validation must precede the case lock")

    monkeypatch.setattr(ingest, "lock_case", unexpected_lock)
    with pytest.raises(Refusal) as caught:
        _admit(case, tmp_path, Reader(identity))
    assert str(caught.value) == RefusalCode.SOURCE_IDENTITY_INVALID.value
    assert caught.value.__suppress_context__
    conn, _ = case
    assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)


@pytest.mark.parametrize(
    "field,value",
    [
        ("x0", float("nan")),
        ("y1", float("inf")),
        ("text", 42),
        ("page", True),
        ("line_id", 2**40),
        ("x1", "secret"),
        ("x1", True),
        ("x1", 2**53 + 1),
        ("x1", 10**400),
    ],
)
def test_bad_output_refuses_whole_pack_before_writes(
    case: tuple[StoreConnection, UUID], tmp_path: Path, field: str, value: object
) -> None:
    class BadSecond(Reader):
        def extract(self, data: bytes, **_kwargs: object) -> list[Token]:
            tokens = PlainTextExtractor().extract(data)
            return (
                [replace(tokens[0], **{field: cast(Any, value)})]
                if data == b"bad"
                else tokens
            )

    conn, case_id = case
    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path),
            case_id=case_id,
            documents=[
                Document(BoundaryText.of("ok"), b"ok"),
                Document(BoundaryText.of("bad"), b"bad"),
            ],
            dispatch=lambda data: cast(
                Extractor, BadSecond(PlainTextExtractor().identity)
            ),
        )
    assert caught.value.code is RefusalCode.SOURCE_IDENTITY_INVALID
    assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)


def test_provenance_has_native_source_fk_and_is_append_only(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    row = _admit(case, tmp_path, PlainTextExtractor())
    conn, _ = case
    conn.commit()
    for statement in (
        "UPDATE source_extractions SET format_version = 1",
        "DELETE FROM source_extractions",
        "TRUNCATE source_extractions",
    ):
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(statement)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO source_extractions VALUES (%s, %s, %s, %s, %s)",
                (uuid4(), *row),
            )
    assert conn.execute("SELECT count(*) FROM source_extractions").fetchone() == (1,)


def test_missing_adapter_identity_refuses(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    with pytest.raises(Refusal) as caught:
        _admit(case, tmp_path, object())
    assert caught.value.code is RefusalCode.SOURCE_IDENTITY_INVALID


def test_adapter_identity_error_is_sanitized(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    class BrokenIdentity:
        @property
        def identity(self) -> ExtractorIdentity:
            raise ValueError("secret_configuration")

    with pytest.raises(Refusal) as caught:
        _admit(case, tmp_path, BrokenIdentity())
    assert str(caught.value) == RefusalCode.SOURCE_IDENTITY_INVALID.value
    assert caught.value.__suppress_context__


def test_digest_reconstructs_exactly_from_stored_output(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    # Config enumeration order and exact integer/float coordinates are immaterial.
    identity = ExtractorIdentity("test", "1", {"a": 1, "b": "two"})
    tokens = [Token("one", 1, 0, 0, 1, 2, 3, 4)]
    first = _admit(case, tmp_path, Reader(identity, tokens))
    identity = replace(identity, config={"b": "two", "a": 1})
    assert _admit(case, tmp_path, Reader(identity, tokens)) == first
    conn, _ = case
    source = conn.execute("SELECT source_id FROM source_extractions LIMIT 1").fetchone()
    assert source is not None
    stored_tokens = conn.execute(
        "SELECT text, page, region_id, line_id, x0, y0, x1, y1 FROM source_tokens"
        " WHERE source_id = %s ORDER BY token_id",
        source,
    ).fetchall()
    stored_blocks = conn.execute(
        "SELECT block_id, page, text FROM source_blocks WHERE source_id = %s"
        " ORDER BY block_id",
        source,
    ).fetchall()
    payload = {
        "format_version": 1,
        "tokens": [
            dict(
                zip(
                    ("text", "page", "region_id", "line_id", "x0", "y0", "x1", "y1"),
                    row,
                    strict=True,
                )
            )
            for row in stored_tokens
        ],
        "blocks": stored_blocks,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert sha256(canonical.encode()).hexdigest() == first[2]
