"""Idempotent governed commands: one receipt per `(actor, scope, key)`.

Task 4.2 decision 6. A command is a governed write (`caos/store/audit.py`)
whose unit also records the receipt it answered with, as the unit's last
domain statement. Four predicates decide every retry:

- **Same key, same request** -- `find_receipt` before the unit finds the
  committed receipt and replays its status and body, writing nothing.
- **Same key, different request** -- the stored `request_sha256` differs:
  `IDEMPOTENCY_KEY_REUSED`, committing nothing.
- **Concurrent twins** -- under a case scope the twin waits at the case lock
  and the in-unit lookup finds the first commit's receipt. Under the nil scope
  (create case) nothing is shared but the primary key: the twin's
  `INSERT ... ON CONFLICT DO NOTHING` waits for the first transaction, then
  inserts zero rows. Either way the twin's whole unit is rolled back and it
  replays or refuses.
- **A lost commit acknowledgement** -- the unit either committed with its
  receipt or did not; the client's retry finds out which through the lookup.

Refusals commit nothing, so a key is never burned by a refused request. A
revoked member's receipts are kept; the route's visibility check answers their
replay before the lookup is reached.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from caos.digest import canonical_digest
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, rollback_or_close
from caos.store.audit import GovernedAction, digest_of, governed_write

# The scope of a command that has no case yet: create case.
NIL_SCOPE = UUID(int=0)
# The one key the envelope adds to every command's audit payload, binding the
# event to the request that made it. A reader that rebuilds a payload to compare
# its digest must account for it: `payload_digests` is how.
REQUEST_KEY = "request_sha256"
_SUCCESS = frozenset({200, 201, 202})


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    """A committed command's receipt row."""

    command: str
    request_sha256: str
    status: int
    receipt: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What the route answers: the status, the receipt body, and whether this
    request replayed an earlier commit rather than making one."""

    status: int
    receipt: dict[str, Any]
    replayed: bool


class _Twin(Exception):
    """Inside the unit: another request already committed this key."""


def request_digest(
    command: str,
    *,
    case_id: UUID | None,
    run_id: UUID | None,
    gate: str | None,
    body: object,
) -> str:
    """SHA-256 of the canonical JSON of what the request asked for.

    `body` is the validated request in JSON mode (for admission, the
    `[{filename_nfc, sha256}]` list in part order). Keys sorted, no spaces,
    UTF-8, and no NaN, so equal requests digest equally.
    """
    return canonical_digest(
        {
            "command": command,
            "case_id": None if case_id is None else str(case_id),
            "run_id": None if run_id is None else str(run_id),
            "gate": gate,
            "body": body,
        }
    )


def find_receipt(
    conn: StoreConnection, *, actor_id: UUID, scope: UUID, key: UUID
) -> StoredReceipt | None:
    """The committed receipt for this key, if any. One round trip."""
    row = conn.execute(
        "SELECT command, request_sha256, status, receipt FROM command_requests"
        " WHERE actor_id = %s AND scope = %s AND idempotency_key = %s",
        (actor_id, scope, key),
    ).fetchone()
    if row is None:
        return None
    return StoredReceipt(str(row[0]), str(row[1]), int(row[2]), dict(row[3]))


def record_receipt(  # noqa: PLR0913 -- one receipt row, keyword-only
    conn: StoreConnection,
    *,
    actor_id: UUID,
    scope: UUID,
    key: UUID,
    command: str,
    request_sha256: str,
    status: int,
    receipt: Mapping[str, Any],
) -> bool:
    """Insert the receipt in the caller's unit; False when the key is taken.

    `ON CONFLICT DO NOTHING` waits for an in-flight twin holding the same key
    and answers zero rows once it commits. The caller must then roll back its
    whole unit.
    """
    cursor = conn.execute(
        "INSERT INTO command_requests (actor_id, scope, idempotency_key, command,"
        " request_sha256, status, receipt) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT DO NOTHING",
        (actor_id, scope, key, command, request_sha256, status, Jsonb(dict(receipt))),
    )
    return cursor.rowcount == 1


def run_command(  # noqa: PLR0913 -- one command's identity and unit, keyword-only
    conn: StoreConnection,
    *,
    scope: UUID,
    key: UUID,
    command: str,
    request_sha256: str,
    action: GovernedAction,
    write: Callable[[StoreConnection], tuple[int, BaseModel]],
    prepare: Callable[[StoreConnection], None] | None = None,
    after_event: Callable[[StoreConnection, str], None] | None = None,
) -> CommandResult:
    """Replay, refuse, or commit `write` with its audit event and receipt.

    The actor is `action.actor_id`; `scope` is `action.case_id`, or
    `NIL_SCOPE` for create case. `prepare` runs first in the same transaction,
    before the case lock -- create case inserts its case and the creator's
    standing there, so the governed write can lock and check them. `write`
    runs under the case lock and live standing and returns the success status
    and receipt; the receipt is inserted after it and the audit link after
    that, in one commit. A `NOT_AUTHORISED` from the unit (standing lost by
    commit time) answers `CASE_NOT_FOUND`, as every unseen case does.

    `after_event` is `governed_write`'s, passed through for the one command
    that must store an object naming its own audit link -- a filing's detached
    receipt. It runs last, after the receipt row, so what it writes is read
    back from the store and never replayed from a receipt.
    """
    if scope not in (action.case_id, NIL_SCOPE):
        raise _Misuse
    row = _Row(action.actor_id, scope, key, command, request_sha256)
    stored = _lookup(conn, row)
    if stored is not None:
        return _replay(conn, stored, request_sha256)

    answered: list[tuple[int, dict[str, Any]]] = []
    governed = replace(action, payload=_WithRequest(action.payload, request_sha256))
    try:
        if prepare is not None:
            _prepare(conn, prepare)
        governed_write(
            conn, governed, _unit(row, write, answered), after_event=after_event
        )
    except _Twin:
        stored = _lookup(conn, row)
        if stored is None:
            rollback_or_close(conn)
            raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
        return _replay(conn, stored, request_sha256)
    except Refusal as refusal:
        if refusal.code is RefusalCode.NOT_AUTHORISED:
            raise Refusal(RefusalCode.CASE_NOT_FOUND) from None
        raise
    [(status, body)] = answered
    return CommandResult(status, body, replayed=False)


class _WithRequest(Mapping[str, Any]):
    """The action's payload and the request digest, as a view rather than a copy.

    `governed_write` digests the payload *after* the unit's write has run, and a
    write that completes its own payload -- a filing naming the receipt it just
    made -- fills the caller's mapping in place inside the unit. A copy taken
    here would be taken before that, so the event would bind a payload the
    command never finished writing, and every reader that rebuilds it would
    refuse. Found by driving a filing over HTTP and reading it back
    (`tests/test_governed_write_routes.py::test_a_deliverable_filed_over_http_reads_back_from_the_committee_section`).

    A payload of its own carrying `request_sha256` would be shadowed by the
    envelope's: `__getitem__` would answer the envelope's value while `__iter__`
    and `__len__` counted the payload's one key, so the view would disagree with
    itself. No `GovernedAction` in the tree carries that key, and this is the one
    place that would hide it, so it is refused rather than left to be found.
    """

    __slots__ = ("_payload", "_request_sha256")

    def __init__(self, payload: Mapping[str, Any], request_sha256: str) -> None:
        if REQUEST_KEY in payload:
            raise Refusal(RefusalCode.INTERNAL_FAULT)
        self._payload = payload
        self._request_sha256 = request_sha256

    def __getitem__(self, key: str) -> object:
        if key == REQUEST_KEY:
            return self._request_sha256
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._payload
        if REQUEST_KEY not in self._payload:
            yield REQUEST_KEY

    def __len__(self) -> int:
        return len(self._payload) + (REQUEST_KEY not in self._payload)


@dataclass(frozen=True, slots=True)
class _Row:
    actor_id: UUID
    scope: UUID
    key: UUID
    command: str
    request_sha256: str


class _Misuse(ValueError):
    """A caller bug: a scope other than the action's case or the nil scope, or
    a success status other than 200, 201 or 202."""


def _unit(
    row: _Row,
    write: Callable[[StoreConnection], tuple[int, BaseModel]],
    answered: list[tuple[int, dict[str, Any]]],
) -> Callable[[StoreConnection], None]:
    """The governed write's body: a twin check under the case lock, the domain
    write, then the receipt as its last statement."""

    def unit(inner: StoreConnection) -> None:
        taken = find_receipt(inner, actor_id=row.actor_id, scope=row.scope, key=row.key)
        if taken is not None:
            raise _Twin
        status, receipt = write(inner)
        if status not in _SUCCESS:
            raise _Misuse
        body = receipt.model_dump(mode="json")
        if not record_receipt(
            inner,
            actor_id=row.actor_id,
            scope=row.scope,
            key=row.key,
            command=row.command,
            request_sha256=row.request_sha256,
            status=status,
            receipt=body,
        ):
            raise _Twin
        answered.append((status, body))

    return unit


def _lookup(conn: StoreConnection, row: _Row) -> StoredReceipt | None:
    """`find_receipt` outside a unit: a store fault is refused, never raised
    with psycopg's message."""
    try:
        return find_receipt(conn, actor_id=row.actor_id, scope=row.scope, key=row.key)
    except psycopg.Error:
        rollback_or_close(conn)
    raise Refusal(RefusalCode.STORE_UNAVAILABLE)


