"""Create case and source admission (Task 4.2 slice 4.2d, decisions 2, 4, 6).

**Create case** (`POST /api/v1/cases`): identity, key, a global role that may
write, then the closed body. One nil-scope unit inserts the case, grants the
creator ADMIN standing and records `CASE_CREATED` beside the receipt -- a
single-actor release under invariant 5.

**Admission** (`POST /api/v1/cases/{case_id}/sources`), in this order:

1. Identity (401), then the envelope from headers alone: `multipart/form-data`
   with a declared `Content-Length` (else `REQUEST_INVALID`) no larger than the
   pack ceiling plus multipart overhead (else 413 `SOURCE_TOO_LARGE`).
2. Key, visibility, global role and the WRITER floor -- so a stranger's pack
   is never parsed, let alone extracted.
3. The standing read's transaction is closed, then the form is parsed with
   the stream held to its declared length: only file parts named `document`,
   each filename `BoundaryText` of at most 255 characters and not blank.
4. The receipt is looked up for the pack's digest and a replay answers without
   extracting; otherwise `prepare_pack` extracts (the §47 child for a PDF) and
   `put_pack` uploads the documents, with no transaction open and no case lock
   or chain head held (ED-5).
5. One governed unit: `admit_prepared`, `SOURCES_ADMITTED` and the receipt.
   A refusal there commits no row; blobs already put are content-addressed
   orphans (CLAUDE.md known gaps).
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.types import Message, Receive

from caos.api.commands._request import (
    CommandRequest,
    Key,
    command_response,
    governed,
    json_body,
    require_case_writer,
)
from caos.api.deps import IDENTITY_FIRST, Blobs, Caller, CasePath, Store
from caos.api.identity import Actor, GlobalRole
from caos.api.wire import TITLE_CHARS, CaseCreated, CreateCase, SourcesAdmitted
from caos.boundary_text import BoundaryText
from caos.evidence.extract import DEFAULT_LIMITS
from caos.evidence.ingest import Document, admit_prepared, prepare_pack, put_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, rollback_or_close
from caos.store.audit import GovernedAction
from caos.store.commands import NIL_SCOPE, CommandResult, StoredReceipt, find_receipt
from caos.store.members import Standing, grant

# Measured by `tests/test_case_commands.py`.
CREATE_CASE_IO = 13  # lookup, the case row and its grant, the governed unit, receipt
ADMISSION_FIXED_IO = 14  # standing, receipt peek, lookup, the governed unit, receipt
ADMISSION_PER_DOCUMENT_IO = 4  # source, tokens, blocks, extraction
REPLAY_IO = 3  # decision 14: standing and the receipt lookup
IO_BUDGET = max(
    CREATE_CASE_IO,
    ADMISSION_FIXED_IO + ADMISSION_PER_DOCUMENT_IO * DEFAULT_LIMITS.max_documents,
)

CREATE_CASE = "CREATE_CASE"
ADMIT_SOURCES = "ADMIT_SOURCES"
DOCUMENT_PART = "document"
FILENAME_CHARS = 255
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = DEFAULT_LIMITS.max_pack_bytes + MULTIPART_OVERHEAD_BYTES

router = APIRouter()


def _require_global_writer(actor: Caller) -> Actor:
    """A global role that may write: ANALYST or ADMIN."""
    if actor.role is GlobalRole.READER:
        raise Refusal(RefusalCode.NOT_AUTHORISED)
    return actor


@router.post("/api/v1/cases", status_code=201, dependencies=[IDENTITY_FIRST])
def create_case_command(
    actor: Caller,
    key: Key,
    _may_write: Annotated[Actor, Depends(_require_global_writer)],
    body: Annotated[CreateCase, Depends(json_body(CreateCase))],
    conn: Store,
) -> Response:
    title = BoundaryText.of(body.title, limit=TITLE_CHARS)
    case_id = uuid4()
    return governed(
        conn,
        scope=NIL_SCOPE,
        key=key,
        request=CommandRequest(CREATE_CASE, None, None, None, {"title": title.value}),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="CASE_CREATED",
            requires=Standing.ADMIN,
            payload={"case_id": str(case_id)},
        ),
        prepare=_open_case(case_id, title, actor.user_id),
        write=lambda _unit: (201, CaseCreated(case_id=case_id)),
        model=CaseCreated,
    )


def _open_case(
    case_id: UUID, title: BoundaryText, creator: UUID
) -> Callable[[StoreConnection], None]:
    """The case row and its creator's ADMIN standing, before the case lock the
    governed write then takes on them."""

    def prepare(conn: StoreConnection) -> None:
        conn.execute(
            "INSERT INTO cases (case_id, title) VALUES (%s, %s)", (case_id, title.value)
        )
        grant(conn, case_id=case_id, user_id=creator, standing=Standing.ADMIN)

    return prepare


def _upload_envelope(request: Request) -> int:
    """The declared body length, checked before a byte of the body is read."""
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    declared = request.headers.get("content-length")
    if (
        media != "multipart/form-data"
        or "transfer-encoding" in request.headers
        or declared is None
        or not (declared.isascii() and declared.isdigit())
    ):
        raise Refusal(RefusalCode.REQUEST_INVALID)
    if int(declared) > MAX_UPLOAD_BYTES:
        raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
    return int(declared)


def _release_read(
    _standing: Annotated[Standing, Depends(require_case_writer)], conn: Store
) -> None:
    """End the standing read's transaction: parsing and extraction hold none."""
    rollback_or_close(conn)


