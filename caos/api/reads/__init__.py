"""One read module per enabled section (Task 4.1), and the evidence page (4.4c).

Each owns its `APIRouter` and its `IO_BUDGET`, so a slice adding a section's
read touches only its own module; `caos/api/app.py` includes them all.
"""

from __future__ import annotations

# The package serves no request path of its own (`scripts/io_budget.py`).
IO_BUDGET = 0
