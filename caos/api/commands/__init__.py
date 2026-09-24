"""The governed commands under `/api/v1/cases` (Task 4.2), and the one
global write, a qualification verdict.

One module per command family, each owning its `APIRouter` and `IO_BUDGET`:
`cases` (create case, admission), `runs` (route, input, preview, approval) and
`execution` (start, retry, cancel) and `qualification` (sign a verdict).
`_request` holds the dependencies they share; `caos/api/app.py` includes
the four routers.
"""

from __future__ import annotations

# The package serves no request path of its own (`scripts/io_budget.py`).
IO_BUDGET = 0
