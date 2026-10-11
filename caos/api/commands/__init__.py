"""The governed commands under `/api/v1/cases` (Task 4.2), and the two
global writes, a qualification verdict and a rate deck.

One module per command family, each owning its `APIRouter` and `IO_BUDGET`:
`cases` (create case, admission), `runs` (route, input, preview, approval) and
`execution` (start, retry, cancel), `qualification` (sign a verdict) and
`rate_decks` (save a rate deck). `_request` holds the dependencies they
share; `caos/api/app.py` includes the routers.
"""

from __future__ import annotations

# The package serves no request path of its own (`scripts/io_budget.py`).
IO_BUDGET = 0
