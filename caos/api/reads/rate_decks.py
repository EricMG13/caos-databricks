"""The latest rate deck, for any signed-in user (Plan 2 Task 1).

Global, like the deck: no case in the path and no standing to read. The
answer is the latest committed deck, or `null` when none was ever saved --
the same deck a run created now would pin (`caos.store.rate_decks`).
"""

from __future__ import annotations

from fastapi import APIRouter

from caos.api.deps import IDENTITY_FIRST, Caller, Store
from caos.api.wire import RateDeckView
from caos.store.rate_decks import latest_saved_deck

# The deck and its rates in one query. Measured in `tests/test_rate_decks.py`.
IO_BUDGET = 1

router = APIRouter()


@router.get(
    "/api/v1/rate-decks/latest",
    response_model=RateDeckView | None,
    dependencies=[IDENTITY_FIRST],
)
def read_latest_rate_deck(actor: Caller, conn: Store) -> RateDeckView | None:
    """`actor` is declared before `conn`: an anonymous request is refused
    before a connection opens; any signed-in role reads the deck. Rates
    travel as plain decimal text (`f` format, never an exponent), never a
    float (invariant 7)."""
    saved = latest_saved_deck(conn)
    if saved is None:
        return None
    return RateDeckView.model_validate(
        {
            "deck_id": saved.deck.deck_id,
            "as_of": saved.deck.as_of,
            "saved_at": saved.saved_at,
            "rates": [
                {
                    "reference_rate": year.reference_rate,
                    "year_offset": year.fiscal_year_offset,
                    "base_rate": f"{year.base:f}",
                    "downside_rate": f"{year.downside:f}",
                }
                for year in saved.deck.years
            ],
        }
    )