async def _admission_documents(
    request: Request,
    declared: Annotated[int, Depends(_upload_envelope)],
    _released: Annotated[None, Depends(_release_read)],
) -> list[Document]:
    """The pack's documents, in part order, from a stream held to its length."""
    bounded = Request(request.scope, _bounded(request.receive, declared))
    try:
        form = await bounded.form(max_files=DEFAULT_LIMITS.max_documents, max_fields=0)
    except (HTTPException, ValueError):
        raise Refusal(RefusalCode.REQUEST_INVALID) from None
    try:
        documents = []
        for name, part in form.multi_items():
            if name != DOCUMENT_PART or not isinstance(part, UploadFile):
                raise Refusal(RefusalCode.REQUEST_INVALID)
            filename = BoundaryText.of(part.filename or "", limit=FILENAME_CHARS)
            if not filename.value.strip():
                raise Refusal(RefusalCode.BOUNDARY_TEXT_INVALID)
            documents.append(Document(filename, await part.read()))
    finally:
        await form.close()
    if not documents:
        raise Refusal(RefusalCode.SOURCE_PACK_EMPTY)
    return documents


def _bounded(receive: Receive, declared: int) -> Receive:
    """`receive`, refusing a body that streams past its declared length."""
    received = 0

    async def bounded() -> Message:
        nonlocal received
        message = await receive()
        received += len(message.get("body", b""))
        if received > declared:
            raise Refusal(RefusalCode.REQUEST_INVALID)
        return message

    return bounded


@router.post(
    "/api/v1/cases/{case_id}/sources", status_code=201, dependencies=[IDENTITY_FIRST]
)
def admit_sources(  # noqa: PLR0913 -- decision 2's dependency order, one per step
    actor: Caller,
    _declared: Annotated[int, Depends(_upload_envelope)],
    key: Key,
    documents: Annotated[list[Document], Depends(_admission_documents)],
    case_id: CasePath,
    conn: Store,
    blobs: Blobs,
) -> Response:
    listing = [
        {
            "filename": document.filename.value,
            "sha256": sha256(document.data).hexdigest(),
        }
        for document in documents
    ]
    request = CommandRequest(ADMIT_SOURCES, case_id, None, None, listing)
    stored = _peek(conn, actor.user_id, case_id, key)
    if stored is not None:
        if stored.request_sha256 != request.digest():
            raise Refusal(RefusalCode.IDEMPOTENCY_KEY_REUSED)
        replay = CommandResult(stored.status, stored.receipt, replayed=True)
        return command_response(replay, SourcesAdmitted)

    pack = prepare_pack(documents)  # no unit open, no case lock held
    # And the uploads, for the same reason (ED-5): inside `governed` the case
    # row and the audit chain head are already held when `write` runs.
    digests = put_pack(blobs, pack)
    return governed(
        conn,
        scope=case_id,
        key=key,
        request=request,
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="SOURCES_ADMITTED",
            requires=Standing.WRITER,
            payload={
                "case_id": str(case_id),
                "document_sha256": [row["sha256"] for row in listing],
            },
        ),
        write=lambda unit: (
            201,
            SourcesAdmitted(
                case_id=case_id,
                source_ids=admit_prepared(unit, case_id, pack, digests),
            ),
        ),
        model=SourcesAdmitted,
    )


def _peek(
    conn: StoreConnection, actor_id: UUID, scope: UUID, key: UUID
) -> StoredReceipt | None:
    """The key's committed receipt, read in a unit closed before extraction."""
    try:
        stored = find_receipt(conn, actor_id=actor_id, scope=scope, key=key)
        conn.rollback()
    except psycopg.Error:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return stored
