"""A global ADMIN saves a rate deck (Plan 2 Task 1).

The second write here that is not a case's, shaped as the first is
(`caos/api/commands/qualification.py`): no case to lock, no standing to hold
and no case audit chain, so no governed unit through `run_command`. The write
is `save_deck` and the command receipt, in one transaction, under the nil
scope create case and a verdict use; a key is unique per actor, which is what
a retry needs.

*The floor is the top global rank.* A deck sets the rates every later run's
projection is pinned to, across every case, so only a global ADMIN saves one
(`at_least`, by rank). Anyone below is answered as an undeclared path is,
before the key, the body or the store is read: the route discloses nothing
to a caller who may not use it.

*The deck is the admin's; the identity is the host's.* `saved_by` is
`Actor.user_id`; a body naming a saver is an undeclared field.

The log line names the deck and its size, never a rate.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Response

from caos.api.commands._request import Key, command_response, json_body
from caos.api.deps import IDENTITY_FIRST, Caller, Store
from caos.api.identity import Actor, GlobalRole, at_least
from caos.api.wire import RateDeckSaved, SaveRateDeck
from caos.calculators.credit_model.projection import RateDeckYear
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, rollback_or_close
from caos.store.commands import (
    NIL_SCOPE,
    CommandResult,
    StoredReceipt,
    find_receipt,
    record_receipt,
    request_digest,
)
from caos.store.rate_decks import save_deck

# The receipt lookup, then `save_deck` (the lock bound, the save lock, the
# deck, its rates, the unit's own bound put back) and the receipt. Measured in
# `tests/test_rate_decks.py`. A twin that loses the key costs one more (the
# lookup after its rollback, 8 in all) and is not counted here, as
# `qualification.py` does not count its own.
SAVE_IO = 1 + 5 + 1
REPLAY_IO = 1  # the receipt lookup alone; a replay writes nothing
IO_BUDGET = SAVE_IO

# Who may save. Compared by rank (`at_least`), not by identity.
SAVES = GlobalRole.ADMIN
# The command this route records a receipt for.
SAVE_RATE_DECK = "SAVE_RATE_DECK"

router = APIRouter()


def require_admin(actor: Caller) -> Actor:
    """The actor, if its global role reaches the saving floor; otherwise the
    answer an undeclared endpoint gets. Declared ahead of the key, the body
    and the store, so a caller below the floor reaches none of them."""
    if not at_least(actor.role, SAVES):
        raise Refusal(RefusalCode.ENDPOINT_NOT_FOUND)
    return actor


Admin = Annotated[Actor, Depends(require_admin)]


@dataclass(frozen=True, slots=True)
class DeckRequest:
    """One save: who asked, under which key, the request's digest and the
    deck it carries, read off the wire once."""

    actor_id: UUID
    key: UUID
    request_sha256: str
    as_of: date
    rates: tuple[RateDeckYear, ...]


def _replayed(
    conn: StoreConnection, stored: StoredReceipt | None, request_sha256: str
) -> CommandResult:
    """The committed receipt for the key: replayed for the same request, the
    idempotency conflict for another. Ends the unit."""
    rollback_or_close(conn)
    if stored is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    if stored.request_sha256 != request_sha256:
        raise Refusal(RefusalCode.IDEMPOTENCY_KEY_REUSED)
    return CommandResult(stored.status, stored.receipt, replayed=True)


def saved_deck(conn: StoreConnection, request: DeckRequest) -> CommandResult:
    """Every statement the save sends, committed as one unit.

    The receipt is looked up first and written last, in the deck's own
    transaction. A twin under the same key that missed the lookup waits at
    the save lock while the first holds it; once the first commits, the
    twin's receipt insert finds the key taken, its whole unit (its deck
    included) is rolled back, and it replays the receipt that won -- one
    deck per key, whatever the interleaving. A twin that waits past the
    lock's bound (`caos.store.rate_decks.LOCK_TIMEOUT_MS`) is refused
    `STORE_UNAVAILABLE` having written nothing, and its retry replays.
    """
    stored = find_receipt(
        conn, actor_id=request.actor_id, scope=NIL_SCOPE, key=request.key
    )
    if stored is not None:
        return _replayed(conn, stored, request.request_sha256)
    deck_id = save_deck(conn, request.actor_id, request.as_of, request.rates)
    receipt = RateDeckSaved(deck_id=deck_id).model_dump(mode="json")
    if not record_receipt(
        conn,
        actor_id=request.actor_id,
        scope=NIL_SCOPE,
        key=request.key,
        command=SAVE_RATE_DECK,
        request_sha256=request.request_sha256,
        status=201,
        receipt=receipt,
    ):
        rollback_or_close(conn)
        twin = find_receipt(
            conn, actor_id=request.actor_id, scope=NIL_SCOPE, key=request.key
        )
        return _replayed(conn, twin, request.request_sha256)
    conn.commit()
    print(
        f"rate_deck_saved deck_id={deck_id} rows={len(request.rates)}",
        file=sys.stderr,
    )
    return CommandResult(201, receipt, replayed=False)


@router.post("/api/v1/rate-decks", dependencies=[IDENTITY_FIRST])
def save_rate_deck(
    admin: Admin,
    key: Key,
    body: Annotated[SaveRateDeck, Depends(json_body(SaveRateDeck))],
    conn: Store,
) -> Response:
    """Save a new rate deck; the latest deck is what every run created after
    it pins. Order: identity, the rank, the `Idempotency-Key`, the body, and
    only then the store. A deck the store would not hold (empty, a repeated
    rate and year, a rate outside (-1, 1)) is `REQUEST_INVALID`, writing
    nothing."""
    document = body.model_dump(mode="json")
    request = DeckRequest(
        actor_id=admin.user_id,
        key=key,
        request_sha256=request_digest(
            SAVE_RATE_DECK, case_id=None, run_id=None, gate=None, body=document
        ),
        as_of=date.fromisoformat(body.as_of),
        rates=tuple(
            RateDeckYear(
                reference_rate=row.reference_rate,
                fiscal_year_offset=row.year_offset,
                base=Decimal(row.base_rate),
                downside=Decimal(row.downside_rate),
            )
            for row in body.rates
        ),
    )
    try:
        result = saved_deck(conn, request)
    except Refusal:
        rollback_or_close(conn)
        raise
    except psycopg.Error:
        # The lookup, the lock and the writes are all the store's to fail;
        # the driver's message never leaves this handler.
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return command_response(result, RateDeckSaved)