def _prepare(conn: StoreConnection, prepare: Callable[[StoreConnection], None]) -> None:
    """Run the pre-lock step; any failure leaves no open unit behind."""
    try:
        prepare(conn)
    except psycopg.Error:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except BaseException:
        rollback_or_close(conn)
        raise


def _replay(
    conn: StoreConnection, stored: StoredReceipt, request_sha256: str
) -> CommandResult:
    """The stored answer for the same request; a conflict for another. Both
    end the read unit, so a replay commits nothing."""
    rollback_or_close(conn)
    if stored.request_sha256 != request_sha256:
        raise Refusal(RefusalCode.IDEMPOTENCY_KEY_REUSED)
    return CommandResult(stored.status, stored.receipt, replayed=True)


def payload_digests(
    conn: StoreConnection,
    *,
    scope: UUID,
    actor_id: UUID,
    payload: Mapping[str, Any],
    commands: Sequence[str],
) -> frozenset[str]:
    """Every digest an audit event for `payload` may legitimately carry.

    A payload is digested and never stored (`digest_of`), so a reader that
    wants to prove an event bound exactly these fields has to rebuild what the
    writer built. There are two writers: a store function called directly,
    whose event binds the payload as given, and a command, whose envelope adds
    `request_sha256`. The second is not recomputable from the payload -- it is
    a digest of the whole request -- so it is read back from the receipts this
    actor committed on this scope, which is a join no column makes.

    `scope` is the **receipt's** scope, which is the case for every command but
    one: `CREATE_CASE` records its receipt under `NIL_SCOPE` while its audit
    event sits on the case it made, so a caller passing that case id could never
    rebuild a `CASE_CREATED` payload. It would refuse fail-closed with nothing
    saying why, which is why it is said here. No reader asks for that today.

    Bounded by the named `commands` this actor committed on this scope, not by
    every receipt it holds. `command_requests` is never collected -- its own
    ledger entry owns that -- and a case ADMIN can add rows to it cheaply and
    successfully, because `grant` upserts, so a repeated grant with a fresh
    idempotency key succeeds with no other effect. Without the filter this read
    was an unbounded scan plus one canonical serialisation and one SHA-256 per
    row, once per actor, on every committee read. The caller knows which
    commands can have written the action it is rebuilding; naming them is what
    bounds this. Found by the Completion Phase 12 adversarial audit.

    The comparison stays exact in both directions: an event whose payload had
    any other field, or a different value in one of these, matches neither
    digest.
    """
    exact = dict(payload)
    digests = {digest_of(exact)}
    rows = conn.execute(
        "SELECT request_sha256 FROM command_requests"
        " WHERE scope = %s AND actor_id = %s AND command = ANY(%s)",
        (scope, actor_id, list(commands)),
    ).fetchall()
    digests |= {digest_of({**exact, REQUEST_KEY: str(row[0])}) for row in rows}
    return frozenset(digests)
